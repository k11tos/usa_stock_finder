"""Deterministic source isolation, validation and publication regressions."""

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, mock_open

import pandas as pd
import pytest

from live_performance_logger import BROKER_EQUITY_SNAPSHOT_HEADERS, append_broker_equity_snapshot
from performance_report_runner import run_performance_report_safely
from telegram_utils import build_performance_summary_message
from tools import broker_equity, performance_report
from tools.broker_equity import AMOUNT_FIELDS, EXPECTED_SOURCE, HEADERS, KST, load_broker_equity

AS_OF = datetime(2026, 1, 10, 23, 0, tzinfo=KST)


@pytest.fixture
def broker_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "data/live/broker_equity_snapshots.csv"
    path.parent.mkdir(parents=True)
    return path


def record(day="2026-01-01", equity="1000000", hour="16", run_id=None):
    return {
        "run_id": run_id or f"{day.replace('-', '')}_{hour}0000",
        "run_date": day,
        "fetched_at_kst": f"{day}T{hour}:00:01+09:00",
        **dict.fromkeys(AMOUNT_FIELDS, "0"),
        "total_asset_krw": equity,
        "source": json.dumps(EXPECTED_SOURCE, sort_keys=True),
        "valuation_currency": "KRW",
    }


def write_records(path, rows):
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def report_args(tmp_path, source="broker_krw"):
    return argparse.Namespace(
        data_source=source, snapshots="data/live/account_snapshots.csv", benchmarks=["SPY", "IWM"],
        output=str(tmp_path / "report"), start_date=None, end_date=None,
        publish_latest=True, history=True, report_run_id="diagnostic-run",
    )


def test_stage2_persisted_csv_is_loaded(broker_path):
    assert HEADERS == BROKER_EQUITY_SNAPSHOT_HEADERS
    row = record()
    equity = {field: float(row[field]) for field in AMOUNT_FIELDS}
    equity.update(fetched_at_kst=row["fetched_at_kst"], source=EXPECTED_SOURCE, query_parameters={
        "WCRC_FRCR_DVSN_CD": "01", "NATN_CD": "840", "TR_MKET_CD": "00", "INQR_DVSN_CD": "00",
    })
    append_broker_equity_snapshot(row["run_id"], row["run_date"], equity)
    original = broker_path.read_bytes()
    result = load_broker_equity(as_of=AS_OF)
    assert result.daily["total_asset_krw"].tolist() == [1000000.0]
    assert result.daily["cash_krw"].tolist() == [0.0]
    assert result.original_csv.encode() == original == broker_path.read_bytes()


def test_latest_valid_run_sorted_by_observation_time(broker_path):
    rows = [record("2026-01-03", "3000000"), record(equity="1500000", hour="18", run_id="a"),
            record(run_id="z"), {**record(hour="23"), "valuation_currency": "USD"}]
    write_records(broker_path, rows)
    result = load_broker_equity(as_of=AS_OF)
    assert result.daily["total_asset_krw"].tolist() == [1500000, 3000000]
    assert result.daily["run_id"].tolist()[0] == "a"
    assert any("duplicate observation date" in warning for warning in result.warnings)
    assert any("Missing calendar" in warning and "2026-01-02" in warning for warning in result.warnings)
    assert any("discontinuity" in warning for warning in result.warnings)
    assert any("Stale observations" in warning for warning in result.warnings)
    assert result.original_csv.encode() == broker_path.read_bytes()


def test_invalid_utf8_is_unusable_and_preserved_byte_for_byte(broker_path):
    original = b"run_id,run_date,fetched_at_kst\nsecret\xff,2026-01-01,2026-01-01T16:00:01+09:00\n"
    broker_path.write_bytes(original)

    result = load_broker_equity(as_of=AS_OF)

    assert result.daily.empty
    assert result.original_csv == ""
    assert result.original_csv_bytes == original
    assert broker_path.read_bytes() == original
    assert result.warnings == ["Invalid UTF-8 in broker KRW snapshot CSV; no observations selected."]
    assert "secret" not in " ".join(result.warnings)


def test_valid_snapshot_corrupted_with_invalid_utf8_selects_nothing(broker_path):
    valid_snapshot = broker_path.parent / "valid.csv"
    write_records(valid_snapshot, [record(), record("2026-01-02", "1100000")])
    original = valid_snapshot.read_bytes() + b"\xff"
    broker_path.write_bytes(original)

    result = load_broker_equity("2026-01-02", "2026-01-04", as_of=AS_OF)

    assert result.daily.empty
    assert result.original_csv_bytes == original
    assert any("Invalid UTF-8" in warning for warning in result.warnings)
    assert not any("Missing calendar observation dates" in warning for warning in result.warnings)


