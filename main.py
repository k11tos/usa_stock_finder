"""
main.py

This module implements the main functionality for the USA Stock Finder application.
It provides a comprehensive system for analyzing US stocks, generating trading signals,
and sending notifications via Telegram. The system is based on Mark Minervini's
trading principles and includes technical analysis features.

Key Features:
    - Stock data fetching and analysis
    - Price-volume correlation calculations
    - Trend analysis and stock selection
    - Investment amount calculation per stock
    - Telegram notifications for trading signals
    - Portfolio management and tracking

Dependencies:
    - asyncio: For asynchronous operations
    - logging: For structured logging
    - dotenv: For environment variable management
    - file_utils: For file operations
    - stock_analysis: For stock data analysis
    - stock_operations: For stock account operations
    - telegram_utils: For Telegram notifications

Author: Breadpig based on the theory from Mark Minervini
Date: 2024.05.19
"""

import asyncio
import logging.config
import logging.handlers
import os.path
from datetime import date
from typing import Any

from dotenv import load_dotenv

from config import ConfigError, EnvironmentConfig, InvestmentConfig, StrategyConfig
from file_utils import read_csv_first_column, save_json
from logging_setup import setup_logging
from sell_signals import SellDecision, SellReason, evaluate_sell_decisions
from stock_analysis import UsaStockFinder
from stock_operations import APIError, fetch_account_balance, fetch_holdings_detail, fetch_us_stock_holdings
from stop_loss_cooldown import is_in_cooldown
from telegram_utils import send_telegram_message

logger = logging.getLogger(__name__)


def calculate_correlations(finder: UsaStockFinder) -> dict[str, dict[str, float]]:
    """
    Calculate price-volume correlations for different time periods.

    This function computes the price-volume correlation percentages
    for 200, 100, and 50-day periods using the provided finder object.
    The correlation helps identify the strength of price-volume relationships
    in different timeframes.

    Args:
        finder (UsaStockFinder): An instance of the UsaStockFinder class with
                              methods to calculate price-volume correlations.

    Returns:
        dict[str, dict[str, float]]: A dictionary containing price-volume correlation percentages
              for 200, 100, and 50-day periods, organized by period and symbol.
    """
    return {str(days): finder.price_volume_correlation_percent(days) for days in [200, 100, 50]}


def select_stocks(finder: UsaStockFinder, correlations: dict[str, dict[str, float]]) -> tuple[list[str], list[str]]:
    """
    Select stocks based on trend validity and strength criteria.

    This function analyzes stocks using two main criteria:
    1. Trend validity (with and without margin)
    2. Price-volume correlation strength

    Args:
        finder (UsaStockFinder): Instance containing stock analysis methods
        correlations (dict[str, dict[str, float]]): Price-volume correlations for different periods

    Returns:
        tuple[list[str], list[str]]: Two lists containing:
            - List of stocks recommended for buying
            - List of stocks recommended to hold (not sell)
    """
    selected_buy, selected_not_sell = [], []
    valid_trend = finder.has_valid_trend_template(StrategyConfig.MARGIN)
    valid_trend_margin = finder.has_valid_trend_template(StrategyConfig.MARGIN_RELAXED)

    for symbol in finder.symbols:
        correlation_50 = correlations.get("50", {}).get(symbol, 0.0)
        if valid_trend[symbol] and correlation_50 >= StrategyConfig.CORRELATION_THRESHOLD_STRICT:
            selected_buy.append(symbol)
            logger.info(
                "Buy signal: %s (Trend: True, Correlation: %.2f%%)",
                symbol,
                correlation_50,
            )
        elif valid_trend_margin[symbol] and correlation_50 >= StrategyConfig.CORRELATION_THRESHOLD_RELAXED:
            selected_not_sell.append(symbol)
            logger.info(
                "Hold signal: %s (Trend(Margin): True, Correlation: %.2f%%)",
                symbol,
                correlation_50,
            )
        log_stock_info(symbol, correlations)

    return selected_buy, selected_not_sell


def log_stock_info(symbol: str, correlations: dict[str, dict[str, float]]) -> None:
    """
    Log debug information about a stock's price-volume correlations.

    Args:
        symbol (str): The stock symbol to log information for
        correlations (dict[str, dict[str, float]]): Dictionary containing correlation data
            for different time periods (200, 100, 50 days)
    """
    logger.debug(
        "%s : %s -> %s -> %s",
        symbol,
        correlations["200"][symbol],
        correlations["100"][symbol],
        correlations["50"][symbol],
    )


