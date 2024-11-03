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
import yfinance as yf
from dotenv import load_dotenv

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


def send_telegram_message(bot_token, chat_id, message):
    """Sends a telegram message to a pre-defined user.

    Args:
        bot_token (string): Unique key for telegram account.
        chat_id (string): Unique key for telegram user.
        message (string): The content to send via telegram.
    """
    bot = telegram.Bot(bot_token)
    asyncio.run(bot.sendMessage(chat_id=chat_id, text=message))


class UsaStockFinder:
    """Finds stock items from the USA stock market."""

    def __init__(self, symbols):
        """Initializes the object to retrieve price data from Yahoo Finance.

        Args:
            symbols (string): Ticker symbols from the USA stock market.
        """
        self.stock_data = yf.download(symbols, period="1y", interval="1d")
        self.symbols = symbols
        self.last_high = {}
        self.last_low = {}
        self.current_price = {}
        for symbol in self.symbols:
            self.last_high[symbol] = self.stock_data["High"][symbol].max()
            self.current_price[symbol] = self.stock_data["Close"][symbol].iloc[-1]
            self.last_low[symbol] = self.stock_data["Low"][symbol].min()

    def is_data_valid(self):
        """Checks if the loaded data is valid.

        Returns:
            dataframe: Price data from Yahoo Finance.
        """
        return not self.stock_data.empty

    def _compare_with_threshold(self, metric, threshold, comparison_func, margin):
        """Generic method for comparing a metric with a threshold."""
        return {symbol: comparison_func(metric[symbol], threshold[symbol], margin) for symbol in self.symbols}

    def is_above_75_percent_of_52_week_high(self, margin):
        """Checks if the current price is higher than 75% of the 52-week high.

        Args:
            margin (float): Value to set margin for comparison.

        Returns:
            bool: True means the current price is higher than 75% of the 52-week high.
        """
        return self._compare_with_threshold(
            self.current_price,
            {symbol: self.last_high[symbol] * 0.75 for symbol in self.symbols},
            lambda x, y, m: x > y * (1 - m),
            margin,
        )

    def is_above_52_week_low(self, margin):
        """Checks if the current price is higher than the 52-week low.

        Args:
            margin (float): Value to set margin for comparison.

        Returns:
            bool: True means the current price has increased over 30% compared to the lowest price.
        """
        return self._compare_with_threshold(
            self.current_price, self.last_low, lambda x, y, m: (x - y) / y * 100 >= 30 * (1 - m), margin
        )

    def get_moving_averages(self, days):
        """Gets the moving average price of the given period.

        Args:
            days (int): The days to calculate the average.

        Returns:
            float: The moving averaged price with the given window.
        """
        return {
            symbol: self.stock_data["Close"][symbol].rolling(window=days).mean().iloc[-1] for symbol in self.symbols
        }

    def is_200_ma_increasing_recently(self, margin):
        """Checks if the latest 200 days moving average has increased recently.

        Args:
            margin (float): Value to set the margin for comparison.

        Returns:
            bool: True means 200 moving averaged prices have increased recently.
        """
        ma_200 = {symbol: self.stock_data["Close"][symbol].rolling(window=200).mean() for symbol in self.symbols}
        return self._compare_with_threshold(
            {symbol: ma_200[symbol].iloc[-1] for symbol in self.symbols},
            {symbol: ma_200[symbol].iloc[-21] for symbol in self.symbols},
            lambda x, y, m: x >= y * (1 - m),
            margin,
        )

    def has_valid_trend_tempate(self, margin):
        """Checks if the price of the ticker meets the trend template.

        Args:
            margin (float): Value to set the margin for comparison.

        Returns:
            bool: True means the current price meets the trend template.
        """
        is_above_75_percent_of_high = self.is_above_75_percent_of_52_week_high(margin)
        is_above_low = self.is_above_52_week_low(margin)
        latest_50_ma = self.get_moving_averages(50)
        latest_150_ma = self.get_moving_averages(150)
        latest_200_ma = self.get_moving_averages(200)
        current_price = self.current_price
        is_ma_increasing = self.is_200_ma_increasing_recently(margin)
        is_increasing_with_volume_and_price = self.compare_volume_price_movement(200, margin)

        valid = {}
        for symbol in self.symbols:
            valid[symbol] = (
                current_price[symbol] >= latest_150_ma[symbol] * (1 - margin)
                and current_price[symbol] >= latest_200_ma[symbol] * (1 - margin)
                and latest_150_ma[symbol] >= latest_200_ma[symbol] * (1 - margin)
                and is_ma_increasing[symbol]
                and latest_50_ma[symbol] >= latest_150_ma[symbol] * (1 - margin)
                and latest_50_ma[symbol] >= latest_200_ma[symbol] * (1 - margin)
                and current_price[symbol] >= latest_50_ma[symbol] * (1 - margin)
                and is_above_low[symbol]
                and is_above_75_percent_of_high[symbol]
                and is_increasing_with_volume_and_price[symbol]
            )

        return valid

    def _calculate_price_volume_correlation(self, period_data, symbol):
        """Calculate the correlations between price and volume changes.

        Args:
            period_data (pd.DataFrame): DataFrame containing price and volume data for the specified period
            symbol (_type_): _description_

        Returns:
            _type_: _description_
        """
        price_diff = period_data["Close"][symbol].diff()
        volume_diff = period_data["Volume"][symbol].diff()
        positive_correlation = ((price_diff >= 0) & (volume_diff >= 0)).mean() * 100
        negative_correlation = ((price_diff < 0) & (volume_diff < 0)).mean() * 100
        return positive_correlation + negative_correlation

    def price_volume_correlation_percent(self, recent_days):
        """Gets the correlation value to decide if it is a bull market or bear market.

        Args:
            recent_days (int): The days to calculate the correlation.

        Returns:
            float: Percent with the positive correlation between the price and the volume.
        """
        period_data = self.stock_data.tail(recent_days)
        return {symbol: self._calculate_price_volume_correlation(period_data, symbol) for symbol in self.symbols}

    def _compare_volume_price(self, period_data, symbol, margin):
        """
        Compare volume and price movements to identify potential bullish signals.

        Args:
            period_data (pandas.DataFrame): Historical price and volume data for multiple symbols.
            symbol (str): The stock symbol to analyze.
            margin (float): A tolerance factor for comparing price up days to down days.

        Returns:
            bool: True if the stock shows a bullish signal based on volume and price comparison, False otherwise.
        """
        average_volume = period_data["Volume"][symbol].mean()
        volume_data = period_data["Volume"][symbol]
        price_diff_data = period_data["Close"][symbol].diff()
        volume_up_days = volume_data > average_volume
        price_up_days = (price_diff_data[volume_up_days] >= 0).sum()
        price_down_days = (price_diff_data[volume_up_days] < 0).sum()
        return price_up_days >= price_down_days * (1 - margin)

    def compare_volume_price_movement(self, recent_days, margin):
        """Checks if the price goes high when the volume is higher than average volume.

        Args:
            recent_days (int): The days to calculate.
            margin (float): The value to set the margin for comparison.

        Returns:
            dictionary: The pair with the tickers and the boolean,
                        which means up days is longer than down days.
        """
        period_data = self.stock_data.tail(recent_days)
        return {symbol: self._compare_volume_price(period_data, symbol, margin) for symbol in self.symbols}


