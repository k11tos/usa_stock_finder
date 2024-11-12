"""
usa_stock_finder.py

This module provides functionalities to find and analyze USA stock data.
It includes functions to fetch stock prices, analyze trends, and generate
reports for better investment decisions.

Author: Breadpig based on the theory from Mark Minervini
Date: 2024.05.19
"""

import asyncio
import atexit
import csv
import json
import logging.config
import logging.handlers
import os.path
import pathlib
import re
from datetime import date

import jmespath
import mojito
import telegram
from dotenv import load_dotenv

from stock_analysis import UsaStockFinder

logger = logging.getLogger(__name__)


def setup_logging():
    """Initializes logging configuration."""
    config_file = pathlib.Path("logging_config/logging_config.json")
    with open(config_file, encoding="utf-8") as f_in:
        config = json.load(f_in)

    logging.config.dictConfig(config)
    queue_handler = logging.getHandlerByName("queue_handler")
    if queue_handler is not None:
        queue_handler.listener.start()
        atexit.register(queue_handler.listener.stop)


async def send_telegram_message(bot_token, chat_id, message):
    """Sends a telegram message to a pre-defined user.

    Args:
        bot_token (string): Unique key for telegram account.
        chat_id (string): Unique key for telegram user.
        message (string): The content to send via telegram.
    """
    bot = telegram.Bot(bot_token)
    await bot.sendMessage(chat_id=chat_id, text=message)


def read_csv_first_column(file_path):
    """Reads the symbol from quantus.kr.

    Args:
        file_path (string): File path for the given csv file from quantus.

    Returns:
        list: List of ticker. The number of the list is 100.
    """
    with open(file_path, newline="", encoding="utf-8") as csvfile:
        return [re.sub("-US$", "", row[0]).replace("/", "-") for row in csv.reader(csvfile)][1:]


def save_json(data, file_path):
    """Saves the chosen tickers to a JSON file.

    Args:
        data (list): The list containing the chosen tickers.
        file_path (string): The location of the JSON file to save the list.
    """
    with open(file_path, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file)


def load_json(file_path):
    """Reads the tickers from the saved JSON file.

    Args:
        file_path (string): The location of the JSON file to retrieve the list.

    Returns:
        list: The list containing the chosen tickers.
    """
    with open(file_path, "r", encoding="utf-8") as json_file:
        return json.load(json_file)


def fetch_stock_tickers():
    """get stock tickers from stock account

    Returns:
        list: ticker list of stock
    """
    load_dotenv()
    exchanges = ["나스닥", "뉴욕"]
    selected_items = []

    for _ in range(5):
        try:
            for exchange in exchanges:
                broker = mojito.KoreaInvestment(
                    api_key=os.getenv("ki_app_key"),
                    api_secret=os.getenv("ki_app_secret_key"),
                    acc_no=os.getenv("account_number"),
                    exchange=exchange,
                )
                balance = broker.fetch_present_balance()

                if balance["rt_cd"] != "0":
                    raise ValueError(balance["msg1"])

                selected_items.extend(jmespath.search("output1[*].pdno", balance))
            return selected_items
        except ValueError as e:
            logger.error("Error fetching stock tickers: %s", str(e))
            asyncio.run(
                send_telegram_message(
                    bot_token=os.getenv("telegram_api_key"),
                    chat_id=os.getenv("telegram_manager_id"),
                    message=str(e),
                )
            )
            if os.path.exists("token.dat"):
                os.remove("token.dat")

    logger.error("Failed to get stock tickers after multiple attempts")
    return []


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
    valid_trend = finder.has_valid_trend_tempate(0)
    valid_trend_margin = finder.has_valid_trend_tempate(0.1)

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
    logging.debug(
        f"{symbol} : {correlations['200'][symbol]} -> {correlations['100'][symbol]} -> {correlations['50'][symbol]}"
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
    return message


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

    prev_items = fetch_stock_tickers()
    if not prev_items:
        logger.error("Failed to get stock tickers from stock account")
        return

    symbols = read_csv_first_column(os.path.join(".", "portfolio/portfolio.csv"))
    finder = UsaStockFinder(symbols)

    if not finder.is_data_valid():
        logger.error("Invalid data in UsaStockFinder")
        return

    correlation = calculate_correlations(finder)
    buy_items, not_sell_items = select_stocks(finder, correlation)

    telegram_message = generate_telegram_message(prev_items, buy_items, not_sell_items)

    if telegram_message:
        asyncio.run(
            send_telegram_message(
                bot_token=os.getenv("telegram_api_key"),
                chat_id=os.getenv("telegram_manager_id"),
                message="\n".join(telegram_message),
            )
        )
        logging.debug(telegram_message)

    final_items = update_final_items(prev_items, buy_items, not_sell_items)
    save_json(final_items, "data.json")


if __name__ == "__main__":
    main()