@pytest.fixture
def fail_snapshot_read():
    """Inject failures only at the input boundary, leaving report output usable."""
    def fail(stage, patcher):
        path = MagicMock(wraps=broker_equity.BROKER_EQUITY_PATH)
        error = OSError("private/account/path and sensitive contents")
        if stage in {"exists", "stat"}:
            getattr(path, stage).side_effect = error
        elif stage in {"open", "permission", "disappeared"}:
            errors = {"open": error, "permission": PermissionError(str(error)),
                      "disappeared": FileNotFoundError(str(error))}
            path.open.side_effect = errors[stage]
        elif stage == "lock":
            patcher.setattr(broker_equity.fcntl, "flock", MagicMock(side_effect=error))
        elif stage == "read":
            opener = mock_open(read_data=b"")
            opener.return_value.read.side_effect = error
            path.open = opener
            patcher.setattr(broker_equity.fcntl, "flock", MagicMock())
        else:
            raise AssertionError("Unknown failure stage")
        patcher.setattr(broker_equity, "BROKER_EQUITY_PATH", path)
        return path
    return fail


@pytest.mark.parametrize("stage", ["exists", "stat", "open", "permission", "disappeared", "lock", "read"])
def test_snapshot_filesystem_failure_is_sanitized_and_recovers(broker_path, monkeypatch, fail_snapshot_read, stage):
    write_records(broker_path, [record()])
    original = broker_path.read_bytes()
    with monkeypatch.context() as scoped:
        path = fail_snapshot_read(stage, scoped)
        result = load_broker_equity("2026-01-02", "2026-01-04", as_of=AS_OF)
        assert result.daily.empty
        assert result.original_csv == "" and result.original_csv_bytes is None
        assert result.warnings == [
            "Broker KRW snapshot CSV is unavailable or unreadable; no fallback source used."]
        assert not any("Missing calendar observation dates" in warning for warning in result.warnings)
        if stage == "read":
            path.open.assert_called_once_with("rb")
            broker_equity.fcntl.flock.assert_called_once_with(path.open.return_value, broker_equity.fcntl.LOCK_SH)

    recovered = load_broker_equity(as_of=AS_OF)
    assert recovered.daily["total_asset_krw"].tolist() == [1000000.0]
    assert recovered.original_csv_bytes == original == broker_path.read_bytes()


def test_snapshot_programming_errors_propagate(broker_path, monkeypatch):
    write_records(broker_path, [record()])
    path = MagicMock(wraps=broker_equity.BROKER_EQUITY_PATH)
    path.open.side_effect = RuntimeError("programming error")
    monkeypatch.setattr(broker_equity, "BROKER_EQUITY_PATH", path)
    with pytest.raises(RuntimeError, match="programming error"):
        load_broker_equity(as_of=AS_OF)


@pytest.mark.parametrize("boundary", ["output", "publication"])
def test_report_filesystem_errors_propagate(broker_path, tmp_path, monkeypatch, boundary):
    write_records(broker_path, [record()])
    failure = MagicMock(side_effect=OSError("output failure"))
    if boundary == "output":
        monkeypatch.setattr(Path, "write_bytes", failure)
    else:
        monkeypatch.setattr(performance_report.shutil, "copy2", failure)
    with pytest.raises(OSError, match="output failure"):
        performance_report.build_report(report_args(tmp_path))


def test_duplicate_run_ids_and_conflicts_are_reported(broker_path):
    row = record()
    write_records(broker_path, [row, row, record("2026-01-02")])
    result = load_broker_equity(as_of=AS_OF)
    assert len(result.daily) == 2
    assert any("duplicate run ID" in warning for warning in result.warnings)
    write_records(broker_path, [row, {**row, "total_asset_krw": "999"}, record("2026-01-02")])
    result = load_broker_equity(as_of=AS_OF)
    assert result.daily["run_date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-01-02"]
    assert any("conflicting duplicate" in warning for warning in result.warnings)


