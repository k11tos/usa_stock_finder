"""
test_main.py

This module contains unit tests for the main module.
It tests the main functions for stock analysis and selection.
"""

import unittest
from unittest.mock import MagicMock, patch

from main import calculate_correlations, generate_telegram_message, log_stock_info, select_stocks, update_final_items


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
        self.assertIn("Buy TSLA", result)
        # No sell message since all prev items are in keep_items

    def test_generate_telegram_message_with_sell_signals(self):
        """Test generate_telegram_message function with sell signals"""
        prev_items = ["AAPL", "MSFT", "GOOGL", "TSLA"]
        buy_items = ["AAPL", "MSFT"]
        not_sell_items = ["AAPL", "MSFT", "GOOGL"]

        result = generate_telegram_message(prev_items, buy_items, not_sell_items)

        # Should return a message with sell signal for TSLA
        self.assertIsNotNone(result)
        self.assertIn("Sell TSLA", result)

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


if __name__ == "__main__":
    unittest.main()
