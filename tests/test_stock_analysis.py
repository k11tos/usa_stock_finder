import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from stock_analysis import UsaStockFinder


class TestUsaStockFinder(unittest.TestCase):

    @patch("yfinance.download")
    def setUp(self, mock_download):
        # Simulate 250 days of data
        periods = 250
        index = pd.date_range(start="2023-01-01", periods=periods, freq="D")

        # Generate more data for testing moving averages
        mock_data = pd.DataFrame(
            {
                ("High", "AAPL"): np.random.random(periods) * 100 + 150,  # Random data for approximation
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
        self.assertTrue(self.finder.is_data_valid())

    def test_is_above_75_percent_of_52_week_high(self):
        result = self.finder.is_above_75_percent_of_52_week_high(margin=0.01)
        self.assertIsInstance(result, dict)
        # Add specific assertions once data is stable.

    def test_is_above_52_week_low(self):
        result = self.finder.is_above_52_week_low(margin=0.01)
        self.assertIsInstance(result, dict)
        # Add specific assertions once data is stable.

    def test_get_moving_averages(self):
        ma = self.finder.get_moving_averages(2)
        self.assertIsInstance(ma, dict)
        for symbol in self.symbols:
            self.assertIn(symbol, ma)

    def test_is_200_ma_increasing_recently(self):
        result = self.finder.is_200_ma_increasing_recently(margin=0.01)
        self.assertIsInstance(result, dict)

    def test_has_valid_trend_template(self):
        result = self.finder.has_valid_trend_template(margin=0.01)
        self.assertIsInstance(result, dict)

    def test_price_volume_correlation_percent(self):
        correlation = self.finder.price_volume_correlation_percent(recent_days=10)
        self.assertIsInstance(correlation, dict)

    def test_compare_volume_price_movement(self):
        result = self.finder.compare_volume_price_movement(recent_days=10, margin=0.01)
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
