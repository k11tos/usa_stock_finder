"""Entry-filter helpers for backtest candidate snapshots.

These functions provide deterministic, stateless row filters so backtests can
compare different trend-template strictness levels without affecting live code.
"""

from __future__ import annotations

import pandas as pd

_REQUIRED_COLUMNS = ["close", "sma50", "sma150", "sma200", "high_52w", "low_52w", "rs_score"]


def _validate_required_columns(universe_df: pd.DataFrame, *, filter_name: str) -> None:
    missing = [column for column in _REQUIRED_COLUMNS if column not in universe_df.columns]
    if missing:
        raise ValueError(f"{filter_name} requires columns that are missing: {missing}.")


def apply_no_filter(universe_df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of the input universe without any entry screening."""
    return universe_df.copy(deep=True)


def apply_trend_relaxed(universe_df: pd.DataFrame) -> pd.DataFrame:
    """Apply a relaxed Minervini-style trend template.

    Looser than the basic filter: lower RS floor and wider 52-week range checks.
    """
    _validate_required_columns(universe_df, filter_name="apply_trend_relaxed")

    mask = (
        (universe_df["close"] > universe_df["sma50"])
        & (universe_df["close"] > universe_df["sma150"])
        & (universe_df["sma50"] > universe_df["sma200"])
        & (universe_df["close"] >= 1.15 * universe_df["low_52w"])
        & (universe_df["close"] >= 0.65 * universe_df["high_52w"])
        & (universe_df["rs_score"] >= 60)
    )
    return universe_df.loc[mask].copy(deep=True).reset_index(drop=True)


def apply_trend_basic(universe_df: pd.DataFrame) -> pd.DataFrame:
    """Apply a basic Minervini-style trend template.

    Mid-point strictness balancing trend alignment, RS, and 52-week positioning.
    """
    _validate_required_columns(universe_df, filter_name="apply_trend_basic")

    mask = (
        (universe_df["close"] > universe_df["sma50"])
        & (universe_df["sma50"] > universe_df["sma150"])
        & (universe_df["sma150"] > universe_df["sma200"])
        & (universe_df["close"] >= 1.25 * universe_df["low_52w"])
        & (universe_df["close"] >= 0.75 * universe_df["high_52w"])
        & (universe_df["rs_score"] >= 70)
    )
    return universe_df.loc[mask].copy(deep=True).reset_index(drop=True)


def apply_trend_strict(universe_df: pd.DataFrame) -> pd.DataFrame:
    """Apply a strict Minervini-style trend template.

    Tighter than the basic filter: stronger RS floor and closer-to-high behavior.
    """
    _validate_required_columns(universe_df, filter_name="apply_trend_strict")

    mask = (
        (universe_df["close"] > universe_df["sma50"])
        & (universe_df["sma50"] > universe_df["sma150"])
        & (universe_df["sma150"] > universe_df["sma200"])
        & (universe_df["sma50"] > universe_df["sma200"])
        & (universe_df["close"] >= 1.35 * universe_df["low_52w"])
        & (universe_df["close"] >= 0.85 * universe_df["high_52w"])
        & (universe_df["rs_score"] >= 80)
    )
    return universe_df.loc[mask].copy(deep=True).reset_index(drop=True)