@pytest.mark.parametrize("invalid_first", [False, True])
def test_conflicting_run_with_invalid_record_is_quarantined(broker_path, invalid_first):
    good = record()
    bad = {**good, "valuation_currency": "USD"}
    write_records(broker_path, [bad, good] if invalid_first else [good, bad])
    assert load_broker_equity(as_of=AS_OF).daily.empty


def test_timestamp_tie_break_is_deterministic(broker_path):
    rows = [record(run_id="b", equity="1200000"), record(run_id="a")]
    for order in [rows, list(reversed(rows))]:
        write_records(broker_path, order)
        result = load_broker_equity(as_of=AS_OF)
        assert result.daily["run_id"].tolist() == ["b"]
        assert any("tie-break" in warning for warning in result.warnings)


def test_timestamp_with_invalid_separator_is_rejected_and_preserved(broker_path):
    invalid = {**record(), "fetched_at_kst": "2026-01-01X16:00:00+09:00"}
    write_records(broker_path, [invalid])
    original = broker_path.read_bytes()

    result = load_broker_equity(as_of=AS_OF)

    assert result.daily.empty
    assert result.original_csv_bytes == original == broker_path.read_bytes()
    assert any("Row 2: invalid broker KRW record" in warning for warning in result.warnings)
    assert "2026-01-01X16:00:00+09:00" not in " ".join(result.warnings)


def test_invalid_timestamp_does_not_discard_valid_rows_or_break_order(broker_path):
    rows = [
        {**record("2026-01-02", "2000000"), "fetched_at_kst": "2026-01-02T16:00:00+09:00"},
        {**record("2026-01-01", "1000000"), "fetched_at_kst": "2026-01-01X17:00:00+09:00"},
        {**record("2026-01-02", "2100000", run_id="later"),
         "fetched_at_kst": "2026-01-02T16:30:00+09:00"},
        {**record("2026-01-01", "1100000", run_id="earlier"),
         "fetched_at_kst": "2026-01-01 16:15:00+09:00"},
    ]
    write_records(broker_path, rows)

    result = load_broker_equity(as_of=AS_OF)

    assert result.daily["run_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-01", "2026-01-02",
    ]
    assert result.daily["run_id"].tolist() == ["earlier", "later"]
    assert result.daily["total_asset_krw"].tolist() == [1100000.0, 2100000.0]
    assert any("invalid broker KRW record" in warning for warning in result.warnings)


def test_valid_mixed_iso_timestamp_precision_and_numeric_notation(broker_path):
    write_records(broker_path, [
        {**record(), "fetched_at_kst": "2026-01-01T16:00+09:00", "total_asset_krw": "1e6"},
        {**record("2026-01-02"), "fetched_at_kst": "2026-01-02 16:00:01+09:00"},
        {**record("2026-01-03"), "fetched_at_kst": "2026-01-03T16:00+09:00"},
        {**record("2026-01-04"), "fetched_at_kst": "2026-01-04T16:00:01.123456789+09:00"},
    ])
    result = load_broker_equity(as_of=AS_OF)
    assert result.daily["run_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04",
    ]
    assert result.daily["total_asset_krw"].tolist() == [1000000.0] * 4


@pytest.mark.parametrize("field", AMOUNT_FIELDS)
@pytest.mark.parametrize("value", ["", None, "bad", "nan", "inf", "-inf", "1e309", "True"])
def test_missing_or_nonfinite_amounts_rejected(broker_path, field, value):
    write_records(broker_path, [{**record(), field: value}])
    result = load_broker_equity(as_of=AS_OF)
    assert result.daily.empty
    assert any("invalid broker KRW record" in warning for warning in result.warnings)


@pytest.mark.parametrize("replacement", [
    {"total_asset_krw": "0"}, {"total_asset_krw": "-1"}, {"run_id": " "},
    {"run_date": ""}, {"run_date": "2026-02-30"}, {"run_date": "20260101"},
    {"run_date": "0000-01-01", "fetched_at_kst": "0000-01-01T16:00:00+09:00"},
    {"fetched_at_kst": "bad"}, {"fetched_at_kst": "2026-01-01T16:00:00"},
    {"fetched_at_kst": "2026-01-01T16:00:00+00:00"},
    {"fetched_at_kst": "2025-12-31T16:00:00+09:00"},
    {"run_date": "2026-01-11", "fetched_at_kst": "2026-01-11T16:00:00+09:00"},
    {"source": "legacy_usd"}, {"source": "{}"}, {"source": "null"},
    {"source": json.dumps({**EXPECTED_SOURCE, "tr_id": "other"})},
    {"source": json.dumps({**EXPECTED_SOURCE, "provider": "other"})},
    {"source": json.dumps({**EXPECTED_SOURCE, "endpoint": "other"})},
    {"valuation_currency": "USD"}, {"valuation_currency": "krw"}, {"valuation_currency": ""},
])
def test_invalid_metadata_or_nonpositive_equity(broker_path, replacement):
    write_records(broker_path, [{**record(), **replacement}])
    assert load_broker_equity(as_of=AS_OF).daily.empty


