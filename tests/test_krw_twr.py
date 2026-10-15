"""Synthetic broker-to-report regressions for Stage 4's accounting boundary."""

import argparse
import csv
import json
import math
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from telegram_utils import build_performance_summary_message
from tools import performance_report
from tools.broker_equity import AMOUNT_FIELDS, EXPECTED_SOURCE, HEADERS, load_broker_equity
from tools.krw_twr import FLOW_HEADERS, calculate_twr, load_external_flow_ledger


def stamp(day):
    return f"2026-01-{day:02d}T16:00:00+09:00"


def snapshot(day, equity, **overrides):
    return {
        "run_id": f"run-{day}", "run_date": f"2026-01-{day:02d}", "fetched_at_kst": stamp(day),
        **dict.fromkeys(AMOUNT_FIELDS, "0"), "total_asset_krw": str(equity),
        "source": json.dumps(EXPECTED_SOURCE), "valuation_currency": "KRW", **overrides,
    }


def attestation(day=2, **overrides):
    return {
        "record_id": f"coverage-{day}", "interval_start": stamp(day - 1), "interval_end": stamp(day),
        "effective_at": "", "amount_krw": "0", "currency": "KRW", "classification": "complete",
        "timing": "none", "source": "synthetic statement", "description": "Entire interval reconciled",
        "verification_status": "verified", **overrides,
    }


def flow(amount, timing="end", day=2, **overrides):
    return attestation(day, **{
        "record_id": f"event-{day}-{amount}-{timing}", "amount_krw": str(amount),
        "classification": "deposit" if amount > 0 else "withdrawal", "timing": timing,
        "effective_at": stamp(day - 1 if timing == "start" else day), **overrides,
    })


def write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "data/live"
    folder.mkdir(parents=True)
    return folder / "broker_equity_snapshots.csv", folder / "krw_external_flows.csv"


def compute(inputs, snapshots, ledger_rows, **kwargs):
    equity_path, ledger_path = inputs
    write_csv(equity_path, HEADERS, snapshots)
    if ledger_rows is not None:
        write_csv(ledger_path, FLOW_HEADERS, ledger_rows)
    loaded = load_broker_equity(kwargs.get("start_date"), kwargs.get("end_date"))
    return calculate_twr(loaded.daily, load_external_flow_ledger(ledger_path),
                         rejected_records=loaded.rejected_records, **kwargs)


@pytest.mark.parametrize("ending,events,expected", [
    (110, [], .1),                                      # Market gain, no flows.
    (150, [flow(50)], 0),                               # Deposit, no market gain.
    (60, [flow(-40)], 0),                               # Withdrawal, no market loss.
    (160, [flow(50)], .1),                              # End deposit + gain.
    (165, [flow(50, "start")], .1),                     # Start deposit + gain.
    (150, [flow(50, classification="domestic_to_overseas")], 0),
    (60, [flow(-40, classification="overseas_to_domestic")], 0),
    (170, [flow(50), flow(20)], 0),                      # Repeated same-day flows.
    (100, [flow(50), flow(-50)], 0),                     # Gross flows, zero net.
    (125, [flow(50, "start"), flow(-40)], .1),           # Both boundaries.
])
def test_mathematical_reconciliation(inputs, ending, events, expected):
    curve, summary = compute(inputs, [snapshot(1, 100), snapshot(2, ending)], [attestation(), *events])
    assert curve.iloc[1]["daily_return"] == pytest.approx(expected)
    assert curve["twr_index"].tolist() == pytest.approx([100, 100 * (1 + expected)])
    assert summary["cumulative_return_pct"] == pytest.approx(expected * 100)
    assert summary["returns_validated"] is True
    assert summary["external_cash_flow_completeness"] == ("verified_nonzero" if events else "verified_zero")


@pytest.mark.parametrize("rows", [None, [], [flow(50)], [attestation(classification="incomplete")],
                                  [attestation(verification_status="pending")],
                                  [attestation(), flow(50, verification_status="pending")]])
def test_missing_or_incomplete_history_is_never_zero(inputs, rows):
    curve, summary = compute(inputs, [snapshot(1, 100), snapshot(2, 150)], rows)
    assert not curve.iloc[1]["return_valid"]
    assert summary["external_cash_flow_completeness"] == "unknown"
    assert summary["cumulative_return_pct"] is None
    assert summary["max_drawdown_pct"] is None
    assert summary["twr_unavailable_reasons"]


@pytest.mark.parametrize("timing,effective", [("intraday", "2026-01-02T12:00:00+09:00"),
                                               ("unknown", ""), ("unknown", "2026-01-02")])
def test_unvalued_flow_is_not_exact_daily_twr_even_if_net_zero(inputs, timing, effective):
    events = [flow(amount, timing, effective_at=effective) for amount in (50, -50)]
    curve, summary = compute(inputs, [snapshot(1, 100), snapshot(2, 100)], [attestation(), *events])
    assert summary["external_cash_flow_completeness"] == "verified_nonzero"
    assert summary["cumulative_return_pct"] is None
    assert "timing" in curve.iloc[1]["reason"]


