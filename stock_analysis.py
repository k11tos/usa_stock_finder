"""
stock_analysis.py

This module provides functionality for analyzing US stock market data using technical indicators.
It includes methods for calculating moving averages, price-volume correlations, trend analysis,
and AVSL (Average Volume Support Level) sell signal detection to identify potential trading opportunities.

Dependencies:
    - yfinance: Yahoo Finance API client for fetching stock data
    - pandas: Data manipulation and analysis
    - typing: Type hints for better code documentation

Main Classes:
    - UsaStockFinder: Analyzes stock data using various technical indicators
"""

import logging
from typing import Dict, List

import yfinance as yf

from config import AVSLConfig, DataQualityConfig, StrategyConfig

logger = logging.getLogger(__name__)


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
        self.stock_data = yf.download(symbols, period="1y", interval="1d", auto_adjust=True)
        self.symbols = symbols
        self.last_high = {}
        self.last_low = {}
        self.current_price = {}
        for symbol in self.symbols:
            try:
                # Separate data validation into helper function
                if self._is_symbol_data_valid(symbol):

                    self.last_high[symbol] = self.stock_data["High"][symbol].max()
                    self.current_price[symbol] = self.stock_data["Close"][symbol].iloc[-1]
                    self.last_low[symbol] = self.stock_data["Low"][symbol].min()
                else:
                    # Set default values when data is not available
                    self.last_high[symbol] = 0.0
                    self.current_price[symbol] = 0.0
                    self.last_low[symbol] = 0.0
                    print(f"Warning: No data available for {symbol}")
            except (IndexError, KeyError, AttributeError) as e:
                # Set default values when error occurs
                self.last_high[symbol] = 0.0
                self.current_price[symbol] = 0.0
                self.last_low[symbol] = 0.0
                print(f"Error processing {symbol}: {e}")

    def _is_symbol_data_valid(self, symbol: str) -> bool:
        """
        Check if the data for a specific symbol is valid and not empty.

        Args:
            symbol (str): Stock symbol to check

        Returns:
            bool: True if the symbol data is valid, False otherwise
        """
        return (
            symbol in self.stock_data["High"]
            and symbol in self.stock_data["Close"]
            and symbol in self.stock_data["Low"]
            and not self.stock_data["High"][symbol].empty
            and not self.stock_data["Close"][symbol].empty
            and not self.stock_data["Low"][symbol].empty
        )

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
        Check if current price is above configured percentage of the 52-week high.

        Args:
            margin (float): Tolerance factor for price comparison

        Returns:
            Dict[str, bool]: True if current price is above configured percentage of 52-week high
        """
        result = {}
        threshold_ratio = StrategyConfig.HIGH_THRESHOLD_RATIO

        for symbol in self.symbols:
            current = self.current_price.get(symbol, 0.0)
            last_high = self.last_high.get(symbol, 0.0)

            if last_high < DataQualityConfig.MIN_PRICE_THRESHOLD:
                result[symbol] = False
                logger.debug(
                    "%s: 52-week high too low (%.2f < %.2f), condition not met",
                    symbol,
                    last_high,
                    DataQualityConfig.MIN_PRICE_THRESHOLD,
                )
                continue

            threshold_price = last_high * threshold_ratio
            result[symbol] = current > threshold_price * (1 - margin)

            logger.debug(
                "%s: Current price %.2f, 52-week high %.2f, Threshold(%.0f%%) %.2f, With margin %.2f -> %s",
                symbol,
                current,
                last_high,
                threshold_ratio * 100,
                threshold_price,
                threshold_price * (1 - margin),
                result[symbol],
            )

        return result

    def is_above_52_week_low(self, margin: float) -> Dict[str, bool]:
        """
        Check if current price has increased by configured percentage from 52-week low.

        Args:
            margin (float): Tolerance factor for price comparison

        Returns:
            Dict[str, bool]: True if price has increased by configured percentage from 52-week low
        """
        result = {}
        threshold_percent = StrategyConfig.LOW_INCREASE_PERCENT

        for symbol in self.symbols:
            current = self.current_price.get(symbol, 0.0)
            last_low = self.last_low.get(symbol, 0.0)

            # Prevent ZeroDivision: Return False if last_low is 0 or too small
            if last_low < DataQualityConfig.MIN_PRICE_THRESHOLD:
                result[symbol] = False
                logger.debug(
                    "%s: 52-week low too low (%.2f < %.2f), condition not met",
                    symbol,
                    last_low,
                    DataQualityConfig.MIN_PRICE_THRESHOLD,
                )
                continue

            # Safe calculation: (current - last_low) / last_low * 100
            increase_percent = ((current - last_low) / last_low) * 100
            threshold = threshold_percent * (1 - margin)
            result[symbol] = increase_percent >= threshold

            logger.debug(
                "%s: Increase from 52-week low %.2f%% (Threshold: %.2f%%, Margin: %.2f%%) -> %s",
                symbol,
                increase_percent,
                threshold_percent,
                margin * 100,
                result[symbol],
            )

        return result

    def get_moving_averages(self, days: int) -> Dict[str, float]:
        """
        Calculate moving average prices for the specified period.

        Args:
            days (int): Number of days for moving average calculation

        Returns:
            Dict[str, float]: Dictionary of moving average prices for each symbol.
                Returns 0.0 for symbols with insufficient data (will be excluded later).
        """
        result = {}
        for symbol in self.symbols:
            try:
                if (
                    symbol in self.stock_data["Close"]
                    and not self.stock_data["Close"][symbol].empty
                    and len(self.stock_data["Close"][symbol]) >= days
                ):
                    ma_value = self.stock_data["Close"][symbol].rolling(window=days).mean().iloc[-1]
                    result[symbol] = float(ma_value)
                    logger.debug("%s: MA%d = %.2f", symbol, days, ma_value)
                else:
                    result[symbol] = 0.0
                    logger.debug(
                        "%s: Insufficient data (Required: %d days, Actual: %d days), Cannot calculate MA%d",
                        symbol,
                        days,
                        len(self.stock_data["Close"][symbol]) if symbol in self.stock_data["Close"] else 0,
                        days,
                    )
            except (IndexError, KeyError, AttributeError) as e:
                result[symbol] = 0.0
                logger.debug("%s: Error calculating MA%d: %s", symbol, days, str(e))
        return result

    def is_200_ma_increasing_recently(self, margin: float) -> Dict[str, bool]:
        """
        Check if 200-day moving average has increased recently.

        Args:
            margin (float): Tolerance factor for comparison

        Returns:
            Dict[str, bool]: True if 200-day MA has increased recently
        """
        result = {}
        check_days = StrategyConfig.MA_INCREASE_CHECK_DAYS
        required_days = StrategyConfig.MA_200_DAYS

        for symbol in self.symbols:
            try:
                if (
                    symbol in self.stock_data["Close"]
                    and not self.stock_data["Close"][symbol].empty
                    and len(self.stock_data["Close"][symbol]) >= required_days
                ):
                    ma_200 = self.stock_data["Close"][symbol].rolling(window=required_days).mean()
                    if len(ma_200) >= check_days:
                        current_ma = ma_200.iloc[-1]
                        past_ma = ma_200.iloc[-check_days]
                        result[symbol] = current_ma >= past_ma * (1 - margin)
                        logger.debug(
                            "%s: MA200 increase check (Current: %.2f, %d days ago: %.2f, Margin: %.2f%%) -> %s",
                            symbol,
                            current_ma,
                            check_days,
                            past_ma,
                            margin * 100,
                            result[symbol],
                        )
                    else:
                        result[symbol] = False
                        logger.debug(
                            "%s: MA200 insufficient data (Required: %d days, Actual: %d days)",
                            symbol,
                            check_days,
                            len(ma_200),
                        )
                else:
                    result[symbol] = False
                    logger.debug(
                        "%s: Cannot calculate MA200 (Required: %d days, Actual: %d days)",
                        symbol,
                        required_days,
                        len(self.stock_data["Close"][symbol]) if symbol in self.stock_data["Close"] else 0,
                    )
            except (IndexError, KeyError, AttributeError) as e:
                result[symbol] = False
                logger.debug("%s: Error checking MA200 increase: %s", symbol, str(e))
        return result

    def has_valid_trend_template(self, margin: float) -> Dict[str, bool]:
        """
        Check if stock price meets the trend template criteria.

        The trend template checks multiple conditions:
        - Price above configured percentage of 52-week high
        - Price above 52-week low with configured increase percentage
        - Price above 50, 150, and 200-day moving averages
        - 200-day MA increasing recently
        - Positive volume-price correlation

        Args:
            margin (float): Tolerance factor for all comparisons

        Returns:
            Dict[str, bool]: True if all trend template conditions are met.
                False if data is insufficient (will be excluded from analysis).
        """
        is_above_75_percent_of_high = self.is_above_75_percent_of_52_week_high(margin)
        is_above_low = self.is_above_52_week_low(margin)
        latest_50_ma = self.get_moving_averages(StrategyConfig.MA_50_DAYS)
        latest_150_ma = self.get_moving_averages(StrategyConfig.MA_150_DAYS)
        latest_200_ma = self.get_moving_averages(StrategyConfig.MA_200_DAYS)
        current_price = self.current_price
        is_ma_increasing = self.is_200_ma_increasing_recently(margin)
        is_increasing_with_volume_and_price = self.compare_volume_price_movement(StrategyConfig.MA_200_DAYS, margin)

        valid = {}
        for symbol in self.symbols:
            # Exclude stocks with insufficient data: MA value of 0 indicates insufficient data
            if latest_50_ma[symbol] == 0.0 or latest_150_ma[symbol] == 0.0 or latest_200_ma[symbol] == 0.0:
                valid[symbol] = False
                logger.debug(
                    "%s: Cannot evaluate trend template due to insufficient data "
                    "(MA50: %.2f, MA150: %.2f, MA200: %.2f)",
                    symbol,
                    latest_50_ma[symbol],
                    latest_150_ma[symbol],
                    latest_200_ma[symbol],
                )
                continue

            # Evaluate each condition individually
            cond1 = current_price[symbol] >= latest_150_ma[symbol] * (1 - margin)
            cond2 = current_price[symbol] >= latest_200_ma[symbol] * (1 - margin)
            cond3 = latest_150_ma[symbol] >= latest_200_ma[symbol] * (1 - margin)
            cond4 = is_ma_increasing[symbol]
            cond5 = latest_50_ma[symbol] >= latest_150_ma[symbol] * (1 - margin)
            cond6 = latest_50_ma[symbol] >= latest_200_ma[symbol] * (1 - margin)
            cond7 = current_price[symbol] >= latest_50_ma[symbol] * (1 - margin)
            cond8 = is_above_low[symbol]
            cond9 = is_above_75_percent_of_high[symbol]
            cond10 = is_increasing_with_volume_and_price[symbol]

            valid[symbol] = (
                cond1 and cond2 and cond3 and cond4 and cond5 and cond6 and cond7 and cond8 and cond9 and cond10
            )

            # Detailed log: Evaluation result of each condition
            logger.debug(
                "%s: Trend template evaluation (Margin: %.2f%%)\n"
                "  Current price >= MA150: %s (%.2f >= %.2f)\n"
                "  Current price >= MA200: %s (%.2f >= %.2f)\n"
                "  MA150 >= MA200: %s (%.2f >= %.2f)\n"
                "  MA200 increasing: %s\n"
                "  MA50 >= MA150: %s (%.2f >= %.2f)\n"
                "  MA50 >= MA200: %s (%.2f >= %.2f)\n"
                "  Current price >= MA50: %s (%.2f >= %.2f)\n"
                "  Increase from 52-week low: %s\n"
                "  52-week high >= %.0f%%: %s\n"
                "  Volume-price correlation: %s\n"
                "  Final result: %s",
                symbol,
                margin * 100,
                cond1,
                current_price[symbol],
                latest_150_ma[symbol] * (1 - margin),
                cond2,
                current_price[symbol],
                latest_200_ma[symbol] * (1 - margin),
                cond3,
                latest_150_ma[symbol],
                latest_200_ma[symbol] * (1 - margin),
                cond4,
                cond5,
                latest_50_ma[symbol],
                latest_150_ma[symbol] * (1 - margin),
                cond6,
                latest_50_ma[symbol],
                latest_200_ma[symbol] * (1 - margin),
                cond7,
                current_price[symbol],
                latest_50_ma[symbol] * (1 - margin),
                cond8,
                cond9,
                StrategyConfig.HIGH_THRESHOLD_RATIO * 100,
                cond10,
                valid[symbol],
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
        positive_correlation = float(((price_diff >= 0) & (volume_diff >= 0)).mean() * 100)
        negative_correlation = float(((price_diff < 0) & (volume_diff < 0)).mean() * 100)
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
        price_up_days = int((price_diff_data[volume_up_days] >= 0).sum())
        price_down_days = int((price_diff_data[volume_up_days] < 0).sum())
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

    def check_avsl_sell_signal(
        self,
        period_days: int | None = None,
        volume_decline_threshold: float | None = None,
        price_decline_threshold: float | None = None,
        recent_days: int | None = None,
    ) -> Dict[str, bool]:
        """
        Check for AVSL (Average Volume Support Level) sell signals based on volume and price decline.

        AVSL sell signal occurs when:
        1. Recent volume is significantly below average volume (support level breaks)
        2. Price is declining while volume is below average
        3. This indicates weakening support and potential trend reversal

        Args:
            period_days (int | None): Number of days for calculating average volume (None = use config default)
            volume_decline_threshold (float | None): Threshold for volume decline ratio (None = use config default)
            price_decline_threshold (float | None): Threshold for price decline percentage (None = use config default)
            recent_days (int | None): Number of recent days to analyze (None = use config default)

        Returns:
            Dict[str, bool]: True if AVSL sell signal is detected for the symbol
        """
        # Use config defaults if not provided
        if period_days is None:
            period_days = AVSLConfig.PERIOD_DAYS
        if volume_decline_threshold is None:
            volume_decline_threshold = AVSLConfig.VOLUME_DECLINE_THRESHOLD
        if price_decline_threshold is None:
            price_decline_threshold = AVSLConfig.PRICE_DECLINE_THRESHOLD
        if recent_days is None:
            recent_days = AVSLConfig.RECENT_DAYS

        result = {}
        for symbol in self.symbols:
            try:
                if (
                    symbol not in self.stock_data["Volume"]
                    or symbol not in self.stock_data["Close"]
                    or self.stock_data["Volume"][symbol].empty
                    or self.stock_data["Close"][symbol].empty
                    or len(self.stock_data["Volume"][symbol]) < period_days
                    or len(self.stock_data["Close"][symbol]) < period_days
                ):
                    result[symbol] = False
                    continue

                # Calculate average volume over the period
                volume_data = self.stock_data["Volume"][symbol]
                price_data = self.stock_data["Close"][symbol]

                if len(volume_data) < period_days or len(price_data) < period_days:
                    result[symbol] = False
                    continue

                # Calculate average volume for the period
                avg_volume = volume_data.tail(period_days).mean()

                if avg_volume <= 0:
                    result[symbol] = False
                    continue

                # Check recent days
                if len(volume_data) < recent_days or len(price_data) < recent_days:
                    result[symbol] = False
                    continue

                recent_volume = volume_data.tail(recent_days)
                recent_price = price_data.tail(recent_days)

                # Check if recent volume is significantly below average
                recent_avg_volume = recent_volume.mean()
                volume_ratio = recent_avg_volume / avg_volume if avg_volume > 0 else 1.0

                # Check if price is declining
                current_price = recent_price.iloc[-1]
                past_price = recent_price.iloc[0] if len(recent_price) > 1 else current_price
                price_change = (current_price - past_price) / past_price if past_price > 0 else 0.0

                # AVSL sell signal: volume below threshold AND price declining
                # Volume support level is broken when volume drops significantly
                is_volume_below_support = volume_ratio < volume_decline_threshold
                is_price_declining = price_change < -price_decline_threshold

                # Additional check: most recent volume is below average
                latest_volume = volume_data.iloc[-1]
                is_latest_volume_low = latest_volume < avg_volume * (1 - volume_decline_threshold)

                result[symbol] = bool(is_volume_below_support and (is_price_declining or is_latest_volume_low))

                logger.debug(
                    "%s: AVSL signal evaluation\n"
                    "  Average volume: %.2f\n"
                    "  Recent average volume: %.2f (ratio: %.2f)\n"
                    "  Latest volume: %.2f\n"
                    "  Price change: %.2f%%\n"
                    "  Volume decline: %s\n"
                    "  Price decline: %s\n"
                    "  Latest volume low: %s\n"
                    "  AVSL sell signal: %s",
                    symbol,
                    avg_volume,
                    recent_avg_volume,
                    volume_ratio,
                    latest_volume,
                    price_change * 100,
                    is_volume_below_support,
                    is_price_declining,
                    is_latest_volume_low,
                    result[symbol],
                )

            except (IndexError, KeyError, AttributeError, ZeroDivisionError) as e:
                result[symbol] = False
                logger.debug("Error checking AVSL signal (%s): %s", symbol, str(e))

        return result