def test_stale_timestamp_warned_and_recent_observation_retained(broker_path):
    write_records(broker_path, [{**record(), "fetched_at_kst": "2025-12-31T16:00:00+09:00"},
                                record("2026-01-10")])
    result = load_broker_equity(as_of=AS_OF)
    assert result.daily["run_date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-01-10"]
    assert any("stale observation" in warning for warning in result.warnings)
    assert not any("Stale observations" in warning for warning in result.warnings)


@pytest.mark.parametrize("age,stale", [(3, False), (4, True)])
def test_staleness_threshold(broker_path, age, stale):
    write_records(broker_path, [record(f"2026-01-{10 - age:02}")])
    warnings = load_broker_equity(as_of=AS_OF).warnings
    assert any("Stale observations" in warning for warning in warnings) == stale


@pytest.mark.parametrize(("previous", "equity", "expected_warning"), [
    ("1000000", "900000", True), ("1000000", "1100000", True),
    ("1000000", "900001", False), ("1000000", "1099999", False),
    ("1000000", "899999", True), ("1000000", "1100001", True),
    ("100.1", "90.09", True), ("100.1", "110.11", True),
    ("100.1", "90.09000000000002", False), ("100.1", "110.10999999999999", False),
    ("100.1", "90.08", True), ("100.1", "110.12", True),
])
def test_discontinuity_threshold_uses_raw_amount_boundary(broker_path, previous, equity, expected_warning):
    write_records(broker_path, [record("2026-01-01", previous), record("2026-01-02", equity)])

    result = load_broker_equity(as_of=AS_OF)

    assert result.daily["total_asset_krw"].tolist() == [float(previous), float(equity)]
    assert any("raw equity discontinuity" in warning for warning in result.warnings) is expected_warning


@pytest.mark.parametrize("suffix", [",extra", "\nshort", '\n"unclosed'])
def test_malformed_records_preserve_input_and_warn(broker_path, suffix):
    write_records(broker_path, [record()])
    # Extra fields on the first data row, missing fields on a later row, and malformed quoting.
    text = broker_path.read_text().rstrip("\n") + suffix + "\n"
    broker_path.write_text(text)
    result = load_broker_equity(as_of=AS_OF)
    assert result.warnings
    assert result.original_csv == text == broker_path.read_text()
    if suffix != "\nshort":
        assert result.daily.empty


def test_wrong_header_fails_closed(broker_path):
    broker_path.write_text("run_id,run_date,total_equity_usd,broker_total_asset_krw\nrun,2026-01-01,10,1000\n")
    result = load_broker_equity("2026-01-02", "2026-01-04", as_of=AS_OF)
    assert result.daily.empty
    assert any("header" in warning for warning in result.warnings)
    assert not any("Missing calendar observation dates" in warning for warning in result.warnings)


def test_period_filter_missing_boundaries_and_no_interpolation(broker_path):
    write_records(broker_path, [record(), record("2026-01-03"), record("2026-01-05")])
    result = load_broker_equity("2026-01-02", "2026-01-04", as_of=AS_OF)
    assert result.daily["run_date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-01-03"]
    assert any("2026-01-02, 2026-01-04" in warning for warning in result.warnings)
    assert "2026-01-05" in result.original_csv


def test_empty_selected_period_reports_all_requested_dates_and_preserves_input(broker_path):
    write_records(broker_path, [record("2026-01-01"), record("2026-01-05")])
    original = broker_path.read_bytes()

    result = load_broker_equity("2026-01-02", "2026-01-04", as_of=AS_OF)

    assert result.daily.empty
    assert any("2026-01-02, 2026-01-03, 2026-01-04" in warning
               for warning in result.warnings)
    assert result.original_csv_bytes == original == broker_path.read_bytes()


