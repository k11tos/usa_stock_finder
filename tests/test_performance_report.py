import argparse
import json

import pandas as pd
import pytest

from tools.performance_report import (
    align_benchmarks_to_strategy_dates,
    build_report,
    build_chart_data,
    calculate_drawdown_series,
    cumulative_return_pct,
    load_strategy_equity_curve,
    max_drawdown_pct,
    normalize_series,
)


def test_cumulative_return_calculation() -> None:
    series = pd.Series([100, 110, 120])
    assert cumulative_return_pct(series) == pytest.approx(20.0)


def test_max_drawdown_calculation() -> None:
    series = pd.Series([100, 120, 90, 130])
    assert round(max_drawdown_pct(series), 2) == -25.0


def test_calculate_drawdown_series() -> None:
    series = pd.Series([100.0, 120.0, 90.0, 130.0])
    drawdown = calculate_drawdown_series(series)
    assert drawdown.iloc[0] == pytest.approx(0.0)
    assert drawdown.iloc[1] == pytest.approx(0.0)
    assert drawdown.iloc[2] == pytest.approx(-25.0)
    assert drawdown.iloc[3] == pytest.approx(0.0)


def test_benchmark_normalization() -> None:
    series = pd.Series([200, 220, 180], index=pd.date_range("2026-01-01", periods=3))
    normalized = normalize_series(series)
    assert normalized.iloc[0] == 1.0
    assert normalized.iloc[1] == 1.1


def test_missing_empty_logs(tmp_path) -> None:
    out = tmp_path / "out"
    args = argparse.Namespace(
        snapshots=str(tmp_path / "missing.csv"),
        trades=str(tmp_path / "trades.csv"),
        benchmarks=["SPY", "IWM"],
        output=str(out),
        start_date=None,
        end_date=None,
        publish_latest=False,
        history=False,
        report_run_id=None,
    )
    build_report(args)
    summary = json.loads((out / "performance_summary.json").read_text(encoding="utf-8"))
    assert "error" in summary


def test_group_duplicate_same_day_snapshots(tmp_path) -> None:
    path = tmp_path / "account_snapshots.csv"
    data = pd.DataFrame(
        [
            {
                "run_id": "20260101_090000",
                "run_date": "2026-01-01",
                "cash": 100,
                "market_value": 50,
                "total_equity": 150,
            },
            {
                "run_id": "20260101_160000",
                "run_date": "2026-01-01",
                "cash": 120,
                "market_value": 60,
                "total_equity": 180,
            },
            {
                "run_id": "20260102_160000",
                "run_date": "2026-01-02",
                "cash": 100,
                "market_value": 100,
                "total_equity": "",
            },
        ]
    )
    data.to_csv(path, index=False)

    result = load_strategy_equity_curve(path)
    assert len(result) == 2
    assert result.iloc[0]["strategy_equity"] == 180
    assert result.iloc[1]["strategy_equity"] == 200


def test_latest_run_fallback_sums_all_symbol_market_values(tmp_path) -> None:
    path = tmp_path / "account_snapshots.csv"
    data = pd.DataFrame(
        [
            {
                "run_id": "20260103_090000",
                "run_date": "2026-01-03",
                "symbol": "OLD",
                "cash": 50,
                "market_value": 100,
                "total_equity": "",
            },
            {
                "run_id": "20260103_160000",
                "run_date": "2026-01-03",
                "symbol": "AAPL",
                "cash": 200,
                "market_value": 300,
                "total_equity": "",
            },
            {
                "run_id": "20260103_160000",
                "run_date": "2026-01-03",
                "symbol": "MSFT",
                "cash": 200,
                "market_value": 400,
                "total_equity": "",
            },
        ]
    )
    data.to_csv(path, index=False)

    result = load_strategy_equity_curve(path)
    assert len(result) == 1
    assert result.iloc[0]["strategy_equity"] == 900


