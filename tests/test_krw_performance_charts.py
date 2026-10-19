"""Stage 5 currency, chart, publication and failure-contract regressions."""

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from PIL import Image
from test_krw_twr import attestation, flow, snapshot, write_csv

from performance_report_runner import run_performance_report_safely
from tools import krw_benchmarks, performance_report
from tools.broker_equity import HEADERS, load_broker_equity
from tools.krw_twr import FLOW_HEADERS, calculate_twr, load_external_flow_ledger


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "data/live"
    folder.mkdir(parents=True)
    equity_path, ledger_path = folder / "broker_equity_snapshots.csv", folder / "krw_external_flows.csv"
    write_csv(equity_path, HEADERS, [snapshot(1, 100), snapshot(2, 160), snapshot(3, 144)])
    write_csv(ledger_path, FLOW_HEADERS, [attestation(), flow(50), attestation(3)])
    dates = pd.date_range("2025-12-31", periods=3)
    quotes = {"SPY": pd.Series([100., 110., 99.], index=dates),
              "IWM": pd.Series([200., 220., 242.], index=dates),
              "KRW=X": pd.Series([1000., 1200., 1300.], index=dates)}
    monkeypatch.setattr(krw_benchmarks, "fetch_series",
                        lambda symbol, *_args: quotes.get(symbol, pd.Series(dtype=float)))
    args = argparse.Namespace(data_source="broker_krw", start_date=None, end_date=None,
                              benchmarks=["SPY", "IWM"], output=str(tmp_path / "report"),
                              publish_latest=True, history=True, report_run_id="stage5")
    return args, quotes, equity_path, ledger_path


def compare_scenario(scenario):
    args, _, _, ledger_path = scenario
    daily = load_broker_equity().daily
    twr, summary = calculate_twr(daily, load_external_flow_ledger(ledger_path))
    return krw_benchmarks.compare_benchmarks(daily, twr, args.benchmarks, summary["returns_validated"])


def test_currency_consistent_total_returns_and_excess(scenario):
    normalized, audit, metrics, warnings = compare_scenario(scenario)
    # USD SPY -1%; KRW SPY +28.7%; portfolio TWR -1%. The difference is -29.7 pp.
    assert metrics["cumulative_return_SPY_pct"] == pytest.approx(28.7)
    assert metrics["excess_return_vs_SPY"] == pytest.approx(-29.7)
    assert metrics["cumulative_return_IWM_pct"] == pytest.approx(57.3)
    assert metrics["best_benchmark"] == "IWM"
    assert normalized["SPY"].tolist() == pytest.approx([100, 132, 128.7])
    assert audit[audit.asset == "SPY"]["usdkrw"].tolist() == [1000, 1200, 1300]
    assert not warnings


@pytest.mark.parametrize("symbol,values", [
    ("KRW=X", []), ("KRW=X", [1000, np.nan, 1300]), ("KRW=X", [0, 1200, 1300]),
    ("KRW=X", [1000, np.inf, 1300]), ("SPY", []), ("SPY", [100, -1, 99]),
])
def test_missing_invalid_fx_or_benchmark_produces_na(scenario, symbol, values):
    quotes = scenario[1]
    quotes[symbol] = pd.Series(values, index=quotes[symbol].index if values else None, dtype=float)
    normalized, audit, metrics, warnings = compare_scenario(scenario)
    assert metrics["cumulative_return_SPY_pct"] is None
    assert metrics["excess_return_vs_SPY"] is None
    assert "SPY" not in normalized
    assert warnings
    assert audit[audit.asset == "SPY"]["benchmark_index"].isna().all()
    if symbol == "KRW=X":
        assert metrics["cumulative_return_IWM_pct"] is None
        assert any("Historical USD/KRW" in warning for warning in warnings)
    else:
        assert metrics["cumulative_return_IWM_pct"] == pytest.approx(57.3)


def test_download_failure_is_sanitized_na(scenario, monkeypatch):
    monkeypatch.setattr(krw_benchmarks, "fetch_series", MagicMock(side_effect=RuntimeError("private provider error")))
    _, _, metrics, warnings = compare_scenario(scenario)
    assert metrics["excess_return_vs_SPY"] is None
    assert warnings and "private provider error" not in " ".join(warnings)


def test_no_current_or_future_fx_and_no_partial_rebasing(scenario):
    scenario[1]["KRW=X"] = pd.Series([1500.], index=pd.to_datetime(["2026-01-02"]))
    normalized, _, metrics, warnings = compare_scenario(scenario)
    assert normalized.empty and metrics["excess_return_vs_SPY"] is None
    assert any("no partial-period rebasing" in warning for warning in warnings)


