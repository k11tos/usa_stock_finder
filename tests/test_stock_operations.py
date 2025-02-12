"""
test function to test stock_operations function
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from stock_operations import fetch_us_stock_holdings


class TestStockOperations(unittest.TestCase):
    """Test stock_operations class"""

    @patch("stock_operations.mojito.KoreaInvestment")
    def test_fetch_us_stock_holdings_success(self, mock_korea_investment):
        """Check fetch_us_stock_holdings success"""
        os.environ["ki_app_key"] = "test_key"
        os.environ["ki_app_secret_key"] = "test_secret"
        os.environ["account_number"] = "test_account"

        mock_broker = MagicMock()
        mock_broker.fetch_present_balance.return_value = {"rt_cd": "0", "output1": [{"pdno": "AAPL"}, {"pdno": "MSFT"}]}
        mock_korea_investment.return_value = mock_broker

        result = fetch_us_stock_holdings()

        # Expect unique tickers only
        expected_result = ["AAPL", "MSFT"]
        self.assertEqual(sorted(result), sorted(expected_result))
        mock_korea_investment.assert_called()

    @patch("stock_operations.mojito.KoreaInvestment")
    def test_fetch_us_stock_holdings_fail(self, mock_korea_investment):
        """Check fetch_us_stock_holdings fail"""
        os.environ["ki_app_key"] = "test_key"
        os.environ["ki_app_secret_key"] = "test_secret"
        os.environ["account_number"] = "test_account"

        mock_broker = MagicMock()
        mock_broker.fetch_present_balance.return_value = {"rt_cd": "-1", "msg1": "Error fetching balance"}
        mock_korea_investment.return_value = mock_broker

        result = fetch_us_stock_holdings()

        self.assertEqual(result, [])
        mock_korea_investment.assert_called()
        mock_broker.fetch_present_balance.assert_called()


if __name__ == "__main__":
    unittest.main()