@pytest.mark.parametrize(("start_date", "end_date", "rows", "missing"), [
    ("2026-01-02", "2026-01-04", [record("2026-01-03"), record("2026-01-04")], "2026-01-02"),
    ("2026-01-01", "2026-01-03", [record("2026-01-01"), record("2026-01-02")], "2026-01-03"),
])
def test_only_missing_requested_boundary_is_reported(broker_path, start_date, end_date, rows, missing):
    write_records(broker_path, rows)

    result = load_broker_equity(start_date, end_date, as_of=AS_OF)

    assert len(result.daily) == len(rows)
    assert any(f"Missing calendar observation dates (no interpolation): {missing}" == warning
               for warning in result.warnings)


def test_requested_interval_keeps_observations_and_reports_internal_and_end_gaps(broker_path):
    write_records(broker_path, [record("2026-01-01"), record("2026-01-03"), record("2026-01-05")])

    result = load_broker_equity("2026-01-01", "2026-01-06", as_of=AS_OF)

    assert result.daily["run_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-01", "2026-01-03", "2026-01-05",
    ]
    assert any("2026-01-02, 2026-01-04, 2026-01-06" in warning for warning in result.warnings)


def test_all_requested_dates_present_have_no_missing_date_warning(broker_path):
    write_records(broker_path, [record(f"2026-01-0{day}") for day in range(1, 4)])

    result = load_broker_equity("2026-01-01", "2026-01-03", as_of=AS_OF)

    assert len(result.daily) == 3
    assert not any("Missing calendar observation dates" in warning for warning in result.warnings)


def test_default_date_range_remains_bounded_by_selected_observations(broker_path):
    write_records(broker_path, [record("2026-01-01"), record("2026-01-03")])

    result = load_broker_equity(as_of=AS_OF)

    assert len(result.daily) == 2
    assert any("2026-01-02" in warning for warning in result.warnings)
    assert not any("2026-01-04" in warning for warning in result.warnings)


def test_krw_report_source_isolation_publication_and_raw_chart(broker_path, tmp_path, monkeypatch):
    write_records(broker_path, [record(), record("2026-01-03", "3000000")])
    original = broker_path.read_bytes()
    legacy_path = broker_path.with_name("account_snapshots.csv")
    legacy_path.write_text("run_date,total_equity_usd,broker_total_asset_krw\n2026-01-02,999999,888888\n")
    cash_flows = broker_path.with_name("cash_flows.csv")
    cash_flows.write_text("date,amount,currency,type,memo\n2026-01-03,2000000,KRW,deposit,test\n")
    legacy_loader = MagicMock(side_effect=AssertionError("KRW mode must not load legacy equity"))
    cash_loader = MagicMock(side_effect=AssertionError("Completeness unknown: do not read cash flows"))
    benchmark_loader = MagicMock(side_effect=AssertionError("Do not compare USD benchmarks with raw KRW"))
    monkeypatch.setattr(performance_report, "load_strategy_equity_curve_with_warnings", legacy_loader)
    monkeypatch.setattr(performance_report, "_load_cash_flows", cash_loader)
    monkeypatch.setattr(performance_report, "fetch_benchmark_prices", benchmark_loader)
    plot = MagicMock(wraps=performance_report._save_line_chart)  # pylint: disable=protected-access
    monkeypatch.setattr(performance_report, "_save_line_chart", plot)
    args = report_args(tmp_path)
    performance_report.build_report(args)
    for loader in [legacy_loader, cash_loader, benchmark_loader]:
        loader.assert_not_called()
    assert plot.call_args_list[0].args[0]["Broker equity"].tolist() == [1000000, 3000000]
    assert "KRW" in plot.call_args_list[0].args[3]
    output = Path(args.output)
    for bundle in [output, output / "latest", output / "history/diagnostic-run"]:
        summary = json.loads((bundle / "performance_summary.json").read_text())
        assert summary["data_source"] == "broker_krw"
        assert summary["valuation_currency"] == "KRW"
        assert summary["returns_validated"] is False
        assert summary["latest_equity_krw"] == 3000000
        for key, value in summary.items():
            if key.endswith("_pct") or key.startswith("excess_return_vs_"):
                assert value is None
        curve = pd.read_csv(bundle / "equity_curve.csv")
        assert curve["total_asset_krw"].tolist() == [1000000, 3000000]
        assert curve["run_date"].tolist() == ["2026-01-01", "2026-01-03"]
        assert "Strategy" not in curve
        assert (bundle / "broker_equity_observations.csv").read_bytes() == original
        for name in [*performance_report.RETURN_CHARTS, performance_report.RAW_KRW_CHART]:
            assert (bundle / "charts" / name).stat().st_size > 0
        html = (bundle / "index.html").read_text()
        assert "not investment returns" in html and "charts/raw_equity_krw.png" in html
        assert "Investment returns: N/A" in html
        assert "raw equity discontinuity" in (bundle / "performance_report.md").read_text()
    assert broker_path.read_bytes() == original
    message = build_performance_summary_message(summary, "https://example.test/latest/")
    assert "자산 진단 (KRW" in message and "현금흐름 완전성 미확인" in message
    assert "전략 성과" not in message and "https://example.test/latest/" in message


