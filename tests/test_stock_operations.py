"""
test function to test stock_operations function
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from stock_operations import APIError, fetch_account_balance, fetch_holdings_detail, fetch_us_stock_holdings


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
        """Check fetch_us_stock_holdings fail - should raise APIError"""
        os.environ["ki_app_key"] = "test_key"
        os.environ["ki_app_secret_key"] = "test_secret"
        os.environ["account_number"] = "test_account"

        mock_broker = MagicMock()
        mock_broker.fetch_present_balance.return_value = {"rt_cd": "-1", "msg1": "Error fetching balance"}
        mock_korea_investment.return_value = mock_broker

        # Now raises APIError instead of returning empty list
        with self.assertRaises(APIError):
            fetch_us_stock_holdings()

        mock_korea_investment.assert_called()
        mock_broker.fetch_present_balance.assert_called()

    @patch("stock_operations._get_broker")
    def test_fetch_account_balance_success(self, mock_get_broker):
        """Check fetch_account_balance success"""
        os.environ["ki_app_key"] = "test_key"
        os.environ["ki_app_secret_key"] = "test_secret"
        os.environ["account_number"] = "test_account"

        mock_broker = MagicMock()
        mock_broker.fetch_present_balance.return_value = {
            "rt_cd": "0",
            "output2": [
                {
                    "dnca_tot_amt": "1000000",  # 예수금 총액
                    "tot_evlu_amt": "5000000",  # 총 평가 금액
                    "nxdy_excc_amt": "950000",  # 익일 정산 금액
                }
            ],
        }
        mock_get_broker.return_value = mock_broker

        result = fetch_account_balance()

        self.assertIsNotNone(result)
        self.assertIn("available_cash", result)
        self.assertIn("total_balance", result)
        self.assertIn("buyable_cash", result)
        self.assertGreater(result["available_cash"], 0)

    @patch("stock_operations._get_broker")
    def test_fetch_account_balance_fail(self, mock_get_broker):
        """Check fetch_account_balance fail - should raise APIError"""
        os.environ["ki_app_key"] = "test_key"
        os.environ["ki_app_secret_key"] = "test_secret"
        os.environ["account_number"] = "test_account"

        mock_broker = MagicMock()
        mock_broker.fetch_present_balance.return_value = {"rt_cd": "-1", "msg1": "Error fetching balance"}
        mock_get_broker.return_value = mock_broker

        # Now raises APIError instead of returning None
        with self.assertRaises(APIError):
            fetch_account_balance()

    @patch("stock_operations._get_broker")
    def test_fetch_holdings_detail_success(self, mock_get_broker):
        """Check fetch_holdings_detail success"""
        os.environ["ki_app_key"] = "test_key"
        os.environ["ki_app_secret_key"] = "test_secret"
        os.environ["account_number"] = "test_account"

        mock_broker = MagicMock()
        mock_broker.fetch_present_balance.return_value = {
            "rt_cd": "0",
            "output1": [
                {
                    "pdno": "AAPL-US",
                    "prdt_name": "Apple Inc",
                    "hldg_qty": "100",
                    "pchs_avg_pric": "150.0",
                    "prpr": "155.0",
                    "evlu_amt": "15500.0",
                },
                {
                    "pdno": "MSFT-US",
                    "prdt_name": "Microsoft Corp",
                    "hldg_qty": "50",
                    "pchs_avg_pric": "300.0",
                    "prpr": "305.0",
                    "evlu_amt": "15250.0",
                },
            ],
        }
        mock_get_broker.return_value = mock_broker

        result = fetch_holdings_detail()

        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        # Two exchanges (나스닥, 뉴욕) * 2 holdings = 4 total
        self.assertEqual(len(result), 4)
        # Check first holding
        self.assertEqual(result[0]["symbol"], "AAPL")
        self.assertEqual(result[0]["quantity"], 100.0)
        self.assertEqual(result[0]["avg_price"], 150.0)
        self.assertEqual(result[0]["current_price"], 155.0)
        self.assertIn("profit_loss", result[0])
        self.assertIn("profit_loss_rate", result[0])
        # Verify all holdings have required fields
        for holding in result:
            self.assertIn("symbol", holding)
            self.assertIn("quantity", holding)
            self.assertIn("avg_price", holding)
            self.assertIn("current_price", holding)
            self.assertIn("exchange", holding)

    @patch("stock_operations._get_broker")
    def test_fetch_holdings_detail_fail(self, mock_get_broker):
        """Check fetch_holdings_detail fail - should raise APIError"""
        os.environ["ki_app_key"] = "test_key"
        os.environ["ki_app_secret_key"] = "test_secret"
        os.environ["account_number"] = "test_account"

        mock_broker = MagicMock()
        mock_broker.fetch_present_balance.return_value = {"rt_cd": "-1", "msg1": "Error fetching balance"}
        mock_get_broker.return_value = mock_broker

        # Now raises APIError instead of returning None
        with self.assertRaises(APIError):
            fetch_holdings_detail()

    @patch("stock_operations._get_broker")
    def test_fetch_holdings_detail_empty(self, mock_get_broker):
        """Check fetch_holdings_detail with empty holdings"""
        os.environ["ki_app_key"] = "test_key"
        os.environ["ki_app_secret_key"] = "test_secret"
        os.environ["account_number"] = "test_account"

        mock_broker = MagicMock()
        mock_broker.fetch_present_balance.return_value = {"rt_cd": "0", "output1": []}
        mock_get_broker.return_value = mock_broker

        result = fetch_holdings_detail()

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
