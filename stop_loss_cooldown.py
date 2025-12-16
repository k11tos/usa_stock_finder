"""
stop_loss_cooldown.py

This module provides functionality for managing Stop Loss cooldown periods.
When a stock is sold due to Stop Loss, it records the event and prevents
the stock from being included in buy signals for a variable cooldown period
based on the loss percentage.

The cooldown period is calculated as:
- Base days (default: 5 days)
- Plus extra days per 10% loss (default: 5 days per 10% loss block)
- With optional maximum cap (default: 60 days)

Example:
    -8% loss → 5 days cooldown
    -15% loss → 10 days cooldown (5 base + 5 for 1 block)
    -25% loss → 15 days cooldown (5 base + 10 for 2 blocks)
"""

import json
import logging
import os
from datetime import date
from typing import Any, Dict

from config import StrategyConfig

logger = logging.getLogger(__name__)

# Stop Loss 로그 파일 경로
STOP_LOSS_LOG_PATH = os.path.join("data", "stop_loss_log.json")


def load_stop_loss_log() -> Dict[str, Dict[str, Any]]:
    """
    stop_loss_log.json을 로드하여 딕셔너리로 반환.

    - 파일이 없거나 깨져 있어도 예외를 터뜨리지 말고, 빈 dict를 반환한다.

    Returns:
        Dict[str, Dict[str, Any]]: Stop Loss 로그 딕셔너리.
            키는 종목 심볼, 값은 {"last_stop_loss_date": "YYYY-MM-DD", "loss_pct": float}
    """
    if not os.path.exists(STOP_LOSS_LOG_PATH):
        logger.debug("Stop Loss 로그 파일이 없음: %s", STOP_LOSS_LOG_PATH)
        return {}

    try:
        with open(STOP_LOSS_LOG_PATH, "r", encoding="utf-8") as f:
            log = json.load(f)
            logger.debug("Stop Loss 로그 로드 성공: %d개 종목", len(log))
            return log
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("Stop Loss 로그 파일 로드 실패: %s, 빈 딕셔너리 반환", str(e))
        return {}


def save_stop_loss_log(log: Dict[str, Dict[str, Any]]) -> None:
    """
    주어진 로그 딕셔너리를 stop_loss_log.json에 저장한다.

    - 디렉토리가 없으면 생성한다.

    Args:
        log (Dict[str, Dict[str, Any]]): 저장할 Stop Loss 로그 딕셔너리
    """
    # 디렉토리 생성
    log_dir = os.path.dirname(STOP_LOSS_LOG_PATH)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
        logger.debug("Stop Loss 로그 디렉토리 생성: %s", log_dir)

    try:
        with open(STOP_LOSS_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2, ensure_ascii=False)
        logger.debug("Stop Loss 로그 저장 성공: %d개 종목", len(log))
    except IOError as e:
        logger.error("Stop Loss 로그 파일 저장 실패: %s", str(e))
        raise


def record_stop_loss_event(symbol: str, loss_pct: float | None, today: date) -> None:
    """
    특정 종목에 대한 매도 이벤트를 기록한다 (쿨다운 관리를 위해).

    - loss_pct가 음수이면 손실률에 비례한 쿨다운 적용
    - loss_pct가 None이거나 0 이상이면 기본 쿨다운만 적용 (수익 매도 등)
    - 동일 종목이 여러 번 매도되면 가장 최근 이벤트로 덮어쓴다.

    Args:
        symbol (str): 종목 심볼
        loss_pct (float | None): 손실률 (음수 값, 예: -0.24 == -24%). 
                                  None이거나 0 이상이면 기본 쿨다운만 적용
        today (date): 오늘 날짜
    """
    # loss_pct가 None이거나 0 이상이면 기본 쿨다운만 적용 (손실률 0으로 기록)
    if loss_pct is None or loss_pct >= 0:
        loss_pct_to_record = 0.0
        logger.debug(
            "%s: 매도 이벤트 기록 (기본 쿨다운) - loss_pct=%s (수익 매도 또는 손실률 없음)",
            symbol,
            loss_pct,
        )
    else:
        loss_pct_to_record = loss_pct

    log = load_stop_loss_log()
    log[symbol] = {
        "last_stop_loss_date": today.isoformat(),
        "loss_pct": loss_pct_to_record,
    }
    save_stop_loss_log(log)

    if loss_pct_to_record < 0:
        logger.info(
            "%s: 매도 이벤트 기록 완료 - loss_pct=%.4f (%.2f%%), date=%s",
            symbol,
            loss_pct_to_record,
            loss_pct_to_record * 100,
            today.isoformat(),
        )
    else:
        logger.info(
            "%s: 매도 이벤트 기록 완료 (기본 쿨다운 적용), date=%s",
            symbol,
            today.isoformat(),
        )


