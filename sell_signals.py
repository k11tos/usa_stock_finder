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
from enum import Enum
from typing import Any, Dict, List

from config import StrategyConfig
from stock_analysis import UsaStockFinder

logger = logging.getLogger(__name__)


class SellReason(str, Enum):
    """Enumeration of reasons for selling a stock."""

    NONE = "HOLD"  # No sell signal - hold the stock
    STOP_LOSS = "STOP_LOSS"  # Absolute stop loss threshold exceeded
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


def evaluate_sell_decisions(
    finder: UsaStockFinder,
    holdings: List[dict[str, Any]],
    selected_buy: List[str],
    selected_not_sell: List[str],
    avsl_signals: Dict[str, bool],
) -> Dict[str, SellDecision]:
    """
    Evaluate sell decisions for all holdings using a 3-tier sell signal system.

    The evaluation follows this priority order:
    1. Stop Loss (highest priority): If loss exceeds STOP_LOSS_PCT, sell immediately
    2. AVSL: If volume support level is broken, sell
    3. Trend: If stock no longer meets buy/hold criteria, sell

    Args:
        finder (UsaStockFinder): Instance containing current stock prices
        holdings (List[dict[str, Any]]): List of current holdings, each containing:
            - "symbol": Stock ticker symbol
            - "quantity": Number of shares held
            - "avg_price": Average purchase price
        selected_buy (List[str]): List of stocks recommended for buying
        selected_not_sell (List[str]): List of stocks recommended to hold (not sell)
        avsl_signals (Dict[str, bool]): Dictionary of AVSL sell signals {symbol: bool}

    Returns:
        Dict[str, SellDecision]: Dictionary mapping stock symbols to sell decisions

    Note:
        - Stop loss takes absolute priority - if triggered, other conditions are ignored
        - AVSL signals are checked only if stop loss is not triggered
        - Trend-based sells are checked only if neither stop loss nor AVSL is triggered
        - Stocks in selected_buy or selected_not_sell are not sold due to trend failure
    """
    decisions: Dict[str, SellDecision] = {}

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
        current_price = finder_price if finder_price > 0 else holding_price

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

        # Tier 2: AVSL (Volume Support Level Broken)
        avsl_signal = avsl_signals.get(symbol, False)
        logger.debug("%s: AVSL 체크 - avsl_signal=%s", symbol, avsl_signal)

        if avsl_signal:
            logger.info(
                "%s: 🟧 AVSL 매도 결정 - 거래량 지지선 붕괴, quantity=%.2f",
                symbol,
                quantity,
            )
            decisions[symbol] = SellDecision(symbol, SellReason.AVSL, quantity)
            continue

        # Tier 3: Trend/Strategy Condition Failure
        # Only sell if stock is not in buy or hold lists
        in_buy_list = symbol in selected_buy
        in_not_sell_list = symbol in selected_not_sell

        logger.debug(
            "%s: Trend 체크 - in_selected_buy=%s, in_selected_not_sell=%s",
            symbol,
            in_buy_list,
            in_not_sell_list,
        )

        if symbol not in selected_buy and symbol not in selected_not_sell:
            logger.info(
                "%s: 🟦 TREND 매도 결정 - 트렌드/전략 조건 이탈, quantity=%.2f",
                symbol,
                quantity,
            )
            decisions[symbol] = SellDecision(symbol, SellReason.TREND, quantity)
            continue

        # No sell signal - hold
        logger.debug(
            "%s: HOLD 결정 - 모든 매도 조건 미충족 (Stop Loss, AVSL, Trend 모두 통과)",
            symbol,
        )
        decisions[symbol] = SellDecision(symbol, SellReason.NONE, 0.0)

    return decisions