@pytest.mark.parametrize("contents", [None, "", ",".join(HEADERS) + "\n", "bad,header\n1,2\n"])
def test_no_valid_krw_data_never_falls_back(broker_path, tmp_path, monkeypatch, contents):
    if contents is not None:
        broker_path.write_text(contents)
    broker_path.with_name("account_snapshots.csv").write_text("run_date,total_equity_usd\n2026-01-01,123\n")
    monkeypatch.setattr(performance_report, "fetch_benchmark_prices", MagicMock(side_effect=AssertionError))
    args = report_args(tmp_path)
    args.start_date, args.end_date = "2026-01-02", "2026-01-04"
    performance_report.build_report(args)
    summary = json.loads((Path(args.output) / "latest/performance_summary.json").read_text())
    assert summary["num_days"] == 0 and summary["latest_equity_krw"] is None
    assert summary["cumulative_return_pct"] is None
    assert any("No valid broker KRW" in warning for warning in summary["data_quality_warnings"])
    assert not any("Missing calendar observation dates" in warning
                   for warning in summary["data_quality_warnings"])
    assert pd.read_csv(Path(args.output) / "equity_curve.csv").empty


def test_all_invalid_timestamps_refresh_published_krw_diagnostics(
        broker_path, tmp_path, monkeypatch):
    write_records(broker_path, [record(), record("2026-01-02", "1100000")])
    legacy_loader = MagicMock(side_effect=AssertionError("KRW mode must not load legacy equity"))
    benchmark_loader = MagicMock(side_effect=AssertionError("KRW mode must not load benchmarks"))
    monkeypatch.setattr(performance_report, "load_strategy_equity_curve_with_warnings", legacy_loader)
    monkeypatch.setattr(performance_report, "fetch_benchmark_prices", benchmark_loader)
    args = report_args(tmp_path)

    performance_report.build_report(args)
    previous = json.loads((Path(args.output) / "latest/performance_summary.json").read_text())
    assert previous["latest_equity_krw"] == 1100000

    invalid_rows = [
        {**record(), "fetched_at_kst": "2026-01-01X16:00:01+09:00"},
        {**record("2026-01-02", "1100000"), "fetched_at_kst": "2026-01-02T16:00:01+00:00"},
    ]
    write_records(broker_path, invalid_rows)
    original = broker_path.read_bytes()

    performance_report.build_report(args)

    for loader in [legacy_loader, benchmark_loader]:
        loader.assert_not_called()
    output = Path(args.output)
    for bundle in [output, output / "latest", output / "history/diagnostic-run"]:
        summary = json.loads((bundle / "performance_summary.json").read_text())
        assert summary["data_source"] == "broker_krw"
        assert summary["num_days"] == 0 and summary["latest_equity_krw"] is None
        assert summary["returns_validated"] is False
        assert summary["cumulative_return_pct"] is None
        assert summary["cash_flow_adjusted_return_pct"] is None
        assert summary["cagr_pct"] is None
        assert summary["max_drawdown_pct"] is None
        assert summary["annualized_volatility_pct"] is None
        assert summary["cumulative_return_SPY_pct"] is None
        assert summary["excess_return_vs_SPY"] is None
        warnings = " ".join(summary["data_quality_warnings"])
        assert "invalid broker KRW record" in warnings
        assert "No valid broker KRW observations" in warnings
        assert "2026-01-01X16:00:01+09:00" not in warnings
        assert pd.read_csv(bundle / "equity_curve.csv").empty
        assert (bundle / "broker_equity_observations.csv").read_bytes() == original
        report = (bundle / "performance_report.md").read_text()
        assert "Investment returns: N/A" in report
        assert "No valid broker KRW observations" in report
    assert json.loads((output / "latest/performance_summary.json").read_text())[
        "latest_equity_krw"] is None


