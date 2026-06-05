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

    @patch("stock_operations._get_broker")
    def test_fetch_account_balance_does_not_treat_krw_cash_conversion_as_usd_equity(self, mock_get_broker):
        """frcr_evlu_amt2 in output2 is KRW-converted cash, not USD total equity."""
        mock_broker = MagicMock()
        mock_broker.fetch_present_balance.return_value = {
            "rt_cd": "0",
            "output1": [{"pdno": "AAPL-US", "cblc_qty13": "2", "ovrs_now_pric1": "150", "frcr_evlu_amt2": "300"}],
            "output2": [
                {
                    "crcy_cd": "USD",
                    "frcr_dncl_amt_2": "1003.05",
                    "frst_bltn_exrt": "1507.2",
                    "frcr_evlu_amt2": "1511796",
                }
            ],
            "output3": [{"tot_asst_amt": "1511796"}],
        }
        mock_get_broker.return_value = mock_broker

        result = fetch_account_balance()

        self.assertEqual(result["available_cash_usd"], 1003.05)
        self.assertAlmostEqual(result["broker_raw_output2_frcr_evlu_amt2"], 1511796.0)
        self.assertAlmostEqual(result["total_equity_usd"], 1303.05)
        self.assertAlmostEqual(result["total_balance"], 1303.05)

    @patch("stock_operations._get_broker")
    def test_fetch_account_balance_deduplicates_repeated_output2_cash(self, mock_get_broker):
        """NASDAQ/NYSE calls can return the same account-level output2 row; do not double-count it."""
        mock_broker = MagicMock()
        mock_broker.fetch_present_balance.return_value = {
            "rt_cd": "0",
            "output1": [],
            "output2": [
                {
                    "crcy_cd": "USD",
                    "frcr_dncl_amt_2": "1000",
                    "frst_bltn_exrt": "1500",
                    "frcr_evlu_amt2": "1500000",
                }
            ],
        }
        mock_get_broker.return_value = mock_broker

        result = fetch_account_balance()

        self.assertEqual(result["available_cash_usd"], 1000.0)
        self.assertEqual(result["currency_cash_krw"], 1500000.0)
        self.assertEqual(result["total_equity_usd"], 1000.0)


if __name__ == "__main__":
    unittest.main()
