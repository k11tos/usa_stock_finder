"""Tests for backtest exit-rule helpers."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from backtests.exit_rules import (
    should_exit_hold_fixed,
    should_exit_stop_loss,
    should_exit_trailing,
    should_exit_trend,
)


@pytest.fixture
def base_position() -> dict[str, float | date]:
    return {
        "symbol": "AAA",
        "entry_date": date(2026, 1, 2),
        "entry_price": 100.0,
        "highest_close": 112.0,
    }


def test_fixed_hold_triggers_on_boundary(base_position: dict[str, float | date]) -> None:
    row = {"trade_date": date(2026, 1, 7), "close": 105.0}  # 5 days held

    should_exit, reason = should_exit_hold_fixed(base_position, row, hold_days=5)

    assert should_exit is True
    assert reason == "hold_fixed"


def test_fixed_hold_does_not_trigger_before_boundary(base_position: dict[str, float | date]) -> None:
    row = {"trade_date": date(2026, 1, 6), "close": 105.0}  # 4 days held

    should_exit, reason = should_exit_hold_fixed(base_position, row, hold_days=5)

    assert should_exit is False
    assert reason is None


def test_stop_loss_triggers_at_threshold(base_position: dict[str, float | date]) -> None:
    row = {"trade_date": date(2026, 1, 10), "close": 92.0}

    should_exit, reason = should_exit_stop_loss(base_position, row, stop_loss_pct=0.08)

    assert should_exit is True
    assert reason == "stop_loss"


def test_stop_loss_triggers_with_numpy_int_close(base_position: dict[str, float | date]) -> None:
    row = {"trade_date": date(2026, 1, 10), "close": np.int64(92)}

    should_exit, reason = should_exit_stop_loss(base_position, row, stop_loss_pct=0.08)

    assert should_exit is True
    assert reason == "stop_loss"


def test_stop_loss_non_trigger_when_above_threshold(base_position: dict[str, float | date]) -> None:
    row = {"trade_date": date(2026, 1, 10), "close": 92.01}

    should_exit, reason = should_exit_stop_loss(base_position, row, stop_loss_pct=0.08)

    assert should_exit is False
    assert reason is None


def test_trailing_stop_triggers_at_threshold(base_position: dict[str, float | date]) -> None:
    # 10% trailing from 112.0 high => stop at 100.8
    row = {"trade_date": date(2026, 1, 10), "close": 100.8}

    should_exit, reason = should_exit_trailing(base_position, row, trailing_pct=0.10)

    assert should_exit is True
    assert reason == "trailing_stop"


def test_trailing_stop_triggers_with_numpy_scalars() -> None:
    position = {
        "symbol": "AAA",
        "entry_date": date(2026, 1, 2),
        "entry_price": 100.0,
        "highest_close": np.float64(112.0),
    }
    row = {"trade_date": date(2026, 1, 10), "close": np.float64(100.8)}

    should_exit, reason = should_exit_trailing(position, row, trailing_pct=0.10)

    assert should_exit is True
    assert reason == "trailing_stop"


def test_trailing_stop_non_trigger_when_above_threshold(base_position: dict[str, float | date]) -> None:
    row = {"trade_date": date(2026, 1, 10), "close": 101.0}

    should_exit, reason = should_exit_trailing(base_position, row, trailing_pct=0.10)

    assert should_exit is False
    assert reason is None


def test_trend_exit_triggers_on_close_below_sma50(base_position: dict[str, float | date]) -> None:
    row = {"trade_date": date(2026, 1, 10), "close": 98.0, "sma50": 100.0}

    should_exit, reason = should_exit_trend(base_position, row)

    assert should_exit is True
    assert reason == "trend_break"


def test_trend_exit_triggers_with_numpy_scalars(base_position: dict[str, float | date]) -> None:
    row = {
        "trade_date": date(2026, 1, 10),
        "close": np.float64(98.0),
        "sma50": np.int64(100),
    }

    should_exit, reason = should_exit_trend(base_position, row)

    assert should_exit is True
    assert reason == "trend_break"


def test_trend_exit_non_trigger_when_close_above_sma50(base_position: dict[str, float | date]) -> None:
    row = {"trade_date": date(2026, 1, 10), "close": 101.0, "sma50": 100.0}

    should_exit, reason = should_exit_trend(base_position, row)

    assert should_exit is False
    assert reason is None


@pytest.mark.parametrize(
    ("fn", "position", "row", "kwargs"),
    [
        (
            should_exit_stop_loss,
            {"entry_price": "100"},
            {"close": 92.0},
            {"stop_loss_pct": 0.08},
        ),
        (
            should_exit_trailing,
            {"highest_close": "112"},
            {"close": 100.8},
            {"trailing_pct": 0.10},
        ),
        (
            should_exit_trend,
            {},
            {"close": "98", "sma50": 100.0},
            {},
        ),
    ],
)
def test_non_numeric_values_are_safely_rejected(
    fn,
    position: dict[str, object],
    row: dict[str, object],
    kwargs: dict[str, object],
) -> None:
    should_exit, reason = fn(position, row, **kwargs)

    assert should_exit is False
    assert reason is None


@pytest.mark.parametrize(
    ("fn", "kwargs"),
    [
        (should_exit_hold_fixed, {"hold_days": 0}),
        (should_exit_stop_loss, {"stop_loss_pct": 0.0}),
        (should_exit_trailing, {"trailing_pct": 0.0}),
    ],
)
def test_invalid_threshold_inputs_do_not_trigger(
    fn,
    kwargs: dict[str, float | int],
    base_position: dict[str, float | date],
) -> None:
    row = {"trade_date": date(2026, 1, 10), "close": 50.0, "sma50": 100.0}

    should_exit, reason = fn(base_position, row, **kwargs)

    assert should_exit is False
    assert reason is None