def read_first_column(file_path):
    """Reads the symbol from quantus.kr.

    Args:
        file_path (string): File path for the given csv file from quantus.

    Returns:
        list: List of ticker. The number of the list is 100.
    """
    data = []
    with open(file_path, newline="", encoding="utf-8") as csvfile:
        csv_reader = csv.reader(csvfile)
        next(csv_reader)  # Skip the header row

        for row in csv_reader:
            if row and row[0]:
                code = re.sub("-US$", "", row[0]).replace("/", "-")
                data.append(code)

    return data


def save_to_json(data, file_path):
    """Saves the chosen tickers to a JSON file.

    Args:
        data (list): The list containing the chosen tickers.
        file_path (string): The location of the JSON file to save the list.
    """
    with open(file_path, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file)


def load_from_json(file_path):
    """Reads the tickers from the saved JSON file.

    Args:
        file_path (string): The location of the JSON file to retrieve the list.

    Returns:
        list: The list containing the chosen tickers.
    """
    with open(file_path, "r", encoding="utf-8") as json_file:
        data = json.load(json_file)
    return data


def get_stock_tickers():
    """get stock tickers from stock account

    Returns:
        list: ticker list of stock
    """
    load_dotenv()

    exchanges = ["나스닥", "뉴욕"]
    previous_selected_items = []
    max_attempts = 5

    for _ in range(max_attempts):
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

                previous_selected_items.extend(jmespath.search("output1[*].pdno", balance))

            return previous_selected_items

        except ValueError(balance["msg1"]) as e:
            logger.error("Error fetching stock tickers: %s", str(e))
            send_telegram_message(
                bot_token=os.getenv("telegram_api_key"),
                chat_id=os.getenv("telegram_manager_id"),
                message=str(e),
            )
            if os.path.exists("token.dat"):
                os.remove("token.dat")

    logger.error("Failed to get stock tickers from stock account after multiple attempts")
    return []


