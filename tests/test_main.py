"""
test_main.py

This module contains unit tests for the main module.
It tests the main functions for stock analysis and selection.
"""

import unittest
from unittest.mock import MagicMock, patch

from main import (
    calculate_correlations,
    calculate_investment_per_stock,
    calculate_sell_quantities,
    calculate_share_quantities,
    generate_telegram_message,
    log_stock_info,
    select_stocks,
    update_final_items,
)


class TestMainFunctions(unittest.TestCase):
    """Test main module functions"""

    def setUp(self):
        """Set up test fixtures"""
        # Mock UsaStockFinder instance
        self.mock_finder = MagicMock()
        self.mock_finder.symbols = ["AAPL", "MSFT", "GOOGL"]

        # Mock correlations data
        self.mock_correlations = {
            "200": {"AAPL": 75.5, "MSFT": 82.3, "GOOGL": 68.9},
            "100": {"AAPL": 71.2, "MSFT": 78.9, "GOOGL": 65.4},
            "50": {"AAPL": 68.7, "MSFT": 76.2, "GOOGL": 62.1},
        }

    def test_calculate_correlations(self):
        """Test calculate_correlations function"""
        # Mock the price_volume_correlation_percent method
        self.mock_finder.price_volume_correlation_percent.side_effect = [
            {"AAPL": 75.5, "MSFT": 82.3, "GOOGL": 68.9},  # 200 days
            {"AAPL": 71.2, "MSFT": 78.9, "GOOGL": 65.4},  # 100 days
            {"AAPL": 68.7, "MSFT": 76.2, "GOOGL": 62.1},  # 50 days
        ]

        result = calculate_correlations(self.mock_finder)

        # Verify the result structure
        self.assertIn("200", result)
        self.assertIn("100", result)
        self.assertIn("50", result)

        # Verify the finder method was called for each period
        self.assertEqual(self.mock_finder.price_volume_correlation_percent.call_count, 3)

        # Verify the calls were made with correct parameters
        expected_calls = [
            ((200,),),
            ((100,),),
            ((50,),),
        ]
        self.mock_finder.price_volume_correlation_percent.assert_has_calls(expected_calls)

    def test_select_stocks_buy_candidates(self):
        """Test select_stocks function for buy candidates"""
        # Mock the has_valid_trend_template method
        self.mock_finder.has_valid_trend_template.side_effect = [
            {"AAPL": True, "MSFT": False, "GOOGL": True},  # margin 0
            {"AAPL": True, "MSFT": True, "GOOGL": True},  # margin 0.1
        ]

        buy_items, not_sell_items = select_stocks(self.mock_finder, self.mock_correlations)

        # AAPL and GOOGL should be in buy_items (valid trend + correlation >= 50)
        self.assertIn("AAPL", buy_items)
        self.assertIn("GOOGL", buy_items)
        # MSFT should not be in buy_items (invalid trend)
        self.assertNotIn("MSFT", buy_items)

    def test_select_stocks_hold_candidates(self):
        """Test select_stocks function for hold candidates"""
        # Mock the has_valid_trend_template method
        self.mock_finder.has_valid_trend_template.side_effect = [
            {"AAPL": False, "MSFT": False, "GOOGL": False},  # margin 0
            {"AAPL": True, "MSFT": True, "GOOGL": False},  # margin 0.1
        ]

        buy_items, not_sell_items = select_stocks(self.mock_finder, self.mock_correlations)

        # AAPL and MSFT should be in not_sell_items (valid trend with margin + correlation >= 40)
        self.assertIn("AAPL", not_sell_items)
        self.assertIn("MSFT", not_sell_items)
        # GOOGL should not be in not_sell_items (invalid trend even with margin)

    def test_select_stocks_no_candidates(self):
        """Test select_stocks function with no valid candidates"""
        # Mock the has_valid_trend_template method to return all False
        self.mock_finder.has_valid_trend_template.side_effect = [
            {"AAPL": False, "MSFT": False, "GOOGL": False},  # margin 0
            {"AAPL": False, "MSFT": False, "GOOGL": False},  # margin 0.1
        ]

        buy_items, not_sell_items = select_stocks(self.mock_finder, self.mock_correlations)

        # Both lists should be empty
        self.assertEqual(len(buy_items), 0)
        self.assertEqual(len(not_sell_items), 0)

    def test_generate_telegram_message_with_changes(self):
        """Test generate_telegram_message function with portfolio changes"""
        prev_items = ["AAPL", "MSFT", "GOOGL"]
        buy_items = ["AAPL", "MSFT", "TSLA"]
        not_sell_items = ["AAPL", "MSFT", "GOOGL"]

        result = generate_telegram_message(prev_items, buy_items, not_sell_items)

        # Should return a message with changes
        self.assertIsNotNone(result)
        # Check for buy signal message format
        has_buy_signal = any("TSLA" in line or "매수" in line for line in result)
        self.assertTrue(has_buy_signal)
        # No sell message since all prev items are in keep_items

    def test_generate_telegram_message_with_sell_signals(self):
        """Test generate_telegram_message function with sell signals"""
        prev_items = ["AAPL", "MSFT", "GOOGL", "TSLA"]
        buy_items = ["AAPL", "MSFT"]
        not_sell_items = ["AAPL", "MSFT", "GOOGL"]

        result = generate_telegram_message(prev_items, buy_items, not_sell_items)

        # Should return a message with sell signal for TSLA
        self.assertIsNotNone(result)
        # Check for sell signal message format
        has_sell_signal = any("TSLA" in line or "매도" in line for line in result)
        self.assertTrue(has_sell_signal)

    def test_generate_telegram_message_no_changes(self):
        """Test generate_telegram_message function with no changes"""
        prev_items = ["AAPL", "MSFT", "GOOGL"]
        buy_items = ["AAPL", "MSFT", "GOOGL"]
        not_sell_items = ["AAPL", "MSFT", "GOOGL"]

        result = generate_telegram_message(prev_items, buy_items, not_sell_items)

        # Should return None when no changes
        self.assertIsNone(result)

    def test_update_final_items(self):
        """Test update_final_items function"""
        prev_items = ["AAPL", "MSFT", "GOOGL"]
        buy_items = ["AAPL", "MSFT", "TSLA"]
        not_sell_items = ["AAPL", "MSFT", "GOOGL"]

        result = update_final_items(prev_items, buy_items, not_sell_items)

        # Should include all items that meet the criteria
        expected_items = ["AAPL", "MSFT", "GOOGL", "TSLA"]
        self.assertEqual(sorted(result), sorted(expected_items))

    def test_update_final_items_no_new_items(self):
        """Test update_final_items function with no new items"""
        prev_items = ["AAPL", "MSFT", "GOOGL"]
        buy_items = ["AAPL", "MSFT"]
        not_sell_items = ["AAPL", "MSFT", "GOOGL"]

        result = update_final_items(prev_items, buy_items, not_sell_items)

        # Should include all items that meet the criteria
        expected_items = ["AAPL", "MSFT", "GOOGL"]
        self.assertEqual(sorted(result), sorted(expected_items))

    def test_update_final_items_empty_inputs(self):
        """Test update_final_items function with empty inputs"""
        prev_items = []
        buy_items = []
        not_sell_items = []

        result = update_final_items(prev_items, buy_items, not_sell_items)

        # Should return empty list
        self.assertEqual(result, [])

    @patch("main.logger")
    def test_log_stock_info(self, mock_logger):
        """Test log_stock_info function"""
        symbol = "AAPL"

        log_stock_info(symbol, self.mock_correlations)

        # Verify logger.debug was called
        mock_logger.debug.assert_called_once()

    def test_calculate_correlations_empty_symbols(self):
        """Test calculate_correlations with empty symbols list"""
        empty_finder = MagicMock()
        empty_finder.symbols = []
        empty_finder.price_volume_correlation_percent.return_value = {}

        result = calculate_correlations(empty_finder)

        # Should still return the expected structure
        self.assertIn("200", result)
        self.assertIn("100", result)
        self.assertIn("50", result)

        # All periods should have empty dictionaries
        for period in result.values():
            self.assertEqual(period, {})

    def test_select_stocks_edge_case_correlations(self):
        """Test select_stocks with edge case correlation values"""
        # Mock the has_valid_trend_template method
        self.mock_finder.has_valid_trend_template.side_effect = [
            {"AAPL": True, "MSFT": True, "GOOGL": True},  # margin 0
            {"AAPL": True, "MSFT": True, "GOOGL": True},  # margin 0.1
        ]

        # Test with correlation exactly at thresholds
        edge_correlations = {
            "200": {"AAPL": 75.5, "MSFT": 82.3, "GOOGL": 68.9},
            "100": {"AAPL": 71.2, "MSFT": 78.9, "GOOGL": 65.4},
            "50": {"AAPL": 50.0, "MSFT": 40.0, "GOOGL": 39.9},  # Edge cases
        }

        buy_items, not_sell_items = select_stocks(self.mock_finder, edge_correlations)

        # AAPL should be in buy_items (correlation = 50.0)
        self.assertIn("AAPL", buy_items)
        # MSFT should be in not_sell_items (correlation = 40.0)
        self.assertIn("MSFT", not_sell_items)
        # GOOGL should not be in either (correlation < 40.0)
        self.assertNotIn("GOOGL", buy_items)
        self.assertNotIn("GOOGL", not_sell_items)

    @patch("main.fetch_account_balance")
    def test_calculate_investment_per_stock_success(self, mock_fetch_balance):
        """Test calculate_investment_per_stock with successful balance fetch"""
        # Mock account balance
        mock_fetch_balance.return_value = {
            "available_cash": 10000.0,
            "buyable_cash": 9500.0,
            "total_balance": 50000.0,
        }

        buy_items = ["AAPL", "MSFT", "GOOGL"]

        result = calculate_investment_per_stock(buy_items)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 3)
        # With default reserve_ratio (0.1), 9500 * 0.9 / 3 = 2850 per stock
        expected_investment = 9500.0 * 0.9 / 3
        self.assertAlmostEqual(result["AAPL"], expected_investment, places=2)
        self.assertAlmostEqual(result["MSFT"], expected_investment, places=2)
        self.assertAlmostEqual(result["GOOGL"], expected_investment, places=2)

    @patch("main.fetch_account_balance")
    def test_calculate_investment_per_stock_with_reserve(self, mock_fetch_balance):
        """Test calculate_investment_per_stock with custom reserve ratio"""
        mock_fetch_balance.return_value = {
            "available_cash": 10000.0,
            "buyable_cash": 10000.0,
            "total_balance": 50000.0,
        }

        buy_items = ["AAPL", "MSFT"]

        result = calculate_investment_per_stock(buy_items, reserve_ratio=0.2)

        self.assertIsNotNone(result)
        # With reserve_ratio=0.2, 10000 * 0.8 / 2 = 4000 per stock
        expected_investment = 10000.0 * 0.8 / 2
        self.assertAlmostEqual(result["AAPL"], expected_investment, places=2)

    @patch("main.fetch_account_balance")
    def test_calculate_investment_per_stock_with_min_investment(self, mock_fetch_balance):
        """Test calculate_investment_per_stock with minimum investment constraint"""
        mock_fetch_balance.return_value = {
            "available_cash": 1000.0,
            "buyable_cash": 1000.0,
            "total_balance": 5000.0,
        }

        buy_items = ["AAPL", "MSFT", "GOOGL", "TSLA"]

        # With 1000 cash and 10% reserve = 900, divided by 4 = 225 per stock
        # But min_investment is 300, so all stocks are below minimum
        # New logic: excludes stocks that can't meet minimum investment
        result = calculate_investment_per_stock(buy_items, min_investment=300.0)

        # All stocks are below minimum investment, so result should be None
        self.assertIsNone(result)

    @patch("main.fetch_account_balance")
    def test_calculate_investment_per_stock_with_max_investment(self, mock_fetch_balance):
        """Test calculate_investment_per_stock with maximum investment constraint"""
        mock_fetch_balance.return_value = {
            "available_cash": 10000.0,
            "buyable_cash": 10000.0,
            "total_balance": 50000.0,
        }

        buy_items = ["AAPL"]

        result = calculate_investment_per_stock(buy_items, max_investment=5000.0)

        self.assertIsNotNone(result)
        # Without max, would be 9000, but max is 5000
        self.assertLessEqual(result["AAPL"], 5000.0)

    @patch("main.fetch_account_balance")
    def test_calculate_investment_per_stock_no_balance(self, mock_fetch_balance):
        """Test calculate_investment_per_stock when balance fetch fails"""
        mock_fetch_balance.return_value = None

        buy_items = ["AAPL", "MSFT"]

        result = calculate_investment_per_stock(buy_items)

        self.assertIsNone(result)

    @patch("main.fetch_account_balance")
    def test_calculate_investment_per_stock_no_buy_items(self, _mock_fetch_balance):
        """Test calculate_investment_per_stock with empty buy items"""
        result = calculate_investment_per_stock([])

        self.assertIsNone(result)

    @patch("main.fetch_account_balance")
    def test_calculate_investment_per_stock_insufficient_cash(self, mock_fetch_balance):
        """Test calculate_investment_per_stock with insufficient cash"""
        mock_fetch_balance.return_value = {
            "available_cash": 50.0,
            "buyable_cash": 50.0,
            "total_balance": 100.0,
        }

        buy_items = ["AAPL", "MSFT"]

        # With 50 cash, 10% reserve = 45, divided by 2 = 22.5 per stock
        # But min_investment default is 100, so insufficient
        result = calculate_investment_per_stock(buy_items, min_investment=100.0)

        self.assertIsNone(result)

    @patch("main.fetch_holdings_detail")
    def test_calculate_share_quantities_success(self, mock_fetch_holdings):
        """Test calculate_share_quantities with successful calculation"""
        # Mock finder
        mock_finder = MagicMock()
        mock_finder.current_price = {"AAPL": 150.0, "MSFT": 300.0}

        # Mock holdings
        mock_fetch_holdings.return_value = [
            {"symbol": "AAPL", "quantity": 10.0, "avg_price": 140.0, "current_price": 150.0}
        ]

        investment_map = {"AAPL": 3000.0, "MSFT": 3000.0}

        result = calculate_share_quantities(investment_map, mock_finder)

        self.assertIsNotNone(result)
        self.assertIn("AAPL", result)
        self.assertIn("MSFT", result)

        # AAPL: 3000 / 150 = 20 shares (target), already holding 10
        # additional_buy = max(20 - 10, 0) = 10 shares
        # total_after_buy = 10 + 10 = 20 shares
        aapl_info = result["AAPL"]
        self.assertEqual(aapl_info["shares_to_buy"], 20)  # Target total shares
        self.assertEqual(aapl_info["current_quantity"], 10)  # Currently holding
        self.assertEqual(aapl_info["additional_buy"], 10)  # Additional shares to buy
        self.assertEqual(aapl_info["total_after_buy"], 20)  # Total after buying

        # MSFT: 3000 / 300 = 10 shares, not holding
        msft_info = result["MSFT"]
        self.assertEqual(msft_info["shares_to_buy"], 10)
        self.assertEqual(msft_info["current_quantity"], 0)
        self.assertEqual(msft_info["total_after_buy"], 10)

    @patch("main.fetch_holdings_detail")
    def test_calculate_sell_quantities_success(self, mock_fetch_holdings):
        """Test calculate_sell_quantities with successful calculation"""
        # Mock finder
        mock_finder = MagicMock()
        mock_finder.current_price = {"TSLA": 250.0}

        # Mock holdings
        mock_fetch_holdings.return_value = [
            {
                "symbol": "TSLA",
                "quantity": 20.0,
                "avg_price": 200.0,
                "current_price": 250.0,
                "profit_loss": 1000.0,
                "profit_loss_rate": 25.0,
            }
        ]

        sell_items = ["TSLA"]

        result = calculate_sell_quantities(sell_items, mock_finder)

        self.assertIsNotNone(result)
        self.assertIn("TSLA", result)

        tsla_info = result["TSLA"]
        self.assertEqual(tsla_info["shares_to_sell"], 20)
        self.assertEqual(tsla_info["current_price"], 250.0)
        self.assertEqual(tsla_info["sell_amount"], 5000.0)
        self.assertEqual(tsla_info["profit_loss"], 1000.0)
        self.assertEqual(tsla_info["profit_loss_rate"], 25.0)

    @patch("main.fetch_holdings_detail")
    def test_generate_telegram_message_with_share_quantities(self, _mock_fetch_holdings):
        """Test generate_telegram_message with share quantities"""
        prev_items = ["AAPL"]
        buy_items = ["AAPL", "MSFT"]
        not_sell_items = ["AAPL"]

        share_quantities = {
            "MSFT": {
                "investment_amount": 3000.0,
                "current_price": 300.0,
                "shares_to_buy": 10,
                "current_quantity": 0,
                "total_after_buy": 10,
            }
        }

        result = generate_telegram_message(prev_items, buy_items, not_sell_items, share_quantities)

        self.assertIsNotNone(result)
        # Check that message contains investment details
        message_text = "\n".join(result)
        self.assertIn("MSFT", message_text)
        self.assertIn("3,000", message_text)  # Investment amount (formatted)
        self.assertIn("10", message_text)  # Shares to buy
        self.assertIn("300.00", message_text)  # Current price

    def test_generate_telegram_message_with_avsl_sell_signal(self):
        """Test generate_telegram_message with AVSL sell signals"""
        prev_items = ["AAPL", "MSFT", "TSLA"]
        buy_items = ["AAPL", "MSFT"]
        not_sell_items = ["AAPL", "MSFT"]

        sell_quantities = {
            "TSLA": {
                "current_quantity": 20,
                "current_price": 250.0,
                "shares_to_sell": 20,
                "sell_amount": 5000.0,
                "profit_loss": 1000.0,
                "profit_loss_rate": 25.0,
            }
        }

        avsl_sell_items = ["TSLA"]

        result = generate_telegram_message(
            prev_items, buy_items, not_sell_items, None, sell_quantities, avsl_sell_items
        )

        self.assertIsNotNone(result)
        message_text = "\n".join(result)
        self.assertIn("TSLA", message_text)
        self.assertIn("AVSL", message_text)  # AVSL signal mentioned
        self.assertIn("5,000", message_text)  # Sell amount (formatted)


if __name__ == "__main__":
    unittest.main()
