"""Lightweight dataclasses for future backtesting workflows."""

from dataclasses import dataclass
from datetime import date


@dataclass(slots=True)
class BacktestCandidateRow:
    """Single candidate row used during universe/entry evaluation."""

    symbol: str
    trade_date: date
    close: float
    volume: float


@dataclass(slots=True)
class BacktestPosition:
    """Represents an open backtest position."""

    symbol: str
    entry_date: date
    entry_price: float
    quantity: float


@dataclass(slots=True)
class BacktestTradeResult:
    """Represents a completed trade outcome."""

    symbol: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    quantity: float

    @property
    def pnl(self) -> float:
        """Absolute profit/loss for the trade."""
        return (self.exit_price - self.entry_price) * self.quantity
