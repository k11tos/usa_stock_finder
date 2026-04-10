"""Backtesting package scaffolding.

This package is intentionally minimal and isolated from runtime execution paths.
"""

from backtests.models import BacktestCandidateRow, BacktestPosition, BacktestTradeResult

__all__ = [
    "BacktestCandidateRow",
    "BacktestPosition",
    "BacktestTradeResult",
]
