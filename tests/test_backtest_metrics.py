"""Tests for compact backtest summary metrics."""

from datetime import date

import pytest

from backtests.metrics import (
    build_summary_metrics,
    calculate_cagr,
    calculate_equity_curve,
    calculate_max_drawdown,
)
from backtests.models import BacktestTradeResult


def _trade(symbol: str, entry: float, exit_: float, qty: float, entry_day: int, exit_day: int) -> BacktestTradeResult:
    return BacktestTradeResult(
        symbol=symbol,
        entry_date=date(2025, 1, entry_day),
        exit_date=date(2025, 1, exit_day),
        entry_price=entry,
        exit_price=exit_,
        quantity=qty,
    )


def test_summary_metrics_simple_positive_sequence() -> None:
    """All-winning sequence should produce positive return metrics."""
    trades = [
        _trade("AAPL", 100.0, 110.0, 1, 1, 5),
        _trade("MSFT", 200.0, 220.0, 1, 6, 10),
    ]

    metrics = build_summary_metrics(trades, starting_equity=1_000.0)

    assert calculate_equity_curve(trades, 1_000.0) == [1_000.0, 1_010.0, 1_030.0]
    assert metrics["total_trades"] == 2
    assert metrics["total_pnl"] == 30.0
    assert metrics["ending_equity"] == 1_030.0
    assert metrics["total_return"] == pytest.approx(0.03)
    assert metrics["win_rate"] == 1.0
    assert metrics["profit_factor"] == float("inf")
    assert metrics["cagr"] > 0.0


def test_max_drawdown_calculation() -> None:
    """Maximum drawdown should capture largest peak-to-trough decline."""
    # Peak 120 -> trough 90 = 25% drawdown.
    equity_curve = [100.0, 120.0, 90.0, 130.0, 125.0]
    assert calculate_max_drawdown(equity_curve) == 0.25


def test_calculate_cagr_total_loss_returns_negative_one() -> None:
    """A wiped-out equity curve should report -100% CAGR."""
    cagr = calculate_cagr([1_000.0, 0.0], date(2025, 1, 1), date(2026, 1, 1))
    assert cagr == -1.0


def test_summary_metrics_wiped_out_reports_negative_one_cagr() -> None:
    """Summary metrics should report -100% CAGR when ending equity is zero."""
    trades = [
        _trade("AAPL", 100.0, 0.0, 10, 1, 10),
    ]

    metrics = build_summary_metrics(trades, starting_equity=1_000.0)

    assert metrics["ending_equity"] == 0.0
    assert metrics["total_return"] == -1.0
    assert metrics["cagr"] == -1.0


def test_summary_metrics_empty_input() -> None:
    """Empty input should return safe default metrics."""
    metrics = build_summary_metrics([], starting_equity=1_000.0)

    assert metrics == {
        "total_trades": 0,
        "total_pnl": 0,
        "ending_equity": 1_000.0,
        "total_return": 0.0,
        "cagr": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
    }


def test_summary_metrics_mixed_win_loss_trades() -> None:
    """Mixed trades should report sensible win rate and profit factor."""
    trades = [
        _trade("AAPL", 100.0, 110.0, 1, 1, 2),  # +10
        _trade("MSFT", 200.0, 190.0, 1, 3, 4),  # -10
        _trade("GOOG", 50.0, 70.0, 1, 5, 7),  # +20
    ]

    metrics = build_summary_metrics(trades, starting_equity=1_000.0)

    assert metrics["win_rate"] == 2 / 3
    assert metrics["profit_factor"] == 3.0  # (10 + 20) / 10
    assert metrics["max_drawdown"] == 10 / 1_010
