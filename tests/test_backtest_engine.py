"""Smoke tests for the first working backtest engine."""

from __future__ import annotations

import pandas as pd
import pytest

from backtests.engine import BacktestEngineOptions, run_backtest


def test_run_backtest_smoke_returns_core_artifacts() -> None:
    candidates = pd.DataFrame(
        [
            {
                "asof_date": "2025-01-02",
                "symbol": "AAA",
                "close": 100.0,
                "market_cap": 800_000_000,
                "avg_dollar_volume": 10_000_000,
                "rs_score": 85.0,
                "pct_below_52w_high": 12.0,
                "sma50": 95.0,
                "sma150": 90.0,
                "sma200": 85.0,
                "high_52w": 110.0,
                "low_52w": 70.0,
            },
            {
                "asof_date": "2025-01-02",
                "symbol": "BBB",
                "close": 50.0,
                "market_cap": 700_000_000,
                "avg_dollar_volume": 8_000_000,
                "rs_score": 72.0,
                "pct_below_52w_high": 20.0,
                "sma50": 49.0,
                "sma150": 45.0,
                "sma200": 40.0,
                "high_52w": 55.0,
                "low_52w": 35.0,
            },
            {
                "asof_date": "2025-02-03",
                "symbol": "AAA",
                "close": 108.0,
                "market_cap": 800_000_000,
                "avg_dollar_volume": 9_500_000,
                "rs_score": 88.0,
                "pct_below_52w_high": 8.0,
                "sma50": 102.0,
                "sma150": 94.0,
                "sma200": 88.0,
                "high_52w": 115.0,
                "low_52w": 75.0,
            },
        ]
    )

    price_history = pd.DataFrame(
        [
            {"date": "2025-01-02", "symbol": "AAA", "close": 100.0, "sma50": 95.0},
            {"date": "2025-01-03", "symbol": "AAA", "close": 103.0, "sma50": 96.0},
            {"date": "2025-01-10", "symbol": "AAA", "close": 108.0, "sma50": 99.0},
            {"date": "2025-02-03", "symbol": "AAA", "close": 108.0, "sma50": 102.0},
            {"date": "2025-02-04", "symbol": "AAA", "close": 111.0, "sma50": 103.0},
            {"date": "2025-01-02", "symbol": "BBB", "close": 50.0, "sma50": 49.0},
            {"date": "2025-01-06", "symbol": "BBB", "close": 51.0, "sma50": 49.5},
            {"date": "2025-01-08", "symbol": "BBB", "close": 49.0, "sma50": 49.8},
        ]
    )

    result = run_backtest(
        candidates=candidates,
        price_history=price_history,
        universe="quantus_minervini",
        entry="trend_basic",
        exit_rule="hold_fixed",
        options=BacktestEngineOptions(
            top_n=1,
            rank_col="rs_score",
            starting_equity=10_000.0,
            hold_days=5,
            stop_loss_pct=0.08,
            trailing_pct=0.10,
            exit_rule="hold_fixed",
        ),
    )

    assert {"trades", "equity_curve", "metrics", "config"}.issubset(result.keys())
    assert isinstance(result["trades"], pd.DataFrame)
    assert isinstance(result["equity_curve"], list)
    assert isinstance(result["metrics"], dict)
    assert not result["trades"].empty


def test_rebalance_dates_pick_earliest_snapshot_per_month_when_unsorted() -> None:
    candidates = pd.DataFrame(
        [
            {"asof_date": "2025-01-20", "symbol": "LATE_JAN", "close": 10.0, "rs_score": 90},
            {"asof_date": "2025-02-20", "symbol": "LATE_FEB", "close": 20.0, "rs_score": 95},
            {"asof_date": "2025-01-03", "symbol": "EARLY_JAN", "close": 30.0, "rs_score": 80},
            {"asof_date": "2025-02-04", "symbol": "EARLY_FEB", "close": 40.0, "rs_score": 85},
        ]
    )
    price_history = pd.DataFrame(
        [
            {"date": "2025-01-03", "symbol": "EARLY_JAN", "close": 31.0},
            {"date": "2025-01-10", "symbol": "EARLY_JAN", "close": 32.0},
            {"date": "2025-02-04", "symbol": "EARLY_FEB", "close": 41.0},
            {"date": "2025-02-10", "symbol": "EARLY_FEB", "close": 42.0},
        ]
    )

    result = run_backtest(
        candidates=candidates,
        price_history=price_history,
        universe="quantus",
        entry="none",
        exit_rule="hold_fixed",
        options=BacktestEngineOptions(
            top_n=1,
            rank_col="symbol",
            starting_equity=100_000.0,
            hold_days=1,
            stop_loss_pct=0.08,
            trailing_pct=0.10,
            exit_rule="hold_fixed",
        ),
    )

    assert list(result["trades"]["symbol"]) == ["EARLY_JAN", "EARLY_FEB"]