@pytest.mark.parametrize("override", [
    {"currency": "USD"}, {"amount_krw": "nan"}, {"amount_krw": "inf"}, {"amount_krw": "-50"},
    {"source": ""}, {"description": ""}, {"record_id": ""}, {"verification_status": "assumed"},
    {"classification": "buy"}, {"classification": "sell"}, {"classification": "dividend"},
    {"classification": "fee"}, {"classification": "tax"}, {"effective_at": "2026-01-02"},
    {"effective_at": "2026-01-02T16:00:00"}, {"effective_at": "2026-01-03T16:00:00+09:00"},
    {"interval_start": stamp(3)}, {"timing": "assume_end"},
])
def test_invalid_ledger_records_fail_closed(inputs, override):
    curve, summary = compute(inputs, [snapshot(1, 100), snapshot(2, 150)],
                             [attestation(), {**flow(50), **override}])
    assert summary["external_cash_flow_completeness"] == "unknown"
    assert summary["cumulative_return_pct"] is None
    assert not curve.iloc[1]["return_valid"]


@pytest.mark.parametrize("rows", [
    [attestation(), flow(50), flow(50)],
    [attestation(), attestation(record_id="other")],
    [attestation(), attestation(3, interval_start=stamp(1))],
])
def test_duplicate_ids_attestations_and_overlaps_are_not_double_counted(inputs, rows):
    _, summary = compute(inputs, [snapshot(1, 100), snapshot(2, 150)], rows)
    assert summary["external_cash_flow_completeness"] == "unknown"


@pytest.mark.parametrize("contents", [b"", b"bad,header\n", b"\xff\xfe", b'"unterminated'])
def test_malformed_ledger_is_unknown(inputs, contents):
    inputs[1].write_bytes(contents)
    ledger = load_external_flow_ledger(inputs[1])
    assert not ledger.intervals and ledger.warnings


def test_unreadable_ledger_is_unknown(inputs):
    inputs[1].mkdir()
    assert load_external_flow_ledger(inputs[1]).warnings


@pytest.mark.parametrize("override", [{"total_asset_krw": "0"}, {"total_asset_krw": "-10"},
                                       {"total_asset_krw": "nan"}, {"total_asset_krw": "inf"},
                                       {"valuation_currency": "USD"}, {"source": "{}"}])
def test_rejected_equity_cannot_shrink_to_false_full_period(inputs, override):
    snapshots = [snapshot(1, 100, **override), snapshot(2, 150), snapshot(3, 150)]
    _, summary = compute(inputs, snapshots, [attestation(), attestation(3)])
    assert summary["cumulative_return_pct"] is None
    assert summary["returns_validated"] is False
    assert summary["valid_daily_return_count"] == 0
    assert "Rejected broker records" in " ".join(summary["twr_unavailable_reasons"])


def test_settlement_and_internal_components_never_create_returns(inputs):
    snapshots = [snapshot(1, 1000, stock_evaluation_krw="800", cash_krw="400", unsettled_buy_krw="200"),
                 snapshot(2, 1000, stock_evaluation_krw="800", cash_krw="200", unsettled_buy_krw="0")]
    _, summary = compute(inputs, snapshots, [attestation()])
    assert summary["cumulative_return_pct"] == 0


def test_dividends_fees_and_taxes_stay_in_performance(inputs):
    # Income +10 and costs -3 are already in the authoritative total.
    _, summary = compute(inputs, [snapshot(1, 100), snapshot(2, 107)], [attestation()])
    assert summary["cumulative_return_pct"] == 7


@pytest.mark.parametrize("end,event", [(50, flow(-100, "start")), (50, flow(50))])
def test_nonpositive_adjusted_capital_is_unavailable(inputs, end, event):
    curve, summary = compute(inputs, [snapshot(1, 100), snapshot(2, end)], [attestation(), event])
    assert summary["cumulative_return_pct"] is None
    assert "Nonpositive" in curve.iloc[1]["reason"]


def test_reproducible_chaining_drawdown_and_volatility(inputs):
    snapshots = [snapshot(1, 100), snapshot(2, 160), snapshot(3, 114), snapshot(4, 125.4)]
    ledger = [attestation(), flow(50), attestation(3), flow(-30, day=3), attestation(4)]
    curve, summary = compute(inputs, snapshots, ledger)
    # (160-50)/100=1.1; (114+30)/160=.9; 125.4/114=1.1.
    assert curve["twr_index"].tolist() == pytest.approx([100, 110, 99, 108.9])
    assert curve["drawdown_pct"].tolist() == pytest.approx([0, 0, -10, -1])
    assert summary["cumulative_return_pct"] == pytest.approx(8.9)
    assert summary["max_drawdown_pct"] == -10
    assert summary["annualized_volatility_pct"] == pytest.approx(math.sqrt(0.04 / 3) * math.sqrt(365.25) * 100)
    assert summary["volatility_scope"] == "full_period"
    reverse_curve, reverse_summary = compute(inputs, snapshots[::-1], ledger[::-1])
    pd.testing.assert_frame_equal(curve, reverse_curve)
    assert reverse_summary == summary