def calculate_cooldown_days(loss_pct: float) -> int:
    """
    손실률에 기반하여 쿨다운 일수를 계산한다.

    공식:
        loss_pct가 0 이상이면 기본 쿨다운만 적용
        loss_pct가 음수이면:
            abs_loss = abs(loss_pct)
            extra_blocks = int(abs_loss / 0.10)  # 10% 단위 블록 수
            cooldown_days = BASE_DAYS + extra_blocks * EXTRA_DAYS_PER_10PCT
        (선택) MAX_DAYS가 0보다 크면 상한 적용

    Args:
        loss_pct (float): 손실률 (음수 값, 예: -0.23 == -23%). 0 이상이면 기본 쿨다운만 적용

    Returns:
        int: 쿨다운 일수
    """
    # 손실률이 0 이상이면 기본 쿨다운만 적용
    if loss_pct >= 0:
        cooldown_days = StrategyConfig.STOP_LOSS_COOLDOWN_BASE_DAYS
        logger.debug(
            "쿨다운 일수 계산 (기본 쿨다운) - loss_pct=%.4f (%.2f%%), cooldown_days=%d",
            loss_pct,
            loss_pct * 100,
            cooldown_days,
        )
        return cooldown_days

    abs_loss = abs(loss_pct)  # 0.23
    extra_blocks = int(abs_loss / 0.10)  # 10% 단위 블록 수 (0.23 → 2)

    cooldown_days = (
        StrategyConfig.STOP_LOSS_COOLDOWN_BASE_DAYS
        + extra_blocks * StrategyConfig.STOP_LOSS_COOLDOWN_EXTRA_DAYS_PER_10PCT
    )

    # (선택) 상한 적용
    if StrategyConfig.STOP_LOSS_COOLDOWN_MAX_DAYS > 0:
        cooldown_days = min(cooldown_days, StrategyConfig.STOP_LOSS_COOLDOWN_MAX_DAYS)

    logger.debug(
        "쿨다운 일수 계산 - loss_pct=%.4f (%.2f%%), abs_loss=%.4f, extra_blocks=%d, cooldown_days=%d",
        loss_pct,
        loss_pct * 100,
        abs_loss,
        extra_blocks,
        cooldown_days,
    )

    return cooldown_days


def is_in_cooldown(symbol: str, today: date) -> bool:
    """
    주어진 심볼이 Stop Loss 쿨다운 기간 내에 있는지 여부를 반환한다.

    - 로그에 해당 심볼이 없으면 False
    - 쿨다운 기간을 초과했으면 False
    - 아직 쿨다운 기간 내라면 True

    Args:
        symbol (str): 종목 심볼
        today (date): 오늘 날짜

    Returns:
        bool: 쿨다운 기간 내이면 True, 아니면 False
    """
    log = load_stop_loss_log()
    entry = log.get(symbol)

    if not entry:
        logger.debug("%s: Stop Loss 로그에 없음, 쿨다운 아님", symbol)
        return False

    try:
        last_date_str = entry["last_stop_loss_date"]
        last_date = date.fromisoformat(last_date_str)
        loss_pct = entry["loss_pct"]

        # 쿨다운 일수 계산
        cooldown_days = calculate_cooldown_days(loss_pct)

        # 경과 일수 계산
        elapsed_days = (today - last_date).days

        is_cooldown = elapsed_days < cooldown_days

        logger.debug(
            "%s: 쿨다운 체크 - last_date=%s, loss_pct=%.4f (%.2f%%), "
            "cooldown_days=%d, elapsed_days=%d, is_in_cooldown=%s",
            symbol,
            last_date_str,
            loss_pct,
            loss_pct * 100,
            cooldown_days,
            elapsed_days,
            is_cooldown,
        )

        return is_cooldown

    except (KeyError, ValueError) as e:
        logger.warning("%s: Stop Loss 로그 항목 파싱 실패: %s, 쿨다운 아님으로 처리", symbol, str(e))
        return False
