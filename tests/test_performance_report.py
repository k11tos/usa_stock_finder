import argparse
import json

import pandas as pd
import pytest

from tools.performance_report import (
    _calculate_modified_dietz_return_pct,
    _extract_benchmark_price_series,
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


def test_extract_benchmark_price_series_prefers_single_level_adj_close() -> None:
    idx = pd.date_range("2026-01-01", periods=3)
    data = pd.DataFrame(
        {"Close": [99.0, 100.0, 101.0], "Adj Close": [98.0, 99.0, 100.0]},
        index=idx,
    )

    result = _extract_benchmark_price_series(data, "SPY")

    assert result.name == "SPY"
    assert result.tolist() == [98.0, 99.0, 100.0]


def test_extract_benchmark_price_series_uses_single_level_close_fallback() -> None:
    idx = pd.date_range("2026-01-01", periods=3)
    data = pd.DataFrame(
        {"Open": [95.0, 96.0, 97.0], "Close": [99.0, 100.0, 101.0]},
        index=idx,
    )

    result = _extract_benchmark_price_series(data, "SPY")

    assert result.name == "SPY"
    assert result.tolist() == [99.0, 100.0, 101.0]


def test_extract_benchmark_price_series_handles_one_column_dataframe_selection() -> None:
    idx = pd.date_range("2026-01-01", periods=3)
    data = pd.DataFrame({"Adj Close": ["98.0", "99.0", None]}, index=idx)

    result = _extract_benchmark_price_series(data, "SPY")

    assert result.name == "SPY"
    assert result.tolist() == [98.0, 99.0]


def test_extract_benchmark_price_series_handles_multiindex_yfinance_output() -> None:
    idx = pd.date_range("2026-01-01", periods=3)
    columns = pd.MultiIndex.from_tuples(
        [("Adj Close", "SPY"), ("Close", "SPY"), ("Adj Close", "IWM")],
        names=["Price", "Ticker"],
    )
    data = pd.DataFrame(
        [[98.0, 99.0, 50.0], [99.0, 100.0, 51.0], [100.0, 101.0, 52.0]],
        index=idx,
        columns=columns,
    )

    result = _extract_benchmark_price_series(data, "SPY")

    assert result.name == "SPY"
    assert result.tolist() == [98.0, 99.0, 100.0]


def test_extract_benchmark_price_series_missing_close_returns_empty() -> None:
    idx = pd.date_range("2026-01-01", periods=3)
    data = pd.DataFrame(
        {"Open": [95.0, 96.0, 97.0], "High": [100.0, 101.0, 102.0]},
        index=idx,
    )

    result = _extract_benchmark_price_series(data, "SPY")

    assert result.name == "SPY"
    assert result.empty


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


def test_build_report_publish_latest_and_history(tmp_path, monkeypatch) -> None:
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

    monkeypatch.setattr(
        "tools.performance_report.fetch_benchmark_prices",
        lambda *_args, **_kwargs: pd.DataFrame(
            {"SPY": [100, 101], "IWM": [100, 100.5]},
            index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
        ),
    )

    out = tmp_path / "perf_publish"
    args = argparse.Namespace(
        snapshots=str(snapshots),
        trades=str(tmp_path / "trades.csv"),
        benchmarks=["SPY", "IWM"],
        output=str(out),
        start_date=None,
        end_date=None,
        publish_latest=True,
        history=True,
        report_run_id="20260527_120000",
    )
    build_report(args)

    assert (out / "index.html").exists()
    assert 'charts/cumulative_return.png' in (out / "index.html").read_text(encoding="utf-8")
    assert (out / "latest" / "index.html").exists()
    assert (out / "history" / "20260527_120000" / "index.html").exists()


def test_build_report_old_namespace_shape_still_works(tmp_path, monkeypatch) -> None:
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
    monkeypatch.setattr(
        "tools.performance_report.fetch_benchmark_prices",
        lambda *_args, **_kwargs: pd.DataFrame(
            {"SPY": [100, 101], "IWM": [100, 100.5]},
            index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
        ),
    )

    out = tmp_path / "perf_old_shape"
    args = argparse.Namespace(
        snapshots=str(snapshots),
        trades=str(tmp_path / "trades.csv"),
        benchmarks=["SPY", "IWM"],
        output=str(out),
        start_date=None,
        end_date=None,
    )
    build_report(args)
    assert (out / "index.html").exists()


def test_empty_snapshot_generates_safe_html(tmp_path) -> None:
    out = tmp_path / "empty_html"
    args = argparse.Namespace(
        snapshots=str(tmp_path / "missing.csv"),
        trades=str(tmp_path / "trades.csv"),
        benchmarks=["SPY", "IWM"],
        output=str(out),
        start_date=None,
        end_date=None,
        publish_latest=True,
        history=True,
        report_run_id="20260527_130000",
    )

    build_report(args)

    html = (out / "index.html").read_text(encoding="utf-8")
    assert "No valid account snapshots" not in html
    assert "Missing chart:" in html
    assert (out / "latest" / "index.html").exists()
    assert (out / "history" / "20260527_130000" / "index.html").exists()


def test_no_cash_flow_file_returns_none() -> None:
    strategy = pd.DataFrame(
        {
            "run_date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "strategy_equity": [1000.0, 1100.0],
        }
    )
    adjusted = _calculate_modified_dietz_return_pct(
        strategy,
        pd.DataFrame(columns=["date", "external_flow"]),
    )
    assert adjusted is None


def test_deposit_reduces_return_distortion() -> None:
    strategy = pd.DataFrame(
        {
            "run_date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "strategy_equity": [1000.0, 1600.0],
        }
    )
    cash_flows = pd.DataFrame(
        {"date": pd.to_datetime(["2026-01-02"]), "external_flow": [500.0]}
    )
    simple_return = cumulative_return_pct(strategy["strategy_equity"])
    adjusted_return = _calculate_modified_dietz_return_pct(strategy, cash_flows)
    assert simple_return == pytest.approx(60.0)
    assert adjusted_return == pytest.approx(10.0)


def test_withdrawal_handling_increases_adjusted_return() -> None:
    strategy = pd.DataFrame(
        {
            "run_date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "strategy_equity": [1000.0, 900.0],
        }
    )
    cash_flows = pd.DataFrame(
        {"date": pd.to_datetime(["2026-01-02"]), "external_flow": [-200.0]}
    )
    simple_return = cumulative_return_pct(strategy["strategy_equity"])
    adjusted_return = _calculate_modified_dietz_return_pct(strategy, cash_flows)
    assert simple_return == pytest.approx(-10.0)
    assert adjusted_return == pytest.approx(10.0)


def test_cash_flow_between_snapshot_dates_is_included() -> None:
    strategy = pd.DataFrame(
        {
            "run_date": pd.to_datetime(["2026-01-01", "2026-01-03"]),
            "strategy_equity": [1000.0, 1550.0],
        }
    )
    cash_flows = pd.DataFrame(
        {"date": pd.to_datetime(["2026-01-02"]), "external_flow": [500.0]}
    )

    simple_return = cumulative_return_pct(strategy["strategy_equity"])
    adjusted_return = _calculate_modified_dietz_return_pct(strategy, cash_flows)

    assert simple_return == pytest.approx(55.0)
    assert adjusted_return == pytest.approx(4.0)
    assert adjusted_return != pytest.approx(simple_return)


def test_invalid_cash_flow_rows_are_reported_safely(tmp_path, monkeypatch) -> None:
    snapshots = tmp_path / "account_snapshots.csv"
    pd.DataFrame(
        [
            {"run_id": "20260101_160000", "run_date": "2026-01-01", "total_equity": 1000},
            {"run_id": "20260102_160000", "run_date": "2026-01-02", "total_equity": 1050},
        ]
    ).to_csv(snapshots, index=False)

    cash_flows = tmp_path / "cash_flows.csv"
    pd.DataFrame(
        [
            {"date": "2026-01-02", "amount": "bad", "currency": "USD", "type": "deposit", "memo": "bad amount"},
            {"date": "2026-01-02", "amount": 20, "currency": "USD", "type": "unknown", "memo": "bad type"},
        ]
    ).to_csv(cash_flows, index=False)

    monkeypatch.setattr("tools.performance_report.fetch_benchmark_prices", lambda *_a, **_k: pd.DataFrame())

    out = tmp_path / "perf_invalid_cf"
    args = argparse.Namespace(
        snapshots=str(snapshots),
        trades=str(tmp_path / "trades.csv"),
        cash_flows=str(cash_flows),
        benchmarks=["SPY"],
        output=str(out),
        start_date=None,
        end_date=None,
        publish_latest=False,
        history=False,
        report_run_id=None,
    )
    build_report(args)
    summary = json.loads((out / "performance_summary.json").read_text(encoding="utf-8"))
    assert summary["cash_flow_adjusted_return_pct"] is None
    assert "Skipped 2 invalid cash-flow row(s)." in summary["cash_flow_warnings"]


def test_prefers_explicit_total_equity_usd(tmp_path) -> None:
    path = tmp_path / "account_snapshots.csv"
    pd.DataFrame(
        [
            {
                "run_id": "20260101_160000",
                "run_date": "2026-01-01",
                "cash": 100,
                "market_value": 50,
                "total_equity": 999999,
                "total_equity_usd": 150,
            },
            {
                "run_id": "20260102_160000",
                "run_date": "2026-01-02",
                "cash": 100,
                "market_value": 70,
                "total_equity": 999999,
                "total_equity_usd": 170,
            },
        ]
    ).to_csv(path, index=False)

    result = load_strategy_equity_curve(path)

    assert result["strategy_equity"].tolist() == [150, 170]


def test_avoids_misleading_legacy_krw_total_equity(tmp_path) -> None:
    from tools.performance_report import load_strategy_equity_curve_with_warnings

    path = tmp_path / "account_snapshots.csv"
    pd.DataFrame(
        [
            {
                "run_id": "20260101_160000",
                "run_date": "2026-01-01",
                "cash": 1000,
                "market_value": 5000,
                "total_equity": 1500000,
            },
            {
                "run_id": "20260102_160000",
                "run_date": "2026-01-02",
                "cash": 1000,
                "market_value": 5200,
                "total_equity": 1500000,
            },
        ]
    ).to_csv(path, index=False)

    result, warnings = load_strategy_equity_curve_with_warnings(path)

    assert result["strategy_equity"].tolist() == [6000, 6200]
    assert any("KRW-converted cash" in warning for warning in warnings)


def test_missing_cash_flow_data_returns_none() -> None:
    strategy = pd.DataFrame(
        {"run_date": pd.to_datetime(["2026-01-01", "2026-01-02"]), "strategy_equity": [1000.0, 1100.0]}
    )

    assert _calculate_modified_dietz_return_pct(strategy, pd.DataFrame(columns=["date", "external_flow"])) is None


def test_suspicious_daily_equity_jump_warning(tmp_path) -> None:
    from tools.performance_report import load_strategy_equity_curve_with_warnings

    path = tmp_path / "account_snapshots.csv"
    pd.DataFrame(
        [
            {"run_id": "20260101_160000", "run_date": "2026-01-01", "total_equity_usd": 1000},
            {"run_id": "20260102_160000", "run_date": "2026-01-02", "total_equity_usd": 1200},
        ]
    ).to_csv(path, index=False)

    _result, warnings = load_strategy_equity_curve_with_warnings(path)

    assert any(">= 10%" in warning for warning in warnings)


def test_annualized_volatility_requires_30_snapshot_days() -> None:
    from tools.performance_report import annualized_volatility_pct

    assert annualized_volatility_pct(pd.Series([0.01] * 28)) is None
    assert annualized_volatility_pct(pd.Series([0.01, -0.01] * 15)) is not None


def test_malformed_snapshot_file_returns_warning(tmp_path) -> None:
    from tools.performance_report import load_strategy_equity_curve_with_warnings

    path = tmp_path / "account_snapshots.csv"
    path.write_text(
        "run_id,run_date,cash,total_equity\n"
        "20260101_160000,2026-01-01,1000,1000\n"
        "20260102_160000,2026-01-02,1000,1000,extra\n",
        encoding="utf-8",
    )

    result, warnings = load_strategy_equity_curve_with_warnings(path)

    assert result.empty
    assert any("Malformed account snapshot CSV" in warning for warning in warnings)