def generate_telegram_message(
    prev_items: list[str],
    buy_items: list[str],
    _not_sell_items: list[str],  # pylint: disable=unused-argument
    share_quantities: dict[str, dict[str, Any]] | None = None,
    sell_quantities: dict[str, dict[str, Any]] | None = None,
    sell_decisions: dict[str, SellDecision] | None = None,
) -> list[str] | None:
    """
    Generate a Telegram message with buy and sell recommendations.

    This function compares the current selection of stocks with the previous selection
    to determine which stocks should be bought or sold. It generates a message that
    includes the current date and specific buy/sell recommendations with investment
    amounts and share quantities.

    Args:
        prev_items (list[str]): List of previously selected stock symbols
        buy_items (list[str]): List of stock symbols recommended for buying
        _not_sell_items (list[str]): List of stock symbols not recommended for selling (currently unused)
        share_quantities (dict[str, dict[str, Any]] | None): Dictionary containing share
            quantity information for buy signals
        sell_quantities (dict[str, dict[str, Any]] | None): Dictionary containing share
            quantity information for sell signals
        sell_decisions (dict[str, SellDecision] | None): Dictionary of sell decisions with reasons

    Returns:
        list[str] | None: A list of strings containing the date and buy/sell recommendations
                         with investment amounts and share quantities, or None if there are
                         no changes to report
    """
    message = [str(date.today())]
    has_changes = False

    # Generate buy messages with investment details
    new_buy_items = [item for item in buy_items if item not in prev_items]
    if new_buy_items:
        message.append("\n📈 Buy Signals:")
        has_changes = True

        for item in new_buy_items:
            if share_quantities and item in share_quantities:
                info = share_quantities[item]
                investment = info.get("investment_amount", 0)
                price = info.get("current_price", 0)
                shares = info.get("shares_to_buy", 0)
                current_qty = info.get("current_quantity", 0)
                total_qty = info.get("total_after_buy", 0)

                if current_qty > 0:
                    msg = f"  🔄 Additional Buy: {item}"
                    msg += f"\n     Current Holdings: {current_qty} shares"
                    msg += f"\n     Additional Buy: {shares} shares"
                    msg += f"\n     Total Holdings: {total_qty} shares"
                else:
                    msg = f"  ✅ New Buy: {item}"
                    msg += f"\n     Buy Quantity: {shares} shares"

                msg += f"\n     Investment Amount: ${investment:,.2f}"
                msg += f"\n     Current Price: ${price:.2f}"
                message.append(msg)
            else:
                message.append(f"  ✅ Buy: {item}")

    # Generate sell messages with quantity details and reasons
    sell_items_to_display = []
    if sell_decisions:
        # Get all sell decisions (excluding HOLD)
        for symbol, decision in sell_decisions.items():
            if decision.reason != SellReason.NONE and decision.quantity > 0:
                sell_items_to_display.append((symbol, decision))

    if sell_items_to_display:
        message.append("\n📉 Sell Signals:")
        has_changes = True

        # Group by reason for better organization
        stop_loss_items = [(s, d) for s, d in sell_items_to_display if d.reason == SellReason.STOP_LOSS]
        trailing_items = [(s, d) for s, d in sell_items_to_display if d.reason == SellReason.TRAILING]
        avsl_items = [(s, d) for s, d in sell_items_to_display if d.reason == SellReason.AVSL]
        trend_items = [(s, d) for s, d in sell_items_to_display if d.reason == SellReason.TREND]

        # Display stop loss items first (highest priority)
        for symbol, decision in stop_loss_items:
            if sell_quantities and symbol in sell_quantities:
                info = sell_quantities[symbol]
                shares = info.get("shares_to_sell", 0)
                price = info.get("current_price", 0)
                sell_amount = info.get("sell_amount", 0)
                profit_loss = info.get("profit_loss", 0.0)
                profit_rate = info.get("profit_loss_rate", 0.0)

                msg = f"  🟥 매도 (절대 손절): {symbol}"
                msg += f"\n     매도 수량: {shares}주"
                msg += f"\n     현재가: ${price:.2f}"
                msg += f"\n     매도 금액: ${sell_amount:,.2f}"

                if profit_loss != 0:
                    profit_sign = "+" if profit_loss >= 0 else ""
                    rate_sign = "+" if profit_rate >= 0 else ""
                    msg += f"\n     손익: {profit_sign}${profit_loss:,.2f} ({rate_sign}{profit_rate:.2f}%)"

                message.append(msg)
            else:
                message.append(f"  🟥 매도 (절대 손절): {symbol}")

        # Display trailing items
        for symbol, decision in trailing_items:
            if sell_quantities and symbol in sell_quantities:
                info = sell_quantities[symbol]
                shares = info.get("shares_to_sell", 0)
                price = info.get("current_price", 0)
                sell_amount = info.get("sell_amount", 0)
                profit_loss = info.get("profit_loss", 0.0)
                profit_rate = info.get("profit_loss_rate", 0.0)

                msg = f"  🟨 매도 (ATR 트레일링 스탑): {symbol}"
                msg += f"\n     매도 수량: {shares}주"
                msg += f"\n     현재가: ${price:.2f}"
                msg += f"\n     매도 금액: ${sell_amount:,.2f}"

                if profit_loss != 0:
                    profit_sign = "+" if profit_loss >= 0 else ""
                    rate_sign = "+" if profit_rate >= 0 else ""
                    msg += f"\n     손익: {profit_sign}${profit_loss:,.2f} ({rate_sign}{profit_rate:.2f}%)"

                message.append(msg)
            else:
                message.append(f"  🟨 매도 (ATR 트레일링 스탑): {symbol}")

        # Display AVSL items
        for symbol, decision in avsl_items:
            if sell_quantities and symbol in sell_quantities:
                info = sell_quantities[symbol]
                shares = info.get("shares_to_sell", 0)
                price = info.get("current_price", 0)
                sell_amount = info.get("sell_amount", 0)
                profit_loss = info.get("profit_loss", 0.0)
                profit_rate = info.get("profit_loss_rate", 0.0)

                msg = f"  🟧 매도 (AVSL 거래량 지지선 붕괴): {symbol}"
                msg += f"\n     매도 수량: {shares}주"
                msg += f"\n     현재가: ${price:.2f}"
                msg += f"\n     매도 금액: ${sell_amount:,.2f}"

                if profit_loss != 0:
                    profit_sign = "+" if profit_loss >= 0 else ""
                    rate_sign = "+" if profit_rate >= 0 else ""
                    msg += f"\n     손익: {profit_sign}${profit_loss:,.2f} ({rate_sign}{profit_rate:.2f}%)"

                message.append(msg)
            else:
                message.append(f"  🟧 매도 (AVSL 거래량 지지선 붕괴): {symbol}")

        # Display trend items
        for symbol, decision in trend_items:
            if sell_quantities and symbol in sell_quantities:
                info = sell_quantities[symbol]
                shares = info.get("shares_to_sell", 0)
                price = info.get("current_price", 0)
                sell_amount = info.get("sell_amount", 0)
                profit_loss = info.get("profit_loss", 0.0)
                profit_rate = info.get("profit_loss_rate", 0.0)

                msg = f"  🟦 매도 (트렌드/전략 조건 이탈): {symbol}"
                msg += f"\n     매도 수량: {shares}주"
                msg += f"\n     현재가: ${price:.2f}"
                msg += f"\n     매도 금액: ${sell_amount:,.2f}"

                if profit_loss != 0:
                    profit_sign = "+" if profit_loss >= 0 else ""
                    rate_sign = "+" if profit_rate >= 0 else ""
                    msg += f"\n     손익: {profit_sign}${profit_loss:,.2f} ({rate_sign}{profit_rate:.2f}%)"

                message.append(msg)
            else:
                message.append(f"  🟦 매도 (트렌드/전략 조건 이탈): {symbol}")

    if has_changes:
        return message
    return None


