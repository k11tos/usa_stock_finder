"""Deterministic exit-rule helpers for the backtesting layer.

These rules are intentionally stateless and conservative so we can compare
whether weak satellite-strategy performance is caused by exits rather than
entries. The helpers accept lightweight row/position objects (dict-like,
``pandas.Series``, or dataclass-style objects) and return:

``(should_exit: bool, exit_reason: str | None)``

No live/runtime modules are imported here; this module is backtest-only.
"""

from __future__ import annotations

from datetime import date
from numbers import Real
from typing import Any


def _get_value(source: Any, key: str) -> Any:
    """Read ``key`` from mapping-like or attribute-style objects."""
    if isinstance(source, dict):
        return source.get(key)

    getter = getattr(source, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except TypeError:
            # Some objects provide ``get`` with incompatible signatures.
            pass

    return getattr(source, key, None)


def _days_held(position: Any, row: Any) -> int | None:
    """Return calendar days from entry date to current row date, inclusive-safe."""
    entry_date = _get_value(position, "entry_date")
    trade_date = _get_value(row, "trade_date")

    if not isinstance(entry_date, date) or not isinstance(trade_date, date):
        return None

    return (trade_date - entry_date).days


def _as_positive_real(value: Any) -> float | None:
    """Return value as float when it is a positive real scalar.

    Accepts Python numeric types and NumPy real scalars. Rejects bool and
    non-numeric values to keep exit checks conservative and predictable.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        return None

    numeric_value = float(value)
    if numeric_value <= 0:
        return None

    return numeric_value


def should_exit_hold_fixed(position: Any, row: Any, hold_days: int) -> tuple[bool, str | None]:
    """Exit after a fixed holding period boundary has been reached.

    Conservative rule:
    - No exit if ``hold_days`` is non-positive or dates are unavailable.
    - Exit only when days held is **greater than or equal** to ``hold_days``.
    """
    if hold_days <= 0:
        return False, None

    days_held = _days_held(position, row)
    if days_held is None:
        return False, None

    if days_held >= hold_days:
        return True, "hold_fixed"

    return False, None


def should_exit_stop_loss(position: Any, row: Any, stop_loss_pct: float) -> tuple[bool, str | None]:
    """Exit when close falls to or below entry-based absolute stop.

    Example: ``stop_loss_pct=0.08`` exits at ``entry_price * 0.92`` or lower.
    """
    if stop_loss_pct <= 0:
        return False, None

    entry_price = _get_value(position, "entry_price")
    close = _get_value(row, "close")

    entry_price_numeric = _as_positive_real(entry_price)
    close_numeric = _as_positive_real(close)
    if entry_price_numeric is None or close_numeric is None:
        return False, None

    stop_price = entry_price_numeric * (1 - stop_loss_pct)
    if close_numeric <= stop_price:
        return True, "stop_loss"

    return False, None


def should_exit_trailing(position: Any, row: Any, trailing_pct: float) -> tuple[bool, str | None]:
    """Exit when close falls ``trailing_pct`` below the run-up high since entry.

    Expected position field:
    - ``highest_close``: highest close seen since entry.

    This helper does not mutate state; callers should update ``highest_close``
    in their simulation loop.
    """
    if trailing_pct <= 0:
        return False, None

    highest_close = _get_value(position, "highest_close")
    close = _get_value(row, "close")

    highest_close_numeric = _as_positive_real(highest_close)
    close_numeric = _as_positive_real(close)
    if highest_close_numeric is None or close_numeric is None:
        return False, None

    trailing_stop_price = highest_close_numeric * (1 - trailing_pct)
    if close_numeric <= trailing_stop_price:
        return True, "trailing_stop"

    return False, None


def should_exit_trend(position: Any, row: Any) -> tuple[bool, str | None]:
    """Exit on a conservative trend break.

    Conservative definition for this first backtest pass:
    - Require ``close`` and ``sma50``.
    - Trigger only when ``close < sma50``.

    We intentionally defer stricter/alternative trend exits (e.g., MA-slope,
    multi-MA violations, AVSL) to later iterations.
    """
    del position  # Reserved for future trend logic that may depend on position age.

    close = _get_value(row, "close")
    sma50 = _get_value(row, "sma50")

    close_numeric = _as_positive_real(close)
    sma50_numeric = _as_positive_real(sma50)
    if close_numeric is None or sma50_numeric is None:
        return False, None

    if close_numeric < sma50_numeric:
        return True, "trend_break"

    return False, None