def test_alignment_honors_timestamp_staleness_and_duplicates():
    quotes = pd.Series([100., 110.], index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
    fetched = pd.Series(["2026-01-03T16:00:00+09:00", "2026-01-05T16:00:00+09:00",
                         "2026-01-06T16:00:00+09:00", "2026-01-10T16:00:00+09:00"])
    aligned = krw_benchmarks.align_observations(quotes, fetched)
    assert aligned.value.iloc[:3].tolist() == [100, 100, 110]  # Monday US close is still in the future in KST.
    assert pd.isna(aligned.value.iloc[-1])
    duplicate = pd.concat([quotes, quotes.iloc[:1]])
    assert krw_benchmarks.align_observations(duplicate, fetched).value.isna().all()


def test_timezone_aware_quote_keeps_its_session_date():
    quotes = pd.Series([1200.], index=pd.date_range("2026-01-02", periods=1, tz="Asia/Seoul"))
    fetched = pd.Series(["2026-01-02T16:00:00+09:00", "2026-01-03T16:00:00+09:00"])
    aligned = krw_benchmarks.align_observations(quotes, fetched)
    assert pd.isna(aligned.value.iloc[0])
    assert aligned.value.iloc[1] == 1200
    assert aligned.quote_date.iloc[1] == pd.Timestamp("2026-01-02")


def test_unknown_benchmark_currency_is_not_assumed_usd(scenario):
    scenario[0].benchmarks = ["005930.KS"]
    normalized, _, metrics, warnings = compare_scenario(scenario)
    assert normalized.empty and metrics["excess_return_vs_005930.KS"] is None
    assert any("currency is not verified" in warning for warning in warnings)


def test_download_preserves_adjusted_prices_and_never_falls_back(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=2)
    download = MagicMock(return_value=pd.DataFrame({"Adj Close": [90, 100], "Close": [100, 100]}, index=dates))
    monkeypatch.setattr(krw_benchmarks.yf, "download", download)
    assert krw_benchmarks.fetch_series("SPY", "Adj Close", dates[0], dates[-1]).tolist() == [90, 100]
    assert download.call_args.kwargs["auto_adjust"] is False
    assert download.call_args.kwargs["timeout"] == 10
    download.return_value = pd.DataFrame({"Close": [100, 100]}, index=dates)
    assert krw_benchmarks.fetch_series("SPY", "Adj Close", dates[0], dates[-1]).empty
    download.return_value = pd.DataFrame([[90, 99], [100, 100]], index=dates,
                                        columns=pd.MultiIndex.from_tuples([("Adj Close", "SPY"), ("Close", "SPY")]))
    assert krw_benchmarks.fetch_series("SPY", "Adj Close", dates[0], dates[-1]).tolist() == [90, 100]


class CheckedHTML(HTMLParser):
    """Check nesting and local resources in the generated standalone document."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.resources = []

    def handle_starttag(self, tag, attrs):
        if tag not in {"meta", "img"}:
            self.stack.append(tag)
        for key, value in attrs:
            if key in {"src", "href"}:
                self.resources.append(value)

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag


def test_full_output_contract_twr_charts_html_and_publishing(scenario, monkeypatch):
    args, _, equity_path, ledger_path = scenario
    original = equity_path.read_bytes(), ledger_path.read_bytes()
    charts = {}
    save_chart = performance_report._save_line_chart  # pylint: disable=protected-access

    def capture_chart(data, path, title, label):
        charts[path.name] = (data.copy(), title, label)
        save_chart(data, path, title, label)

    monkeypatch.setattr(performance_report, "_save_line_chart", capture_chart)
    assert performance_report.build_report(args) is True
    twr_index = charts["cumulative_return.png"][0]["Portfolio TWR (KRW)"]
    assert twr_index.tolist() == [100, 110, 99]  # Raw equity would be [100, 160, 144].
    assert charts["drawdown.png"][0]["Portfolio TWR"].tolist() == [0, 0, -10]
    volatility = charts["twr_volatility.png"][0].iloc[-1, 0]
    assert volatility == pytest.approx(pd.Series([.1, -.1]).std(ddof=1) * np.sqrt(365.25) * 100)
    assert charts["excess_return.png"][0].iloc[-1, 0] == pytest.approx(-29.7)
    for _, title, label in charts.values():
        assert "$" not in title + label and "USD" not in title + label
    output = Path(args.output)
    for bundle in (output, output / "latest", output / "history/stage5"):
        summary = json.loads((bundle / "performance_summary.json").read_text())
        assert summary["returns_validated"] is True and summary["report_status"].startswith("validated")
        assert summary["valid_snapshot_count"] == 3
        assert summary["cumulative_return_pct"] == -1
        assert summary["max_drawdown_pct"] == -10
        assert summary["annualized_volatility_pct"] == pytest.approx(volatility)
        assert summary["excess_return_vs_SPY"] == pytest.approx(-29.7)
        assert len(pd.read_csv(bundle / "benchmark_curve.csv")) == 6
        comparison = pd.read_csv(bundle / "benchmark_comparison.csv")
        assert set(comparison.valuation_currency) == {"KRW"}
        html = (bundle / "index.html").read_text()
        parser = CheckedHTML()
        parser.feed(html)
        assert not parser.stack
        for resource in parser.resources:
            assert (bundle / resource).is_file()
        for text in ("Valuation currency: KRW", "Valid snapshots: 3", "Methodology:", "External flow history:",
                     "Data Quality Warnings", "percentage points", "viewport", "grid-template-columns",
                     "max-width: 100%"):
            assert text in html
        for name in charts:
            with Image.open(bundle / "charts" / name) as image:
                assert image.format == "PNG" and image.width > 0
    assert original == (equity_path.read_bytes(), ledger_path.read_bytes())


def test_weekend_only_report_keeps_valid_twr_chart_without_daily_returns(scenario, monkeypatch):
    args, _, equity_path, ledger_path = scenario
    args.benchmarks = []
    write_csv(equity_path, HEADERS, [snapshot(9, 100), snapshot(12, 105)])
    write_csv(ledger_path, FLOW_HEADERS, [attestation(12, interval_start="2026-01-09T16:00:00+09:00")])
    capture = MagicMock()
    monkeypatch.setattr(performance_report, "_save_line_chart", capture)
    assert performance_report.build_report(args) is True
    charts = {call.args[1].name: call.args[0] for call in capture.call_args_list}
    assert charts["cumulative_return.png"]["Portfolio TWR (KRW)"].tolist() == [100, 105]
    assert charts["drawdown.png"]["Portfolio TWR"].tolist() == [0, 0]
    summary = json.loads((Path(args.output) / "performance_summary.json").read_text())
    assert summary["valid_daily_return_count"] == 0 and summary["valid_interval_return_count"] == 1


def test_weekend_report_preserves_benchmark_dates_and_marks_mixed_volatility_na(scenario, monkeypatch):
    args, quotes, equity_path, ledger_path = scenario
    args.report_run_id = "stage7"
    write_csv(equity_path, HEADERS, [snapshot(8, 100), snapshot(9, 110), snapshot(12, 99), snapshot(13, 108.9)])
    write_csv(ledger_path, FLOW_HEADERS,
              [attestation(9), attestation(12, interval_start="2026-01-09T16:00:00+09:00"), attestation(13)])
    dates = pd.to_datetime(["2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12"])
    quotes.update({"SPY": pd.Series([100., 110., 100., 105.], index=dates),
                   "IWM": pd.Series([200., 200., 200., 200.], index=dates),
                   "KRW=X": pd.Series([1000., 1000., 1100., 1100.], index=dates)})
    original = equity_path.read_bytes(), ledger_path.read_bytes()
    charts = {}
    save_chart = performance_report._save_line_chart  # pylint: disable=protected-access

    def capture(data, path, title, label):
        charts[path.name] = (data.copy(), title)
        save_chart(data, path, title, label)

    monkeypatch.setattr(performance_report, "_save_line_chart", capture)
    assert performance_report.build_report(args) is True
    assert charts["cumulative_return.png"][0]["Portfolio TWR (KRW)"].tolist() == [100, 110, 99, 108.9]
    assert charts["drawdown.png"][0]["Portfolio TWR"].tolist() == [0, 0, -10, -1]
    assert charts["twr_volatility.png"][0].isna().all().all()
    assert "Mixed elapsed interval durations" in charts["twr_volatility.png"][1]
    for bundle in (Path(args.output), Path(args.output) / "latest", Path(args.output) / "history/stage7"):
        summary = json.loads((bundle / "performance_summary.json").read_text())
        assert summary["cumulative_return_pct"] == 8.9
        assert summary["max_drawdown_pct"] == -10
        assert summary["valid_interval_return_count"] == summary["expected_interval_return_count"] == 3
        assert summary["annualized_volatility_pct"] is None
        assert summary["cumulative_return_SPY_pct"] == pytest.approx(15.5)
        assert summary["excess_return_vs_SPY"] == pytest.approx(-6.6)
        audit = pd.read_csv(bundle / "benchmark_curve.csv")
        spy = audit[audit.asset == "SPY"]
        assert spy["date"].tolist() == ["2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13"]
        assert spy["benchmark_date"].tolist() == spy["fx_date"].tolist() == dates.strftime("%Y-%m-%d").tolist()
        curve = pd.read_csv(bundle / "twr_curve.csv")
        assert len(curve) == 4 and pd.isna(curve.iloc[2]["daily_return"])
        assert curve.iloc[2]["interval_return"] == -.1
        for report in ("index.html", "performance_report.md"):
            text = (bundle / report).read_text()
            assert "Annualized volatility: N/A" in text and "Mixed elapsed interval durations" in text
            assert "3 / 3 actual observation intervals" in text
            assert "Observation interval validation" in text
    assert original == (equity_path.read_bytes(), ledger_path.read_bytes())


@pytest.mark.parametrize("failure", ["invalid_equity", "gap_without_matching_verification",
                                     "missing_flow", "requested_boundary"])
def test_invalid_new_data_publishes_diagnostics_and_returns_failure(scenario, monkeypatch, failure, caplog):
    args, _, equity_path, ledger_path = scenario
    assert performance_report.build_report(args)
    old_history = (Path(args.output) / "history/stage5/performance_summary.json").read_bytes()
    if failure == "invalid_equity":
        write_csv(equity_path, HEADERS, [snapshot(1, 100), snapshot(2, 160), snapshot(3, -1)])
    elif failure == "gap_without_matching_verification":
        write_csv(equity_path, HEADERS, [snapshot(1, 100), snapshot(3, 144)])
    elif failure == "missing_flow":
        ledger_path.unlink()
    else:
        args.start_date = "2025-12-31"
    args.report_run_id = "invalid-run"
    fetch = MagicMock(side_effect=AssertionError("invalid TWR must not be compared"))
    monkeypatch.setattr(krw_benchmarks, "fetch_series", fetch)
    assert performance_report.build_report(args) is False
    summary = json.loads((Path(args.output) / "latest/performance_summary.json").read_text())
    assert summary["report_status"] == "invalid" and summary["error"]
    assert summary["cumulative_return_pct"] is None and summary["max_drawdown_pct"] is None
    assert summary["excess_return_vs_SPY"] is None and summary["data_quality_warnings"]
    fetch.assert_not_called()
    assert old_history == (Path(args.output) / "history/stage5/performance_summary.json").read_bytes()
    # The optional daily runner must propagate the failure without affecting trading orchestration.
    monkeypatch.setenv("PERFORMANCE_REPORT_ENABLED", "true")
    monkeypatch.setenv("PERFORMANCE_REPORT_DATA_SOURCE", "broker_krw")
    monkeypatch.setenv("PERFORMANCE_REPORT_OUTPUT_DIR", args.output)
    monkeypatch.setattr("performance_report_runner.build_report", lambda _args: performance_report.build_report(args))
    assert run_performance_report_safely() is False
    assert "diagnostic report only" in caplog.text


def test_legacy_switch_removes_stage5_artifacts_and_never_splices(scenario, monkeypatch):
    args = scenario[0]
    legacy_path = Path("data/live/account_snapshots.csv")
    pd.DataFrame({"run_date": ["2025-12-30", "2025-12-31"], "total_equity_usd": [900, 1000]}).to_csv(
        legacy_path, index=False)
    assert performance_report.build_report(args)
    assert json.loads((Path(args.output) / "performance_summary.json").read_text())["start_date"] == "2026-01-01"
    args.data_source, args.snapshots = "legacy_usd", str(legacy_path)
    monkeypatch.setattr(performance_report, "fetch_benchmark_prices", lambda *_args: pd.DataFrame())
    performance_report.build_report(args)
    for bundle in (Path(args.output), Path(args.output) / "latest"):
        summary = json.loads((bundle / "performance_summary.json").read_text())
        assert summary["valuation_currency"] == "USD"
        assert summary["cumulative_return_pct"] == pytest.approx((1000 / 900 - 1) * 100)
        for name in ("benchmark_curve.csv", "twr_curve.csv", "charts/twr_volatility.png", "charts/raw_equity_krw.png"):
            assert not (bundle / name).exists()
