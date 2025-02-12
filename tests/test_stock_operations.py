import os
import unittest
from unittest.mock import MagicMock, patch

from stock_operations import fetch_us_stock_holdings


class TestStockOperations(unittest.TestCase):

    @patch("stock_operations.mojito.KoreaInvestment")
    @patch("stock_operations.load_dotenv")
    def test_fetch_us_stock_holdings_success(self, mock_load_dotenv, mock_KoreaInvestment):
        os.environ["ki_app_key"] = "test_key"
        os.environ["ki_app_secret_key"] = "test_secret"
        os.environ["account_number"] = "test_account"

        mock_broker = MagicMock()
        mock_broker.fetch_present_balance.return_value = {"rt_cd": "0", "output1": [{"pdno": "AAPL"}, {"pdno": "MSFT"}]}
        mock_KoreaInvestment.return_value = mock_broker

        result = fetch_us_stock_holdings()

        # Expect unique tickers only
        expected_result = ["AAPL", "MSFT"]
        self.assertEqual(sorted(result), sorted(expected_result))
        mock_KoreaInvestment.assert_called()

    @patch("stock_operations.mojito.KoreaInvestment")
    @patch("stock_operations.load_dotenv")
    def test_fetch_us_stock_holdings_fail(self, mock_load_dotenv, mock_KoreaInvestment):
        os.environ["ki_app_key"] = "test_key"
        os.environ["ki_app_secret_key"] = "test_secret"
        os.environ["account_number"] = "test_account"

        mock_broker = MagicMock()
        mock_broker.fetch_present_balance.return_value = {"rt_cd": "-1", "msg1": "Error fetching balance"}
        mock_KoreaInvestment.return_value = mock_broker

        result = fetch_us_stock_holdings()

        self.assertEqual(result, [])
        mock_KoreaInvestment.assert_called()
        mock_broker.fetch_present_balance.assert_called()


if __name__ == "__main__":
    unittest.main()