def calculate_investment_per_stock(
    buy_items: list[str],
    reserve_ratio: float | None = None,
    min_investment: float | None = None,
    max_investment: float | None = None,
) -> dict[str, float] | None:
    """
    Calculate investment amount per stock based on available cash and buy signals.

    This function:
    1. Fetches account balance and available cash
    2. Calculates investment amount per stock using configured distribution strategy
    3. Applies reserve ratio to keep some cash reserved
    4. Applies min/max investment constraints

    Args:
        buy_items (list[str]): List of stock symbols recommended for buying
        reserve_ratio (float | None): Ratio of cash to reserve (None = use config default)
        min_investment (float | None): Minimum investment amount per stock (None = use config default)
        max_investment (float | None): Maximum investment amount per stock (None = use config default)

    Returns:
        dict[str, float] | None: Dictionary mapping stock symbols to investment amounts,
                                 or None if account balance cannot be fetched or no buy signals

    Note:
        - Supports equal distribution or proportional distribution strategies
        - Applies reserve ratio to keep emergency funds
        - Respects min/max investment constraints
        - Returns None if account balance fetch fails
        - Automatically excludes stocks that cannot afford minimum investment
    """
    if not buy_items:
        logger.warning("No buy signals to calculate investment amounts")
        return None

    # Use config defaults if not provided
    if reserve_ratio is None:
        reserve_ratio = InvestmentConfig.RESERVE_RATIO
    if min_investment is None:
        min_investment = InvestmentConfig.MIN_INVESTMENT
    if max_investment is None or max_investment == 0:
        max_investment = InvestmentConfig.MAX_INVESTMENT if InvestmentConfig.MAX_INVESTMENT > 0 else None

    try:
        account_balance = fetch_account_balance()
    except APIError as e:
        logger.error("Failed to fetch account balance: %s", str(e))
        return None

    if not account_balance:
        logger.error("Failed to fetch account balance")
        return None

    available_cash = account_balance.get("available_cash", 0.0)
    buyable_cash = account_balance.get("buyable_cash", available_cash)
    total_balance = account_balance.get("total_balance", available_cash)

    if buyable_cash <= 0:
        logger.warning(
            "No buyable cash available (Available cash: %.2f, Buyable cash: %.2f)", available_cash, buyable_cash
        )
        return None

    # Calculate total investment amount (excluding reserve)
    total_investment = buyable_cash * (1 - reserve_ratio)
    num_stocks = len(buy_items)

    if num_stocks == 0:
        logger.warning("No stocks to invest in")
        return None

    # Calculate investment per stock based on distribution strategy
    if InvestmentConfig.DISTRIBUTION_STRATEGY == "proportional" and InvestmentConfig.PROPORTIONAL_PERCENTAGE > 0:
        # Proportional distribution: each stock gets a percentage of total balance
        investment_per_stock = total_balance * InvestmentConfig.PROPORTIONAL_PERCENTAGE
        logger.info(
            "Using proportional distribution: %.2f%% of total balance per stock",
            InvestmentConfig.PROPORTIONAL_PERCENTAGE * 100,
        )
    else:
        # Equal distribution: divide total investment equally among stocks
        investment_per_stock = total_investment / num_stocks
        logger.info("Using equal distribution strategy")

    # Apply min/max constraints and filter affordable stocks
    affordable_stocks = []
    for symbol in buy_items:
        stock_investment = investment_per_stock

        # Apply max constraint
        if max_investment and stock_investment > max_investment:
            stock_investment = max_investment

        # Check if meets minimum investment
        if stock_investment >= min_investment:
            affordable_stocks.append((symbol, stock_investment))
        else:
            logger.debug(
                "Excluding stock %s: Investment amount %.2f < Minimum investment %.2f",
                symbol,
                stock_investment,
                min_investment,
            )

    if not affordable_stocks:
        logger.warning(
            "Available cash (%s) is insufficient for minimum investment (%s) for any stock",
            total_investment,
            min_investment,
        )
        return None

    # Create investment mapping
    investment_map = {symbol: round(investment, 2) for symbol, investment in affordable_stocks}

    logger.info(
        "Investment calculation: Total: %s, Reserve: %s, Per stock: %s, Stocks: %d (original: %d)",
        buyable_cash,
        buyable_cash * reserve_ratio,
        investment_per_stock,
        len(investment_map),
        num_stocks,
    )

    return investment_map


