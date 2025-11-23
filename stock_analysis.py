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

import numpy as np
import pandas as pd
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

    def _get_symbol_df(self, symbol: str) -> pd.DataFrame | None:
        """
        Get a DataFrame for a specific symbol with High, Low, Close columns.

        Args:
            symbol (str): Stock symbol to get data for

        Returns:
            pd.DataFrame | None: DataFrame with High, Low, Close columns, or None if data is invalid
        """
        try:
            if not self._is_symbol_data_valid(symbol):
                return None

            df = pd.DataFrame(
                {
                    "High": self.stock_data["High"][symbol],
                    "Low": self.stock_data["Low"][symbol],
                    "Close": self.stock_data["Close"][symbol],
                }
            )
            return df
        except (IndexError, KeyError, AttributeError) as e:
            logger.debug("Error getting symbol DataFrame for %s: %s", symbol, str(e))
            return None

    def get_atr(self, symbol: str, period: int | None = None) -> float:
        """
        주어진 심볼에 대해 ATR(평균 진폭 범위)을 계산해 반환한다.

        - period 기간 동안의 ATR을 구하고, 가장 최신 ATR 값을 반환.
        - 데이터가 부족하거나 계산이 불가능하면 0.0을 반환한다.

        Args:
            symbol (str): Stock symbol to calculate ATR for
            period (int | None): ATR calculation period (None = use config default)

        Returns:
            float: Latest ATR value, or 0.0 if calculation fails
        """
        if period is None:
            period = StrategyConfig.TRAILING_ATR_PERIOD

        df = self._get_symbol_df(symbol)
        if df is None or len(df) < period + 1:
            logger.debug(
                "%s: ATR 계산 불가 - 데이터 부족 (필요: %d일, 실제: %d일)",
                symbol,
                period + 1,
                len(df) if df is not None else 0,
            )
            return 0.0

        try:
            high = df["High"]
            low = df["Low"]
            close = df["Close"]

            # True Range 계산
            prev_close = close.shift(1)
            tr1 = high - low
            tr2 = (high - prev_close).abs()
            tr3 = (low - prev_close).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

            # ATR = TR의 period 이동 평균 (단순 평균)
            atr = tr.rolling(window=period, min_periods=period).mean()

            latest_atr = atr.iloc[-1]
            if pd.isna(latest_atr):
                logger.debug("%s: ATR 계산 결과 NaN", symbol)
                return 0.0

            atr_value = float(latest_atr)
            logger.debug("%s: ATR 계산 완료 - period=%d, ATR=%.4f", symbol, period, atr_value)
            return atr_value

        except (IndexError, KeyError, AttributeError, ValueError) as e:
            logger.debug("Error calculating ATR for %s: %s", symbol, str(e))
            return 0.0

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

    def calculate_vpci_components(
        self, symbol: str, fast_period: int | None = None, slow_period: int | None = None
    ) -> pd.DataFrame | None:
        """
        Calculate VPC, VPR, VM, and VPCI components for Buff Dormeier AVSL.

        VPC (Volume Price Component): Difference between price-based average and volume-weighted average
        VPR (Volume Price Ratio): Ratio of fast to slow price moving averages
        VM (Volume Multiplier): Ratio of fast to slow volume moving averages
        VPCI: VPC × VPR × VM (combined volume-price relationship indicator)

        Args:
            symbol (str): Stock symbol to analyze
            fast_period (int | None): Fast moving average period (None = use config default)
            slow_period (int | None): Slow moving average period (None = use config default)

        Returns:
            pd.DataFrame | None: DataFrame with columns ['VPC', 'VPR', 'VM', 'VPCI'], or None if insufficient data
        """
        if fast_period is None:
            fast_period = AVSLConfig.FAST_PERIOD
        if slow_period is None:
            slow_period = AVSLConfig.SLOW_PERIOD

        try:
            if (
                symbol not in self.stock_data["Close"]
                or symbol not in self.stock_data["Volume"]
                or symbol not in self.stock_data["Low"]
                or self.stock_data["Close"][symbol].empty
                or len(self.stock_data["Close"][symbol]) < slow_period
            ):
                return None

            close = self.stock_data["Close"][symbol]
            volume = self.stock_data["Volume"][symbol]
            low = self.stock_data["Low"][symbol]

            # Calculate moving averages
            fast_ma_price = close.rolling(window=fast_period).mean()
            slow_ma_price = close.rolling(window=slow_period).mean()
            fast_ma_volume = volume.rolling(window=fast_period).mean()
            slow_ma_volume = volume.rolling(window=slow_period).mean()

            # VWAP (Volume Weighted Average Price) approximation
            # Using a rolling window for VWAP calculation
            typical_price = (self.stock_data["High"][symbol] + low + close) / 3
            vwap = (typical_price * volume).rolling(window=slow_period).sum() / volume.rolling(window=slow_period).sum()

            # VPC: Difference between close price and VWAP (normalized)
            # Normalize by dividing by close price to make it comparable across stocks
            vpc = (close - vwap) / close

            # VPR: Fast MA / Slow MA ratio (price)
            vpr = fast_ma_price / slow_ma_price

            # VM: Fast MA / Slow MA ratio (volume)
            # Avoid division by zero
            vm = fast_ma_volume / slow_ma_volume.replace(0, np.nan)

            # VPCI: Combined indicator
            # Using absolute value of VPC to ensure positive values, then multiply by ratios
            vpci = np.abs(vpc) * vpr * vm

            # Create DataFrame
            result = pd.DataFrame(
                {
                    "VPC": vpc,
                    "VPR": vpr,
                    "VM": vm,
                    "VPCI": vpci,
                },
                index=close.index,
            )

            return result

        except (IndexError, KeyError, AttributeError, ZeroDivisionError) as e:
            logger.debug("Error calculating VPCI components for %s: %s", symbol, str(e))
            return None

    def calculate_avsl_series(
        self,
        symbol: str,
        bars: int | None = None,
        stddev_mult: float | None = None,
        fast_period: int | None = None,
        slow_period: int | None = None,
    ) -> pd.Series | None:
        """
        Calculate Buff Dormeier AVSL (Anti-Volume Stop Loss) series.

        AVSL is a dynamic trailing stop based on:
        1. VPCI (Volume Price Component Indicator) to determine adaptive length
        2. Price component (low price adjusted by VPC/VPR)
        3. Bollinger Band lower band using standard deviation

        Args:
            symbol (str): Stock symbol to analyze
            bars (int | None): Base period for calculation (None = use config default)
            stddev_mult (float | None): Standard deviation multiplier for Bollinger Band (None = use config default)
            fast_period (int | None): Fast moving average period for VPCI (None = use config default)
            slow_period (int | None): Slow moving average period for VPCI (None = use config default)

        Returns:
            pd.Series | None: Series of AVSL stop loss prices, or None if insufficient data
        """
        if bars is None:
            bars = AVSLConfig.BARS
        if stddev_mult is None:
            stddev_mult = AVSLConfig.STDDEV_MULT
        if fast_period is None:
            fast_period = AVSLConfig.FAST_PERIOD
        if slow_period is None:
            slow_period = AVSLConfig.SLOW_PERIOD

        try:
            # Calculate VPCI components
            vpci_df = self.calculate_vpci_components(symbol, fast_period, slow_period)
            if vpci_df is None:
                return None

            if symbol not in self.stock_data["Low"] or self.stock_data["Low"][symbol].empty or len(vpci_df) < bars:
                return None

            low = self.stock_data["Low"][symbol]
            vpci = vpci_df["VPCI"]
            vpc = vpci_df["VPC"]

            # Calculate adaptive length: Length = 3 + VPCI (rounded, clamped)
            # VPCI is typically normalized, so we scale it appropriately
            # Using the latest VPCI value to determine length
            # For each bar, we use a rolling window based on the VPCI at that point
            length_base = AVSLConfig.MIN_LENGTH
            length_max = AVSLConfig.MAX_LENGTH

            # Price component: Low price adjusted by VPC and VPR
            # Adjustment factor based on VPC and VPR
            adjustment = 1.0 + (vpc * 0.1)  # Scale VPC adjustment
            price_component = low * adjustment

            # Calculate AVSL using adaptive length
            # For simplicity, use a rolling window based on average VPCI over the period
            avg_vpci = vpci.rolling(window=bars).mean()
            # Convert VPCI to length (scaled appropriately)
            # VPCI values are typically small, so we scale them
            dynamic_length = (length_base + avg_vpci * 10).clip(lower=length_base, upper=length_max).round().astype(int)

            # Calculate moving average of price component with adaptive length
            # Use a simplified approach: use the most recent dynamic_length value
            recent_length = int(dynamic_length.iloc[-1]) if not dynamic_length.empty else length_base
            recent_length = max(length_base, min(recent_length, length_max))

            # Price component moving average
            price_component_ma = price_component.rolling(window=recent_length).mean()

            # Calculate standard deviation of price component
            price_component_std = price_component.rolling(window=recent_length).std()

            # AVSL = Price Component MA - (StdDev × Multiplier)
            # This creates the lower Bollinger Band
            avsl = price_component_ma - (price_component_std * stddev_mult)

            # Fill NaN values with forward fill (use previous valid AVSL)
            avsl = avsl.ffill()

            return avsl

        except (IndexError, KeyError, AttributeError, ZeroDivisionError, ValueError) as e:
            logger.debug("Error calculating AVSL series for %s: %s", symbol, str(e))
            return None

    def get_latest_avsl(self, symbol: str) -> float | None:
        """
        Get the most recent AVSL (Anti-Volume Stop Loss) value for a symbol.

        Args:
            symbol (str): Stock symbol to analyze

        Returns:
            float | None: Latest AVSL stop loss price, or None if calculation fails
        """
        try:
            avsl_series = self.calculate_avsl_series(symbol)
            if avsl_series is None or avsl_series.empty:
                return None

            # Get the last valid value
            latest_avsl = avsl_series.dropna().iloc[-1] if not avsl_series.dropna().empty else None

            if latest_avsl is None or np.isnan(latest_avsl) or latest_avsl <= 0:
                return None

            return float(latest_avsl)

        except (IndexError, KeyError, AttributeError, ValueError) as e:
            logger.debug("Error getting latest AVSL for %s: %s", symbol, str(e))
            return None

    def check_avsl_sell_signal(
        self,
        period_days: int | None = None,
        volume_decline_threshold: float | None = None,
        price_decline_threshold: float | None = None,
        recent_days: int | None = None,
        use_buff_avsl: bool = True,
    ) -> Dict[str, bool]:
        """
        Check for AVSL (Anti-Volume Stop Loss) sell signals based on Buff Dormeier's method.

        When use_buff_avsl=True (default):
        - Uses Buff Dormeier AVSL calculation (VPCI + Bollinger Band based dynamic stop)
        - Sell signal occurs when current price (close or low) falls below the AVSL line
        - This indicates support level break and potential trend reversal

        When use_buff_avsl=False (legacy mode):
        - Uses simple volume/price decline threshold method
        - Kept for backward compatibility

        Args:
            period_days (int | None): Legacy parameter - not used in Buff AVSL mode
            volume_decline_threshold (float | None): Legacy parameter - not used in Buff AVSL mode
            price_decline_threshold (float | None): Legacy parameter - not used in Buff AVSL mode
            recent_days (int | None): Legacy parameter - not used in Buff AVSL mode
            use_buff_avsl (bool): If True, use Buff Dormeier AVSL method (default: True)

        Returns:
            Dict[str, bool]: True if AVSL sell signal is detected (current price < AVSL stop loss)
        """
        result = {}

        if not use_buff_avsl:
            # Legacy mode: simple volume/price decline method
            if period_days is None:
                period_days = AVSLConfig.PERIOD_DAYS
            if volume_decline_threshold is None:
                volume_decline_threshold = AVSLConfig.VOLUME_DECLINE_THRESHOLD
            if price_decline_threshold is None:
                price_decline_threshold = AVSLConfig.PRICE_DECLINE_THRESHOLD
            if recent_days is None:
                recent_days = AVSLConfig.RECENT_DAYS

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

                    volume_data = self.stock_data["Volume"][symbol]
                    price_data = self.stock_data["Close"][symbol]

                    if len(volume_data) < period_days or len(price_data) < period_days:
                        result[symbol] = False
                        continue

                    avg_volume = volume_data.tail(period_days).mean()

                    if avg_volume <= 0:
                        result[symbol] = False
                        continue

                    if len(volume_data) < recent_days or len(price_data) < recent_days:
                        result[symbol] = False
                        continue

                    recent_volume = volume_data.tail(recent_days)
                    recent_price = price_data.tail(recent_days)

                    recent_avg_volume = recent_volume.mean()
                    volume_ratio = recent_avg_volume / avg_volume if avg_volume > 0 else 1.0

                    current_price = recent_price.iloc[-1]
                    past_price = recent_price.iloc[0] if len(recent_price) > 1 else current_price
                    price_change = (current_price - past_price) / past_price if past_price > 0 else 0.0

                    is_volume_below_support = volume_ratio < volume_decline_threshold
                    is_price_declining = price_change < -price_decline_threshold

                    latest_volume = volume_data.iloc[-1]
                    is_latest_volume_low = latest_volume < avg_volume * (1 - volume_decline_threshold)

                    result[symbol] = bool(is_volume_below_support and (is_price_declining or is_latest_volume_low))

                except (IndexError, KeyError, AttributeError, ZeroDivisionError) as e:
                    result[symbol] = False
                    logger.debug("Error checking AVSL signal (legacy mode) for %s: %s", symbol, str(e))

            return result

        # Buff Dormeier AVSL mode (default)
        for symbol in self.symbols:
            try:
                # Get latest AVSL stop loss level
                latest_avsl = self.get_latest_avsl(symbol)

                if latest_avsl is None:
                    result[symbol] = False
                    logger.debug("%s: AVSL calculation failed or insufficient data", symbol)
                    continue

                # Get current price (use close price, or low if available)
                if symbol not in self.stock_data["Close"] or self.stock_data["Close"][symbol].empty:
                    result[symbol] = False
                    continue

                current_price = self.stock_data["Close"][symbol].iloc[-1]

                # Alternative: use low price for more sensitive detection
                # current_price = (
                #     self.stock_data["Low"][symbol].iloc[-1]
                #     if symbol in self.stock_data["Low"]
                #     else current_price
                # )

                # AVSL sell signal: current price falls below AVSL stop loss
                is_stop_hit = current_price < latest_avsl

                result[symbol] = bool(is_stop_hit)

                logger.debug(
                    "%s: Buff AVSL signal evaluation\n"
                    "  Current price: %.2f\n"
                    "  AVSL stop loss: %.2f\n"
                    "  Price below AVSL: %s\n"
                    "  AVSL sell signal: %s",
                    symbol,
                    current_price,
                    latest_avsl,
                    is_stop_hit,
                    result[symbol],
                )

            except (IndexError, KeyError, AttributeError, ValueError) as e:
                result[symbol] = False
                logger.debug("Error checking Buff AVSL signal for %s: %s", symbol, str(e))

        return result
