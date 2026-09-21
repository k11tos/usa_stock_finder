"""Tests for the research-only Nasdaq Trader universe cache."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from trend_expansion.universe_source import (
    SOURCE_URLS,
    UniverseSourceError,
    build_snapshot,
    load_snapshot,
    normalize_exchange,
    normalize_records,
    parse_directory,
)

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT_DATE = "2026-09-15"


def _fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}.txt").read_bytes()


def _downloader(url: str) -> bytes:
    source = next(name for name, source_url in SOURCE_URLS.items() if source_url == url)
    return _fixture(source)


def test_parse_nasdaq_directory_preserves_filter_fields_and_ignores_footer_and_malformed_row():
    records = parse_directory(
        _fixture("nasdaqlisted").decode(), "nasdaqlisted", SNAPSHOT_DATE
    )

    assert [record["symbol"] for record in records] == ["ZZZ", "AAPL", "TEST"]
    assert records[0] == {
        "symbol": "ZZZ",
        "security_name": "Zeta Units",
        "exchange": "NASDAQ",
        "market_category": "S",
        "financial_status": "N",
        "round_lot_size": "100",
        "etf": "N",
        "test_issue": "N",
        "next_shares": "N",
        "cqs_symbol": "",
        "nasdaq_symbol": "",
        "source": "nasdaqlisted",
        "snapshot_date": SNAPSHOT_DATE,
    }
    assert records[2]["test_issue"] == "Y"


def test_parse_other_directory_and_normalize_all_exchange_codes():
    records = parse_directory(
        _fixture("otherlisted").decode(), "otherlisted", SNAPSHOT_DATE
    )

    assert [record["symbol"] for record in records] == ["IBM", "SPY", "AMEXW", "AAPL"]
    assert records[0]["exchange"] == "NYSE"
    assert records[0]["cqs_symbol"] == "IBM"
    assert records[1]["exchange"] == "NYSE ARCA"
    assert records[1]["etf"] == "Y"
    assert records[2]["exchange"] == "NYSE AMERICAN"
    assert normalize_exchange("V", "otherlisted") == "IEX"
    assert normalize_exchange("Z", "otherlisted") == "CBOE BZX"
    assert normalize_exchange("x", "otherlisted") == "X"


@pytest.mark.parametrize("text", ["not|the|header\nvalue|value|value\n", ""])
def test_parse_directory_rejects_malformed_header(text):
    with pytest.raises(UniverseSourceError, match="header"):
        parse_directory(text, "nasdaqlisted", SNAPSHOT_DATE)


def test_duplicate_symbols_use_deterministic_precedence_and_output_order():
    combined = parse_directory(
        _fixture("otherlisted").decode(), "otherlisted", SNAPSHOT_DATE
    )
    combined += parse_directory(
        _fixture("nasdaqlisted").decode(), "nasdaqlisted", SNAPSHOT_DATE
    )

    records, duplicate_count = normalize_records(reversed(combined))

    assert [record["symbol"] for record in records] == [
        "AAPL",
        "AMEXW",
        "IBM",
        "SPY",
        "TEST",
        "ZZZ",
    ]
    assert records[0]["source"] == "nasdaqlisted"
    assert duplicate_count == 1


def test_build_and_load_snapshot_records_auditable_metadata(tmp_path):
    metadata = build_snapshot(
        tmp_path, snapshot_date=SNAPSHOT_DATE, downloader=_downloader
    )
    records, loaded_metadata = load_snapshot(tmp_path)

    snapshot_bytes = (tmp_path / "universe.csv").read_bytes()
    assert metadata == loaded_metadata
    assert metadata["schema_version"] == 1
    assert metadata["snapshot_date"] == SNAPSHOT_DATE
    assert metadata["record_count"] == 6
    assert metadata["duplicate_symbol_count"] == 1
    assert metadata["snapshot_sha256"] == hashlib.sha256(snapshot_bytes).hexdigest()
    assert metadata["sources"]["nasdaqlisted"]["url"] == SOURCE_URLS["nasdaqlisted"]
    assert (
        metadata["sources"]["nasdaqlisted"]["sha256"]
        == hashlib.sha256(_fixture("nasdaqlisted")).hexdigest()
    )
    assert [record["symbol"] for record in records] == sorted(
        record["symbol"] for record in records
    )


def test_same_inputs_produce_identical_csv(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    build_snapshot(first, snapshot_date=SNAPSHOT_DATE, downloader=_downloader)
    build_snapshot(second, snapshot_date=SNAPSHOT_DATE, downloader=_downloader)

    assert (first / "universe.csv").read_bytes() == (
        second / "universe.csv"
    ).read_bytes()


def test_load_rejects_missing_or_tampered_cache(tmp_path):
    with pytest.raises(UniverseSourceError, match="--refresh"):
        load_snapshot(tmp_path)

    build_snapshot(tmp_path, snapshot_date=SNAPSHOT_DATE, downloader=_downloader)
    (tmp_path / "universe.csv").write_text("tampered", encoding="utf-8")
    with pytest.raises(UniverseSourceError, match="checksum"):
        load_snapshot(tmp_path)


def test_refresh_network_failure_is_clear_and_does_not_fall_back_to_cache(tmp_path):
    build_snapshot(tmp_path, snapshot_date=SNAPSHOT_DATE, downloader=_downloader)
    original_metadata = json.loads(
        (tmp_path / "metadata.json").read_text(encoding="utf-8")
    )

    def unavailable(_url: str) -> bytes:
        raise OSError("network unavailable")

    with pytest.raises(
        UniverseSourceError, match="Failed to refresh.*network unavailable"
    ):
        build_snapshot(tmp_path, snapshot_date="2026-09-16", downloader=unavailable)

    _, metadata = load_snapshot(tmp_path)
    assert metadata == original_metadata
