"""Tests for the research-only Trend Expansion base-universe filter."""

from __future__ import annotations

import csv
import json

import pytest

from trend_expansion.base_universe import filter_base_universe, write_filter_outputs


def _record(symbol: str, name: str, exchange: str = "NASDAQ", **values):
    record = {
        "symbol": symbol, "security_name": name, "exchange": exchange,
        "market_category": "Q", "financial_status": "N", "round_lot_size": "100",
        "etf": "N", "test_issue": "N", "next_shares": "N", "cqs_symbol": "",
        "nasdaq_symbol": symbol,
        "source": "nasdaqlisted",
        "snapshot_date": "2026-09-15",
    }
    record.update(values)
    return record


@pytest.mark.parametrize("exchange", ["NASDAQ", "NYSE", "NYSE AMERICAN", "AMEX"])
def test_allowed_exchange_common_stocks_pass(exchange):
    accepted, rejected, diagnostics = filter_base_universe(
        [_record("abc", "ABC Holdings Common Stock", exchange)]
    )
    assert [row["symbol"] for row in accepted] == ["ABC"]
    assert accepted[0]["source_pool"] == "trend_expansion"
    assert not rejected
    assert diagnostics["final_common_equity_count"] == 1


@pytest.mark.parametrize(("record", "reason"), [
    (_record("OTC", "Ordinary Common Stock", "OTCQX"), "exchange_not_allowed"),
    (_record("ETF", "Index Portfolio", etf="Y"), "etf_fund"),
    (_record("FUND", "Example Income Fund"), "etf_fund"),
    (_record("W", "Example Corp Warrants"), "warrant"),
    (_record("U", "Example Acquisition Corp Units"), "unit"),
    (_record("R", "Example Subscription Rights"), "right"),
    (_record("P", "Example 7% Preferred Stock"), "preferred"),
    (_record("TEST", "Normal Common Stock", test_issue="Y"), "test_issue"),
    (_record("SPAC", "Example Acquisition Corporation Class A"), "other_non_common"),
])
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
        _record("Z", "Zeta Common Stock", "NYSE"), _record("W", "Widgets Warrants"),
        _record("A", "Alpha Common Stock"), _record("P", "Preferred Shares"),
        _record("E", "Exchange Traded Fund"), _record("X", "Unsupported Common", "IEX"),
        _record("T", "Test Common", test_issue="Y"),
    ]
    accepted, rejected, diagnostics = filter_base_universe(reversed(records))
    assert [row["symbol"] for row in accepted] == ["A", "Z"]
    mapping = {
        "exchange_not_allowed": "excluded_by_exchange_count",
        "etf_fund": "etf_fund_count",
        "warrant": "warrant_count", "unit": "unit_count", "right": "right_count",
        "preferred": "preferred_count", "test_issue": "test_issue_count",
        "other_non_common": "other_non_common_count",
        "duplicate_symbol": "duplicate_symbol_count",
    }
    for reason, count_name in mapping.items():
        assert diagnostics[count_name] == sum(
            row["reason"] == reason for row in rejected
        )
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
        paths.append((csv_path, report_path))
    assert paths[0][0].read_bytes() == paths[1][0].read_bytes()
    assert paths[0][1].read_bytes() == paths[1][1].read_bytes()
    with paths[0][0].open(newline="", encoding="utf-8") as stream:
        assert list(csv.DictReader(stream))[0]["source_pool"] == "trend_expansion"
    report = json.loads(paths[0][1].read_text(encoding="utf-8"))
    assert report["exclusions"][0]["reason"] == "warrant"
