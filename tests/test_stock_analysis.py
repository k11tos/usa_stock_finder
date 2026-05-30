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

    def test_check_avsl_sell_signal_with_custom_params(self):
        """check check_avsl_sell_signal with custom parameters"""
        result = self.finder.check_avsl_sell_signal(
            period_days=30, volume_decline_threshold=0.6, price_decline_threshold=0.05, recent_days=3
        )
        self.assertIsInstance(result, dict)
        for symbol in self.symbols:
            self.assertIn(symbol, result)

    def test_check_avsl_sell_signal_legacy_mode_true_on_clear_decline(self):
        """legacy AVSL mode should trigger when recent price and volume clearly collapse"""
        with patch("yfinance.download") as mock_download:
            periods = 60
            index = pd.date_range(start="2024-01-01", periods=periods, freq="D")

            close = np.concatenate([np.full(55, 100.0), np.array([99.0, 97.0, 95.0, 93.0, 90.0])])
            volume = np.concatenate([np.full(55, 1000.0), np.full(5, 100.0)])

            mock_data = pd.DataFrame(
                {
                    ("High", "DROP"): close * 1.01,
                    ("Low", "DROP"): close * 0.99,
                    ("Close", "DROP"): close,
                    ("Volume", "DROP"): volume,
                },
                index=index,
            )
            mock_data.columns = pd.MultiIndex.from_tuples(mock_data.columns)
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["DROP"])
            result = finder.check_avsl_sell_signal(
                use_buff_avsl=False,
                period_days=50,
                recent_days=5,
                volume_decline_threshold=0.5,
                price_decline_threshold=0.03,
            )

            self.assertEqual(result, {"DROP": True})

    def test_check_avsl_sell_signal_legacy_mode(self):
        """check check_avsl_sell_signal in legacy mode"""
        result = self.finder.check_avsl_sell_signal(use_buff_avsl=False)
        self.assertIsInstance(result, dict)
        for symbol in self.symbols:
            self.assertIn(symbol, result)
            self.assertIsInstance(result[symbol], (bool, type(True)))

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
            self.assertFalse(finder.is_special_situation_price_pinned("VOLGAP"))

    def test_is_special_situation_price_pinned_false_when_atr_invalid_zero(self):
        """ATR calc failure (0.0) must not trigger special-situation exclusion."""
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
            mock_download.return_value = mock_data

            finder = UsaStockFinder(["EWCZ"])
            with patch.object(finder, "get_atr", return_value=0.0):
                metrics = finder.get_special_situation_price_pinned_metrics("EWCZ")
                self.assertFalse(metrics["is_special_situation"])
                self.assertEqual(metrics["atr_pct"], 0.0)
                self.assertFalse(finder.is_special_situation_price_pinned("EWCZ"))


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

    def test_calculate_vpci_components(self):
        """check calculate_vpci_components function"""
        for symbol in self.symbols:
            vpci_df = self.finder.calculate_vpci_components(symbol)
            if vpci_df is not None:
                self.assertIsInstance(vpci_df, pd.DataFrame)
                self.assertIn("VPC", vpci_df.columns)
                self.assertIn("VPR", vpci_df.columns)
                self.assertIn("VM", vpci_df.columns)
                self.assertIn("VPCI", vpci_df.columns)

    def test_calculate_avsl_series(self):
        """check calculate_avsl_series function"""
        for symbol in self.symbols:
            avsl_series = self.finder.calculate_avsl_series(symbol)
            if avsl_series is not None:
                self.assertIsInstance(avsl_series, pd.Series)
                # AVSL should be positive values
                if not avsl_series.empty:
                    valid_values = avsl_series.dropna()
                    if not valid_values.empty:
                        self.assertTrue((valid_values > 0).all())

    def test_get_latest_avsl(self):
        """check get_latest_avsl function"""
        for symbol in self.symbols:
            latest_avsl = self.finder.get_latest_avsl(symbol)
            if latest_avsl is not None:
                self.assertIsInstance(latest_avsl, (float, np.floating))
                self.assertGreater(latest_avsl, 0)

    def test_calculate_avsl_series_returns_valid_values_for_normal_ohlcv(self):
        """legacy AVSL should return positive values when enough OHLCV data exists"""
        with patch("yfinance.download") as mock_download:
            mock_download.return_value = _deterministic_ohlcv(periods=100, symbol="AVSL")
            finder = UsaStockFinder(["AVSL"])

        avsl_series = finder.calculate_avsl_series("AVSL")

        self.assertIsNotNone(avsl_series)
        self.assertIsInstance(avsl_series, pd.Series)
        valid_values = avsl_series.dropna()
        self.assertFalse(valid_values.empty)
        self.assertTrue(np.isfinite(valid_values.to_numpy()).all())
        self.assertTrue((valid_values > 0).all())

    def test_get_latest_avsl_returns_positive_float_for_sufficient_data(self):
        """latest legacy AVSL should be available for a normal synthetic dataset"""
        with patch("yfinance.download") as mock_download:
            mock_download.return_value = _deterministic_ohlcv(periods=100, symbol="AVSL")
            finder = UsaStockFinder(["AVSL"])

        latest_avsl = finder.get_latest_avsl("AVSL")

        self.assertIsInstance(latest_avsl, float)
        self.assertGreater(latest_avsl, 0.0)

    def test_calculate_avsl_series_handles_early_non_finite_vpci_lengths(self):
        """early NaN/inf VPCI values should not make integer length conversion fail"""
        symbol = "AAPL"
        index = self.finder.stock_data.index
        vpci = pd.Series(np.linspace(0.05, 0.15, len(index)), index=index)
        vpci.iloc[:5] = [np.nan, np.inf, -np.inf, np.nan, 0.05]
        vpci_df = pd.DataFrame(
            {
                "VPC": pd.Series(0.05, index=index),
                "VPR": pd.Series(1.0, index=index),
                "VM": pd.Series(1.0, index=index),
                "VPCI": vpci,
            }
        )

        with patch.object(self.finder, "calculate_vpci_components", return_value=vpci_df):
            avsl_series = self.finder.calculate_avsl_series(symbol)

        self.assertIsNotNone(avsl_series)
        valid_values = avsl_series.dropna()
        self.assertFalse(valid_values.empty)
        self.assertTrue(np.isfinite(valid_values.to_numpy()).all())

    def test_check_avsl_sell_signal_legacy_approximate_mode(self):
        """check check_avsl_sell_signal in legacy/approximate AVSL mode (default)"""
        result = self.finder.check_avsl_sell_signal(use_buff_avsl=True)
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
            result = finder.check_avsl_sell_signal(use_buff_avsl=True)

            self.assertIn("TEST", result)
            # AVSL should detect the price decline with volume drop
            # (exact result depends on calculation, but should be boolean)


if __name__ == "__main__":
    unittest.main()
