"""
trailing_stop.py

This module provides functionality for managing trailing stop state,
specifically tracking the highest close price for each symbol to support
ATR-based trailing stop loss calculations.

The trailing stop uses the highest close price reached during the locally
observable holding period and calculates a stop level from ATR.  The observed
period can start after the actual purchase when snapshot logging is newer.
"""

import json
import logging
import os
from csv import DictReader
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict

import pandas as pd

logger = logging.getLogger(__name__)

TRAILING_STATE_PATH = os.path.join("data", "trailing_state.json")
ACCOUNT_SNAPSHOTS_PATH = os.path.join("data", "live", "account_snapshots.csv")


@dataclass(frozen=True)
class ObservedHoldingSnapshot:
    """Position facts observed during one complete account snapshot run."""

    run_date: date
    quantity: float
    avg_price: float | None
    run_id: str = ""


def _read_observed_holding_runs(
    snapshots_path: str | os.PathLike[str],
) -> list[dict[str, Any]]:
    """Read valid account snapshot runs in execution order."""
    path = Path(snapshots_path)
    if not path.exists():
        return []

    try:
        with path.open(newline="", encoding="utf-8") as file_obj:
            rows = list(DictReader(file_obj))
    except (OSError, UnicodeError):
        logger.warning(
            "Unable to read account snapshots for trailing recovery: %s", path
        )
        return []

    runs: dict[str, dict[str, Any]] = {}
    for row in rows:
        run_id = (row.get("run_id") or "").strip()
        run_date = (row.get("run_date") or "").strip()
        if not run_id or not run_date:
            continue
        try:
            parsed_date = date.fromisoformat(run_date)
            quantity = float(row.get("quantity") or 0.0)
        except (TypeError, ValueError):
            runs.setdefault(
                run_id,
                {"run_id": run_id, "date": None, "invalid": True, "symbols": {}},
            )
            runs[run_id]["invalid"] = True
            continue
        run = runs.setdefault(
            run_id,
            {"run_id": run_id, "date": parsed_date, "invalid": False, "symbols": {}},
        )
        if run["date"] != parsed_date:
            run["invalid"] = True
        row_symbol = (row.get("symbol") or "").strip().upper()
        if row_symbol:
            position = run["symbols"].setdefault(
                row_symbol,
                {"quantity": 0.0, "cost": 0.0, "avg_valid": True},
            )
            position["quantity"] += quantity
            try:
                row_avg = float(row.get("avg_price") or 0.0)
            except (TypeError, ValueError):
                row_avg = 0.0
            if quantity > 0 and row_avg > 0:
                position["cost"] += quantity * row_avg
            elif quantity > 0:
                position["avg_valid"] = False

    return sorted(
        (
            run
            for run in runs.values()
            if not run["invalid"] and run["date"] is not None
        ),
        key=lambda run: (run["date"], run["run_id"]),
    )


def get_observed_holding_history(
    symbol: str,
    snapshots_path: str | os.PathLike[str] = ACCOUNT_SNAPSHOTS_PATH,
) -> list[ObservedHoldingSnapshot]:
    """Return snapshots in the current observed positive-holding segment.

    An invalid average price remains represented as ``None`` rather than being
    replaced with the latest cost basis.  This lets activation recovery decline
    to make a retroactive inference when the contemporaneous basis is unknown.
    """
    ordered = _read_observed_holding_runs(snapshots_path)
    target = symbol.upper()
    if not ordered or ordered[-1]["symbols"].get(target, {}).get("quantity", 0.0) <= 0:
        return []

    current_segment = []
    for run in reversed(ordered):
        position = run["symbols"].get(target, {})
        quantity = position.get("quantity", 0.0)
        if quantity <= 0:
            break
        avg_price = (
            position["cost"] / quantity
            if position.get("avg_valid", False) and position.get("cost", 0.0) > 0
            else None
        )
        current_segment.append(
            ObservedHoldingSnapshot(run["date"], quantity, avg_price, run["run_id"])
        )
    return list(reversed(current_segment))


