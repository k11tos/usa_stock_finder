"""
sell_signals.py

This module provides data structures and functions for evaluating sell decisions
based on a 3-tier sell signal system:
1. Stop Loss (absolute loss threshold)
2. AVSL (Average Volume Support Level) decline
3. Trend/Strategy condition failure

The 3-tier system ensures that stocks with significant losses are sold immediately,
regardless of other conditions, preventing situations like EGAN where a -19% loss
would not trigger a sell signal.
"""

import logging
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Dict, List

from config import StrategyConfig
from stock_analysis import UsaStockFinder
from stop_loss_cooldown import record_stop_loss_event
from trailing_stop import load_trailing_state, save_trailing_state, update_highest_close

logger = logging.getLogger(__name__)


def select_current_price(finder_price: float, holding_price: float) -> float:
    """Return sell-calculation price, preferring positive finder price."""
    return finder_price if finder_price > 0 else holding_price


class SellReason(str, Enum):
    """Enumeration of reasons for selling a stock."""

    NONE = "HOLD"  # No sell signal - hold the stock
    STOP_LOSS = "STOP_LOSS"  # Absolute stop loss threshold exceeded
    TRAILING = "TRAILING"  # ATR 기반 트레일링 스탑
    SPECIAL_SITUATION_TAKE_PROFIT = "SPECIAL_SITUATION_TAKE_PROFIT"  # 이벤트 가격 고정 수익실현
    AVSL = "AVSL"  # Average Volume Support Level broken
    TREND = "TREND"  # Trend/strategy conditions no longer met


@dataclass
class SellDecision:
    """
    Data class representing a sell decision for a stock.

    Attributes:
        symbol (str): Stock ticker symbol
        reason (SellReason): Reason for the sell decision
        quantity (float): Quantity to sell (0.0 means hold, >0 means sell that amount)
    """

    symbol: str
    reason: SellReason
    quantity: float  # 0이면 매도 안 함, >0이면 매도 수량


def evaluate_holding_trend_exit(
    symbol: str,
    selected_buy: List[str],
    selected_not_sell: List[str],
    holding_trend_exit_signals: Dict[str, bool] | None = None,
) -> tuple[bool, bool]:
    """Return explicit trend-exit 여부 and stale_holding 여부 for an existing holding."""
    in_buy_list = symbol in selected_buy
    in_not_sell_list = symbol in selected_not_sell
    stale_holding = not in_buy_list and not in_not_sell_list
    should_exit_trend = holding_trend_exit_signals.get(symbol, False) if holding_trend_exit_signals else False
    return should_exit_trend, stale_holding