def calculate_share_quantities(
    investment_map: dict[str, float],
    finder: UsaStockFinder,
    current_holdings: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]] | None:
    """
    Calculate share quantities to buy/sell based on investment amounts and current prices.

    This function:
    1. Calculates number of shares to buy for each stock based on investment amount and current price
    2. Compares with current holdings to determine additional buy or sell quantities
    3. Returns detailed information including buy/sell quantities and current holdings

    Args:
        investment_map (dict[str, float]): Dictionary mapping stock symbols to investment amounts
        finder (UsaStockFinder): Instance containing current stock prices
        current_holdings (list[dict[str, Any]] | None): Current holdings detail from account.
            If None, will fetch from account.

    Returns:
        dict[str, dict[str, Any]] | None: Dictionary mapping stock symbols to trading information.
            Each value contains:
            - "investment_amount": Investment amount for this stock
            - "current_price": Current market price
            - "shares_to_buy": Number of shares to buy
            - "current_quantity": Current number of shares held (0 if not held)
            - "additional_buy": Additional shares to buy (if already holding)
            - "total_after_buy": Total shares after buying
            Returns None if investment_map is empty or prices unavailable

    Note:
        - Uses current_price from finder
        - Rounds down shares to buy (cannot buy fractional shares)
        - If stock is already held, calculates additional buy quantity
        - Returns None if prices are unavailable
    """
    if not investment_map:
        logger.warning("No investment map provided")
        return None

    # Fetch current holdings if not provided
    if current_holdings is None:
        current_holdings = fetch_holdings_detail()

    # Create a mapping of current holdings for quick lookup
    holdings_map: dict[str, float] = {}
    if current_holdings:
        for holding in current_holdings:
            symbol = holding.get("symbol", "")
            quantity = holding.get("quantity", 0.0)
            if symbol:
                holdings_map[symbol] = quantity

    result: dict[str, dict[str, Any]] = {}

    for symbol, investment_amount in investment_map.items():
        current_price = finder.current_price.get(symbol, 0.0)

        if current_price <= 0:
            logger.warning("Invalid price for %s: %s", symbol, current_price)
            continue

        # Calculate target total quantity (목표 총 보유 수량)
        # 투자금으로 살 수 있는 최대 수량 (소수점 이하 절삭)
        target_total_quantity = int(investment_amount / current_price)

        if target_total_quantity <= 0:
            logger.warning(
                "Investment amount %s too small for %s at price %s", investment_amount, symbol, current_price
            )
            continue

        # Get current holding quantity
        current_quantity = holdings_map.get(symbol, 0.0)

        # Calculate actual shares to buy
        # 신규 매수: 현재 보유 없음 → 목표 수량 전체 매수
        # 추가 매수: 현재 보유 있음 → (목표 수량 - 현재 보유)만큼 추가 매수
        #            단, 이미 목표 수량 이상 보유 중이면 추가 매수 0
        if current_quantity == 0:
            shares_to_buy = target_total_quantity  # 신규 매수
            is_new_buy = True
        else:
            shares_to_buy = max(target_total_quantity - int(current_quantity), 0)  # 추가 매수
            is_new_buy = False

        total_after_buy = int(current_quantity) + shares_to_buy

        # Calculate actual investment amount (actual shares to buy * price)
        actual_investment = shares_to_buy * current_price

        result[symbol] = {
            "investment_amount": round(investment_amount, 2),
            "current_price": round(current_price, 2),
            "shares_to_buy": shares_to_buy,  # Actual shares to buy (신규 매수 or 추가 매수 수량)
            "current_quantity": int(current_quantity),
            "additional_buy": shares_to_buy,  # Same as shares_to_buy (kept for backward compatibility)
            "total_after_buy": total_after_buy,
            "actual_investment": round(actual_investment, 2),
        }

        # 명확한 로깅: 신규 매수 vs 추가 매수
        if is_new_buy:
            logger.debug(
                "%s: 신규 매수 계산 - 투자금=$%.2f, 현재가=$%.2f, 매수 수량=%d주, 실제 투자금=$%.2f",
                symbol,
                investment_amount,
                current_price,
                shares_to_buy,
                actual_investment,
            )
        else:
            logger.debug(
                "%s: 추가 매수 계산 - 투자금=$%.2f, 현재가=$%.2f, 목표 총 수량=%d주, 현재 보유=%d주, "
                "추가 매수=%d주, 매수 후 총=%d주, 실제 투자금=$%.2f",
                symbol,
                investment_amount,
                current_price,
                target_total_quantity,
                int(current_quantity),
                shares_to_buy,
                total_after_buy,
                actual_investment,
            )

    if not result:
        logger.warning("No valid share quantities calculated")
        return None

    return result


