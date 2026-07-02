"""
stock_analysis.py

This module provides functionality for analyzing US stock market data using technical indicators.
It includes methods for calculating moving averages, price-volume correlations, trend analysis,
and AVSL (Average Volume Support Level) sell signal detection to identify potential
trading opportunities.

Dependencies:
    - yfinance: Yahoo Finance API client for fetching stock data
    - pandas: Data manipulation and analysis
    - typing: Type hints for better code documentation

Main Classes:
    - UsaStockFinder: Analyzes stock data using various technical indicators
"""

import logging
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import yfinance as yf

from config import AVSLConfig, DataQualityConfig, StrategyConfig
from original_avsl import calculate_original_avsl

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

    def get_special_situation_price_pinned_metrics(
        self,
        symbol: str,
        lookback_days: int = 30,
        post_window_days: int = 10,
        min_gap_up_pct: float = 0.15,
        max_recent_range_pct: float = 0.015,
        max_recent_abs_return_pct: float = 0.02,
        max_atr_pct: float = 0.015,
    ) -> dict[str, float | bool]:
        """Compute conservative pinned-price special-situation metrics from OHLC data."""
        defaults: dict[str, float | bool] = {
            "is_special_situation": False,
            "max_gap_up_pct": 0.0,
            "recent_range_pct": 0.0,
            "recent_abs_return_pct": 0.0,
            "atr_pct": 0.0,
            "plateau_deviation_pct": 0.0,
        }
        df = self._get_symbol_df(symbol)
        if df is None or len(df) < max(lookback_days + 1, post_window_days + 1, StrategyConfig.TRAILING_ATR_PERIOD + 1):
            return defaults

        close = df["Close"].dropna()
        if len(close) < max(lookback_days + 1, post_window_days + 1):
            return defaults

        recent_close = close.iloc[-post_window_days:]
        current_close = float(close.iloc[-1])
        if current_close <= 0:
            return defaults

        lookback_close = close.iloc[-(lookback_days + 1) :]
        close_to_close_returns = lookback_close.pct_change().dropna()
        if close_to_close_returns.empty:
            return defaults

        max_gap_up_pct = float(close_to_close_returns.max())
        recent_range_pct = float((recent_close.max() - recent_close.min()) / current_close)
        recent_abs_return_pct = float(abs((recent_close.iloc[-1] - recent_close.iloc[0]) / recent_close.iloc[0]))
        plateau_price = float(recent_close.mean())
        plateau_deviation_pct = float(abs(current_close - plateau_price) / plateau_price) if plateau_price > 0 else 0.0
        atr = self.get_atr(symbol, period=14)
        if atr is None or not np.isfinite(atr) or atr <= 0.0:
            return {
                "is_special_situation": False,
                "max_gap_up_pct": max_gap_up_pct,
                "recent_range_pct": recent_range_pct,
                "recent_abs_return_pct": recent_abs_return_pct,
                "atr_pct": 0.0,
                "plateau_deviation_pct": plateau_deviation_pct,
            }
        atr_pct = float(atr / current_close) if current_close > 0 else 0.0

        is_special_situation = bool(
            max_gap_up_pct >= min_gap_up_pct
            and recent_range_pct <= max_recent_range_pct
            and recent_abs_return_pct <= max_recent_abs_return_pct
            and atr_pct <= max_atr_pct
            and plateau_deviation_pct <= max_recent_range_pct
        )
        return {
            "is_special_situation": is_special_situation,
            "max_gap_up_pct": max_gap_up_pct,
            "recent_range_pct": recent_range_pct,
            "recent_abs_return_pct": recent_abs_return_pct,
            "atr_pct": atr_pct,
            "plateau_deviation_pct": plateau_deviation_pct,
        }

    def get_event_quarantine_metrics(
        self,
        symbol: str,
        lookback_days: int = 5,
        min_gap_up_pct: float = 0.15,
        max_current_vs_gap_close_pct: float = 0.05,
        max_drawdown_from_post_gap_high_pct: float = 0.07,
    ) -> dict[str, float | bool]:
        """Compute conservative event-quarantine metrics using only recent OHLC close data."""
        defaults: dict[str, float | bool] = {
            "is_event_quarantine": False,
            "max_gap_up_pct": 0.0,
            "days_since_gap": float(lookback_days + 1),
            "current_vs_gap_close_pct": 0.0,
            "drawdown_from_post_gap_high_pct": 1.0,
        }
        df = self._get_symbol_df(symbol)
        if df is None:
            return defaults

        close = df["Close"].dropna()
        if len(close) < lookback_days + 1:
            return defaults

        lookback_close = close.iloc[-(lookback_days + 1) :]
        returns = lookback_close.pct_change().dropna()
        if returns.empty:
            return defaults

        max_gap_up_pct = float(returns.max())
        if max_gap_up_pct < min_gap_up_pct:
            defaults["max_gap_up_pct"] = max_gap_up_pct
            return defaults

        event_return_pos = int(np.argmax(returns.to_numpy()))
        # pct_change result aligns to lookback_close positions starting at index 1
        gap_close_pos = event_return_pos + 1
        gap_close = float(lookback_close.iloc[gap_close_pos])
        post_gap_close = lookback_close.iloc[gap_close_pos:]
        if post_gap_close.empty or gap_close <= 0:
            defaults["max_gap_up_pct"] = max_gap_up_pct
            return defaults

        current_close = float(close.iloc[-1])
        post_gap_high = float(post_gap_close.max())
        days_since_gap = int(len(lookback_close) - 1 - gap_close_pos)
        current_vs_gap_close_pct = float(abs(current_close - gap_close) / gap_close)
        drawdown_from_post_gap_high_pct = (
            float((post_gap_high - current_close) / post_gap_high) if post_gap_high > 0 else 1.0
        )

        is_event_quarantine = bool(
            days_since_gap <= lookback_days
            and current_vs_gap_close_pct <= max_current_vs_gap_close_pct
            and drawdown_from_post_gap_high_pct <= max_drawdown_from_post_gap_high_pct
        )

        return {
            "is_event_quarantine": is_event_quarantine,
            "max_gap_up_pct": max_gap_up_pct,
            "days_since_gap": float(days_since_gap),
            "current_vs_gap_close_pct": current_vs_gap_close_pct,
            "drawdown_from_post_gap_high_pct": drawdown_from_post_gap_high_pct,
        }

    def is_event_quarantine(
        self,
        symbol: str,
        lookback_days: int = 5,
        min_gap_up_pct: float = 0.15,
        max_current_vs_gap_close_pct: float = 0.05,
        max_drawdown_from_post_gap_high_pct: float = 0.07,
    ) -> bool:
        """Return event-quarantine eligibility for fresh post-gap new buy suppression."""
        metrics = self.get_event_quarantine_metrics(
            symbol,
            lookback_days=lookback_days,
            min_gap_up_pct=min_gap_up_pct,
            max_current_vs_gap_close_pct=max_current_vs_gap_close_pct,
            max_drawdown_from_post_gap_high_pct=max_drawdown_from_post_gap_high_pct,
        )
        return bool(metrics["is_event_quarantine"])

    def is_special_situation_price_pinned(
        self,
        symbol: str,
        lookback_days: int = 30,
        post_window_days: int = 10,
        min_gap_up_pct: float = 0.15,
        max_recent_range_pct: float = 0.015,
        max_recent_abs_return_pct: float = 0.02,
        max_atr_pct: float = 0.015,
    ) -> bool:
        """Return True when OHLC behavior looks like a pinned merger-arb/take-private profile."""
        metrics = self.get_special_situation_price_pinned_metrics(
            symbol=symbol,
            lookback_days=lookback_days,
            post_window_days=post_window_days,
            min_gap_up_pct=min_gap_up_pct,
            max_recent_range_pct=max_recent_range_pct,
            max_recent_abs_return_pct=max_recent_abs_return_pct,
            max_atr_pct=max_atr_pct,
        )
        return bool(metrics["is_special_situation"])

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
        diagnostics = self.get_trend_template_diagnostics(margin)
        return {symbol: bool(data["final_result"]) for symbol, data in diagnostics.items()}

    def get_trend_template_diagnostics(self, margin: float) -> Dict[str, Dict[str, Any]]:
        """Evaluate trend-template conditions and return per-symbol diagnostics."""
        is_above_75_percent_of_high = self.is_above_75_percent_of_52_week_high(margin)
        is_above_low = self.is_above_52_week_low(margin)
        latest_50_ma = self.get_moving_averages(StrategyConfig.MA_50_DAYS)
        latest_150_ma = self.get_moving_averages(StrategyConfig.MA_150_DAYS)
        latest_200_ma = self.get_moving_averages(StrategyConfig.MA_200_DAYS)
        current_price = self.current_price
        is_ma_increasing = self.is_200_ma_increasing_recently(margin)
        is_increasing_with_volume_and_price = self.compare_volume_price_movement(StrategyConfig.MA_200_DAYS, margin)

        diagnostics: Dict[str, Dict[str, Any]] = {}
        for symbol in self.symbols:
            has_sufficient_ma_data = not (
                latest_50_ma[symbol] == 0.0 or latest_150_ma[symbol] == 0.0 or latest_200_ma[symbol] == 0.0
            )

            conditions = {
                "price_above_ma150": has_sufficient_ma_data
                and current_price[symbol] >= latest_150_ma[symbol] * (1 - margin),
                "price_above_ma200": has_sufficient_ma_data
                and current_price[symbol] >= latest_200_ma[symbol] * (1 - margin),
                "ma150_above_ma200": has_sufficient_ma_data
                and latest_150_ma[symbol] >= latest_200_ma[symbol] * (1 - margin),
                "ma200_increasing": has_sufficient_ma_data and is_ma_increasing[symbol],
                "ma50_above_ma150": has_sufficient_ma_data
                and latest_50_ma[symbol] >= latest_150_ma[symbol] * (1 - margin),
                "ma50_above_ma200": has_sufficient_ma_data
                and latest_50_ma[symbol] >= latest_200_ma[symbol] * (1 - margin),
                "price_above_ma50": (
                    has_sufficient_ma_data and current_price[symbol] >= latest_50_ma[symbol] * (1 - margin)
                ),
                "above_52_week_low_threshold": is_above_low[symbol],
                "above_52_week_high_threshold": is_above_75_percent_of_high[symbol],
                "positive_volume_price_correlation": is_increasing_with_volume_and_price[symbol],
            }

            failed_conditions = [name for name, passed in conditions.items() if not passed]
            if not has_sufficient_ma_data:
                failed_conditions.insert(0, "has_sufficient_ma_data")
                logger.debug(
                    "%s: Cannot evaluate trend template due to insufficient data "
                    "(MA50: %.2f, MA150: %.2f, MA200: %.2f)",
                    symbol,
                    latest_50_ma[symbol],
                    latest_150_ma[symbol],
                    latest_200_ma[symbol],
                )

            final_result = has_sufficient_ma_data and all(conditions.values())
            diagnostics[symbol] = {
                "final_result": final_result,
                "has_sufficient_ma_data": has_sufficient_ma_data,
                "conditions": conditions,
                "failed_conditions": failed_conditions,
            }

        return diagnostics

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

    def calculate_original_avsl_report(self, symbol: str) -> pd.DataFrame | None:
        """Return original Buff Dormeier AVSL diagnostics for live sell decisions.

        This helper uses already-loaded ``self.stock_data`` only and does not call
        network APIs. Its latest valid ``original_avsl`` value is the live AVSL
        sell implementation used by ``check_avsl_sell_signal()``.
        """
        if not AVSLConfig.ENABLED:
            return None

        try:
            if any(
                symbol not in self.stock_data[column] or self.stock_data[column][symbol].empty
                for column in ("High", "Low", "Close", "Volume")
            ):
                return None

            ohlcv = pd.DataFrame(
                {
                    "High": self.stock_data["High"][symbol],
                    "Low": self.stock_data["Low"][symbol],
                    "Close": self.stock_data["Close"][symbol],
                    "Volume": self.stock_data["Volume"][symbol],
                }
            )
            return calculate_original_avsl(ohlcv)

        except (IndexError, KeyError, AttributeError, ValueError) as e:
            logger.debug("Error calculating AVSL report for %s: %s", symbol, str(e))
            return None

    def get_latest_avsl(self, symbol: str) -> float | None:
        """Return the latest positive finite live original AVSL value for a symbol."""
        try:
            report = self.calculate_original_avsl_report(symbol)
            if report is None or report.empty or "original_avsl" not in report:
                return None

            latest_value = report["original_avsl"].iloc[-1]
            latest_avsl = float(latest_value)
            if not np.isfinite(latest_avsl) or latest_avsl <= 0:
                return None

            return latest_avsl

        except (IndexError, KeyError, AttributeError, TypeError, ValueError) as e:
            logger.debug("Error getting latest AVSL for %s: %s", symbol, str(e))
            return None

    def check_avsl_sell_signal(self) -> Dict[str, bool]:
        """Check for live AVSL sell signals.

        Sell signals are based solely on the live original AVSL calculation:
        ``latest_close < latest_avsl``. Symbols with insufficient or invalid data
        return ``False``.
        """
        result: Dict[str, bool] = {}
        logger.info("AVSL signal evaluation uses original AVSL")

        for symbol in self.symbols:
            try:
                latest_avsl = self.get_latest_avsl(symbol)
                if latest_avsl is None:
                    result[symbol] = False
                    logger.debug("%s: AVSL calculation failed or insufficient data", symbol)
                    continue

                if symbol not in self.stock_data["Close"] or self.stock_data["Close"][symbol].empty:
                    result[symbol] = False
                    logger.debug("%s: AVSL signal skipped because close data is unavailable", symbol)
                    continue

                current_close = float(self.stock_data["Close"][symbol].iloc[-1])
                if not np.isfinite(current_close):
                    result[symbol] = False
                    logger.debug("%s: AVSL signal skipped because latest close is non-finite", symbol)
                    continue

                is_stop_hit = current_close < latest_avsl
                result[symbol] = bool(is_stop_hit)

                logger.debug(
                    "%s: AVSL signal evaluation - close=%.2f, avsl=%.2f, sell=%s",
                    symbol,
                    current_close,
                    latest_avsl,
                    result[symbol],
                )

            except (IndexError, KeyError, AttributeError, TypeError, ValueError) as e:
                result[symbol] = False
                logger.debug("Error checking AVSL signal for %s: %s", symbol, str(e))

        return result
