"""Tests for backtest universe construction helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from backtests.universe import (
    build_quantus_minervini_universe,
    build_quantus_universe,
)


@pytest.fixture
def candidate_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "asof_date": ["2025-01-02", "2025-01-02", "2025-01-02", "2025-01-03"],
            "symbol": ["AAA", "BBB", "CCC", "ZZZ"],
            "market_cap": [500_000_000, 100_000_000, 600_000_000, 800_000_000],
            "avg_dollar_volume": [8_000_000, 6_000_000, 2_000_000, 10_000_000],
            "rs_score": [75, 90, 80, 95],
            "pct_below_52w_high": [20, 15, 10, 5],
        }
    )


def test_build_quantus_universe_filters_to_requested_date(candidate_fixture: pd.DataFrame) -> None:
    universe = build_quantus_universe(candidate_fixture, "2025-01-02")

    assert set(universe["symbol"]) == {"AAA", "BBB", "CCC"}
    assert (universe["asof_date"].apply(lambda value: value.date()) == pd.Timestamp("2025-01-02").date()).all()


def test_quantus_universe_matches_utc_timestamp_string_rows() -> None:
    candidates = pd.DataFrame(
        {
            "asof_date": ["2025-01-02T00:00:00Z", "2025-01-03T00:00:00Z"],
            "symbol": ["AAA", "ZZZ"],
        }
    )

    universe = build_quantus_universe(candidates, "2025-01-02")

    assert list(universe["symbol"]) == ["AAA"]


def test_quantus_universe_matches_rows_with_time_component() -> None:
    candidates = pd.DataFrame(
        {
            "asof_date": ["2025-01-02 15:30:00", "2025-01-03 09:15:00"],
            "symbol": ["AAA", "ZZZ"],
        }
    )

    universe = build_quantus_universe(candidates, "2025-01-02")

    assert list(universe["symbol"]) == ["AAA"]


def test_minervini_universe_is_subset_of_quantus_universe_with_normalized_dates() -> None:
    candidates = pd.DataFrame(
        {
            "asof_date": [
                "2025-01-02T00:00:00Z",
                "2025-01-02 15:30:00",
                "2025-01-02",
                "2025-01-03",
            ],
            "symbol": ["AAA", "BBB", "CCC", "ZZZ"],
            "market_cap": [500_000_000, 100_000_000, 600_000_000, 800_000_000],
            "avg_dollar_volume": [8_000_000, 6_000_000, 2_000_000, 10_000_000],
            "rs_score": [75, 90, 80, 95],
            "pct_below_52w_high": [20, 15, 10, 5],
        }
    )

    quantus = build_quantus_universe(candidates, "2025-01-02")
    minervini = build_quantus_minervini_universe(candidates, "2025-01-02")

    assert set(minervini["symbol"]).issubset(set(quantus["symbol"]))
    assert set(minervini["symbol"]) == {"AAA"}


def test_minervini_universe_missing_required_column_raises_clear_error(
    candidate_fixture: pd.DataFrame,
) -> None:
    candidates_without_market_cap = candidate_fixture.drop(columns=["market_cap"])

    with pytest.raises(ValueError, match="requires columns") as exc_info:
        build_quantus_minervini_universe(candidates_without_market_cap, "2025-01-02")

    assert "market_cap" in str(exc_info.value)
