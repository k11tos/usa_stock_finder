"""Backtest metrics skeleton tests."""

from datetime import date

import backtests.metrics  # noqa: F401
from backtests.models import BacktestCandidateRow, BacktestPosition, BacktestTradeResult


def test_backtest_metrics_module_imports() -> None:
    """Skeleton module should be import-safe."""
    assert backtests.metrics is not None


def test_backtest_models_are_lightweight() -> None:
    """Model dataclasses should be constructable with minimal fields."""
    candidate = BacktestCandidateRow("AAPL", date(2026, 1, 2), 200.0, 1_000_000)
    position = BacktestPosition("AAPL", date(2026, 1, 2), 200.0, 10)
    trade = BacktestTradeResult("AAPL", date(2026, 1, 2), date(2026, 1, 10), 200.0, 220.0, 10)

    assert candidate.symbol == "AAPL"
    assert position.quantity == 10
    assert trade.pnl == 200.0
