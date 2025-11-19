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

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

from config import StrategyConfig
from stock_analysis import UsaStockFinder


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
            continue

        quantity = holding.get("quantity", 0.0)
        if quantity <= 0:
            # No shares to sell
            decisions[symbol] = SellDecision(symbol, SellReason.NONE, 0.0)
            continue

        avg_price = holding.get("avg_price", 0.0)
        current_price = finder.current_price.get(symbol, 0.0)

        # Tier 1: Stop Loss (Absolute Priority)
        if avg_price > 0 and current_price > 0:
            loss_pct = (current_price - avg_price) / avg_price

            if loss_pct <= -StrategyConfig.STOP_LOSS_PCT:
                # Stop loss triggered - sell immediately regardless of other conditions
                decisions[symbol] = SellDecision(symbol, SellReason.STOP_LOSS, quantity)
                continue

        # Tier 2: AVSL (Volume Support Level Broken)
        if avsl_signals.get(symbol, False):
            decisions[symbol] = SellDecision(symbol, SellReason.AVSL, quantity)
            continue

        # Tier 3: Trend/Strategy Condition Failure
        # Only sell if stock is not in buy or hold lists
        if symbol not in selected_buy and symbol not in selected_not_sell:
            decisions[symbol] = SellDecision(symbol, SellReason.TREND, quantity)
            continue

        # No sell signal - hold
        decisions[symbol] = SellDecision(symbol, SellReason.NONE, 0.0)

    return decisions