def test_absent_requested_period_publishes_empty_diagnostic_and_missing_dates(
        broker_path, tmp_path, monkeypatch):
    write_records(broker_path, [record("2026-01-01"), record("2026-01-05")])
    original = broker_path.read_bytes()
    monkeypatch.setattr(performance_report, "fetch_benchmark_prices", MagicMock(side_effect=AssertionError))
    args = report_args(tmp_path)
    args.start_date, args.end_date = "2026-01-02", "2026-01-04"

    performance_report.build_report(args)

    output = Path(args.output)
    for bundle in [output, output / "latest", output / "history/diagnostic-run"]:
        summary = json.loads((bundle / "performance_summary.json").read_text())
        assert summary["num_days"] == 0 and summary["latest_equity_krw"] is None
        assert summary["cumulative_return_pct"] is None
        warning = next(w for w in summary["data_quality_warnings"]
                       if "Missing calendar observation dates" in w)
        assert "2026-01-02, 2026-01-03, 2026-01-04" in warning
        assert any("No valid broker KRW observations" in w
                   for w in summary["data_quality_warnings"])
        for metric in ["cash_flow_adjusted_return_pct", "cagr_pct", "max_drawdown_pct",
                       "annualized_volatility_pct", "cumulative_return_SPY_pct", "excess_return_vs_SPY"]:
            assert summary[metric] is None
        assert pd.read_csv(bundle / "equity_curve.csv").empty
        report = (bundle / "performance_report.md").read_text()
        assert "Investment returns: N/A" in report
        assert warning in report
        assert (bundle / "broker_equity_observations.csv").read_bytes() == original


@pytest.mark.parametrize("failure", ["utf8", "filesystem"])
def test_unusable_input_publishes_empty_krw_latest_and_history(
        broker_path, tmp_path, monkeypatch, fail_snapshot_read, failure):
    write_records(broker_path, [record(), record("2026-01-02", "1100000")])
    for path, content in [
        (broker_path.with_name("account_snapshots.csv"), "run_date,total_equity_usd\n2026-01-01,999\n"),
        (broker_path.with_name("cash_flows.csv"), "date,amount,currency,type,memo\n2026-01-01,1,KRW,deposit,x\n"),
    ]:
        path.write_text(content)
    monkeypatch.setattr(performance_report, "load_strategy_equity_curve_with_warnings",
                        MagicMock(side_effect=AssertionError("KRW mode must not load legacy equity")))
    monkeypatch.setattr(performance_report, "_load_cash_flows",
                        MagicMock(side_effect=AssertionError("KRW mode must not load cash flows")))
    monkeypatch.setattr(performance_report, "fetch_benchmark_prices",
                        MagicMock(side_effect=AssertionError("KRW mode must not load benchmarks")))
    args = report_args(tmp_path)

    performance_report.build_report(args)
    assert json.loads((Path(args.output) / "latest/performance_summary.json").read_text())["num_days"] == 2

    original = broker_path.read_bytes()
    corrupted = original + b"\xff"
    with monkeypatch.context() as scoped:
        if failure == "utf8":
            broker_path.write_bytes(corrupted)
        else:
            fail_snapshot_read("permission", scoped)
        performance_report.build_report(args)

    output = Path(args.output)
    for bundle in [output, output / "latest", output / "history/diagnostic-run"]:
        summary = json.loads((bundle / "performance_summary.json").read_text())
        assert summary["data_source"] == "broker_krw"
        assert summary["num_days"] == 0 and summary["latest_equity_krw"] is None
        assert summary["returns_validated"] is False
        assert summary["cumulative_return_pct"] is None
        assert summary["cash_flow_adjusted_return_pct"] is None
        assert summary["cagr_pct"] is None
        assert summary["max_drawdown_pct"] is None
        assert summary["annualized_volatility_pct"] is None
        assert summary["cumulative_return_SPY_pct"] is None
        assert summary["excess_return_vs_SPY"] is None
        expected_warning = "Invalid UTF-8" if failure == "utf8" else "unavailable or unreadable"
        assert any(expected_warning in warning for warning in summary["data_quality_warnings"])
        assert pd.read_csv(bundle / "equity_curve.csv").empty
        artifact = bundle / "broker_equity_observations.csv"
        if failure == "utf8":
            assert artifact.read_bytes() == corrupted
        else:
            assert not artifact.exists()
            assert 'href="broker_equity_observations.csv"' not in (bundle / "index.html").read_text()
        report = (bundle / "performance_report.md").read_text()
        assert "Investment returns: N/A" in report
        assert expected_warning in report
        if failure == "filesystem":
            assert "Original snapshot input unavailable" in report
            assert "are preserved in broker_equity_observations.csv" not in report

    if failure == "filesystem":
        performance_report.build_report(args)
        assert (output / "latest/broker_equity_observations.csv").read_bytes() == original
        assert json.loads((output / "latest/performance_summary.json").read_text())["num_days"] == 2


