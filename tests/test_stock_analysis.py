"""
test function to test UsaStockFinder class
"""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from stock_analysis import UsaStockFinder


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

    def test_check_avsl_sell_signal_buff_mode(self):
        """check check_avsl_sell_signal in Buff AVSL mode (default)"""
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
