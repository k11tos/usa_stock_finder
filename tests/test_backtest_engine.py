"""Smoke tests for the first working backtest engine."""

from __future__ import annotations

import pandas as pd

from backtests.engine import run_backtest


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
        exit="hold_fixed",
        top_n=1,
        hold_days=5,
        starting_equity=10_000.0,
    )

    assert {"trades", "equity_curve", "metrics", "config"}.issubset(result.keys())
    assert isinstance(result["trades"], pd.DataFrame)
    assert isinstance(result["equity_curve"], list)
    assert isinstance(result["metrics"], dict)
    assert not result["trades"].empty
