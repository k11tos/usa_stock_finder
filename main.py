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

from dotenv import load_dotenv

from file_utils import read_csv_first_column, save_json
from logging_setup import setup_logging
from stock_analysis import UsaStockFinder
from stock_operations import fetch_account_balance, fetch_us_stock_holdings
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
    prev_items: list[str], buy_items: list[str], not_sell_items: list[str]
) -> list[str] | None:
    """
    Generate a Telegram message with buy and sell recommendations.

    This function compares the current selection of stocks with the previous selection
    to determine which stocks should be bought or sold. It generates a message that
    includes the current date and specific buy/sell recommendations.

    Args:
        prev_items (list[str]): List of previously selected stock symbols
        buy_items (list[str]): List of stock symbols recommended for buying
        not_sell_items (list[str]): List of stock symbols not recommended for selling

    Returns:
        list[str] | None: A list of strings containing the date and buy/sell recommendations,
                         or None if there are no changes to report
    """
    keep_items = set(buy_items) | set(not_sell_items)
    message = [str(date.today())]
    message.extend(f"Buy {item}" for item in buy_items if item not in prev_items)
    message.extend(f"Sell {item}" for item in prev_items if item not in keep_items)

    if len(message) > 1:
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
    if buy_items:
        investment_map = calculate_investment_per_stock(buy_items)
        if investment_map:
            logger.info(
                "Investment amounts calculated: %d stocks, total investment: %s",
                len(investment_map),
                sum(investment_map.values()),
            )
        else:
            logger.warning("Failed to calculate investment amounts")

    telegram_message = generate_telegram_message(us_stock_holdings, buy_items, not_sell_items)

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
