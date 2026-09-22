"""Tests for the research-only Trend Expansion base-universe filter."""

from __future__ import annotations

import csv
import io
from argparse import Namespace

import pytest

from tools import build_trend_expansion_universe as cli
from trend_expansion import base_universe
from trend_expansion.base_universe import (
    filter_base_universe,
    load_filter_outputs,
    write_filter_outputs,
)


def _record(symbol: str, name: str, exchange: str = "NASDAQ", **values):
    record = {
        "symbol": symbol,
        "security_name": name,
        "exchange": exchange,
        "market_category": "Q",
        "financial_status": "N",
        "round_lot_size": "100",
        "etf": "N",
        "test_issue": "N",
        "next_shares": "N",
        "cqs_symbol": "",
        "nasdaq_symbol": symbol,
        "source": "nasdaqlisted",
        "snapshot_date": "2026-09-15",
    }
    record.update(values)
    return record


@pytest.mark.parametrize("exchange", ["NASDAQ", "NYSE", "NYSE AMERICAN", "AMEX"])
def test_allowed_exchange_common_stocks_pass(exchange):
    accepted, rejected, diagnostics = filter_base_universe([_record("abc", "ABC Holdings Common Stock", exchange)])
    assert [row["symbol"] for row in accepted] == ["ABC"]
    assert accepted[0]["source_pool"] == "trend_expansion"
    assert not rejected
    assert diagnostics["final_common_equity_count"] == 1


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        (_record("OTC", "Ordinary Common Stock", "OTCQX"), "exchange_not_allowed"),
        (_record("ETF", "Index Portfolio", etf="Y"), "etf_fund"),
        (_record("FUND", "Example Income Fund"), "etf_fund"),
        (_record("W", "Example Corp Warrants"), "warrant"),
        (_record("U", "Example Acquisition Corp Units"), "unit"),
        (_record("R", "Example Subscription Rights"), "right"),
        (_record("P", "Example 7% Preferred Stock"), "preferred"),
        (_record("PS", "Example Preference Shares"), "preferred"),
        (_record("PK", "Example Preference Stock"), "preferred"),
        (_record("D", "Example Corp. 6.50% Senior Notes due 2029"), "debt"),
        (_record("ETN", "Example Index ETN"), "debt"),
        (_record("ETNS", "Example Index ETNs due 2035"), "debt"),
        (_record("XTN", "Example Exchange-Traded Note"), "debt"),
        (_record("TEST", "Normal Common Stock", test_issue="Y"), "test_issue"),
        (_record("SPAC", "Example Acquisition Corporation Class A"), "other_non_common"),
    ],
)
def test_reliable_non_common_evidence_is_rejected(record, reason):
    accepted, rejected, _ = filter_base_universe([record])
    assert not accepted
    assert rejected[0]["reason"] == reason


def test_absent_optional_metadata_does_not_reject_normal_listing():
    accepted, rejected, _ = filter_base_universe(
        [{"symbol": "plain", "security_name": "Plain Industries", "exchange": "NYSE"}]
    )
    assert accepted[0]["symbol"] == "PLAIN"
    assert not rejected


@pytest.mark.parametrize(
    "name",
    [
        "Example plc - American Depositary Shares",
        "Example plc - American Depositary Shares, each representing two Ordinary Shares",
        "Example plc - American Depositary Shares, each representing ten Common Shares",
    ],
)
def test_ordinary_or_common_equity_depositary_shares_pass(name):
    accepted, rejected, _ = filter_base_universe([_record("ADR", name)])

    assert [row["symbol"] for row in accepted] == ["ADR"]
    assert not rejected


@pytest.mark.parametrize(
    "name",
    [
        "Example Depositary Shares, each representing preferred stock",
        "Example Depositary Shares, each representing preference shares",
        "Example 7% Pfd Shs",
        "Example 7% Pfd Sh",
        "Example Pfd Stock",
        "Example Pfd Ser A",
        "Example Pfd 3 Ordinary Shares",
        "Example Pfd Shs - Common Stock",
    ],
)
def test_explicit_preferred_security_evidence_is_rejected(name):
    accepted, rejected, diagnostics = filter_base_universe([_record("PREF", name)])

    assert not accepted
    assert rejected[0]["reason"] == "preferred"
    assert diagnostics["preferred_count"] == 1