def calculate_sell_quantities(
    sell_items: list[str],
    finder: UsaStockFinder,
    current_holdings: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]] | None:
    """
    Calculate share quantities to sell for stocks that need to be sold.

    Args:
        sell_items (list[str]): List of stock symbols to sell
        finder (UsaStockFinder): Instance containing current stock prices
        current_holdings (list[dict[str, Any]] | None): Current holdings detail from account.
            If None, will fetch from account.

    Returns:
        dict[str, dict[str, Any]] | None: Dictionary mapping stock symbols to sell information.
            Each value contains:
            - "current_quantity": Current number of shares held
            - "current_price": Current market price
            - "shares_to_sell": Number of shares to sell (all if selling)
            - "sell_amount": Estimated sell amount (shares * price)
            Returns None if no sell items or holdings unavailable
    """
    if not sell_items:
        return None

    # Fetch current holdings if not provided
    if current_holdings is None:
        current_holdings = fetch_holdings_detail()

    if not current_holdings:
        logger.warning("No current holdings available for sell calculation")
        return None

    # Create a mapping of current holdings for quick lookup
    holdings_map: dict[str, dict[str, Any]] = {}
    for holding in current_holdings:
        symbol = holding.get("symbol", "")
        if symbol:
            holdings_map[symbol] = holding

    result: dict[str, dict[str, Any]] = {}

    for symbol in sell_items:
        holding = holdings_map.get(symbol)
        if not holding:
            logger.debug("%s not in current holdings, skipping sell calculation", symbol)
            continue

        current_quantity = holding.get("quantity", 0.0)
        if current_quantity <= 0:
            logger.debug("%s has no shares to sell", symbol)
            continue

        # 가격 검증: holdings의 current_price와 finder.current_price 비교
        holding_current_price = holding.get("current_price", 0.0)
        finder_current_price = finder.current_price.get(symbol, 0.0)
        avg_price = holding.get("avg_price", 0.0)
        profit_loss_rate = holding.get("profit_loss_rate", 0.0)

        # finder.current_price 우선 사용, 없으면 holdings의 current_price 사용
        current_price = finder_current_price if finder_current_price > 0 else holding_current_price

        logger.debug(
            "%s: 매도 수량 계산 - avg_price=%.4f, holding_current_price=%.4f, finder_current_price=%.4f, "
            "selected_price=%.4f, profit_loss_rate=%.4f%%, quantity=%.2f",
            symbol,
            avg_price,
            holding_current_price,
            finder_current_price,
            current_price,
            profit_loss_rate,
            current_quantity,
        )

        if current_price <= 0:
            logger.warning(
                "Invalid price for %s: current_price=%s (holding=%s, finder=%s)",
                symbol,
                current_price,
                holding_current_price,
                finder_current_price,
            )
            continue

        # 손익률 재계산 검증 (holdings의 profit_loss_rate와 비교)
        if avg_price > 0:
            calculated_loss_pct = ((current_price - avg_price) / avg_price) * 100
            logger.debug(
                "%s: 손익률 검증 - holdings.profit_loss_rate=%.4f%%, 계산된 loss_pct=%.4f%%",
                symbol,
                profit_loss_rate,
                calculated_loss_pct,
            )

            # 큰 차이가 있으면 경고
            if abs(calculated_loss_pct - profit_loss_rate) > 0.1:  # 0.1% 이상 차이
                logger.warning(
                    "%s: 손익률 불일치 - holdings.profit_loss_rate=%.4f%%, 계산된 loss_pct=%.4f%%, 차이=%.4f%%",
                    symbol,
                    profit_loss_rate,
                    calculated_loss_pct,
                    abs(calculated_loss_pct - profit_loss_rate),
                )

        # Sell all shares
        shares_to_sell = int(current_quantity)
        sell_amount = shares_to_sell * current_price

        result[symbol] = {
            "current_quantity": int(current_quantity),
            "current_price": round(current_price, 2),
            "shares_to_sell": shares_to_sell,
            "sell_amount": round(sell_amount, 2),
            "avg_price": avg_price,
            "profit_loss": holding.get("profit_loss", 0.0),
            "profit_loss_rate": profit_loss_rate,
        }

        logger.info(
            "%s: 매도 수량 계산 완료 - %d주 @ $%.2f = $%.2f (avg_price=%.2f, 손익률=%.2f%%)",
            symbol,
            shares_to_sell,
            current_price,
            sell_amount,
            avg_price,
            profit_loss_rate,
        )

    if not result:
        logger.warning("No valid sell quantities calculated")
        return None

    return result