def test_align_benchmarks_handles_non_trading_strategy_dates() -> None:
    benchmark_index = pd.to_datetime(["2026-01-02", "2026-01-05"])
    strategy_index = pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"])
    benchmarks = pd.DataFrame({"SPY": [100.0, 101.0]}, index=benchmark_index)

    aligned = align_benchmarks_to_strategy_dates(benchmarks, strategy_index)

    assert aligned.loc[pd.Timestamp("2026-01-03"), "SPY"] == 100.0
    assert aligned.loc[pd.Timestamp("2026-01-04"), "SPY"] == 100.0
    assert aligned.loc[pd.Timestamp("2026-01-05"), "SPY"] == 101.0


def test_build_report_with_mocked_benchmarks(tmp_path, monkeypatch) -> None:
    snapshots = tmp_path / "account_snapshots.csv"
    pd.DataFrame(
        [
            {
                "run_id": "20260101_160000",
                "run_date": "2026-01-01",
                "cash": 100,
                "market_value": 100,
                "total_equity": 200,
            },
            {
                "run_id": "20260102_160000",
                "run_date": "2026-01-02",
                "cash": 100,
                "market_value": 120,
                "total_equity": 220,
            },
        ]
    ).to_csv(snapshots, index=False)

    def fake_fetch(_symbols, _start, _end):
        idx = pd.to_datetime(["2026-01-01", "2026-01-02"])
        return pd.DataFrame({"SPY": [100, 102], "IWM": [100, 101]}, index=idx)

    monkeypatch.setattr("tools.performance_report.fetch_benchmark_prices", fake_fetch)

    out = tmp_path / "perf"
    args = argparse.Namespace(
        snapshots=str(snapshots),
        trades=str(tmp_path / "trades.csv"),
        benchmarks=["SPY", "IWM"],
        output=str(out),
        start_date=None,
        end_date=None,
        publish_latest=False,
        history=False,
        report_run_id=None,
    )
    build_report(args)

    assert (out / "equity_curve.csv").exists()
    assert (out / "benchmark_comparison.csv").exists()
    assert (out / "performance_summary.json").exists()
    assert (out / "performance_report.md").exists()
    assert (out / "charts" / "cumulative_return.png").exists()
    assert (out / "charts" / "drawdown.png").exists()
    assert (out / "charts" / "excess_return.png").exists()
    assert (out / "charts" / "cumulative_return.png").stat().st_size > 0
    assert (out / "charts" / "drawdown.png").stat().st_size > 0
    assert (out / "charts" / "excess_return.png").stat().st_size > 0


def test_build_chart_data_with_missing_benchmark_series() -> None:
    idx = pd.to_datetime(["2026-01-01", "2026-01-02"])
    norm_df = pd.DataFrame({"Strategy": [1.0, 1.1]}, index=idx)
    chart_data = build_chart_data(norm_df, ["SPY", "IWM"])

    assert list(chart_data["cumulative"].columns) == ["Strategy"]
    assert list(chart_data["drawdown"].columns) == ["Strategy"]
    assert chart_data["excess"].empty


def test_build_report_with_no_benchmark_data(tmp_path, monkeypatch) -> None:
    snapshots = tmp_path / "account_snapshots.csv"
    pd.DataFrame(
        [
            {
                "run_id": "20260101_160000",
                "run_date": "2026-01-01",
                "cash": 100,
                "market_value": 100,
                "total_equity": 200,
            },
            {
                "run_id": "20260102_160000",
                "run_date": "2026-01-02",
                "cash": 100,
                "market_value": 120,
                "total_equity": 220,
            },
        ]
    ).to_csv(snapshots, index=False)

    monkeypatch.setattr("tools.performance_report.fetch_benchmark_prices", lambda *_args, **_kwargs: pd.DataFrame())

    out = tmp_path / "perf_no_bench"
    args = argparse.Namespace(
        snapshots=str(snapshots),
        trades=str(tmp_path / "trades.csv"),
        benchmarks=["SPY", "IWM"],
        output=str(out),
        start_date=None,
        end_date=None,
        publish_latest=False,
        history=False,
        report_run_id=None,
    )
    build_report(args)

    for chart_name in ["cumulative_return.png", "drawdown.png", "excess_return.png"]:
        chart_path = out / "charts" / chart_name
        assert chart_path.exists()
        assert chart_path.stat().st_size > 0


