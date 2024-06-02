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
        self.symbol_list = symbols
        self.last_high = {}
        self.last_low = {}
        self.current_price = {}
        for symbol in self.symbol_list:
            self.last_high[symbol] = self.stock_data["High"][symbol].max()
            self.current_price[symbol] = self.stock_data["Close"][symbol].iloc[-1]
            self.last_low[symbol] = self.stock_data["Low"][symbol].min()

    def is_data_valid(self):
        """Checks if the loaded data is valid.

        Returns:
            dataframe: Price data from Yahoo Finance.
        """
        return not self.stock_data.empty

    def is_above_75_percent_of_52_week_high(self, margin):
        """Checks if the current price is higher than 75% of the 52-week high.

        Args:
            margin (float): Value to set margin for comparison.

        Returns:
            bool: True means the current price is higher than 75% of the 52-week high.
        """
        is_above_75_percent_of_high = {}
        for symbol in self.symbol_list:
            is_above_75_percent_of_high[symbol] = self.current_price[symbol] > self.last_high[symbol] * 0.75 * (
                1 - margin
            )

        return is_above_75_percent_of_high

    def is_above_52_week_low(self, margin):
        """Checks if the current price is higher than the 52-week low.

        Args:
            margin (float): Value to set margin for comparison.

        Returns:
            bool: True means the current price has increased over 30% compared to the lowest price.
        """
        is_above_low = {}
        for symbol in self.symbol_list:
            increase_percentage = (self.current_price[symbol] - self.last_low[symbol]) / self.last_low[symbol] * 100
            is_above_low[symbol] = increase_percentage >= 30 * (1 - margin)
        return is_above_low

    def get_moving_averages(self, days):
        """Gets the moving average price of the given period.

        Args:
            days (int): The days to calculate the average.

        Returns:
            float: The moving averaged price with the given window.
        """
        latest_ma = {}
        for symbol in self.symbol_list:
            hist_data = self.stock_data["Close"][symbol].rolling(window=days).mean()
            latest_ma[symbol] = hist_data.iloc[-1]

        return latest_ma

    def is_200_ma_increasing_recently(self, margin):
        """Checks if the latest 200 days moving average has increased recently.

        Args:
            margin (float): Value to set the margin for comparison.

        Returns:
            bool: True means 200 moving averaged prices have increased recently.
        """
        is_increasing = {}
        for symbol in self.symbol_list:
            # Calculate 200-day moving average
            ma_200 = self.stock_data["Close"][symbol].rolling(window=200).mean()

            current_data = ma_200.iloc[-1]
            one_month_ago_data = ma_200.iloc[-21]

            # Check if current moving average is higher than one month ago
            is_increasing[symbol] = current_data >= one_month_ago_data * (1 - margin)

        return is_increasing

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
        for symbol in self.symbol_list:
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

    def price_volume_correlation_percent(self, recent_days):
        """Gets the correlation value to decide if it is a bull market or bear market.

        Args:
            recent_days (int): The days to calculate the correlation.

        Returns:
            float: Percent with the positive correlation between the price and the volume.
        """
        total_price_volume = {}
        period_data = self.stock_data.tail(recent_days)
        for symbol in self.symbol_list:
            price_diff = period_data["Close"][symbol].diff()
            volume_diff = period_data["Volume"][symbol].diff()
            positive_price_volume = (
                period_data[(price_diff >= 0) & (volume_diff >= 0)].shape[0] / period_data.shape[0] * 100
            )
            negative_price_volume = (
                period_data[(price_diff < 0) & (volume_diff < 0)].shape[0] / period_data.shape[0] * 100
            )
            total_price_volume[symbol] = positive_price_volume + negative_price_volume
        return total_price_volume

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
        comparison_result = {}
        for symbol in self.symbol_list:
            average_volume = period_data["Volume"][symbol].mean()
            volume_data = period_data["Volume"][symbol]
            price_diff_data = period_data["Close"][symbol].diff()
            volume_up_days = volume_data[volume_data > average_volume]
            price_up_days = volume_up_days[(price_diff_data >= 0)].shape[0]
            price_down_days = volume_up_days[price_diff_data < 0].shape[0]
            comparison_result[symbol] = price_up_days >= price_down_days * (1 - margin)
        return comparison_result


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
        first_row = next(csv_reader)  # 첫 번째 행을 읽어옴
        if first_row[0] == "Code":  # "Code" 행인 경우 pass
            next(csv_reader)
        for row in csv_reader:
            if row[0] == "":
                continue
            code = row[0].split("-")[0]  # '-' 이전의 문자열만 선택
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

    broker = mojito.KoreaInvestment(
        api_key=os.getenv("ki_app_key"),
        api_secret=os.getenv("ki_app_secret_key"),
        acc_no=os.getenv("account_number"),
        exchange="나스닥",
    )
    balance = broker.fetch_present_balance()
    previous_selected_items = jmespath.search("output1[*].pdno", balance)
    return previous_selected_items


def main():
    """Main function."""
    setup_logging()
    load_dotenv()

    previous_selected_items = get_stock_tickers()

    symbols = read_first_column(os.path.join(".", "portfolio.csv"))
    finder = UsaStockFinder(symbols)
    telegram_send_string = []
    strong_in = {}
    if finder.is_data_valid():
        has_valid_trend = finder.has_valid_trend_tempate(0)
        has_valid_trend_w_margin = finder.has_valid_trend_tempate(0.1)
        strong_in["200"] = finder.price_volume_correlation_percent(200)
        strong_in["100"] = finder.price_volume_correlation_percent(100)
        strong_in["50"] = finder.price_volume_correlation_percent(50)
        selected_buy_items = []
        selected_not_sell_items = []
        for symbol in symbols:
            if has_valid_trend[symbol] and strong_in["50"][symbol] >= 50:
                selected_buy_items.append(symbol)
                send_string = (
                    symbol
                    + " : "
                    + str(strong_in["200"][symbol])
                    + " -> "
                    + str(strong_in["100"][symbol])
                    + " -> "
                    + str(strong_in["50"][symbol])
                )
                logging.debug(send_string)
            elif has_valid_trend_w_margin[symbol] and strong_in["50"][symbol] >= 40:
                selected_not_sell_items.append(symbol)
                send_string = (
                    symbol
                    + " : "
                    + str(strong_in["200"][symbol])
                    + " -> "
                    + str(strong_in["100"][symbol])
                    + " -> "
                    + str(strong_in["50"][symbol])
                )
                logging.debug(send_string)

        today_string = str(date.today())
        telegram_send_string.append(today_string)

        final_items = previous_selected_items.copy()

        for item in selected_buy_items:
            if item not in previous_selected_items:
                send_string = "Buy " + item
                telegram_send_string.append(send_string)
                final_items.append(item)

        keep_items = list(set(selected_buy_items) | set(selected_not_sell_items))

        for item in previous_selected_items:
            if item not in keep_items:
                send_string = "Sell " + item
                telegram_send_string.append(send_string)
                final_items.remove(item)

        if len(telegram_send_string) > 1:
            send_telegram_message(
                bot_token=os.getenv("telegram_api_key"),
                chat_id=os.getenv("telegram_manager_id"),
                message="\n".join(telegram_send_string),
            )
            logging.debug(telegram_send_string)

        save_to_json(final_items, "data.json")


if __name__ == "__main__":
    main()