def test_mode_switch_replaces_old_artifacts_without_stale_returns(broker_path, tmp_path, monkeypatch):
    write_records(broker_path, [record(), record("2026-01-02", "3000000")])
    pd.DataFrame({"run_date": ["2026-01-01", "2026-01-02"], "total_equity_usd": [100, 110]}).to_csv(
        broker_path.with_name("account_snapshots.csv"), index=False,
    )
    monkeypatch.setattr(performance_report, "fetch_benchmark_prices", lambda *_a: pd.DataFrame())
    args = report_args(tmp_path, "legacy_usd")
    performance_report.build_report(args)
    output = Path(args.output)
    legacy_chart = (output / "latest/charts/cumulative_return.png").read_bytes()
    legacy_summary = json.loads((output / "performance_summary.json").read_text())
    assert legacy_summary["cumulative_return_pct"] == pytest.approx(10)
    args.data_source = "broker_krw"
    performance_report.build_report(args)
    assert (output / "latest/charts/cumulative_return.png").read_bytes() != legacy_chart
    del args.data_source  # Existing Namespace callers still default to legacy_usd.
    performance_report.build_report(args)
    assert json.loads((output / "performance_summary.json").read_text()) == legacy_summary
    assert (output / "latest/charts/cumulative_return.png").read_bytes() == legacy_chart
    for bundle in [output, output / "latest", output / "history/diagnostic-run"]:
        assert not (bundle / "charts/raw_equity_krw.png").exists()
        assert not (bundle / "broker_equity_observations.csv").exists()


@pytest.mark.parametrize("source", [None, "legacy_usd", "broker_krw"])
def test_runner_source_selection_preserves_output_and_publishing(monkeypatch, source):
    monkeypatch.setenv("PERFORMANCE_REPORT_ENABLED", "true")
    monkeypatch.setenv("PERFORMANCE_REPORT_OUTPUT_DIR", "custom/output")
    monkeypatch.setenv("PERFORMANCE_REPORT_PUBLISH_LATEST", "true")
    monkeypatch.setenv("PERFORMANCE_REPORT_HISTORY", "true")
    if source is None:
        monkeypatch.delenv("PERFORMANCE_REPORT_DATA_SOURCE", raising=False)
    else:
        monkeypatch.setenv("PERFORMANCE_REPORT_DATA_SOURCE", source)
    builder = MagicMock()
    monkeypatch.setattr("performance_report_runner.build_report", builder)
    assert run_performance_report_safely()
    args = builder.call_args.args[0]
    assert args.data_source == (source or "legacy_usd")
    assert args.output == "custom/output" and args.publish_latest and args.history


def test_unknown_source_fails_before_overwriting_output(tmp_path, monkeypatch):
    args = report_args(tmp_path, "unknown")
    with pytest.raises(ValueError, match="Unsupported performance data source"):
        performance_report.build_report(args)
    assert not Path(args.output).exists()
    monkeypatch.setenv("PERFORMANCE_REPORT_ENABLED", "true")
    monkeypatch.setenv("PERFORMANCE_REPORT_DATA_SOURCE", "unknown")
    monkeypatch.setenv("PERFORMANCE_REPORT_OUTPUT_DIR", args.output)
    assert not run_performance_report_safely()
    assert not Path(args.output).exists()


def test_cli_defaults_and_direct_script_execution(broker_path, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["performance_report.py"])
    assert performance_report.parse_args().data_source == "legacy_usd"
    write_records(broker_path, [record()])
    script = Path(performance_report.__file__)
    completed = subprocess.run(
        [sys.executable, str(script), "--data-source", "broker_krw", "--output", str(tmp_path / "cli")],
        check=False, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads((tmp_path / "cli/performance_summary.json").read_text())["data_source"] == "broker_krw"
