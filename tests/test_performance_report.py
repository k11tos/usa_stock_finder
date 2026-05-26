import pytest
import argparse
import json

import pandas as pd

from tools.performance_report import (
    build_report,
    cumulative_return_pct,
    load_strategy_equity_curve,
    max_drawdown_pct,
    normalize_series,
)


def test_cumulative_return_calculation() -> None:
    s = pd.Series([100, 110, 120])
    assert cumulative_return_pct(s) == pytest.approx(20.0)


def test_max_drawdown_calculation() -> None:
    s = pd.Series([100, 120, 90, 130])
    assert round(max_drawdown_pct(s), 2) == -25.0


def test_benchmark_normalization() -> None:
    s = pd.Series([200, 220, 180], index=pd.date_range("2026-01-01", periods=3))
    n = normalize_series(s)
    assert n.iloc[0] == 1.0
    assert n.iloc[1] == 1.1


def test_missing_empty_logs(tmp_path) -> None:
    out = tmp_path / "out"
    args = argparse.Namespace(
        snapshots=str(tmp_path / "missing.csv"),
        trades=str(tmp_path / "trades.csv"),
        benchmarks=["SPY", "IWM"],
        output=str(out),
        start_date=None,
        end_date=None,
    )
    build_report(args)
    summary = json.loads((out / "performance_summary.json").read_text(encoding="utf-8"))
    assert "error" in summary


def test_group_duplicate_same_day_snapshots(tmp_path) -> None:
    path = tmp_path / "account_snapshots.csv"
    df = pd.DataFrame(
        [
            {"run_id": "20260101_090000", "run_date": "2026-01-01", "cash": 100, "market_value": 50, "total_equity": 150},
            {"run_id": "20260101_160000", "run_date": "2026-01-01", "cash": 120, "market_value": 60, "total_equity": 180},
            {"run_id": "20260102_160000", "run_date": "2026-01-02", "cash": 100, "market_value": 100, "total_equity": ""},
        ]
    )
    df.to_csv(path, index=False)

    out = load_strategy_equity_curve(path)
    assert len(out) == 2
    assert out.iloc[0]["strategy_equity"] == 180
    assert out.iloc[1]["strategy_equity"] == 200


def test_build_report_with_mocked_benchmarks(tmp_path, monkeypatch) -> None:
    snapshots = tmp_path / "account_snapshots.csv"
    pd.DataFrame(
        [
            {"run_id": "20260101_160000", "run_date": "2026-01-01", "cash": 100, "market_value": 100, "total_equity": 200},
            {"run_id": "20260102_160000", "run_date": "2026-01-02", "cash": 100, "market_value": 120, "total_equity": 220},
        ]
    ).to_csv(snapshots, index=False)

    def fake_fetch(symbols, start, end):
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
    )
    build_report(args)

    assert (out / "equity_curve.csv").exists()
    assert (out / "benchmark_comparison.csv").exists()
    assert (out / "performance_summary.json").exists()
    assert (out / "performance_report.md").exists()
