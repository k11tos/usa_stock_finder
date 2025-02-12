"""
UsaStockFinder class for finding stock items from the USA stock market.
"""

from typing import List

import yfinance as yf


class UsaStockFinder:
    """Finds stock items from the USA stock market."""

    def __init__(self, symbols: List[str]):
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

    def has_valid_trend_template(self, margin):
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