def get_observed_holding_since(
    symbol: str,
    snapshots_path: str | os.PathLike[str] = ACCOUNT_SNAPSHOTS_PATH,
) -> date | None:
    """Return the first date in the latest *observed* positive-holding segment.

    A snapshot run contains every holding returned by the broker.  Consequently a
    symbol missing from a valid run is an observed zero position; calendar dates
    without a run are simply unknown and do not break a segment.  If the latest
    recorded run does not contain ``symbol`` (for example, a re-purchase after the
    last snapshot), there is no defensible start date and ``None`` is returned.

    This is deliberately named "observed" holding start.  The CSV may have been
    introduced after the purchase, so the returned date is not asserted to be the
    broker's actual purchase date.
    """
    history = get_observed_holding_history(symbol, snapshots_path)
    return history[0].run_date if history else None


def reconstruct_highest_close(
    finder: Any,
    symbol: str,
    observed_holding_since: date,
) -> float | None:
    """Return the maximum loaded daily Close on/after an observed holding start."""
    try:
        closes = finder.stock_data["Close"][symbol]
        index_dates = pd.to_datetime(closes.index, errors="coerce").date
        eligible = pd.to_numeric(closes, errors="coerce")[
            index_dates >= observed_holding_since
        ].dropna()
        eligible = eligible[eligible > 0]
        return float(eligible.max()) if not eligible.empty else None
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def reconstruct_activated_highest_close(
    finder: Any,
    symbol: str,
    history: list[ObservedHoldingSnapshot],
    min_profit_pct: float,
) -> float | None:
    """Recover an activated high without retroactively applying a new basis.

    When every observed cost basis is the same, all closes in the observed
    segment can be evaluated.  If the basis changed, only closes on snapshot
    dates have a contemporaneously observed basis.  Once activation is proven,
    normal trailing semantics resume and every later close can update the high.
    """
    if not history:
        return None
    try:
        closes = pd.to_numeric(
            finder.stock_data["Close"][symbol], errors="coerce"
        ).dropna()
        closes_by_date = {
            timestamp.date(): float(close)
            for timestamp, close in zip(
                pd.to_datetime(closes.index, errors="coerce"), closes
            )
            if not pd.isna(timestamp) and float(close) > 0
        }
    except (AttributeError, KeyError, TypeError, ValueError):
        return None

    known_bases = [
        snapshot.avg_price for snapshot in history if snapshot.avg_price is not None
    ]
    all_bases_known = len(known_bases) == len(history)
    constant_basis = all_bases_known and all(
        abs(basis - known_bases[0]) <= 1e-6 for basis in known_bases[1:]
    )
    activation_date = None
    if constant_basis:
        threshold = known_bases[0] * (1 + min_profit_pct)
        activation_date = next(
            (
                close_date
                for close_date, close in sorted(closes_by_date.items())
                if close_date >= history[0].run_date and close >= threshold
            ),
            None,
        )
    else:
        for snapshot in history:
            close = closes_by_date.get(snapshot.run_date)
            if (
                snapshot.avg_price is not None
                and close is not None
                and close >= snapshot.avg_price * (1 + min_profit_pct)
            ):
                activation_date = snapshot.run_date
                break

    if activation_date is None:
        return None
    activated_closes = [
        close
        for close_date, close in closes_by_date.items()
        if close_date >= activation_date
    ]
    return max(activated_closes) if activated_closes else None


def has_constant_observed_cost_basis(
    history: list[ObservedHoldingSnapshot],
    current_avg_price: float,
) -> bool:
    """Return whether every observed basis is known and equals the current basis."""
    return bool(history) and all(
        snapshot.avg_price is not None
        and abs(snapshot.avg_price - current_avg_price) <= 1e-6
        for snapshot in history
    )


def state_matches_observed_segment(
    state_entry: dict[str, Any],
    observed_holding_history: list[ObservedHoldingSnapshot],
    symbol: str,
    snapshots_path: str | os.PathLike[str] = ACCOUNT_SNAPSHOTS_PATH,
) -> bool:
    """Return whether state explicitly identifies the current holding segment.

    The snapshot ``run_id`` is the segment boundary.  A date-only marker is
    accepted only for legacy state when snapshot history proves that no earlier
    positive run for the symbol exists on that same date.  This preserves safe
    legacy state while rejecting the ambiguous same-day exit/re-entry case.
    """
    if not observed_holding_history:
        return False

    current_segment = observed_holding_history[0]
    if "observed_holding_run_id" in state_entry:
        return (
            bool(current_segment.run_id)
            and str(state_entry.get("observed_holding_run_id", "")).strip()
            == current_segment.run_id
        )

    try:
        legacy_since = date.fromisoformat(str(state_entry.get("observed_holding_since", "")))
    except ValueError:
        return False

    if legacy_since != current_segment.run_date:
        return False
    if not current_segment.run_id:
        return True

    ordered = _read_observed_holding_runs(snapshots_path)
    current_index = next(
        (
            index
            for index, run in enumerate(ordered)
            if run["run_id"] == current_segment.run_id
        ),
        None,
    )
    if current_index is None:
        return False

    target = symbol.upper()
    return not any(
        run["date"] == current_segment.run_date
        and run["symbols"].get(target, {}).get("quantity", 0.0) > 0
        for run in ordered[:current_index]
    )