def update_final_items(prev_items: list[str], buy_items: list[str], not_sell_items: list[str]) -> list[str]:
    """
    Update the final list of items based on previous selections and new buy/not sell decisions.

    This function combines the previous portfolio with new selections, maintaining
    stocks that meet the criteria for holding while adding new stocks that meet
    the buying criteria.

    Args:
        prev_items (list[str]): List of items previously selected
        buy_items (list[str]): List of items selected to buy
        not_sell_items (list[str]): List of items selected not to sell

    Returns:
        list[str]: Updated final list of items to keep in the portfolio
    """
    keep_items = set(buy_items) | set(not_sell_items)
    new_items = [item for item in buy_items if item not in prev_items]
    return [item for item in prev_items + new_items if item in keep_items]


def main() -> None:
    """
    Main function that orchestrates the stock analysis and notification process.

    This function:
    1. Sets up logging and loads environment variables
    2. Validates required environment variables
    3. Fetches current stock holdings
    4. Analyzes candidate stocks
    5. Generates trading signals
    6. Sends notifications via Telegram
    7. Updates the portfolio data

    Note:
        - Requires environment variables for Telegram API and account information
        - Expects a portfolio.csv file in the portfolio directory
        - Saves the final portfolio to data/data.json

    Raises:
        ConfigError: If required environment variables are missing
    """
    setup_logging()
    load_dotenv()

    # Validate environment variables at startup
    try:
        EnvironmentConfig.validate()
        logger.info("Environment variables validated successfully")
    except ConfigError as e:
        logger.error("Environment variable validation failed: %s", str(e))
        raise

    try:
        us_stock_holdings = fetch_us_stock_holdings()
        if not us_stock_holdings:
            logger.warning("No stock holdings found in account")
            us_stock_holdings = []
    except APIError as e:
        logger.error("Failed to fetch holdings due to API error: %s", str(e))
        return

    candidate_stocks = read_csv_first_column(os.path.join(".", "portfolio/portfolio.csv"))
    finder = UsaStockFinder(candidate_stocks)

    if not finder.is_data_valid():
        logger.error("Invalid data in UsaStockFinder")
        return

    correlation = calculate_correlations(finder)
    buy_items, not_sell_items = select_stocks(finder, correlation)

    # 🔵 Stop Loss 쿨다운 필터링: 쿨다운 기간 내 종목은 매수 후보에서 제외
    today = date.today()
    original_buy_count = len(buy_items)
    filtered_buy_items = []
    for symbol in buy_items:
        if is_in_cooldown(symbol, today):
            logger.info("Symbol %s is in stop-loss cooldown. Skipping buy signal.", symbol)
        else:
            filtered_buy_items.append(symbol)
    buy_items = filtered_buy_items

    if len(buy_items) < original_buy_count:
        logger.info(
            "Stop Loss 쿨다운 필터링 완료 - 원래: %d개, 필터링 후: %d개",
            original_buy_count,
            len(buy_items),
        )

    # Calculate investment amount per stock
    investment_map = None
    share_quantities = None
    sell_quantities = None

    if buy_items:
        investment_map = calculate_investment_per_stock(buy_items)
        if investment_map:
            logger.info(
                "Investment amounts calculated: %d stocks, total investment: %s",
                len(investment_map),
                sum(investment_map.values()),
            )
            # Calculate share quantities for buy signals
            share_quantities = calculate_share_quantities(investment_map, finder)
            if share_quantities:
                logger.info("Share quantities calculated for %d stocks", len(share_quantities))
        else:
            logger.warning("Failed to calculate investment amounts")

    # Evaluate sell decisions using 3-tier system
    sell_decisions = {}
    current_holdings_detail = fetch_holdings_detail()
    if current_holdings_detail:
        logger.info("매도 평가 시작 - 보유 종목 수: %d", len(current_holdings_detail))

        # 보유 종목 정보 검증 로그
        for holding in current_holdings_detail:
            symbol = holding.get("symbol", "")
            avg_price = holding.get("avg_price", 0.0)
            current_price_holding = holding.get("current_price", 0.0)
            quantity = holding.get("quantity", 0.0)
            profit_loss_rate = holding.get("profit_loss_rate", 0.0)
            finder_price = finder.current_price.get(symbol, 0.0)

            logger.debug(
                "%s: 보유 정보 - avg_price=%.4f, holding.current_price=%.4f, finder.current_price=%.4f, "
                "quantity=%.2f, profit_loss_rate=%.4f%%",
                symbol,
                avg_price,
                current_price_holding,
                finder_price,
                quantity,
                profit_loss_rate,
            )

            # 가격 불일치 경고
            if finder_price > 0 and current_price_holding > 0:
                price_diff_pct = abs((finder_price - current_price_holding) / current_price_holding) * 100
                if price_diff_pct > 1.0:  # 1% 이상 차이
                    logger.warning(
                        "%s: 가격 불일치 - holding.current_price=%.4f, finder.current_price=%.4f, 차이=%.2f%%",
                        symbol,
                        current_price_holding,
                        finder_price,
                        price_diff_pct,
                    )

        # Get AVSL signals for all symbols in finder
        avsl_signals = finder.check_avsl_sell_signal()
        avsl_count = sum(1 for v in avsl_signals.values() if v)
        logger.info("AVSL 시그널 확인 완료 - AVSL=True인 종목: %d개", avsl_count)

        # Evaluate sell decisions using 3-tier system
        sell_decisions = evaluate_sell_decisions(
            finder=finder,
            holdings=current_holdings_detail,
            selected_buy=buy_items,
            selected_not_sell=not_sell_items,
            avsl_signals=avsl_signals,
        )

        # Log sell decisions by reason
        stop_loss_count = sum(1 for d in sell_decisions.values() if d.reason == SellReason.STOP_LOSS)
        trailing_count = sum(1 for d in sell_decisions.values() if d.reason == SellReason.TRAILING)
        avsl_count = sum(1 for d in sell_decisions.values() if d.reason == SellReason.AVSL)
        trend_count = sum(1 for d in sell_decisions.values() if d.reason == SellReason.TREND)
        hold_count = sum(1 for d in sell_decisions.values() if d.reason == SellReason.NONE)

        logger.info(
            "매도 결정 평가 완료 - Stop Loss=%d, Trailing=%d, AVSL=%d, Trend=%d, Hold=%d",
            stop_loss_count,
            trailing_count,
            avsl_count,
            trend_count,
            hold_count,
        )

        # Log individual sell decisions with detailed information
        for symbol, decision in sell_decisions.items():
            if decision.reason != SellReason.NONE:
                # 해당 종목의 보유 정보 찾기
                holding_info = next((h for h in current_holdings_detail if h.get("symbol") == symbol), None)
                if holding_info:
                    avg_price = holding_info.get("avg_price", 0.0)
                    current_price = finder.current_price.get(symbol, holding_info.get("current_price", 0.0))
                    profit_loss_rate = holding_info.get("profit_loss_rate", 0.0)

                    logger.info(
                        "매도 결정: %s - 이유=%s, 수량=%.2f, avg_price=%.4f, current_price=%.4f, 손익률=%.2f%%",
                        symbol,
                        decision.reason.value,
                        decision.quantity,
                        avg_price,
                        current_price,
                        profit_loss_rate,
                    )
                else:
                    logger.warning(
                        "매도 결정: %s - 이유=%s, 수량=%.2f (보유 정보 없음)",
                        symbol,
                        decision.reason.value,
                        decision.quantity,
                    )

    # Get list of symbols to sell (for calculate_sell_quantities)
    all_sell_items = [
        symbol
        for symbol, decision in sell_decisions.items()
        if decision.reason != SellReason.NONE and decision.quantity > 0
    ]

    logger.debug(
        "매도 대상 종목 필터링 - 전체 결정=%d개, 매도 결정=%d개, quantity>0인 매도 결정=%d개",
        len(sell_decisions),
        sum(1 for d in sell_decisions.values() if d.reason != SellReason.NONE),
        len(all_sell_items),
    )

    if all_sell_items:
        logger.info("매도 수량 계산 시작 - 대상 종목: %s", ", ".join(all_sell_items))
        sell_quantities = calculate_sell_quantities(all_sell_items, finder, current_holdings_detail)
        if sell_quantities:
            logger.info("매도 수량 계산 완료 - %d개 종목", len(sell_quantities))

            # 매도 수량 검증 로그
            for symbol, sell_info in sell_quantities.items():
                decision = sell_decisions.get(symbol)
                if decision:
                    logger.debug(
                        "%s: 매도 수량 검증 - decision.quantity=%.2f, sell_info.shares_to_sell=%d, "
                        "sell_info.current_quantity=%d",
                        symbol,
                        decision.quantity,
                        sell_info.get("shares_to_sell", 0),
                        sell_info.get("current_quantity", 0),
                    )
        else:
            logger.warning("매도 수량 계산 실패 - sell_quantities가 None 반환됨")
    else:
        logger.info("매도 대상 종목 없음")
        sell_quantities = None

    telegram_message = generate_telegram_message(
        us_stock_holdings, buy_items, not_sell_items, share_quantities, sell_quantities, sell_decisions
    )

    if telegram_message:
        bot_token = EnvironmentConfig.get("TELEGRAM_BOT_TOKEN")
        chat_id = EnvironmentConfig.get("TELEGRAM_CHAT_ID")

        if bot_token and chat_id:
            asyncio.run(
                send_telegram_message(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    message="\n".join(telegram_message),
                )
            )
            logger.debug(telegram_message)
        else:
            logger.error("Missing Telegram API credentials")

    final_items = update_final_items(us_stock_holdings, buy_items, not_sell_items)
    save_json(final_items, "data/data.json")


if __name__ == "__main__":
    main()
