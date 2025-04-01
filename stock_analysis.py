"""
stock_analysis.py

This module provides functionality for analyzing US stock market data using technical indicators.
It includes methods for calculating moving averages, price-volume correlations, and trend analysis
to identify potential trading opportunities.

Dependencies:
    - yfinance: Yahoo Finance API client for fetching stock data
    - pandas: Data manipulation and analysis
    - typing: Type hints for better code documentation

Main Classes:
    - UsaStockFinder: Analyzes stock data using various technical indicators
"""

from typing import Dict, List

import yfinance as yf


class UsaStockFinder:
    """
    A class for analyzing US stock market data using technical indicators.

    This class provides methods to analyze stock price movements, volume trends,
    and various technical indicators to identify potential trading opportunities.

    Attributes:
        stock_data (pd.DataFrame): Historical price and volume data for the given symbols
        symbols (List[str]): List of stock ticker symbols to analyze
        last_high (Dict[str, float]): 52-week high prices for each symbol
        last_low (Dict[str, float]): 52-week low prices for each symbol
        current_price (Dict[str, float]): Current closing prices for each symbol
    """

    def __init__(self, symbols: List[str]):
        """
        Initialize the UsaStockFinder with stock symbols and fetch historical data.

        Args:
            symbols (List[str]): List of stock ticker symbols to analyze

        Note:
            - Fetches 1 year of daily data from Yahoo Finance
            - Calculates initial high, low, and current prices for each symbol
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

    def is_data_valid(self) -> bool:
        """
        Check if the loaded stock data is valid and not empty.

        Returns:
            bool: True if the stock data contains valid information, False otherwise
        """
        return not self.stock_data.empty

    def _compare_with_threshold(
        self, metric: Dict[str, float], threshold: Dict[str, float], comparison_func, margin: float
    ) -> Dict[str, bool]:
        """
        Generic method for comparing metrics with thresholds.

        Args:
            metric (Dict[str, float]): Dictionary of metric values for each symbol
            threshold (Dict[str, float]): Dictionary of threshold values for each symbol
            comparison_func: Function to compare metric with threshold
            margin (float): Tolerance factor for comparison

        Returns:
            Dict[str, bool]: Dictionary of comparison results for each symbol
        """
        return {symbol: comparison_func(metric[symbol], threshold[symbol], margin) for symbol in self.symbols}

    def is_above_75_percent_of_52_week_high(self, margin: float) -> Dict[str, bool]:
        """
        Check if current price is above 75% of the 52-week high.

        Args:
            margin (float): Tolerance factor for price comparison

        Returns:
            Dict[str, bool]: True if current price is above 75% of 52-week high
        """
        return self._compare_with_threshold(
            self.current_price,
            {symbol: self.last_high[symbol] * 0.75 for symbol in self.symbols},
            lambda x, y, m: x > y * (1 - m),
            margin,
        )

    def is_above_52_week_low(self, margin: float) -> Dict[str, bool]:
        """
        Check if current price has increased by 30% from 52-week low.

        Args:
            margin (float): Tolerance factor for price comparison

        Returns:
            Dict[str, bool]: True if price has increased by 30% from 52-week low
        """
        return self._compare_with_threshold(
            self.current_price, self.last_low, lambda x, y, m: (x - y) / y * 100 >= 30 * (1 - m), margin
        )

    def get_moving_averages(self, days: int) -> Dict[str, float]:
        """
        Calculate moving average prices for the specified period.

        Args:
            days (int): Number of days for moving average calculation

        Returns:
            Dict[str, float]: Dictionary of moving average prices for each symbol
        """
        return {
            symbol: self.stock_data["Close"][symbol].rolling(window=days).mean().iloc[-1] for symbol in self.symbols
        }

    def is_200_ma_increasing_recently(self, margin: float) -> Dict[str, bool]:
        """
        Check if 200-day moving average has increased recently.

        Args:
            margin (float): Tolerance factor for comparison

        Returns:
            Dict[str, bool]: True if 200-day MA has increased recently
        """
        ma_200 = {symbol: self.stock_data["Close"][symbol].rolling(window=200).mean() for symbol in self.symbols}
        return self._compare_with_threshold(
            {symbol: ma_200[symbol].iloc[-1] for symbol in self.symbols},
            {symbol: ma_200[symbol].iloc[-21] for symbol in self.symbols},
            lambda x, y, m: x >= y * (1 - m),
            margin,
        )

    def has_valid_trend_template(self, margin: float) -> Dict[str, bool]:
        """
        Check if stock price meets the trend template criteria.

        The trend template checks multiple conditions:
        - Price above 75% of 52-week high
        - Price above 52-week low with 30% increase
        - Price above 50, 150, and 200-day moving averages
        - 200-day MA increasing recently
        - Positive volume-price correlation

        Args:
            margin (float): Tolerance factor for all comparisons

        Returns:
            Dict[str, bool]: True if all trend template conditions are met
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

    def _calculate_price_volume_correlation(self, period_data, symbol: str) -> float:
        """
        Calculate the correlation between price and volume changes.

        Args:
            period_data (pd.DataFrame): DataFrame containing price and volume data
            symbol (str): Stock symbol to analyze

        Returns:
            float: Percentage of positive price-volume correlation
        """
        price_diff = period_data["Close"][symbol].diff()
        volume_diff = period_data["Volume"][symbol].diff()
        positive_correlation = ((price_diff >= 0) & (volume_diff >= 0)).mean() * 100
        negative_correlation = ((price_diff < 0) & (volume_diff < 0)).mean() * 100
        return positive_correlation + negative_correlation

    def price_volume_correlation_percent(self, recent_days: int) -> Dict[str, float]:
        """
        Calculate price-volume correlation for the specified period.

        Args:
            recent_days (int): Number of days to analyze

        Returns:
            Dict[str, float]: Dictionary of correlation percentages for each symbol
        """
        period_data = self.stock_data.tail(recent_days)
        return {symbol: self._calculate_price_volume_correlation(period_data, symbol) for symbol in self.symbols}

    def _compare_volume_price(self, period_data, symbol: str, margin: float) -> bool:
        """
        Compare volume and price movements to identify potential bullish signals.

        Args:
            period_data (pd.DataFrame): Historical price and volume data
            symbol (str): Stock symbol to analyze
            margin (float): Tolerance factor for comparison

        Returns:
            bool: True if bullish signal is detected based on volume and price comparison
        """
        average_volume = period_data["Volume"][symbol].mean()
        volume_data = period_data["Volume"][symbol]
        price_diff_data = period_data["Close"][symbol].diff()
        volume_up_days = volume_data > average_volume
        price_up_days = (price_diff_data[volume_up_days] >= 0).sum()
        price_down_days = (price_diff_data[volume_up_days] < 0).sum()
        return price_up_days >= price_down_days * (1 - margin)

    def compare_volume_price_movement(self, recent_days: int, margin: float) -> Dict[str, bool]:
        """
        Check if price increases occur with above-average volume.

        Args:
            recent_days (int): Number of days to analyze
            margin (float): Tolerance factor for comparison

        Returns:
            Dict[str, bool]: True if price increases occur with above-average volume
        """
        period_data = self.stock_data.tail(recent_days)
        return {symbol: self._compare_volume_price(period_data, symbol, margin) for symbol in self.symbols}
