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
from datetime import date
from pathlib import Path
from typing import Any, Dict

import pandas as pd

logger = logging.getLogger(__name__)

TRAILING_STATE_PATH = os.path.join("data", "trailing_state.json")
ACCOUNT_SNAPSHOTS_PATH = os.path.join("data", "live", "account_snapshots.csv")


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
    path = Path(snapshots_path)
    if not path.exists():
        return None

    try:
        with path.open(newline="", encoding="utf-8") as file_obj:
            rows = list(DictReader(file_obj))
    except (OSError, UnicodeError):
        logger.warning("Unable to read account snapshots for trailing recovery: %s", path)
        return None

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
            # A partially written run cannot safely establish presence/absence.
            runs.setdefault(run_id, {"date": None, "invalid": True, "symbols": {}})
            runs[run_id]["invalid"] = True
            continue
        run = runs.setdefault(run_id, {"date": parsed_date, "invalid": False, "symbols": {}})
        if run["date"] != parsed_date:
            run["invalid"] = True
        row_symbol = (row.get("symbol") or "").strip().upper()
        if row_symbol:
            run["symbols"][row_symbol] = run["symbols"].get(row_symbol, 0.0) + quantity

    ordered = sorted(
        (run for run in runs.values() if not run["invalid"] and run["date"] is not None),
        key=lambda run: run["date"],
    )
    if not ordered or ordered[-1]["symbols"].get(symbol.upper(), 0.0) <= 0:
        return None

    observed_start = ordered[-1]["date"]
    for run in reversed(ordered[:-1]):
        if run["symbols"].get(symbol.upper(), 0.0) <= 0:
            break
        observed_start = run["date"]
    return observed_start


def reconstruct_highest_close(
    finder: Any,
    symbol: str,
    observed_holding_since: date,
) -> float | None:
    """Return the maximum loaded daily Close on/after an observed holding start."""
    try:
        closes = finder.stock_data["Close"][symbol]
        index_dates = pd.to_datetime(closes.index, errors="coerce").date
        eligible = pd.to_numeric(closes, errors="coerce")[index_dates >= observed_holding_since].dropna()
        eligible = eligible[eligible > 0]
        return float(eligible.max()) if not eligible.empty else None
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


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
        logger.warning("Failed to parse trailing state file: %s. Returning empty state.", str(e))
        return {}
    except Exception as e:
        logger.warning("Error loading trailing state file: %s. Returning empty state.", str(e))
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
