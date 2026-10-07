"""
test function to test UsaStockFinder class
"""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from stock_analysis import UsaStockFinder


def _deterministic_ohlcv(periods: int = 100, symbol: str = "TEST") -> pd.DataFrame:
    """Build stable positive OHLCV data with enough history for AVSL tests."""
    index = pd.date_range(start="2024-01-01", periods=periods, freq="D")
    trend = np.linspace(25.0, 35.0, periods)
    wave = np.sin(np.linspace(0.0, 8.0, periods)) * 0.5
    close = trend + wave
    high = close + 1.0
    low = close - 1.0
    volume = (
        np.linspace(1000.0, 1800.0, periods)
        + np.cos(np.linspace(0.0, 6.0, periods)) * 50.0
    )
    data = pd.DataFrame(
        {
            ("High", symbol): high,
            ("Low", symbol): low,
            ("Close", symbol): close,
            ("Volume", symbol): volume,
        },
        index=index,
    )
    data.columns = pd.MultiIndex.from_tuples(data.columns)
    return data


class TestUsaStockFinder(unittest.TestCase):
    """Test UsaStockFinder class"""

    def setUp(self):
        """Set up test fixtures, if any."""
        # Mock download inside the setUp using a context manager
        with patch("yfinance.download") as mock_download:
            # Simulate 250 days of data
            periods = 250
            index = pd.date_range(start="2023-01-01", periods=periods, freq="D")

            # Generate more data for testing moving averages
            mock_data = pd.DataFrame(
                {
                    ("High", "AAPL"): np.random.random(periods) * 100 + 150,
                    ("Low", "AAPL"): np.random.random(periods) * 100 + 145,
                    ("Close", "AAPL"): np.random.random(periods) * 100 + 148,
                    ("Volume", "AAPL"): np.random.randint(1000, 2000, periods),
                    ("High", "MSFT"): np.random.random(periods) * 100 + 300,
                    ("Low", "MSFT"): np.random.random(periods) * 100 + 290,
                    ("Close", "MSFT"): np.random.random(periods) * 100 + 295,
                    ("Volume", "MSFT"): np.random.randint(1500, 2500, periods),
                },
                index=index,
            )

            # Set MultiIndex to mock returned DataFrame
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            self.symbols = ["AAPL", "MSFT"]
            self.finder = UsaStockFinder(self.symbols)

    def test_is_data_valid(self):
        """check is_data_valid function"""
        self.assertTrue(self.finder.is_data_valid())

    def test_is_above_75_percent_of_52_week_high(self):
        """check is_above_75_percent_of_52_week_high function"""
        result = self.finder.is_above_75_percent_of_52_week_high(margin=0.01)
        self.assertIsInstance(result, dict)
        # Add specific assertions once data is stable.

    def test_is_above_52_week_low(self):
        """check is_above_52_week_low function"""
        result = self.finder.is_above_52_week_low(margin=0.01)
        self.assertIsInstance(result, dict)
        # Add specific assertions once data is stable.

    def test_get_moving_averages(self):
        """check get_moving_averages function"""
        ma = self.finder.get_moving_averages(2)
        self.assertIsInstance(ma, dict)
        for symbol in self.symbols:
            self.assertIn(symbol, ma)

    def test_get_moving_averages_deterministic_series(self):
        """moving average should be deterministic for explicit close prices"""
        with patch("yfinance.download") as mock_download:
            index = pd.date_range(start="2024-01-01", periods=5, freq="D")
            close_prices = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
            mock_data = pd.DataFrame(
                {
                    ("High", "TEST"): close_prices + 1.0,
                    ("Low", "TEST"): close_prices - 1.0,
                    ("Close", "TEST"): close_prices,
                    ("Volume", "TEST"): np.full(5, 1000),
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["TEST"])
            ma_3 = finder.get_moving_averages(3)

            # Last 3 closes are 30, 40, 50 -> MA = 40
            self.assertEqual(ma_3["TEST"], 40.0)

    def test_is_200_ma_increasing_recently(self):
        """check is_200_ma_increasing_recently function"""
        result = self.finder.is_200_ma_increasing_recently(margin=0.01)
        self.assertIsInstance(result, dict)

    def test_has_valid_trend_template(self):
        """check has_valid_trend_template function"""
        result = self.finder.has_valid_trend_template(margin=0.01)
        self.assertIsInstance(result, dict)

    def test_has_valid_trend_template_true_for_clear_uptrend(self):
        """trend template should pass for a long, steady uptrend with rising volume"""
        with patch("yfinance.download") as mock_download:
            periods = 250
            index = pd.date_range(start="2024-01-01", periods=periods, freq="D")
            close = np.linspace(100.0, 200.0, periods)
            volume = np.linspace(1000.0, 5000.0, periods)

            mock_data = pd.DataFrame(
                {
                    ("High", "TREND"): close * 1.01,
                    ("Low", "TREND"): close * 0.99,
                    ("Close", "TREND"): close,
                    ("Volume", "TREND"): volume,
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["TREND"])
            result = finder.has_valid_trend_template(margin=0.0)

            self.assertEqual(result, {"TREND": True})

    def test_has_valid_trend_template_false_with_insufficient_history(self):
        """trend template should fail when there is not enough data for MA200"""
        with patch("yfinance.download") as mock_download:
            periods = 199
            index = pd.date_range(start="2024-01-01", periods=periods, freq="D")
            close = np.linspace(100.0, 120.0, periods)

            mock_data = pd.DataFrame(
                {
                    ("High", "SHORT"): close * 1.01,
                    ("Low", "SHORT"): close * 0.99,
                    ("Close", "SHORT"): close,
                    ("Volume", "SHORT"): np.full(periods, 1500.0),
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["SHORT"])
            result = finder.has_valid_trend_template(margin=0.0)

            self.assertEqual(result, {"SHORT": False})

    def test_get_trend_template_diagnostics_exposes_failed_conditions(self):
        """diagnostics should expose per-condition booleans and failed condition names."""
        with patch("yfinance.download") as mock_download:
            periods = 250
            index = pd.date_range(start="2024-01-01", periods=periods, freq="D")
            close = np.linspace(100.0, 200.0, periods)
            volume = np.linspace(1000.0, 5000.0, periods)

            mock_data = pd.DataFrame(
                {
                    ("High", "TREND"): close * 1.01,
                    ("Low", "TREND"): close * 0.99,
                    ("Close", "TREND"): close,
                    ("Volume", "TREND"): volume,
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["TREND"])
            with patch.object(finder, "compare_volume_price_movement", return_value={"TREND": False}):
                diagnostics = finder.get_trend_template_diagnostics(margin=0.0)

            self.assertIn("TREND", diagnostics)
            self.assertFalse(diagnostics["TREND"]["final_result"])
            self.assertFalse(diagnostics["TREND"]["conditions"]["positive_volume_price_correlation"])
            self.assertIn("positive_volume_price_correlation", diagnostics["TREND"]["failed_conditions"])

    def test_price_volume_correlation_percent(self):
        """check price_volume_correlation_percent function"""
        correlation = self.finder.price_volume_correlation_percent(recent_days=10)
        self.assertIsInstance(correlation, dict)

    def test_compare_volume_price_movement(self):
        """check compare_volume_price_movement function"""
        result = self.finder.compare_volume_price_movement(recent_days=10, margin=0.01)
        self.assertIsInstance(result, dict)

    def test_check_avsl_sell_signal(self):
        """check check_avsl_sell_signal function"""
        result = self.finder.check_avsl_sell_signal()
        self.assertIsInstance(result, dict)
        for symbol in self.symbols:
            self.assertIn(symbol, result)
            # Result should be boolean (numpy bool is also acceptable)
            self.assertIsInstance(result[symbol], (bool, type(True)))

    def test_get_latest_avsl_returns_latest_row_when_positive_finite(self):
        """live AVSL helper should return the actual latest row value."""
        report = pd.DataFrame({"original_avsl": [90.0, 95.0, 101.25]})

        with patch.object(self.finder, "calculate_original_avsl_report", return_value=report):
            latest_original = self.finder.get_latest_avsl("AAPL")

        self.assertEqual(latest_original, 101.25)

    def test_get_latest_avsl_returns_none_when_latest_row_nan(self):
        """live AVSL helper must not fall back when the latest row is NaN."""
        report = pd.DataFrame({"original_avsl": [90.0, 95.0, np.nan]})

        with patch.object(self.finder, "calculate_original_avsl_report", return_value=report):
            latest_original = self.finder.get_latest_avsl("AAPL")

        self.assertIsNone(latest_original)

    def test_get_latest_avsl_returns_none_when_latest_row_invalid(self):
        """live AVSL helper should reject inf, zero, and negative latest rows."""
        for invalid_value in (np.inf, -np.inf, 0.0, -1.0):
            with self.subTest(invalid_value=invalid_value):
                report = pd.DataFrame({"original_avsl": [90.0, 95.0, invalid_value]})

                with patch.object(self.finder, "calculate_original_avsl_report", return_value=report):
                    latest_original = self.finder.get_latest_avsl("AAPL")

                self.assertIsNone(latest_original)

    def test_check_avsl_sell_signal_false_when_latest_avsl_row_invalid(self):
        """live AVSL should hold on invalid latest AVSL."""
        self.finder.stock_data.loc[self.finder.stock_data.index[-1], ("Close", "AAPL")] = 50.0
        report = pd.DataFrame({"original_avsl": [40.0, 45.0, np.nan]})

        with patch.object(self.finder, "calculate_original_avsl_report", return_value=report):
            result = self.finder.check_avsl_sell_signal()

        for symbol in self.symbols:
            self.assertFalse(result[symbol])

    def test_check_avsl_sell_signal_true_when_close_below_original_avsl(self):
        """live AVSL should sell when current close is below latest original AVSL"""
        self.finder.stock_data.loc[self.finder.stock_data.index[-1], ("Close", "AAPL")] = 95.0

        with patch.object(self.finder, "get_latest_avsl", return_value=100.0):
            result = self.finder.check_avsl_sell_signal()

        self.assertTrue(result["AAPL"])

    def test_check_avsl_sell_signal_false_when_close_at_or_above_original_avsl(self):
        """live AVSL should hold when current close is at or above latest original AVSL"""
        self.finder.stock_data.loc[self.finder.stock_data.index[-1], ("Close", "AAPL")] = 100.0

        with patch.object(self.finder, "get_latest_avsl", return_value=100.0):
            equal_result = self.finder.check_avsl_sell_signal()

        self.assertFalse(equal_result["AAPL"])

        self.finder.stock_data.loc[self.finder.stock_data.index[-1], ("Close", "AAPL")] = 101.0
        with patch.object(self.finder, "get_latest_avsl", return_value=100.0):
            above_result = self.finder.check_avsl_sell_signal()

        self.assertFalse(above_result["AAPL"])

    def test_check_avsl_sell_signal_false_for_insufficient_original_avsl_data(self):
        """live AVSL should hold when original AVSL cannot be calculated"""
        with patch.object(self.finder, "get_latest_avsl", return_value=None):
            result = self.finder.check_avsl_sell_signal()

        for symbol in self.symbols:
            self.assertFalse(result[symbol])

    def test_is_special_situation_price_pinned_detects_ewcz_like_pattern(self):
        """Large gap-up followed by tight, low-volatility pinning should be detected."""
        with patch("yfinance.download") as mock_download:
            periods = 90
            index = pd.date_range(start="2024-01-01", periods=periods, freq="D")
            close = np.concatenate(
                [
                    np.linspace(10.0, 11.0, 60),
                    np.array([14.3]),
                    np.full(29, 14.35),
                ]
            )
            high = close + 0.03
            low = close - 0.03
            mock_data = pd.DataFrame(
                {
                    ("High", "EWCZ"): high,
                    ("Low", "EWCZ"): low,
                    ("Close", "EWCZ"): close,
                    ("Volume", "EWCZ"): np.full(periods, 1000.0),
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["EWCZ"])
            self.assertTrue(finder.is_special_situation_price_pinned("EWCZ"))

    def test_is_special_situation_price_pinned_false_for_normal_trend(self):
        """Steady uptrend without extreme one-day gap should not be detected."""
        with patch("yfinance.download") as mock_download:
            periods = 120
            index = pd.date_range(start="2024-01-01", periods=periods, freq="D")
            close = np.linspace(50.0, 80.0, periods)
            mock_data = pd.DataFrame(
                {
                    ("High", "TREND"): close * 1.01,
                    ("Low", "TREND"): close * 0.99,
                    ("Close", "TREND"): close,
                    ("Volume", "TREND"): np.full(periods, 1500.0),
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["TREND"])
            self.assertFalse(finder.is_special_situation_price_pinned("TREND"))

    def test_is_special_situation_price_pinned_false_when_post_gap_is_volatile(self):
        """Large gap-up with broad post-window range/high ATR should not be detected."""
        with patch("yfinance.download") as mock_download:
            periods = 90
            index = pd.date_range(start="2024-01-01", periods=periods, freq="D")
            pre = np.linspace(20.0, 21.0, 60)
            gap = np.array([27.5])
            post = np.array([28.0, 26.0] * 14 + [27.2])
            close = np.concatenate([pre, gap, post])
            high = close * 1.05
            low = close * 0.95
            mock_data = pd.DataFrame(
                {
                    ("High", "VOLGAP"): high,
                    ("Low", "VOLGAP"): low,
                    ("Close", "VOLGAP"): close,
                    ("Volume", "VOLGAP"): np.full(periods, 2000.0),
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["VOLGAP"])
            metrics = finder.get_special_situation_price_pinned_metrics("VOLGAP")
            self.assertGreater(metrics["post_gap_atr_pct"], 0.015)
            self.assertFalse(metrics["is_special_situation"])

    def test_is_special_situation_price_pinned_false_when_post_gap_volatility_is_invalid(self):
        """Invalid post-gap OHLC must not trigger special-situation exclusion."""
        with patch("yfinance.download") as mock_download:
            periods = 90
            index = pd.date_range(start="2024-01-01", periods=periods, freq="D")
            close = np.concatenate(
                [
                    np.linspace(10.0, 11.0, 60),
                    np.array([14.3]),
                    np.full(29, 14.35),
                ]
            )
            mock_data = pd.DataFrame(
                {
                    ("High", "EWCZ"): close + 0.03,
                    ("Low", "EWCZ"): close - 0.03,
                    ("Close", "EWCZ"): close,
                    ("Volume", "EWCZ"): np.full(periods, 1000.0),
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_data.loc[mock_data.index[-1], ("High", "EWCZ")] = np.nan
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["EWCZ"])
            metrics = finder.get_special_situation_price_pinned_metrics("EWCZ")
            self.assertFalse(metrics["is_special_situation"])
            self.assertEqual(metrics["atr_pct"], 0.0)
            self.assertEqual(metrics["post_gap_atr_pct"], 0.0)
            self.assertFalse(finder.is_special_situation_price_pinned("EWCZ"))

    def test_is_special_situation_price_pinned_detects_prth_like_plateau_inside_atr_window(self):
        """The event gap must not mask a tight plateau while it remains in ATR(14)."""
        with patch("yfinance.download") as mock_download:
            pre = np.linspace(10.0, 11.0, 60)
            gap = np.array([14.3])
            post = np.full(10, 14.35)
            close = np.concatenate([pre, gap, post])
            mock_data = pd.DataFrame(
                {
                    ("High", "PRTH"): close + 0.03,
                    ("Low", "PRTH"): close - 0.03,
                    ("Close", "PRTH"): close,
                    ("Volume", "PRTH"): np.full(len(close), 1000.0),
                },
                index=pd.date_range(start="2024-01-01", periods=len(close), freq="D"),
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["PRTH"])
            ordinary_atr_pct = finder.get_atr("PRTH", period=14) / close[-1]
            metrics = finder.get_special_situation_price_pinned_metrics("PRTH")

            self.assertFalse(finder.is_event_quarantine("PRTH"))
            self.assertGreater(ordinary_atr_pct, 0.015)
            self.assertTrue(metrics["is_special_situation"])
            self.assertEqual(metrics["days_since_gap"], 10.0)
            self.assertEqual(metrics["post_gap_observation_count"], 10.0)
            self.assertLess(metrics["post_gap_atr_pct"], 0.015)

    def test_is_special_situation_price_pinned_false_with_insufficient_post_gap_history(self):
        """A large gap with fewer than five post-event observations is not enough."""
        with patch("yfinance.download") as mock_download:
            pre = np.linspace(10.0, 11.0, 60)
            close = np.concatenate([pre, np.array([14.3]), np.full(4, 14.35)])
            mock_data = pd.DataFrame(
                {
                    ("High", "SHORT"): close + 0.03,
                    ("Low", "SHORT"): close - 0.03,
                    ("Close", "SHORT"): close,
                    ("Volume", "SHORT"): np.full(len(close), 1000.0),
                },
                index=pd.date_range(start="2024-01-01", periods=len(close), freq="D"),
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["SHORT"])
            metrics = finder.get_special_situation_price_pinned_metrics("SHORT")

            self.assertEqual(metrics["post_gap_observation_count"], 4.0)
            self.assertFalse(metrics["is_special_situation"])

    def test_is_special_situation_price_pinned_when_event_has_left_ordinary_atr_window(self):
        """The detector remains correct after the event has naturally left ATR(14)."""
        with patch("yfinance.download") as mock_download:
            pre = np.linspace(10.0, 11.0, 60)
            close = np.concatenate([pre, np.array([14.3]), np.full(15, 14.35)])
            mock_data = pd.DataFrame(
                {
                    ("High", "OLDER"): close + 0.03,
                    ("Low", "OLDER"): close - 0.03,
                    ("Close", "OLDER"): close,
                    ("Volume", "OLDER"): np.full(len(close), 1000.0),
                },
                index=pd.date_range(start="2024-01-01", periods=len(close), freq="D"),
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["OLDER"])
            ordinary_atr_pct = finder.get_atr("OLDER", period=14) / close[-1]
            metrics = finder.get_special_situation_price_pinned_metrics("OLDER")

            self.assertFalse(finder.is_event_quarantine("OLDER"))
            self.assertLess(ordinary_atr_pct, 0.015)
            self.assertTrue(metrics["is_special_situation"])

    def test_prth_like_gap_quarantine_expiry_still_detects_pinned_price(self):
        """A 30% gap ten sessions ago is detected once its plateau is proven.

        Ordinary ATR(14) still contains the event-day True Range, while the
        5-session event quarantine can no longer see the event. The
        special-situation metric must instead measure the ten tightly clustered
        post-gap sessions.
        """
        symbol = "SYNTH"
        pre_event_close = np.linspace(99.5, 100.0, 50)
        post_gap_close = np.array(
            [130.00, 130.05, 129.98, 130.02, 130.04, 129.99, 130.01, 130.03, 130.00, 130.02]
        )
        close = np.concatenate([pre_event_close, [130.0], post_gap_close])
        high = close * 1.001
        low = close * 0.999
        # The event close is 30% above the prior close; keep its OHLC range tight.
        high[len(pre_event_close)] = 130.2
        low[len(pre_event_close)] = 129.8
        synthetic_data = pd.DataFrame(
            {
                ("High", symbol): high,
                ("Low", symbol): low,
                ("Close", symbol): close,
                ("Volume", symbol): np.full(len(close), 1000.0),
            },
            index=pd.date_range("2024-01-01", periods=len(close), freq="B"),
        )
        synthetic_data.columns = pd.MultiIndex.from_tuples(synthetic_data.columns)

        with patch("yfinance.download", return_value=synthetic_data):
            finder = UsaStockFinder([symbol])
            event_metrics = finder.get_event_quarantine_metrics(symbol, lookback_days=5)
            pinned_metrics = finder.get_special_situation_price_pinned_metrics(symbol)

        # Construction facts: 10 completed sessions since a 30% close-to-close gap.
        gap_pct = close[len(pre_event_close)] / pre_event_close[-1] - 1.0
        self.assertAlmostEqual(gap_pct, 0.30)
        self.assertGreaterEqual(pinned_metrics["max_gap_up_pct"], 0.15)
        self.assertEqual(len(post_gap_close), 10)
        self.assertGreater(
            len(post_gap_close), 5
        )  # ten sessions old is outside the configured 5-session window
        self.assertFalse(event_metrics["is_event_quarantine"])

        # Pinning shape is within all current non-ATR thresholds.
        self.assertAlmostEqual(pinned_metrics["max_gap_up_pct"], gap_pct)
        self.assertLessEqual(pinned_metrics["recent_range_pct"], 0.015)
        self.assertLessEqual(pinned_metrics["recent_abs_return_pct"], 0.02)
        self.assertLessEqual(pinned_metrics["plateau_deviation_pct"], 0.015)
        self.assertGreater(finder.get_atr(symbol, period=14) / close[-1], 0.015)
        self.assertLessEqual(pinned_metrics["post_gap_atr_pct"], 0.015)
        self.assertEqual(pinned_metrics["atr_pct"], pinned_metrics["post_gap_atr_pct"])
        self.assertTrue(pinned_metrics["is_special_situation"])
        self.assertTrue(finder.is_special_situation_price_pinned(symbol))


    def test_is_event_quarantine_true_for_recent_gap_and_flat_price(self):
        """Recent 20% gap-up with flat post-gap action should be quarantined."""
        with patch("yfinance.download") as mock_download:
            periods = 80
            index = pd.date_range(start="2024-01-01", periods=periods, freq="D")
            pre = np.linspace(10.0, 10.5, 75)
            post = np.array([12.6, 12.58, 12.57, 12.59, 12.6])
            close = np.concatenate([pre, post])
            mock_data = pd.DataFrame(
                {
                    ("High", "GAPF"): close * 1.01,
                    ("Low", "GAPF"): close * 0.99,
                    ("Close", "GAPF"): close,
                    ("Volume", "GAPF"): np.full(periods, 1200.0),
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["GAPF"])
            self.assertTrue(finder.is_event_quarantine("GAPF"))

    def test_is_event_quarantine_false_when_gap_is_outside_lookback(self):
        """Older gap outside recent lookback should not be quarantined."""
        with patch("yfinance.download") as mock_download:
            periods = 80
            index = pd.date_range(start="2024-01-01", periods=periods, freq="D")
            close = np.concatenate([np.linspace(10.0, 10.2, 70), np.linspace(12.2, 12.4, 10)])
            close[60] = close[59] * 1.2
            mock_data = pd.DataFrame(
                {
                    ("High", "OLDG"): close * 1.01,
                    ("Low", "OLDG"): close * 0.99,
                    ("Close", "OLDG"): close,
                    ("Volume", "OLDG"): np.full(periods, 1200.0),
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["OLDG"])
            self.assertFalse(finder.is_event_quarantine("OLDG", lookback_days=5))

    def test_event_quarantine_expires_at_lookback_boundary(self):
        """A five-day quarantine sees a gap four days ago, but not five days ago."""
        with patch("yfinance.download") as mock_download:
            pre = np.linspace(10.0, 10.5, 70)
            gap = np.array([12.6])
            close = np.concatenate([pre, gap, np.full(5, 12.6)])
            mock_data = pd.DataFrame(
                {
                    ("High", "BOUND"): close * 1.01,
                    ("Low", "BOUND"): close * 0.99,
                    ("Close", "BOUND"): close,
                    ("Volume", "BOUND"): np.full(len(close), 1200.0),
                },
                index=pd.date_range(start="2024-01-01", periods=len(close), freq="D"),
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["BOUND"])
            self.assertFalse(finder.is_event_quarantine("BOUND", lookback_days=5))

            finder.stock_data = finder.stock_data.iloc[:-1]
            self.assertTrue(finder.is_event_quarantine("BOUND", lookback_days=5))

    def test_is_event_quarantine_false_when_recent_gap_has_large_pullback(self):
        """Recent gap with large drawdown should not be quarantined."""
        with patch("yfinance.download") as mock_download:
            periods = 80
            index = pd.date_range(start="2024-01-01", periods=periods, freq="D")
            pre = np.linspace(30.0, 31.0, 74)
            post = np.array([37.2, 38.0, 35.0, 34.5, 34.2, 34.0])
            close = np.concatenate([pre, post])
            mock_data = pd.DataFrame(
                {
                    ("High", "PULL"): close * 1.01,
                    ("Low", "PULL"): close * 0.99,
                    ("Close", "PULL"): close,
                    ("Volume", "PULL"): np.full(periods, 1200.0),
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["PULL"])
            self.assertFalse(finder.is_event_quarantine("PULL"))

    def test_is_event_quarantine_false_for_normal_uptrend(self):
        """Normal uptrend without a single large gap should not be quarantined."""
        with patch("yfinance.download") as mock_download:
            periods = 100
            index = pd.date_range(start="2024-01-01", periods=periods, freq="D")
            close = np.linspace(50.0, 60.0, periods)
            mock_data = pd.DataFrame(
                {
                    ("High", "NORM"): close * 1.01,
                    ("Low", "NORM"): close * 0.99,
                    ("Close", "NORM"): close,
                    ("Volume", "NORM"): np.full(periods, 1200.0),
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["NORM"])
            self.assertFalse(finder.is_event_quarantine("NORM"))

    def test_calculate_original_avsl_report_returns_valid_values_for_normal_ohlcv(self):
        """live AVSL report should return positive finite values with enough OHLCV data."""
        with patch("yfinance.download") as mock_download:
            mock_download.return_value = _deterministic_ohlcv(periods=100, symbol="AVSL")
            finder = UsaStockFinder(["AVSL"])

        report = finder.calculate_original_avsl_report("AVSL")

        self.assertIsNotNone(report)
        self.assertIsInstance(report, pd.DataFrame)
        valid_values = report["original_avsl"].dropna()
        self.assertFalse(valid_values.empty)
        self.assertTrue(np.isfinite(valid_values.to_numpy()).all())
        self.assertTrue((valid_values > 0).all())

    def test_get_latest_avsl_returns_positive_float_for_sufficient_data(self):
        """latest AVSL should be available for a normal synthetic dataset."""
        with patch("yfinance.download") as mock_download:
            mock_download.return_value = _deterministic_ohlcv(periods=100, symbol="AVSL")
            finder = UsaStockFinder(["AVSL"])

        latest_avsl = finder.get_latest_avsl("AVSL")

        self.assertIsInstance(latest_avsl, float)
        self.assertGreater(latest_avsl, 0.0)

    def test_check_avsl_sell_signal_original_live_mode(self):
        """check check_avsl_sell_signal in original AVSL live mode."""
        result = self.finder.check_avsl_sell_signal()
        self.assertIsInstance(result, dict)
        for symbol in self.symbols:
            self.assertIn(symbol, result)
            self.assertIsInstance(result[symbol], (bool, type(True)))

    def test_avsl_with_volume_decline_scenario(self):
        """Test AVSL behavior when volume declines significantly"""
        # Create test data with declining volume
        with patch("yfinance.download") as mock_download:
            periods = 100
            index = pd.date_range(start="2023-01-01", periods=periods, freq="D")

            # Generate data with declining volume in recent periods
            base_price = 150.0
            base_volume = 2000

            prices = np.linspace(base_price, base_price * 0.95, periods)  # Slight decline
            volumes = np.concatenate(
                [
                    np.full(periods - 10, base_volume),  # Normal volume
                    np.full(10, base_volume * 0.3),  # Recent volume decline
                ]
            )

            mock_data = pd.DataFrame(
                {
                    ("High", "TEST"): prices * 1.01,
                    ("Low", "TEST"): prices * 0.99,
                    ("Close", "TEST"): prices,
                    ("Volume", "TEST"): volumes,
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["TEST"])
            result = finder.check_avsl_sell_signal()

            self.assertIn("TEST", result)
            # AVSL should detect the price decline with volume drop
            # (exact result depends on calculation, but should be boolean)


if __name__ == "__main__":
    unittest.main()