def test_metrics_and_equity_curve_use_chronologically_sorted_trades() -> None:
    candidates = pd.DataFrame(
        [
            {
                "asof_date": "2025-01-02",
                "symbol": "AAA",
                "close": 100.0,
                "rs_score": 90,
            },
            {
                "asof_date": "2025-02-03",
                "symbol": "BBB",
                "close": 100.0,
                "rs_score": 90,
            },
        ]
    )
    price_history = pd.DataFrame(
        [
            {"date": "2025-01-02", "symbol": "AAA", "close": 100.0},
            {"date": "2025-01-03", "symbol": "AAA", "close": 102.0},
            {"date": "2025-03-01", "symbol": "AAA", "close": 110.0},
            {"date": "2025-02-03", "symbol": "BBB", "close": 100.0},
            {"date": "2025-02-04", "symbol": "BBB", "close": 95.0},
        ]
    )

    result = run_backtest(
        candidates=candidates,
        price_history=price_history,
        universe="quantus",
        entry="none",
        exit_rule="hold_fixed",
        options=BacktestEngineOptions(
            top_n=1,
            rank_col="rs_score",
            starting_equity=100.0,
            hold_days=1,
            stop_loss_pct=0.08,
            trailing_pct=0.10,
            exit_rule="hold_fixed",
        ),
    )

    trades = result["trades"]
    assert list(trades["symbol"]) == ["AAA", "BBB"]
    assert result["equity_curve"] == [100.0, 100.0, 102.0, 102.0, 96.9, 96.9]
    assert result["metrics"]["total_pnl"] == pytest.approx(-3.1)


def test_prevents_duplicate_reentry_while_position_is_open() -> None:
    candidates = pd.DataFrame(
        [
            {"asof_date": "2025-01-02", "symbol": "AAA", "close": 100.0, "rs_score": 90},
            {"asof_date": "2025-02-03", "symbol": "AAA", "close": 105.0, "rs_score": 95},
        ]
    )
    price_history = pd.DataFrame(
        [
            {"date": "2025-01-02", "symbol": "AAA", "close": 100.0},
            {"date": "2025-02-03", "symbol": "AAA", "close": 105.0},
            {"date": "2025-03-03", "symbol": "AAA", "close": 110.0},
        ]
    )

    result = run_backtest(
        candidates=candidates,
        price_history=price_history,
        universe="quantus",
        entry="none",
        exit_rule="hold_fixed",
        options=BacktestEngineOptions(
            top_n=1,
            rank_col="rs_score",
            starting_equity=10_000.0,
            hold_days=120,
            stop_loss_pct=0.08,
            trailing_pct=0.10,
            exit_rule="hold_fixed",
        ),
    )

    trades = result["trades"]
    assert len(trades) == 1
    assert list(trades["symbol"]) == ["AAA"]
    assert trades.iloc[0]["entry_date"].isoformat() == "2025-01-02"


def test_supports_multiple_open_positions_and_marks_equity_to_market() -> None:
    candidates = pd.DataFrame(
        [
            {"asof_date": "2025-01-02", "symbol": "AAA", "close": 100.0, "rs_score": 99},
            {"asof_date": "2025-01-02", "symbol": "BBB", "close": 50.0, "rs_score": 98},
        ]
    )
    price_history = pd.DataFrame(
        [
            {"date": "2025-01-02", "symbol": "AAA", "close": 100.0},
            {"date": "2025-01-03", "symbol": "AAA", "close": 102.0},
            {"date": "2025-01-04", "symbol": "AAA", "close": 103.0},
            {"date": "2025-01-02", "symbol": "BBB", "close": 50.0},
            {"date": "2025-01-03", "symbol": "BBB", "close": 48.0},
            {"date": "2025-01-04", "symbol": "BBB", "close": 55.0},
        ]
    )

    result = run_backtest(
        candidates=candidates,
        price_history=price_history,
        universe="quantus",
        entry="none",
        exit_rule="hold_fixed",
        options=BacktestEngineOptions(
            top_n=2,
            rank_col="rs_score",
            starting_equity=100.0,
            hold_days=30,
            stop_loss_pct=0.08,
            trailing_pct=0.10,
            exit_rule="hold_fixed",
        ),
    )

    trades = result["trades"]
    assert len(trades) == 2
    assert set(trades["symbol"]) == {"AAA", "BBB"}
    assert result["equity_curve"] == [100.0, 100.0, 99.0, 106.5]
    assert result["metrics"]["ending_equity"] == 106.5