@pytest.mark.parametrize(
    "name",
    [
        "Pfd Holdings Corporation - Common Stock",
        "Example Pfdly Named Corporation - Common Stock",
    ],
)
def test_ambiguous_or_embedded_pfd_text_does_not_reject_common_stock(name):
    accepted, rejected, _ = filter_base_universe([_record("COMMON", name)])

    assert [row["symbol"] for row in accepted] == ["COMMON"]
    assert not rejected


@pytest.mark.parametrize(
    "name",
    [
        "Northern Trust Corporation - Common Stock",
        "Community Bank Notes Company - Common Stock",
        "Bond Street Holdings, Inc. - Common Stock",
        "Etnyre International - Common Stock",
        "Unit Corporation - Common Stock",
        "Preference Holdings Corporation - Common Stock",
    ],
)
def test_issuer_name_words_do_not_override_explicit_common_stock(name):
    accepted, rejected, _ = filter_base_universe([_record("COMMON", name)])

    assert [row["symbol"] for row in accepted] == ["COMMON"]
    assert not rejected


def test_genuine_trust_instrument_is_still_rejected():
    accepted, rejected, _ = filter_base_universe(
        [_record("TRUST", "Example Investment Trust - Shares of Beneficial Interest")]
    )

    assert not accepted
    assert rejected[0]["reason"] == "other_non_common"


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("Example Corp Senior Notes due 2035 - Common Stock", "debt"),
        ("Example Warrants - Common Stock", "warrant"),
        ("Example Preferred Shares - Common Stock", "preferred"),
        ("Example Acquisition Corp Units - Common Stock", "unit"),
    ],
)
def test_explicit_non_common_evidence_beats_common_stock_text(name, reason):
    accepted, rejected, _ = filter_base_universe([_record("NONCOMMON", name)])

    assert not accepted
    assert rejected[0]["reason"] == reason


def test_duplicates_have_stable_precedence_and_auditable_rejection():
    preferred = _record("dup", "Deterministic Nasdaq row")
    other = _record("DUP", "Other row", "NYSE")
    other["source"] = "otherlisted"
    first = filter_base_universe([other, preferred])
    second = filter_base_universe([preferred, other])
    assert first == second
    assert first[0][0]["security_name"] == "Deterministic Nasdaq row"
    assert first[1] == [
        {
            "symbol": "DUP",
            "security_name": "Other row",
            "exchange": "NYSE",
            "reason": "duplicate_symbol",
        }
    ]
    assert first[2]["duplicate_symbol_count"] == 1


def test_reason_counts_match_exclusion_records_and_output_is_sorted():
    records = [
        _record("Z", "Zeta Common Stock", "NYSE"),
        _record("W", "Widgets Warrants"),
        _record("A", "Alpha Common Stock"),
        _record("P", "Preferred Shares"),
        _record("E", "Exchange Traded Fund"),
        _record("X", "Unsupported Common", "IEX"),
        _record("T", "Test Common", test_issue="Y"),
    ]
    accepted, rejected, diagnostics = filter_base_universe(reversed(records))
    assert [row["symbol"] for row in accepted] == ["A", "Z"]
    mapping = {
        "exchange_not_allowed": "excluded_by_exchange_count",
        "etf_fund": "etf_fund_count",
        "warrant": "warrant_count",
        "unit": "unit_count",
        "right": "right_count",
        "preferred": "preferred_count",
        "test_issue": "test_issue_count",
        "debt": "debt_count",
        "other_non_common": "other_non_common_count",
        "duplicate_symbol": "duplicate_symbol_count",
    }
    for reason, count_name in mapping.items():
        assert diagnostics[count_name] == sum(row["reason"] == reason for row in rejected)
    assert diagnostics["excluded_count"] == len(rejected)
    assert diagnostics["input_count"] == len(records)


def test_fixed_input_writes_byte_stable_csv_and_report(tmp_path):
    records = [_record("B", "Beta Common", "NYSE"), _record("A", "Alpha Warrants")]
    paths = []
    source_variants = (("one", records), ("two", reversed(records)))
    for directory_name, source_records in source_variants:
        csv_path = tmp_path / directory_name / "base.csv"
        report_path = tmp_path / directory_name / "report.json"
        write_filter_outputs(source_records, csv_path, report_path)
        paths.append(load_filter_outputs(csv_path, report_path))
    assert paths[0] == paths[1]
    with io.StringIO(paths[0][0].decode("utf-8"), newline="") as stream:
        assert list(csv.DictReader(stream))[0]["source_pool"] == "trend_expansion"
    report = paths[0][1]
    assert report["exclusions"][0]["reason"] == "warrant"