def test_incomplete_period_never_rechains_after_gap(inputs):
    snapshots = [snapshot(day, 100 + day) for day in range(1, 6)]
    curve, summary = compute(inputs, snapshots, [attestation(), attestation(4), attestation(5)])
    assert curve["return_valid"].tolist() == [False, True, False, True, True]
    assert curve["twr_index"].iloc[2:].isna().all()
    assert summary["cumulative_return_pct"] is None and summary["max_drawdown_pct"] is None
    assert summary["annualized_volatility_pct"] is not None
    assert summary["volatility_scope"] == "valid_returns_only_incomplete_period"
    assert summary["volatility_valid_return_count"] == 3


def test_calendar_gap_is_not_one_daily_return(inputs):
    curve, summary = compute(inputs, [snapshot(1, 100), snapshot(3, 120)],
                             [attestation(3, interval_start=stamp(1))])
    assert "calendar" in curve.iloc[1]["reason"]
    assert summary["cumulative_return_pct"] is None
    assert summary["expected_daily_return_count"] == 2


def test_missing_requested_endpoint_is_not_partial_period_return(inputs):
    _, summary = compute(inputs, [snapshot(2, 100), snapshot(3, 120)], [attestation(3)],
                         start_date="2026-01-01", end_date="2026-01-03")
    assert summary["cumulative_return_pct"] is None
    assert "Requested period endpoint" in " ".join(summary["twr_unavailable_reasons"])


def test_attestation_must_match_selected_snapshot_instants(inputs):
    _, summary = compute(inputs, [snapshot(1, 100), snapshot(2, 120, fetched_at_kst=stamp(2).replace("16:", "17:"))],
                         [attestation()])
    assert summary["external_cash_flow_completeness"] == "unknown"


def test_equivalent_timezone_instants_match(inputs):
    rows = [attestation(interval_start="2026-01-01T07:00:00Z", interval_end="2026-01-02T07:00:00Z")]
    _, summary = compute(inputs, [snapshot(1, 100), snapshot(2, 110)], rows)
    assert summary["cumulative_return_pct"] == 10


def test_full_report_publishing_and_legacy_isolation(inputs, tmp_path, monkeypatch):
    snapshots = [snapshot(1, 100), snapshot(2, 160), snapshot(3, 144)]
    compute(inputs, snapshots, [attestation(), flow(50), attestation(3)])
    legacy = inputs[0].with_name("cash_flows.csv")
    legacy.write_text("date,amount,currency,type,memo\n2026-01-02,999,USD,deposit,legacy\n")
    original = legacy.read_bytes(), inputs[0].read_bytes(), inputs[1].read_bytes()
    monkeypatch.setattr(performance_report, "fetch_benchmark_prices", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr("tools.krw_benchmarks.fetch_series", lambda *_args: pd.Series(dtype=float))
    monkeypatch.setattr(performance_report, "_load_cash_flows", MagicMock(side_effect=AssertionError))
    args = argparse.Namespace(data_source="broker_krw", start_date=None, end_date=None, benchmarks=["SPY"],
                              output=str(tmp_path / "report"), publish_latest=True, history=True, report_run_id="twr")
    performance_report.build_report(args)
    for bundle in (Path(args.output), Path(args.output) / "latest", Path(args.output) / "history/twr"):
        summary = json.loads((bundle / "performance_summary.json").read_text())
        assert summary["returns_validated"] is True
        assert summary["cumulative_return_pct"] == -1
        assert summary["cumulative_return_SPY_pct"] is None
        assert pd.read_csv(bundle / "twr_curve.csv")["twr_index"].tolist() == [100, 110, 99]
        assert "Investment returns: -1.00%" in (bundle / "index.html").read_text()
        assert "verified_nonzero" in (bundle / "performance_report.md").read_text()
        assert (bundle / "charts/cumulative_return.png").stat().st_size > 0
    assert "TWR): -1.00%" in build_performance_summary_message(summary, None)
    assert original == (legacy.read_bytes(), inputs[0].read_bytes(), inputs[1].read_bytes())
    inputs[1].unlink()
    performance_report.build_report(args)
    summary = json.loads((Path(args.output) / "latest/performance_summary.json").read_text())
    assert summary["cumulative_return_pct"] is None
    assert "Investment returns: N/A" in (Path(args.output) / "latest/index.html").read_text()
    assert pd.read_csv(Path(args.output) / "latest/twr_curve.csv")["twr_index"].iloc[1:].isna().all()


def test_legacy_cash_flow_semantics_remain_unchanged(tmp_path):
    path = tmp_path / "cash_flows.csv"
    path.write_text("date,amount,currency,type,memo\n2026-01-02,10,USD,dividend,income\n"
                    "2026-01-02,2,USD,fee,cost\n2026-01-02,3,USD,withdrawal,out\n")
    frame, _ = performance_report._load_cash_flows(path)  # pylint: disable=protected-access
    assert frame.iloc[0]["external_flow"] == 9  # Preserve old sign/type semantics, including fee.
    assert not load_external_flow_ledger(path).intervals