def evaluate_sell_decisions(
    finder: UsaStockFinder,
    holdings: List[dict[str, Any]],
    selected_buy: List[str],
    selected_not_sell: List[str],
    avsl_signals: Dict[str, bool],
    holding_trend_exit_signals: Dict[str, bool] | None = None,
) -> Dict[str, SellDecision]:
    """
    Evaluate sell decisions for all holdings using sell signal priority rules.

    The evaluation follows this priority order:
    1. Stop Loss (highest priority): If loss exceeds STOP_LOSS_PCT, sell immediately
    2. Special Situation Take Profit: If pinned near event price with enough profit, sell
    3. Trailing stop: If ATR trailing stop is broken, sell
    4. AVSL: If volume support level is broken, sell
    5. Trend: If explicit holding trend-exit condition is met, sell

    Args:
        finder (UsaStockFinder): Instance containing current stock prices
        holdings (List[dict[str, Any]]): List of current holdings, each containing:
            - "symbol": Stock ticker symbol
            - "quantity": Number of shares held
            - "avg_price": Average purchase price
        selected_buy (List[str]): List of stocks recommended for buying
        selected_not_sell (List[str]): List of stocks recommended to hold (not sell)
        avsl_signals (Dict[str, bool]): Dictionary of AVSL sell signals {symbol: bool}
        holding_trend_exit_signals (Dict[str, bool] | None): Explicit trend-exit
            signals for holdings {symbol: bool}

    Returns:
        Dict[str, SellDecision]: Dictionary mapping stock symbols to sell decisions

    Note:
        - Stop loss takes absolute priority - if triggered, other conditions are ignored
        - AVSL signals are checked only if stop loss is not triggered
        - Trend-based sells are checked only if earlier tiers are not triggered
        - Holdings outside selected_buy/selected_not_sell are treated as stale_holding,
          and are not sold unless explicit holding trend-exit is True
    """
    decisions: Dict[str, SellDecision] = {}

    # 트레일링 스탑 상태 로드 (한 번만)
    trailing_state = load_trailing_state()
    trailing_state_modified = False

    for holding in holdings:
        symbol = holding.get("symbol", "")
        if not symbol:
            logger.debug("Skipping holding with empty symbol: %s", holding)
            continue

        quantity = holding.get("quantity", 0.0)
        if quantity <= 0:
            # No shares to sell
            logger.debug("%s: No shares to sell (quantity=%.2f)", symbol, quantity)
            decisions[symbol] = SellDecision(symbol, SellReason.NONE, 0.0)
            continue

        avg_price = holding.get("avg_price", 0.0)

        # finder.current_price 우선 사용, 없거나 0이면 holdings의 current_price 사용
        finder_price = finder.current_price.get(symbol, 0.0)
        holding_price = holding.get("current_price", 0.0)
        current_price = select_current_price(finder_price, holding_price)

        # 기본 정보 로깅
        logger.debug(
            "%s: 매도 평가 시작 - avg_price=%.4f, finder.current_price=%.4f, holding.current_price=%.4f, "
            "selected_price=%.4f, quantity=%.2f",
            symbol,
            avg_price,
            finder_price,
            holding_price,
            current_price,
            quantity,
        )

        # Tier 1: Stop Loss (Absolute Priority)
        if avg_price > 0 and current_price > 0:
            loss_pct = (current_price - avg_price) / avg_price

            logger.debug(
                "%s: Stop Loss 체크 - loss_pct=%.4f (%.2f%%), STOP_LOSS_PCT=%.4f (%.2f%%)",
                symbol,
                loss_pct,
                loss_pct * 100,
                StrategyConfig.STOP_LOSS_PCT,
                StrategyConfig.STOP_LOSS_PCT * 100,
            )

            if loss_pct <= -StrategyConfig.STOP_LOSS_PCT:
                # Stop loss triggered - sell immediately regardless of other conditions
                # 🔴 Stop Loss 이벤트 기록 (쿨다운 관리를 위해)
                record_stop_loss_event(symbol, loss_pct, date.today())

                logger.info(
                    "%s: 🟥 STOP_LOSS 매도 결정 - loss_pct=%.4f (%.2f%%) <= -STOP_LOSS_PCT=%.4f (%.2f%%), quantity=%.2f",
                    symbol,
                    loss_pct,
                    loss_pct * 100,
                    StrategyConfig.STOP_LOSS_PCT,
                    StrategyConfig.STOP_LOSS_PCT * 100,
                    quantity,
                )
                decisions[symbol] = SellDecision(symbol, SellReason.STOP_LOSS, quantity)
                continue

            logger.debug(
                "%s: Stop Loss 미충족 - loss_pct=%.4f > -STOP_LOSS_PCT=%.4f",
                symbol,
                loss_pct,
                -StrategyConfig.STOP_LOSS_PCT,
            )
        else:
            if avg_price <= 0:
                logger.warning(
                    "%s: Stop Loss 체크 불가 - avg_price=%.4f <= 0 (평단가 없음)",
                    symbol,
                    avg_price,
                )
            if current_price <= 0:
                logger.warning(
                    "%s: Stop Loss 체크 불가 - current_price=%.4f <= 0 (finder=%.4f, holding=%.4f, 둘 다 0 이하)",
                    symbol,
                    current_price,
                    finder_price,
                    holding_price,
                )


        # Tier 2: Special Situation Take Profit (price-pinned event gain realization)
        if StrategyConfig.SPECIAL_SITUATION_TAKE_PROFIT_ENABLED and avg_price > 0 and current_price > 0:
            profit_pct = (current_price - avg_price) / avg_price
            min_profit_pct = StrategyConfig.SPECIAL_SITUATION_TAKE_PROFIT_MIN_PROFIT_PCT
            is_profit_eligible = profit_pct >= min_profit_pct
            is_pinned = finder.is_special_situation_price_pinned(symbol) if is_profit_eligible else False

            logger.debug(
                "%s: SPECIAL_SITUATION_TAKE_PROFIT 체크 - "
                "profit_pct=%.4f (%.2f%%), min_profit_pct=%.4f (%.2f%%), pinned=%s",
                symbol,
                profit_pct,
                profit_pct * 100,
                min_profit_pct,
                min_profit_pct * 100,
                is_pinned,
            )

            if is_profit_eligible and is_pinned:
                logger.info(
                    "%s: 🟩 SPECIAL_SITUATION_TAKE_PROFIT 매도 결정 - "
                    "profit_pct=%.4f (%.2f%%), current_price=%.4f, avg_price=%.4f, "
                    "reason=%s, quantity=%.2f",
                    symbol,
                    profit_pct,
                    profit_pct * 100,
                    current_price,
                    avg_price,
                    SellReason.SPECIAL_SITUATION_TAKE_PROFIT.value,
                    quantity,
                )
                decisions[symbol] = SellDecision(symbol, SellReason.SPECIAL_SITUATION_TAKE_PROFIT, quantity)
                continue

        # Tier 3: ATR 기반 TRAILING STOP (수익 보호용)
        if StrategyConfig.TRAILING_ENABLED and avg_price > 0 and current_price > 0:
            profit_pct = (current_price - avg_price) / avg_price
            state_entry = trailing_state.get(symbol, {})
            trailing_activated = bool(state_entry.get("activated", False))

            if trailing_activated:
                logger.debug(
                    "%s: TRAILING 이미 활성화됨 - profit_pct=%.4f (%.2f%%), "
                    "TRAILING_MIN_PROFIT_PCT=%.4f (%.2f%%)",
                    symbol,
                    profit_pct,
                    profit_pct * 100,
                    StrategyConfig.TRAILING_MIN_PROFIT_PCT,
                    StrategyConfig.TRAILING_MIN_PROFIT_PCT * 100,
                )
            elif profit_pct >= StrategyConfig.TRAILING_MIN_PROFIT_PCT:
                trailing_activated = True
                trailing_state.setdefault(symbol, {})["activated"] = True
                trailing_state_modified = True
                logger.info(
                    "%s: TRAILING 신규 활성화 - profit_pct=%.4f (%.2f%%) >= "
                    "TRAILING_MIN_PROFIT_PCT=%.4f (%.2f%%)",
                    symbol,
                    profit_pct,
                    profit_pct * 100,
                    StrategyConfig.TRAILING_MIN_PROFIT_PCT,
                    StrategyConfig.TRAILING_MIN_PROFIT_PCT * 100,
                )
            else:
                logger.debug(
                    "%s: TRAILING 미활성화 - profit_pct=%.4f (%.2f%%) < "
                    "TRAILING_MIN_PROFIT_PCT=%.4f (%.2f%%)",
                    symbol,
                    profit_pct,
                    profit_pct * 100,
                    StrategyConfig.TRAILING_MIN_PROFIT_PCT,
                    StrategyConfig.TRAILING_MIN_PROFIT_PCT * 100,
                )

            if trailing_activated:
                today = date.today()

                # 트레일링에 사용할 "종가" 개념: 여기서는 current_price를 사용
                close_for_trailing = current_price

                # 최고 종가 갱신
                highest_close = update_highest_close(
                    trailing_state,
                    symbol,
                    close_for_trailing,
                    today,
                )
                trailing_state.setdefault(symbol, {})["activated"] = True
                trailing_state_modified = True

                # ATR 계산
                atr_value = finder.get_atr(symbol, StrategyConfig.TRAILING_ATR_PERIOD)

                if atr_value > 0 and highest_close > 0:
                    trailing_stop_price = highest_close - atr_value * StrategyConfig.TRAILING_ATR_MULTIPLIER

                    logger.debug(
                        "%s: TRAILING 체크 - profit_pct=%.4f (%.2f%%), highest_close=%.4f, "
                        "ATR=%.4f, multiplier=%.2f, trailing_stop_price=%.4f, current_price=%.4f",
                        symbol,
                        profit_pct,
                        profit_pct * 100,
                        highest_close,
                        atr_value,
                        StrategyConfig.TRAILING_ATR_MULTIPLIER,
                        trailing_stop_price,
                        current_price,
                    )

                    # 현재가가 트레일링 스탑 아래로 내려가면 매도
                    if current_price <= trailing_stop_price:
                        # 쿨다운 이벤트 기록 (손익률 계산)
                        trailing_loss_pct = (current_price - avg_price) / avg_price if avg_price > 0 else None
                        record_stop_loss_event(symbol, trailing_loss_pct, date.today())

                        logger.info(
                            "%s: 🟨 TRAILING 매도 결정 - current_price=%.4f <= trailing_stop_price=%.4f, "
                            "highest_close=%.4f, ATR=%.4f, quantity=%.2f",
                            symbol,
                            current_price,
                            trailing_stop_price,
                            highest_close,
                            atr_value,
                            quantity,
                        )
                        decisions[symbol] = SellDecision(symbol, SellReason.TRAILING, quantity)
                        continue
                else:
                    if atr_value <= 0:
                        logger.debug(
                            "%s: TRAILING 체크 스킵 - ATR 계산 실패 (atr_value=%.4f)",
                            symbol,
                            atr_value,
                        )
                    if highest_close <= 0:
                        logger.debug(
                            "%s: TRAILING 체크 스킵 - highest_close=%.4f <= 0",
                            symbol,
                            highest_close,
                        )
        else:
            if not StrategyConfig.TRAILING_ENABLED:
                logger.debug("%s: TRAILING 체크 스킵 - TRAILING_ENABLED=False", symbol)
            elif avg_price <= 0:
                logger.debug("%s: TRAILING 체크 스킵 - avg_price=%.4f <= 0", symbol, avg_price)
            elif current_price <= 0:
                logger.debug("%s: TRAILING 체크 스킵 - current_price=%.4f <= 0", symbol, current_price)

        # Tier 4: AVSL (Volume Support Level Broken)
        avsl_signal = avsl_signals.get(symbol, False)
        logger.debug("%s: AVSL 체크 - avsl_signal=%s", symbol, avsl_signal)

        if avsl_signal:
            # 쿨다운 이벤트 기록 (손익률 계산)
            avsl_loss_pct = (current_price - avg_price) / avg_price if avg_price > 0 and current_price > 0 else None
            record_stop_loss_event(symbol, avsl_loss_pct, date.today())

            logger.info(
                "%s: 🟧 AVSL 매도 결정 - 거래량 지지선 붕괴, quantity=%.2f",
                symbol,
                quantity,
            )
            decisions[symbol] = SellDecision(symbol, SellReason.AVSL, quantity)
            continue

        # Tier 5: Trend/Strategy Condition Failure (explicit holding trend-exit only)
        should_exit_trend, stale_holding = evaluate_holding_trend_exit(
            symbol=symbol,
            selected_buy=selected_buy,
            selected_not_sell=selected_not_sell,
            holding_trend_exit_signals=holding_trend_exit_signals,
        )

        logger.debug(
            "%s: Trend 체크 - explicit_holding_trend_exit=%s, stale_holding=%s",
            symbol,
            should_exit_trend,
            stale_holding,
        )

        if should_exit_trend:
            # 쿨다운 이벤트 기록 (손익률 계산)
            trend_loss_pct = (current_price - avg_price) / avg_price if avg_price > 0 and current_price > 0 else None
            record_stop_loss_event(symbol, trend_loss_pct, date.today())

            logger.info(
                "%s: 🟦 TREND 매도 결정 - explicit holding trend-exit signal, quantity=%.2f",
                symbol,
                quantity,
            )
            decisions[symbol] = SellDecision(symbol, SellReason.TREND, quantity)
            continue

        # No sell signal - hold
        logger.debug(
            "%s: HOLD 결정 - 모든 매도 조건 미충족 (Stop Loss, Special Situation Take Profit, Trailing, AVSL, Trend 모두 통과)",
            symbol,
        )
        decisions[symbol] = SellDecision(symbol, SellReason.NONE, 0.0)

    # 매도 결정된 종목의 트레일링 상태 초기화 (재매수 시 새로운 최고가부터 시작)
    for symbol, decision in decisions.items():
        if decision.reason != SellReason.NONE and decision.quantity > 0:
            # 매도 결정된 종목의 트레일링 상태 삭제
            if symbol in trailing_state:
                del trailing_state[symbol]
                trailing_state_modified = True
                logger.info(
                    "%s: 매도로 인한 트레일링 상태 초기화 완료 (reason=%s, quantity=%.2f)",
                    symbol,
                    decision.reason.value,
                    decision.quantity,
                )

    # 트레일링 스탑 상태 저장 (수정된 경우에만)
    if trailing_state_modified:
        save_trailing_state(trailing_state)

    return decisions