def test_failed_second_artifact_keeps_previous_generation(tmp_path, monkeypatch):
    csv_path = tmp_path / "base.csv"
    report_path = tmp_path / "report.json"
    old_records = [_record("OLD", "Old Common Stock")]
    write_filter_outputs(old_records, csv_path, report_path)
    old_generation = (tmp_path / "FILTER_CURRENT").read_text(encoding="ascii")
    old_artifacts = load_filter_outputs(csv_path, report_path)
    real_atomic_write = base_universe._atomic_write  # pylint: disable=protected-access

    def fail_report(path, content):
        if path.name == "report.json":
            raise OSError("injected report failure")
        return real_atomic_write(path, content)

    monkeypatch.setattr(base_universe, "_atomic_write", fail_report)
    with pytest.raises(OSError, match="injected report failure"):
        write_filter_outputs([_record("NEW", "New Common Stock")], csv_path, report_path)

    assert (tmp_path / "FILTER_CURRENT").read_text(encoding="ascii") == old_generation
    assert load_filter_outputs(csv_path, report_path) == old_artifacts
    assert not any(path.name.startswith(".staging-") for path in (tmp_path / "filter_generations").iterdir())


def test_retry_after_failed_publication_selects_complete_new_generation(tmp_path, monkeypatch):
    csv_path = tmp_path / "base.csv"
    report_path = tmp_path / "report.json"
    write_filter_outputs([_record("OLD", "Old Common Stock")], csv_path, report_path)
    real_atomic_write = base_universe._atomic_write  # pylint: disable=protected-access

    def fail_report(path, content):
        if path.name == "report.json":
            raise OSError("injected report failure")
        return real_atomic_write(path, content)

    monkeypatch.setattr(base_universe, "_atomic_write", fail_report)
    with pytest.raises(OSError):
        write_filter_outputs([_record("NEW", "New Common Stock")], csv_path, report_path)
    monkeypatch.setattr(base_universe, "_atomic_write", real_atomic_write)
    write_filter_outputs([_record("NEW", "New Common Stock")], csv_path, report_path)

    csv_bytes, report = load_filter_outputs(csv_path, report_path)
    assert b"NEW,New Common Stock" in csv_bytes
    assert b"OLD,Old Common Stock" not in csv_bytes
    assert report["diagnostics"]["final_common_equity_count"] == 1


def test_publication_requires_one_selector_directory(tmp_path):
    with pytest.raises(ValueError, match="must share a directory"):
        write_filter_outputs(
            [_record("A", "Alpha Common Stock")],
            tmp_path / "one" / "base.csv",
            tmp_path / "two" / "report.json",
        )


def test_filter_publication_does_not_replace_snapshot_selector(tmp_path):
    snapshot_generation = "stage-a-generation\n"
    (tmp_path / "CURRENT").write_text(snapshot_generation, encoding="ascii")

    write_filter_outputs(
        [_record("A", "Alpha Common Stock")],
        tmp_path / "base.csv",
        tmp_path / "report.json",
    )

    assert (tmp_path / "CURRENT").read_text(encoding="ascii") == snapshot_generation
    assert (tmp_path / "FILTER_CURRENT").is_file()


@pytest.mark.parametrize("refresh", [False, True])
def test_cli_filter_loads_records_for_cached_and_refreshed_snapshots(tmp_path, monkeypatch, refresh):
    records = [_record("A", "Alpha Common Stock")]
    metadata = {
        "snapshot_date": "2026-09-15",
        "record_count": 1,
        "duplicate_symbol_count": 0,
        "schema_version": 1,
        "sources": {},
    }
    calls = []
    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda: Namespace(
            output_dir=tmp_path,
            refresh=refresh,
            filter=True,
            filter_output=None,
            exclusion_report=None,
            snapshot_date="2026-09-15",
        ),
    )
    monkeypatch.setattr(
        cli,
        "build_snapshot",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.setattr(cli, "load_snapshot", lambda _path: (records, metadata))
    monkeypatch.setattr(
        cli,
        "write_filter_outputs",
        lambda actual, *_paths: {"input_count": len(actual)},
    )

    cli.main()

    assert bool(calls) is refresh
