"""
trailing_stop.py

This module provides functionality for managing trailing stop state,
specifically tracking the highest close price for each symbol to support
ATR-based trailing stop loss calculations.

The trailing stop uses the highest close price reached since purchase
and calculates a stop loss level based on ATR (Average True Range).
"""

import json
import logging
import os
from datetime import date
from typing import Any, Dict

logger = logging.getLogger(__name__)

TRAILING_STATE_PATH = os.path.join("data", "trailing_state.json")


def load_trailing_state() -> Dict[str, Dict[str, Any]]:
    """
    trailing_state.json을 로드하여 딕셔너리로 반환.

    파일이 없거나 파싱에 실패하면 빈 dict를 반환한다.

    Returns:
        Dict[str, Dict[str, Any]]: Dictionary mapping symbols to their trailing state.
            Each value contains:
            - "highest_close": Highest close price reached
            - "last_update": ISO format date string of last update
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
