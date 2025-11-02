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

from file_utils import read_csv_first_column, save_json
from logging_setup import setup_logging
from stock_analysis import UsaStockFinder
from stock_operations import fetch_account_balance, fetch_holdings_detail, fetch_us_stock_holdings
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
    valid_trend = finder.has_valid_trend_template(0)
    valid_trend_margin = finder.has_valid_trend_template(0.1)

    for symbol in finder.symbols:
        if valid_trend[symbol] and correlations["50"][symbol] >= 50:
            selected_buy.append(symbol)
        elif valid_trend_margin[symbol] and correlations["50"][symbol] >= 40:
            selected_not_sell.append(symbol)
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
    not_sell_items: list[str],
    share_quantities: dict[str, dict[str, Any]] | None = None,
    sell_quantities: dict[str, dict[str, Any]] | None = None,
    avsl_sell_items: list[str] | None = None,
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
        not_sell_items (list[str]): List of stock symbols not recommended for selling
        share_quantities (dict[str, dict[str, Any]] | None): Dictionary containing share
            quantity information for buy signals
        sell_quantities (dict[str, dict[str, Any]] | None): Dictionary containing share
            quantity information for sell signals
        avsl_sell_items (list[str] | None): List of stock symbols with AVSL sell signals

    Returns:
        list[str] | None: A list of strings containing the date and buy/sell recommendations
                         with investment amounts and share quantities, or None if there are
                         no changes to report
    """
    keep_items = set(buy_items) | set(not_sell_items)
    message = [str(date.today())]
    has_changes = False

    # Generate buy messages with investment details
    new_buy_items = [item for item in buy_items if item not in prev_items]
    if new_buy_items:
        message.append("\n📈 매수 신호:")
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
                    msg = f"  🔄 추가 매수: {item}"
                    msg += f"\n     현재 보유: {current_qty}주"
                    msg += f"\n     추가 매수: {shares}주"
                    msg += f"\n     총 보유: {total_qty}주"
                else:
                    msg = f"  ✅ 신규 매수: {item}"
                    msg += f"\n     매수 수량: {shares}주"

                msg += f"\n     투자 금액: ${investment:,.2f}"
                msg += f"\n     현재가: ${price:.2f}"
                message.append(msg)
            else:
                message.append(f"  ✅ 매수: {item}")

    # Generate sell messages with quantity details
    sell_items = [item for item in prev_items if item not in keep_items]
    if sell_items or (avsl_sell_items and len(avsl_sell_items) > 0):
        message.append("\n📉 매도 신호:")
        has_changes = True

        # Regular sell items
        for item in sell_items:
            if item in (avsl_sell_items or []):
                continue  # Skip if already in AVSL list (will be handled below)
            
            if sell_quantities and item in sell_quantities:
                info = sell_quantities[item]
                shares = info.get("shares_to_sell", 0)
                price = info.get("current_price", 0)
                sell_amount = info.get("sell_amount", 0)
                profit_loss = info.get("profit_loss", 0.0)
                profit_rate = info.get("profit_loss_rate", 0.0)

                msg = f"  ❌ 매도: {item}"
                msg += f"\n     매도 수량: {shares}주"
                msg += f"\n     현재가: ${price:.2f}"
                msg += f"\n     매도 금액: ${sell_amount:,.2f}"

                if profit_loss != 0:
                    profit_sign = "+" if profit_loss >= 0 else ""
                    rate_sign = "+" if profit_rate >= 0 else ""
                    msg += f"\n     손익: {profit_sign}${profit_loss:,.2f} ({rate_sign}{profit_rate:.2f}%)"

                message.append(msg)
            else:
                message.append(f"  ❌ 매도: {item}")

        # AVSL sell items (with special marking)
        if avsl_sell_items:
            for item in avsl_sell_items:
                if sell_quantities and item in sell_quantities:
                    info = sell_quantities[item]
                    shares = info.get("shares_to_sell", 0)
                    price = info.get("current_price", 0)
                    sell_amount = info.get("sell_amount", 0)
                    profit_loss = info.get("profit_loss", 0.0)
                    profit_rate = info.get("profit_loss_rate", 0.0)

                    msg = f"  ⚠️ AVSL 하락신호: {item}"
                    msg += f"\n     매도 수량: {shares}주"
                    msg += f"\n     현재가: ${price:.2f}"
                    msg += f"\n     매도 금액: ${sell_amount:,.2f}"

                    if profit_loss != 0:
                        profit_sign = "+" if profit_loss >= 0 else ""
                        rate_sign = "+" if profit_rate >= 0 else ""
                        msg += f"\n     손익: {profit_sign}${profit_loss:,.2f} ({rate_sign}{profit_rate:.2f}%)"

                    message.append(msg)
                else:
                    message.append(f"  ⚠️ AVSL 하락신호: {item}")

    if has_changes:
        return message
    return None


def calculate_investment_per_stock(
    buy_items: list[str],
    reserve_ratio: float = 0.1,
    min_investment: float = 100.0,
    max_investment: float | None = None,
) -> dict[str, float] | None:
    """
    Calculate investment amount per stock based on available cash and buy signals.

    This function:
    1. Fetches account balance and available cash
    2. Calculates investment amount per stock using equal distribution strategy
    3. Applies reserve ratio to keep some cash reserved
    4. Applies min/max investment constraints

    Args:
        buy_items (list[str]): List of stock symbols recommended for buying
        reserve_ratio (float): Ratio of cash to reserve (default: 0.1 = 10%)
        min_investment (float): Minimum investment amount per stock (default: 100.0)
        max_investment (float | None): Maximum investment amount per stock (None = no limit)

    Returns:
        dict[str, float] | None: Dictionary mapping stock symbols to investment amounts,
                                 or None if account balance cannot be fetched or no buy signals

    Note:
        - Uses equal distribution strategy (available cash divided equally among buy signals)
        - Applies reserve ratio to keep emergency funds
        - Respects min/max investment constraints
        - Returns None if account balance fetch fails
    """
    if not buy_items:
        logger.warning("No buy signals to calculate investment amounts")
        return None

    account_balance = fetch_account_balance()
    if not account_balance:
        logger.error("Failed to fetch account balance")
        return None

    available_cash = account_balance.get("available_cash", 0.0)
    buyable_cash = account_balance.get("buyable_cash", available_cash)

    if buyable_cash <= 0:
        logger.warning("No buyable cash available")
        return None

    # Calculate total investment amount (excluding reserve)
    total_investment = buyable_cash * (1 - reserve_ratio)
    num_stocks = len(buy_items)

    if num_stocks == 0:
        logger.warning("No stocks to invest in")
        return None

    # Equal distribution: divide total investment equally among stocks
    investment_per_stock = total_investment / num_stocks

    # Apply min/max constraints
    affordable_stocks = buy_items
    if investment_per_stock < min_investment:
        # If investment per stock is below minimum, check if we can invest in fewer stocks
        max_affordable_stocks = int(total_investment / min_investment)
        if max_affordable_stocks == 0:
            logger.warning(
                "Available cash (%s) is insufficient for minimum investment (%s) for any stock",
                total_investment,
                min_investment,
            )
            return None

        # Only invest in stocks that can meet minimum investment
        investment_per_stock = min_investment
        num_affordable_stocks = min(num_stocks, max_affordable_stocks)
        affordable_stocks = buy_items[:num_affordable_stocks]
        logger.info(
            "Adjusting investment: %d stocks can afford minimum investment of %s",
            num_affordable_stocks,
            min_investment,
        )

    if max_investment and investment_per_stock > max_investment:
        investment_per_stock = max_investment
        logger.info("Capping investment per stock to maximum: %s", max_investment)

    # Create investment mapping
    investment_map = {symbol: round(investment_per_stock, 2) for symbol in affordable_stocks}

    logger.info(
        "Investment calculation: Total: %s, Reserve: %s, Per stock: %s, Stocks: %d",
        buyable_cash,
        buyable_cash * reserve_ratio,
        investment_per_stock,
        len(investment_map),
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

        # Calculate shares to buy (round down to whole shares)
        shares_to_buy = int(investment_amount / current_price)

        if shares_to_buy <= 0:
            logger.warning(
                "Investment amount %s too small for %s at price %s", investment_amount, symbol, current_price
            )
            continue

        # Get current holding quantity
        current_quantity = holdings_map.get(symbol, 0.0)

        # Calculate additional buy (if already holding) or total shares to buy
        additional_buy = shares_to_buy if current_quantity == 0 else shares_to_buy
        total_after_buy = current_quantity + shares_to_buy

        # Calculate actual investment amount (shares * price)
        actual_investment = shares_to_buy * current_price

        result[symbol] = {
            "investment_amount": round(investment_amount, 2),
            "current_price": round(current_price, 2),
            "shares_to_buy": shares_to_buy,
            "current_quantity": int(current_quantity),
            "additional_buy": additional_buy,
            "total_after_buy": total_after_buy,
            "actual_investment": round(actual_investment, 2),
        }

        logger.debug(
            "%s: Investment=%s, Price=%s, Shares=%d, Current=%d, Total=%d",
            symbol,
            investment_amount,
            current_price,
            shares_to_buy,
            int(current_quantity),
            total_after_buy,
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

        current_price = finder.current_price.get(symbol, holding.get("current_price", 0.0))
        if current_price <= 0:
            logger.warning("Invalid price for %s: %s", symbol, current_price)
            continue

        # Sell all shares
        shares_to_sell = int(current_quantity)
        sell_amount = shares_to_sell * current_price

        result[symbol] = {
            "current_quantity": int(current_quantity),
            "current_price": round(current_price, 2),
            "shares_to_sell": shares_to_sell,
            "sell_amount": round(sell_amount, 2),
            "avg_price": holding.get("avg_price", 0.0),
            "profit_loss": holding.get("profit_loss", 0.0),
            "profit_loss_rate": holding.get("profit_loss_rate", 0.0),
        }

        logger.debug(
            "%s: Sell %d shares at %s, Amount=%s",
            symbol,
            shares_to_sell,
            current_price,
            sell_amount,
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
    2. Fetches current stock holdings
    3. Analyzes candidate stocks
    4. Generates trading signals
    5. Sends notifications via Telegram
    6. Updates the portfolio data

    Note:
        - Requires environment variables for Telegram API and account information
        - Expects a portfolio.csv file in the portfolio directory
        - Saves the final portfolio to data.json
    """
    setup_logging()
    load_dotenv()

    us_stock_holdings = fetch_us_stock_holdings()
    if not us_stock_holdings:
        logger.error("Failed to get stock tickers from stock account")
        return

    candidate_stocks = read_csv_first_column(os.path.join(".", "portfolio/portfolio.csv"))
    finder = UsaStockFinder(candidate_stocks)

    if not finder.is_data_valid():
        logger.error("Invalid data in UsaStockFinder")
        return

    correlation = calculate_correlations(finder)
    buy_items, not_sell_items = select_stocks(finder, correlation)

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

    # Check for AVSL sell signals on holdings
    avsl_sell_items = []
    current_holdings_detail = fetch_holdings_detail()
    if current_holdings_detail:
        # Get symbols from holdings
        holdings_symbols = [holding.get("symbol", "") for holding in current_holdings_detail if holding.get("symbol")]
        
        # Check AVSL for all symbols in finder (includes candidate stocks)
        # But we only care about holdings that are in the finder
        avsl_signals = finder.check_avsl_sell_signal()
        
        # Filter AVSL signals to only include holdings
        for symbol in holdings_symbols:
            if symbol in avsl_signals and avsl_signals[symbol]:
                avsl_sell_items.append(symbol)
                logger.info("AVSL sell signal detected for %s", symbol)

    # Calculate sell quantities for stocks to sell (including AVSL signals)
    keep_items = set(buy_items) | set(not_sell_items)
    # Regular sell items (no longer in buy/not_sell)
    regular_sell_items = [item for item in us_stock_holdings if item not in keep_items]
    # Combine regular sell items and AVSL sell items (avoid duplicates)
    all_sell_items = list(set(regular_sell_items + avsl_sell_items))
    
    if all_sell_items:
        sell_quantities = calculate_sell_quantities(all_sell_items, finder)
        if sell_quantities:
            logger.info("Sell quantities calculated for %d stocks (%d regular, %d AVSL)", 
                       len(sell_quantities), len(regular_sell_items), len(avsl_sell_items))

    telegram_message = generate_telegram_message(
        us_stock_holdings, buy_items, not_sell_items, share_quantities, sell_quantities, avsl_sell_items
    )

    if telegram_message:
        bot_token = os.getenv("telegram_api_key")
        chat_id = os.getenv("telegram_manager_id")

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
    save_json(final_items, "data.json")


if __name__ == "__main__":
    main()
