"""Tests for backtest entry filter helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from backtests.entry_filters import (
    apply_no_filter,
    apply_trend_basic,
    apply_trend_relaxed,
    apply_trend_strict,
)


@pytest.fixture
def candidate_snapshot_df() -> pd.DataFrame:
    """Fixture with rows intentionally spanning relaxed/basic/strict thresholds."""
    return pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "close": 100.0,
                "sma50": 95.0,
                "sma150": 90.0,
                "sma200": 85.0,
                "high_52w": 110.0,
                "low_52w": 70.0,
                "rs_score": 88.0,
            },
            {
                "symbol": "BBB",
                "close": 82.0,
                "sma50": 80.0,
                "sma150": 78.0,
                "sma200": 75.0,
                "high_52w": 105.0,
                "low_52w": 62.0,
                "rs_score": 74.0,
            },
            {
                "symbol": "CCC",
                "close": 72.0,
                "sma50": 69.0,
                "sma150": 67.0,
                "sma200": 65.0,
                "high_52w": 105.0,
                "low_52w": 58.0,
                "rs_score": 64.0,
            },
            {
                "symbol": "DDD",
                "close": 60.0,
                "sma50": 62.0,
                "sma150": 63.0,
                "sma200": 64.0,
                "high_52w": 110.0,
                "low_52w": 50.0,
                "rs_score": 85.0,
            },
        ]
    )


def test_no_filter_preserves_rows(candidate_snapshot_df: pd.DataFrame) -> None:
    """No filter should preserve every row and return a separate frame."""
    result = apply_no_filter(candidate_snapshot_df)

    assert len(result) == len(candidate_snapshot_df)
    pd.testing.assert_frame_equal(result, candidate_snapshot_df)
    assert result is not candidate_snapshot_df


def test_relaxed_basic_strict_hierarchy(candidate_snapshot_df: pd.DataFrame) -> None:
    """Relaxed should be a superset of basic, and basic of strict on fixture data."""
    relaxed = apply_trend_relaxed(candidate_snapshot_df)
    basic = apply_trend_basic(candidate_snapshot_df)
    strict = apply_trend_strict(candidate_snapshot_df)

    assert len(relaxed) >= len(basic) >= len(strict)

    relaxed_symbols = set(relaxed["symbol"])
    basic_symbols = set(basic["symbol"])
    strict_symbols = set(strict["symbol"])

    assert basic_symbols.issubset(relaxed_symbols)
    assert strict_symbols.issubset(basic_symbols)


@pytest.mark.parametrize(
    "filter_fn",
    [apply_trend_relaxed, apply_trend_basic, apply_trend_strict],
)
def test_missing_required_columns_fail_clearly(filter_fn) -> None:
    """Trend filters should fail with a clear missing-column error."""
    missing_columns_df = pd.DataFrame(
        [{"close": 100.0, "sma50": 95.0, "sma150": 90.0, "high_52w": 110.0, "low_52w": 70.0}]
    )

    with pytest.raises(ValueError, match="requires columns that are missing"):
        filter_fn(missing_columns_df)
