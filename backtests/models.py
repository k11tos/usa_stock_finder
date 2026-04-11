"""Lightweight dataclasses for future backtesting workflows."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class LMReviewDecision(StrEnum):
    """LM review decision for a candidate."""

    PASSED = "passed"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class LMReviewFinalAction(StrEnum):
    """Portfolio action after LM review."""

    KEEP = "keep"
    DROP = "drop"
    DEFER = "defer"


class LMReviewReasonCode(StrEnum):
    """Short enumerable reason codes for LM-assisted qualitative review."""

    NEWS_RISK = "news_risk"
    EVENT_RISK = "event_risk"
    EARNINGS_SOON = "earnings_soon"
    LIQUIDITY_FLAG = "liquidity_flag"
    THESIS_WEAK = "thesis_weak"
    TECHNICAL_WEAK = "technical_weak"
    NO_CLEAR_EDGE = "no_clear_edge"
    MANUAL_OVERRIDE = "manual_override"


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
# Intentional flat schema for persisted trade diagnostics.
# pylint: disable=too-many-instance-attributes
class BacktestTradeResult:
    """Represents a completed trade outcome."""

    symbol: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    quantity: float
    universe: str | None = None
    entry_filter: str | None = None
    exit_rule: str | None = None
    exit_reason: str | None = None
    entry_signal_date: date | None = None
    holding_days: int | None = None
    rank_value: float | None = None

    @property
    def pnl(self) -> float:
        """Absolute profit/loss for the trade."""
        return (self.exit_price - self.entry_price) * self.quantity


@dataclass(slots=True)
class LMCandidateReviewLog:
    """Structured qualitative review outcome for a candidate symbol."""

    date: date
    symbol: str
    decision: LMReviewDecision
    confidence: float
    reason_codes: tuple[LMReviewReasonCode, ...]
    final_action: LMReviewFinalAction
