"""
usa_stock_finder.py

This module provides functionalities to find and analyze USA stock data.
It includes functions to fetch stock prices, analyze trends, and generate
reports for better investment decisions.

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
from stock_operations import fetch_us_stock_holdings
from telegram_utils import send_telegram_message

logger = logging.getLogger(__name__)


def calculate_correlations(finder):
    """
    Calculate price-volume correlations for different time periods.

    This function computes the price-volume correlation percentages
    for 200, 100, and 50-day periods using the provided finder object.

    Args:
        finder (UsaStockFinder): An instance of the UsaStockFinder class with
                              methods to calculate price-volume correlations.

    Returns:
        dict: A dictionary containing price-volume correlation percentages
              for 200, 100, and 50-day periods.
    """
    return {str(days): finder.price_volume_correlation_percent(days) for days in [200, 100, 50]}


def select_stocks(finder, correlations):
    """Select stocks based on trend validity and strength criteria."""
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


def log_stock_info(symbol, correlations):
    """Log debug information about a stock's moving averages.

    Args:
        symbol (str): The stock symbol.
        correlations (dict): Dictionary containing moving average data for the stock.
    """
    logger.debug(
        "%s : %s -> %s -> %s",
        symbol,
        correlations["200"][symbol],
        correlations["100"][symbol],
        correlations["50"][symbol],
    )


def generate_telegram_message(prev_items, buy_items, not_sell_items):
    """Generate a Telegram message with buy and sell recommendations.

    This function compares the current selection of stocks with the previous selection
    to determine which stocks should be bought or sold.

    Args:
        prev_items (list): List of previously selected stock symbols.
        buy_items (list): List of stock symbols recommended for buying.
        not_sell_items (list): List of stock symbols not recommended for selling.

    Returns:
        list: A list of strings containing the date and buy/sell recommendations.
    """
    keep_items = set(buy_items) | set(not_sell_items)
    message = [str(date.today())]
    message.extend(f"Buy {item}" for item in buy_items if item not in prev_items)
    message.extend(f"Sell {item}" for item in prev_items if item not in keep_items)

    if len(message) > 1:
        return message
    return None


def update_final_items(prev_items, buy_items, not_sell_items):
    """
    Update the final list of items based on previous selections and new buy/not sell decisions.

    Args:
        prev_items (list): List of items previously selected.
        buy_items (list): List of items selected to buy.
        not_sell_items (list): List of items selected not to sell.

    Returns:
        list: Updated final list of items to keep.
    """
    keep_items = set(buy_items) | set(not_sell_items)
    new_items = [item for item in buy_items if item not in prev_items]
    return [item for item in prev_items + new_items if item in keep_items]


def main():
    """Main function."""
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

    telegram_message = generate_telegram_message(us_stock_holdings, buy_items, not_sell_items)

    if telegram_message:
        asyncio.run(
            send_telegram_message(
                bot_token=os.getenv("telegram_api_key"),
                chat_id=os.getenv("telegram_manager_id"),
                message="\n".join(telegram_message),
            )
        )
        logger.debug(telegram_message)

    final_items = update_final_items(us_stock_holdings, buy_items, not_sell_items)
    save_json(final_items, "data.json")


if __name__ == "__main__":
    main()