def main():
    """Main function."""
    setup_logging()
    load_dotenv()

    previous_selected_items = get_stock_tickers()
    if not previous_selected_items:
        logger.error("Failed to get stock tickers from stock account")
        return

    symbols = read_first_column(os.path.join(".", "portfolio/portfolio.csv"))
    finder = UsaStockFinder(symbols)

    if not finder.is_data_valid():
        logger.error("Invalid data in UsaStockFinder")
        return

    strong_in = calculate_price_volume_correlations(finder)
    selected_buy_items, selected_not_sell_items = select_stocks(finder, strong_in)

    telegram_send_string = generate_telegram_message(
        previous_selected_items, selected_buy_items, selected_not_sell_items
    )

    if len(telegram_send_string) > 1:
        send_telegram_message(
            bot_token=os.getenv("telegram_api_key"),
            chat_id=os.getenv("telegram_manager_id"),
            message="\n".join(telegram_send_string),
        )
        logging.debug(telegram_send_string)

    final_items = update_final_items(previous_selected_items, selected_buy_items, selected_not_sell_items)
    save_to_json(final_items, "data.json")


def calculate_price_volume_correlations(finder):
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
    return {
        "200": finder.price_volume_correlation_percent(200),
        "100": finder.price_volume_correlation_percent(100),
        "50": finder.price_volume_correlation_percent(50),
    }


def select_stocks(finder, strong_in):
    """
    Select stocks based on trend validity and strength criteria.

    Args:
        finder (UsaStockFinder): An instance of the UsaStockFinder class containing stock data and analysis methods.
        strong_in (dict): A dictionary containing strength indicators for different time periods.

    Returns:
        tuple: Two lists - selected buy items and selected not-sell items.
    """
    has_valid_trend = finder.has_valid_trend_tempate(0)
    has_valid_trend_w_margin = finder.has_valid_trend_tempate(0.1)
    selected_buy_items = []
    selected_not_sell_items = []

    for symbol in finder.symbols:
        if has_valid_trend[symbol] and strong_in["50"][symbol] >= 50:
            selected_buy_items.append(symbol)
        elif has_valid_trend_w_margin[symbol] and strong_in["50"][symbol] >= 40:
            selected_not_sell_items.append(symbol)

        log_stock_info(symbol, strong_in)

    return selected_buy_items, selected_not_sell_items


def log_stock_info(symbol, strong_in):
    """Log debug information about a stock's moving averages.

    Args:
        symbol (str): The stock symbol.
        strong_in (dict): Dictionary containing moving average data for the stock.
    """
    send_string = (
        f"{symbol} : {strong_in['200'][symbol]} -> " f"{strong_in['100'][symbol]} -> {strong_in['50'][symbol]}"
    )
    logging.debug(send_string)


def generate_telegram_message(previous_selected_items, selected_buy_items, selected_not_sell_items):
    """Generate a Telegram message with buy and sell recommendations.

    This function compares the current selection of stocks with the previous selection
    to determine which stocks should be bought or sold.

    Args:
        previous_selected_items (list): List of previously selected stock symbols.
        selected_buy_items (list): List of stock symbols recommended for buying.
        selected_not_sell_items (list): List of stock symbols not recommended for selling.

    Returns:
        list: A list of strings containing the date and buy/sell recommendations.
    """
    keep_items = set(selected_buy_items) | set(selected_not_sell_items)
    telegram_send_string = [str(date.today())]

    telegram_send_string.extend(f"Buy {item}" for item in selected_buy_items if item not in previous_selected_items)
    telegram_send_string.extend(f"Sell {item}" for item in previous_selected_items if item not in keep_items)

    return telegram_send_string


def update_final_items(previous_selected_items, selected_buy_items, selected_not_sell_items):
    """
    Update the final list of items based on previous selections and new buy/not sell decisions.

    Args:
        previous_selected_items (list): List of items previously selected.
        selected_buy_items (list): List of items selected to buy.
        selected_not_sell_items (list): List of items selected not to sell.

    Returns:
        list: Updated final list of items to keep.
    """
    keep_items = set(selected_buy_items) | set(selected_not_sell_items)

    new_items = [item for item in selected_buy_items if item not in previous_selected_items]
    final_items = [item for item in previous_selected_items + new_items if item in keep_items]

    return final_items


if __name__ == "__main__":
    main()