def load_trailing_state() -> Dict[str, Dict[str, Any]]:
    """
    trailing_state.json을 로드하여 딕셔너리로 반환.

    파일이 없거나 파싱에 실패하면 빈 dict를 반환한다.

    Returns:
        Dict[str, Dict[str, Any]]: Dictionary mapping symbols to their trailing state.
            Each value contains:
            - "highest_close": Highest close price reached
            - "last_update": ISO format date string of last update
            - "activated": Whether ATR trailing has been activated for the symbol
            - "observed_holding_since": Earliest date of the current segment seen in snapshots
            - "observed_holding_run_id": First snapshot run_id of the current segment
    """
    if not os.path.exists(TRAILING_STATE_PATH):
        logger.debug("Trailing state file does not exist: %s", TRAILING_STATE_PATH)
        return {}

    try:
        with open(TRAILING_STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
            logger.debug("Trailing state loaded: %d symbols", len(state))
            return state
    except json.JSONDecodeError as e:
        logger.warning(
            "Failed to parse trailing state file: %s. Returning empty state.", str(e)
        )
        return {}
    except Exception as e:
        logger.warning(
            "Error loading trailing state file: %s. Returning empty state.", str(e)
        )
        return {}


def save_trailing_state(state: Dict[str, Dict[str, Any]]) -> None:
    """
    주어진 상태 딕셔너리를 trailing_state.json에 저장한다.

    디렉토리가 없으면 생성한다.

    Args:
        state (Dict[str, Dict[str, Any]]): Trailing state dictionary to save
    """
    try:
        os.makedirs(os.path.dirname(TRAILING_STATE_PATH), exist_ok=True)
        with open(TRAILING_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        logger.debug("Trailing state saved: %d symbols", len(state))
    except Exception as e:
        logger.error("Error saving trailing state file: %s", str(e))
        raise


def update_highest_close(
    state: Dict[str, Dict[str, Any]],
    symbol: str,
    close_price: float,
    today: date,
) -> float:
    """
    주어진 심볼에 대해 최고 종가(highest_close)를 업데이트한다.

    - 기존 값이 없으면 현재 종가를 최고가로 설정.
    - 기존 값이 있으면 max(기존, 현재)로 갱신.
    - state를 직접 수정하고, 최신 highest_close를 반환한다.

    Args:
        state (Dict[str, Dict[str, Any]]): Trailing state dictionary (modified in place)
        symbol (str): Stock symbol
        close_price (float): Current close price
        today (date): Current date

    Returns:
        float: Updated highest close price
    """
    if close_price <= 0:
        prev_high = state.get(symbol, {}).get("highest_close", 0.0)
        logger.debug(
            "%s: Invalid close_price (%.4f), returning previous highest_close (%.4f)",
            symbol,
            close_price,
            prev_high,
        )
        return prev_high

    entry = state.get(symbol, {})
    prev_high = float(entry.get("highest_close", 0.0))

    new_high = max(prev_high, close_price) if prev_high > 0 else close_price

    state[symbol] = {
        **entry,
        "highest_close": new_high,
        "last_update": today.isoformat(),
    }

    if new_high > prev_high:
        logger.debug(
            "%s: 최고 종가 갱신 - 이전: %.4f, 현재: %.4f, 새로운 최고가: %.4f",
            symbol,
            prev_high,
            close_price,
            new_high,
        )
    else:
        logger.debug(
            "%s: 최고 종가 유지 - 현재: %.4f, 최고가: %.4f",
            symbol,
            close_price,
            new_high,
        )

    return new_high