def test_html_report_and_publish_bundles(tmp_path, monkeypatch) -> None:
    snapshots = tmp_path / "account_snapshots.csv"
    pd.DataFrame(
        [
            {
                "run_id": "20260101_160000",
                "run_date": "2026-01-01",
                "cash": 100,
                "market_value": 100,
                "total_equity": 200,
            },
            {
                "run_id": "20260102_160000",
                "run_date": "2026-01-02",
                "cash": 100,
                "market_value": 120,
                "total_equity": 220,
            },
        ]
    ).to_csv(snapshots, index=False)

    def fake_fetch(_symbols, _start, _end):
        idx = pd.to_datetime(["2026-01-01", "2026-01-02"])
        return pd.DataFrame({"SPY": [100, 102], "IWM": [100, 101]}, index=idx)

    monkeypatch.setattr("tools.performance_report.fetch_benchmark_prices", fake_fetch)

    out = tmp_path / "perf_publish"
    run_id = "20260115_101010"
    args = argparse.Namespace(
        snapshots=str(snapshots),
        trades=str(tmp_path / "trades.csv"),
        benchmarks=["SPY", "IWM"],
        output=str(out),
        start_date=None,
        end_date=None,
        publish_latest=True,
        history=True,
        report_run_id=run_id,
    )
    build_report(args)

    assert (out / "index.html").exists()
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "charts/cumulative_return.png" in html
    assert "charts/drawdown.png" in html
    assert "charts/excess_return.png" in html

    latest = out / "latest"
    history = out / "history" / run_id
    for bundle_dir in [latest, history]:
        assert (bundle_dir / "index.html").exists()
        assert (bundle_dir / "performance_report.md").exists()
        assert (bundle_dir / "performance_summary.json").exists()
        assert (bundle_dir / "equity_curve.csv").exists()
        assert (bundle_dir / "benchmark_comparison.csv").exists()
        assert (bundle_dir / "charts" / "cumulative_return.png").exists()
        assert (bundle_dir / "charts" / "drawdown.png").exists()
        assert (bundle_dir / "charts" / "excess_return.png").exists()


def test_empty_snapshot_generates_safe_html(tmp_path) -> None:
    out = tmp_path / "out_empty_html"
    args = argparse.Namespace(
        snapshots=str(tmp_path / "missing.csv"),
        trades=str(tmp_path / "trades.csv"),
        benchmarks=["SPY", "IWM"],
        output=str(out),
        start_date=None,
        end_date=None,
        publish_latest=False,
        history=False,
        report_run_id=None,
    )
    build_report(args)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "usa_stock_finder Performance Report" in html
    assert "Chart unavailable" in html


@pytest.mark.parametrize(
    "invalid_run_id",
    ["/tmp/x", "../../outside", "nested/path"],
)
def test_invalid_history_run_id_raises_value_error(
    tmp_path,
    monkeypatch,
    invalid_run_id: str,
) -> None:
    snapshots = tmp_path / "account_snapshots.csv"
    pd.DataFrame(
        [
            {
                "run_id": "20260101_160000",
                "run_date": "2026-01-01",
                "cash": 100,
                "market_value": 100,
                "total_equity": 200,
            },
            {
                "run_id": "20260102_160000",
                "run_date": "2026-01-02",
                "cash": 100,
                "market_value": 120,
                "total_equity": 220,
            },
        ]
    ).to_csv(snapshots, index=False)

    def fake_fetch(_symbols, _start, _end):
        idx = pd.to_datetime(["2026-01-01", "2026-01-02"])
        return pd.DataFrame({"SPY": [100, 102], "IWM": [100, 101]}, index=idx)

    monkeypatch.setattr("tools.performance_report.fetch_benchmark_prices", fake_fetch)

    out = tmp_path / "perf_publish_invalid"
    args = argparse.Namespace(
        snapshots=str(snapshots),
        trades=str(tmp_path / "trades.csv"),
        benchmarks=["SPY", "IWM"],
        output=str(out),
        start_date=None,
        end_date=None,
        publish_latest=False,
        history=True,
        report_run_id=invalid_run_id,
    )

    with pytest.raises(ValueError):
        build_report(args)

    outside_path = (out / "history" / invalid_run_id).resolve()
    assert not outside_path.exists()
