"""Tests for the research-only Nasdaq Trader universe cache."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from trend_expansion import universe_source
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


@pytest.mark.parametrize(
    ("source", "fixture_name", "missing_header"),
    [
        ("nasdaqlisted", "nasdaqlisted", "ETF"),
        ("otherlisted", "otherlisted", "Test Issue"),
    ],
)
def test_parse_directory_rejects_missing_non_symbol_required_header(
    source, fixture_name, missing_header
):
    lines = _fixture(fixture_name).decode().splitlines()
    header = lines[0].split("|")
    missing_index = header.index(missing_header)
    lines[0] = "|".join(header[:missing_index] + header[missing_index + 1 :])

    with pytest.raises(UniverseSourceError, match=rf"missing.*{missing_header}"):
        parse_directory("\n".join(lines), source, SNAPSHOT_DATE)


@pytest.mark.parametrize(
    ("source", "text"),
    [
        (
            "nasdaqlisted",
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
            "SHORT|Truncated Nasdaq row|Q|N|N|100\n",
        ),
        (
            "otherlisted",
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
            "SHORT|Truncated other row|N|SHORT|N\n",
        ),
    ],
)
def test_parse_directory_skips_truncated_rows(source, text):
    assert not parse_directory(text, source, SNAPSHOT_DATE)


def test_parse_directory_preserves_legitimately_empty_optional_values():
    text = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "EMPTY|Optional aliases omitted|N||N|100|N|\n"
    )

    records = parse_directory(text, "otherlisted", SNAPSHOT_DATE)

    assert len(records) == 1
    assert records[0]["cqs_symbol"] == ""
    assert records[0]["nasdaq_symbol"] == ""


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

    generation = (tmp_path / "CURRENT").read_text(encoding="ascii").strip()
    snapshot_bytes = (
        tmp_path / "generations" / generation / "universe.csv"
    ).read_bytes()
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

    first_generation = (first / "CURRENT").read_text(encoding="ascii").strip()
    second_generation = (second / "CURRENT").read_text(encoding="ascii").strip()
    assert (first / "generations" / first_generation / "universe.csv").read_bytes() == (
        second / "generations" / second_generation / "universe.csv"
    ).read_bytes()


def test_load_rejects_missing_or_tampered_cache(tmp_path):
    with pytest.raises(UniverseSourceError, match="--refresh"):
        load_snapshot(tmp_path)

    build_snapshot(tmp_path, snapshot_date=SNAPSHOT_DATE, downloader=_downloader)
    generation = (tmp_path / "CURRENT").read_text(encoding="ascii").strip()
    (tmp_path / "generations" / generation / "universe.csv").write_text(
        "tampered", encoding="utf-8"
    )
    with pytest.raises(UniverseSourceError, match="checksum"):
        load_snapshot(tmp_path)


def test_refresh_network_failure_is_clear_and_does_not_fall_back_to_cache(tmp_path):
    build_snapshot(tmp_path, snapshot_date=SNAPSHOT_DATE, downloader=_downloader)
    original_records, original_metadata = load_snapshot(tmp_path)

    def unavailable(_url: str) -> bytes:
        raise OSError("network unavailable")

    with pytest.raises(
        UniverseSourceError, match="Failed to refresh.*network unavailable"
    ):
        build_snapshot(tmp_path, snapshot_date="2026-09-16", downloader=unavailable)

    records, metadata = load_snapshot(tmp_path)
    assert records == original_records
    assert metadata == original_metadata


@pytest.mark.parametrize("failure_target", ["metadata.json", "CURRENT"])
def test_failed_generation_publication_preserves_previous_snapshot(
    tmp_path, monkeypatch, failure_target
):
    build_snapshot(tmp_path, snapshot_date=SNAPSHOT_DATE, downloader=_downloader)
    old_records, old_metadata = load_snapshot(tmp_path)
    old_current = (tmp_path / "CURRENT").read_text(encoding="ascii")
    # Exercise the private publication seam to inject a filesystem failure.
    # pylint: disable=protected-access
    real_atomic_write = universe_source._atomic_write
    # pylint: enable=protected-access

    def fail_publication(path, content):
        if path.name == failure_target:
            raise OSError(f"injected {failure_target} publication failure")
        return real_atomic_write(path, content)

    monkeypatch.setattr(universe_source, "_atomic_write", fail_publication)

    with pytest.raises(OSError, match="injected"):
        build_snapshot(tmp_path, snapshot_date="2026-09-16", downloader=_downloader)

    assert (tmp_path / "CURRENT").read_text(encoding="ascii") == old_current
    records, metadata = load_snapshot(tmp_path)
    assert records == old_records
    assert metadata == old_metadata


def test_successful_refresh_selects_new_complete_generation(tmp_path):
    build_snapshot(tmp_path, snapshot_date=SNAPSHOT_DATE, downloader=_downloader)
    old_current = (tmp_path / "CURRENT").read_text(encoding="ascii")

    metadata = build_snapshot(
        tmp_path, snapshot_date="2026-09-16", downloader=_downloader
    )

    assert (tmp_path / "CURRENT").read_text(encoding="ascii") != old_current
    records, loaded_metadata = load_snapshot(tmp_path)
    assert loaded_metadata == metadata
    assert loaded_metadata["snapshot_date"] == "2026-09-16"
    assert all(record["snapshot_date"] == "2026-09-16" for record in records)
