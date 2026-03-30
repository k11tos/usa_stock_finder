"""
test_main.py

This module contains unit tests for the main module.
It tests the main functions for stock analysis and selection.
"""

import unittest
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import MagicMock, patch

from main import (
    calculate_profit_loss_rate_safely,
    calculate_correlations,
    calculate_investment_per_stock,
    is_profit_loss_rate_mismatch,
    calculate_sell_quantities,
    calculate_share_quantities,
    generate_telegram_message,
    is_within_execution_window,
    log_stock_info,
    main,
    select_stocks,
    update_final_items,
)
from sell_signals import SellDecision, SellReason


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

        # TSLA is not in buy_items or not_sell_items, so it should be sold due to trend
        sell_decisions = {"TSLA": SellDecision("TSLA", SellReason.TREND, 100.0)}

        result = generate_telegram_message(prev_items, buy_items, not_sell_items, None, None, sell_decisions)

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

    @patch("main.ScheduleConfig.TIME_CHECK_ENABLED", False)
    def test_is_within_execution_window_time_check_disabled(self):
        """Should always allow execution when time check is disabled."""
        self.assertTrue(is_within_execution_window())

    @patch("main.ScheduleConfig.TIME_CHECK_ENABLED", True)
    @patch("main.ScheduleConfig.TIMEZONE", "Asia/Seoul")
    @patch("main.ScheduleConfig.EXECUTION_HOUR", 20)
    @patch("main.ScheduleConfig.EXECUTION_MINUTE", 0)
    @patch("main.ScheduleConfig.EXECUTION_MARGIN_MINUTES", 10)
    @patch("main.datetime")
    def test_is_within_execution_window_inside_and_boundaries(self, mock_datetime):
        """Should return True when current time is inside window or exactly on boundaries."""
        mock_datetime.combine.side_effect = datetime.combine

        # Exactly at target time
        mock_datetime.now.return_value = datetime(2026, 1, 1, 20, 0, 0)
        self.assertTrue(is_within_execution_window())

        # Exactly at start boundary: 19:50
        mock_datetime.now.return_value = datetime(2026, 1, 1, 19, 50, 0)
        self.assertTrue(is_within_execution_window())

        # Exactly at end boundary: 20:10
        mock_datetime.now.return_value = datetime(2026, 1, 1, 20, 10, 0)
        self.assertTrue(is_within_execution_window())

    @patch("main.ScheduleConfig.TIME_CHECK_ENABLED", True)
    @patch("main.ScheduleConfig.TIMEZONE", "Asia/Seoul")
    @patch("main.ScheduleConfig.EXECUTION_HOUR", 20)
    @patch("main.ScheduleConfig.EXECUTION_MINUTE", 0)
    @patch("main.ScheduleConfig.EXECUTION_MARGIN_MINUTES", 10)
    @patch("main.datetime")
    def test_is_within_execution_window_outside_window(self, mock_datetime):
        """Should return False when current time is outside execution window."""
        mock_datetime.combine.side_effect = datetime.combine
        mock_datetime.now.return_value = datetime(2026, 1, 1, 20, 11, 0)

        self.assertFalse(is_within_execution_window())

    @patch("main.ScheduleConfig.TIME_CHECK_ENABLED", True)
    @patch("main.ScheduleConfig.TIMEZONE", "Asia/Seoul")
    @patch("main.ScheduleConfig.EXECUTION_HOUR", 0)
    @patch("main.ScheduleConfig.EXECUTION_MINUTE", 5)
    @patch("main.ScheduleConfig.EXECUTION_MARGIN_MINUTES", 10)
    @patch("main.datetime")
    def test_is_within_execution_window_crossing_midnight(self, mock_datetime):
        """Should handle execution windows that cross midnight."""
        mock_datetime.combine.side_effect = datetime.combine

        # In-window on previous day side (23:58)
        mock_datetime.now.return_value = datetime(2026, 1, 1, 23, 58, 0)
        self.assertTrue(is_within_execution_window())

        # In-window on next day side (00:12)
        mock_datetime.now.return_value = datetime(2026, 1, 1, 0, 12, 0)
        self.assertTrue(is_within_execution_window())

        # Out of window (00:16)
        mock_datetime.now.return_value = datetime(2026, 1, 1, 0, 16, 0)
        self.assertFalse(is_within_execution_window())

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
        # But min_investment is 300, so all stocks are below minimum.
        # NOTE: A future behavior-change PR could consider reducing candidate count
        # and recomputing sizing, but current behavior should remain unchanged here.
        result = calculate_investment_per_stock(buy_items, min_investment=300.0)

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
    @patch("main.InvestmentConfig.DISTRIBUTION_STRATEGY", "equal")
    def test_calculate_investment_per_stock_additional_cash_increases_buyable_cash(self, mock_fetch_balance):
        """Additional cash should increase effective buyable cash before sizing."""
        mock_fetch_balance.return_value = {
            "available_cash": 100.0,
            "buyable_cash": 100.0,
            "total_balance": 1000.0,
        }

        buy_items = ["AAPL", "MSFT"]
        result = calculate_investment_per_stock(
            buy_items,
            reserve_ratio=0.0,
            min_investment=1.0,
            additional_cash=100.0,
        )

        self.assertEqual(result, {"AAPL": 100.0, "MSFT": 100.0})

    @patch("main.fetch_account_balance")
    @patch("main.InvestmentConfig.PROPORTIONAL_PERCENTAGE", 0.1)
    @patch("main.InvestmentConfig.DISTRIBUTION_STRATEGY", "proportional")
    def test_calculate_investment_per_stock_proportional_distribution(self, mock_fetch_balance):
        """Proportional strategy should use total balance percentage per stock."""
        mock_fetch_balance.return_value = {
            "available_cash": 10000.0,
            "buyable_cash": 9000.0,
            "total_balance": 50000.0,
        }

        buy_items = ["AAPL", "MSFT", "GOOGL"]
        result = calculate_investment_per_stock(buy_items, min_investment=100.0)

        self.assertIsNotNone(result)
        self.assertEqual(result, {"AAPL": 5000.0, "MSFT": 5000.0, "GOOGL": 5000.0})

    @patch("main.fetch_account_balance")
    @patch("main.InvestmentConfig.PROPORTIONAL_PERCENTAGE", 0.2)
    @patch("main.InvestmentConfig.DISTRIBUTION_STRATEGY", "proportional")
    def test_calculate_investment_per_stock_proportional_distribution_with_max_cap(self, mock_fetch_balance):
        """Proportional sizing should still respect max investment cap."""
        mock_fetch_balance.return_value = {
            "available_cash": 10000.0,
            "buyable_cash": 9000.0,
            "total_balance": 50000.0,
        }

        buy_items = ["AAPL", "MSFT"]
        result = calculate_investment_per_stock(
            buy_items,
            min_investment=100.0,
            max_investment=6000.0,
        )

        self.assertEqual(result, {"AAPL": 6000.0, "MSFT": 6000.0})

    @patch("main.fetch_account_balance")
    @patch("main.InvestmentConfig.DISTRIBUTION_STRATEGY", "equal")
    def test_calculate_investment_per_stock_equal_distribution_min_filtering_is_all_or_nothing(
        self, mock_fetch_balance
    ):
        """Equal-distribution min filtering currently behaves as all-or-nothing across candidates."""
        mock_fetch_balance.return_value = {
            "available_cash": 500.0,
            "buyable_cash": 500.0,
            "total_balance": 500.0,
        }

        buy_items = ["AAPL", "MSFT", "GOOGL"]
        result = calculate_investment_per_stock(
            buy_items,
            reserve_ratio=0.0,
            min_investment=200.0,
        )

        # Under current implementation, all symbols receive the same target investment,
        # so filtering by min investment is all-or-nothing.
        # NOTE: Mixed-subset affordability could be explored in a future behavior-change PR.
        self.assertIsNone(result)

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

        # AAPL: 3000 / 150 = 20 shares (target total quantity)
        # Currently holding 10 shares
        # shares_to_buy = max(20 - 10, 0) = 10 shares (additional buy)
        # total_after_buy = 10 + 10 = 20 shares
        aapl_info = result["AAPL"]
        self.assertEqual(aapl_info["shares_to_buy"], 10)  # Actual shares to buy (additional)
        self.assertEqual(aapl_info["current_quantity"], 10)  # Currently holding
        self.assertEqual(aapl_info["additional_buy"], 10)  # Additional shares to buy (same as shares_to_buy)
        self.assertEqual(aapl_info["total_after_buy"], 20)  # Total after buying

        # MSFT: 3000 / 300 = 10 shares (target total), not holding any
        # shares_to_buy = 10 shares (new buy)
        msft_info = result["MSFT"]
        self.assertEqual(msft_info["shares_to_buy"], 10)  # New buy quantity
        self.assertEqual(msft_info["current_quantity"], 0)  # Not holding
        self.assertEqual(msft_info["total_after_buy"], 10)  # Total after buying

    def test_calculate_share_quantities_filters_symbol_when_existing_holding_above_target(self):
        """Symbol should be filtered out when current holding already exceeds target quantity."""
        mock_finder = MagicMock()
        mock_finder.current_price = {"AAPL": 100.0}

        investment_map = {"AAPL": 500.0}  # target_total_quantity = 5
        current_holdings = [{"symbol": "AAPL", "quantity": 8.0}]

        result = calculate_share_quantities(investment_map, mock_finder, current_holdings)

        self.assertIsNone(result)

    def test_calculate_share_quantities_skips_invalid_current_price(self):
        """Invalid current price should cause symbol to be skipped."""
        mock_finder = MagicMock()
        mock_finder.current_price = {"AAPL": 0.0}

        investment_map = {"AAPL": 1000.0}
        current_holdings = []

        result = calculate_share_quantities(investment_map, mock_finder, current_holdings)

        self.assertIsNone(result)

    def test_calculate_share_quantities_skips_too_small_investment_amount(self):
        """Too-small investment that results in zero shares should be skipped."""
        mock_finder = MagicMock()
        mock_finder.current_price = {"AAPL": 1000.0}

        investment_map = {"AAPL": 10.0}  # target_total_quantity = 0
        current_holdings = []

        result = calculate_share_quantities(investment_map, mock_finder, current_holdings)

        self.assertIsNone(result)

    def test_calculate_share_quantities_returns_partial_result_when_one_symbol_is_skipped(self):
        """Should return only valid symbol when another symbol is skipped."""
        mock_finder = MagicMock()
        mock_finder.current_price = {"AAPL": 100.0, "MSFT": 0.0}

        investment_map = {"AAPL": 1000.0, "MSFT": 1000.0}
        current_holdings = []

        result = calculate_share_quantities(investment_map, mock_finder, current_holdings)

        self.assertIsNotNone(result)
        self.assertEqual(list(result.keys()), ["AAPL"])
        self.assertEqual(result["AAPL"]["shares_to_buy"], 10)
        self.assertNotIn("MSFT", result)

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

    def test_calculate_sell_quantities_uses_finder_price_when_available(self):
        """Test sell sizing uses finder.current_price when it is positive"""
        mock_finder = MagicMock()
        mock_finder.current_price = {"TSLA": 250.0}

        current_holdings = [
            {
                "symbol": "TSLA",
                "quantity": 10.0,
                "avg_price": 200.0,
                "current_price": 240.0,
                "profit_loss": 400.0,
                "profit_loss_rate": 20.0,
            }
        ]

        result = calculate_sell_quantities(["TSLA"], mock_finder, current_holdings)

        self.assertIsNotNone(result)
        self.assertEqual(result["TSLA"]["current_price"], 250.0)
        self.assertEqual(result["TSLA"]["sell_amount"], 2500.0)

    def test_calculate_sell_quantities_falls_back_to_holdings_price(self):
        """Test sell sizing uses holding.current_price when finder price is missing or zero"""
        mock_finder = MagicMock()
        mock_finder.current_price = {"TSLA": 0.0}

        current_holdings = [
            {
                "symbol": "TSLA",
                "quantity": 10.0,
                "avg_price": 200.0,
                "current_price": 245.0,
                "profit_loss": 450.0,
                "profit_loss_rate": 22.5,
            },
            {
                "symbol": "AAPL",
                "quantity": 5.0,
                "avg_price": 180.0,
                "current_price": 190.0,
                "profit_loss": 50.0,
                "profit_loss_rate": 5.56,
            },
        ]

        result = calculate_sell_quantities(["TSLA", "AAPL"], mock_finder, current_holdings)

        self.assertIsNotNone(result)
        self.assertEqual(result["TSLA"]["current_price"], 245.0)  # finder price is zero
        self.assertEqual(result["AAPL"]["current_price"], 190.0)  # finder price is missing

    def test_calculate_sell_quantities_skips_symbol_missing_from_holdings(self):
        """Test symbols not in holdings are skipped"""
        mock_finder = MagicMock()
        mock_finder.current_price = {"TSLA": 250.0}

        current_holdings = [
            {
                "symbol": "AAPL",
                "quantity": 5.0,
                "avg_price": 180.0,
                "current_price": 190.0,
            }
        ]

        result = calculate_sell_quantities(["TSLA"], mock_finder, current_holdings)

        self.assertIsNone(result)

    def test_calculate_sell_quantities_skips_zero_quantity_holding(self):
        """Test holdings with zero quantity are skipped"""
        mock_finder = MagicMock()
        mock_finder.current_price = {"TSLA": 250.0}

        current_holdings = [
            {
                "symbol": "TSLA",
                "quantity": 0.0,
                "avg_price": 200.0,
                "current_price": 240.0,
            }
        ]

        result = calculate_sell_quantities(["TSLA"], mock_finder, current_holdings)

        self.assertIsNone(result)

    def test_calculate_sell_quantities_skips_when_both_prices_invalid(self):
        """Test symbol is skipped when both finder and holdings prices are invalid"""
        mock_finder = MagicMock()
        mock_finder.current_price = {"TSLA": 0.0}

        current_holdings = [
            {
                "symbol": "TSLA",
                "quantity": 10.0,
                "avg_price": 200.0,
                "current_price": 0.0,
            }
        ]

        result = calculate_sell_quantities(["TSLA"], mock_finder, current_holdings)

        self.assertIsNone(result)

    def test_calculate_profit_loss_rate_safely(self):
        """Profit/loss percentage should be calculated only when avg_price is positive."""
        self.assertEqual(calculate_profit_loss_rate_safely(200.0, 250.0), 25.0)
        self.assertIsNone(calculate_profit_loss_rate_safely(0.0, 250.0))

    def test_is_profit_loss_rate_mismatch_threshold_behavior(self):
        """Mismatch check should preserve existing 0.1% threshold behavior."""
        self.assertFalse(is_profit_loss_rate_mismatch(25.0, 25.09))  # below 0.1 => no warning
        self.assertTrue(is_profit_loss_rate_mismatch(25.0, 25.11))  # over 0.1 => warning

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

        sell_decisions = {"TSLA": SellDecision("TSLA", SellReason.AVSL, 20.0)}

        result = generate_telegram_message(prev_items, buy_items, not_sell_items, None, sell_quantities, sell_decisions)

        self.assertIsNotNone(result)
        message_text = "\n".join(result)
        self.assertIn("TSLA", message_text)
        self.assertIn("AVSL", message_text)  # AVSL signal mentioned
        self.assertIn("5,000", message_text)  # Sell amount (formatted)


class TestMainOrchestrationSmoke(unittest.TestCase):
    """Conservative orchestration smoke tests for main.main()."""

    def test_main_happy_path_smoke(self):
        """Main orchestration should call critical integration points with mocked dependencies."""
        with ExitStack() as stack:
            mock_setup_logging = stack.enter_context(patch("main.setup_logging"))
            mock_load_dotenv = stack.enter_context(patch("main.load_dotenv"))
            mock_execution_window = stack.enter_context(patch("main.is_within_execution_window"))
            mock_validate = stack.enter_context(patch("main.EnvironmentConfig.validate"))
            mock_env_get = stack.enter_context(patch("main.EnvironmentConfig.get"))
            mock_fetch_holdings = stack.enter_context(patch("main.fetch_us_stock_holdings"))
            mock_read_csv = stack.enter_context(patch("main.read_csv_first_column"))
            mock_finder_cls = stack.enter_context(patch("main.UsaStockFinder"))
            mock_calculate_correlations = stack.enter_context(patch("main.calculate_correlations"))
            mock_select_stocks = stack.enter_context(patch("main.select_stocks"))
            mock_in_cooldown = stack.enter_context(patch("main.is_in_cooldown"))
            mock_fetch_holdings_detail = stack.enter_context(patch("main.fetch_holdings_detail"))
            mock_evaluate_sell = stack.enter_context(patch("main.evaluate_sell_decisions"))
            mock_calculate_sell_quantities = stack.enter_context(patch("main.calculate_sell_quantities"))
            mock_calculate_investment = stack.enter_context(patch("main.calculate_investment_per_stock"))
            mock_calculate_share_quantities = stack.enter_context(patch("main.calculate_share_quantities"))
            mock_generate_message = stack.enter_context(patch("main.generate_telegram_message"))
            mock_update_final_items = stack.enter_context(patch("main.update_final_items"))
            mock_send_telegram = stack.enter_context(patch("main.send_telegram_message"))
            mock_save_json = stack.enter_context(patch("main.save_json"))

            mock_execution_window.return_value = True
            env_values = {
                "TELEGRAM_BOT_TOKEN": "fake-bot-token",
                "TELEGRAM_CHAT_ID": "fake-chat-id",
            }
            mock_env_get.side_effect = env_values.get
            mock_fetch_holdings.return_value = ["AAPL"]
            mock_read_csv.return_value = ["AAPL", "MSFT"]

            mock_finder = MagicMock()
            mock_finder.is_data_valid.return_value = True
            mock_finder.check_avsl_sell_signal.return_value = {"AAPL": False}
            mock_finder.current_price = {"AAPL": 100.0, "MSFT": 200.0}
            mock_finder_cls.return_value = mock_finder

            mock_calculate_correlations.return_value = {"50": {"AAPL": 55.0, "MSFT": 52.0}}
            mock_select_stocks.return_value = (["MSFT"], ["AAPL"])
            mock_in_cooldown.return_value = False
            mock_fetch_holdings_detail.return_value = [{"symbol": "AAPL", "quantity": 1.0}]
            mock_evaluate_sell.return_value = {}
            mock_calculate_sell_quantities.return_value = None
            mock_calculate_investment.return_value = {"MSFT": 500.0}
            mock_calculate_share_quantities.return_value = {"MSFT": {"shares_to_buy": 2}}
            mock_generate_message.return_value = ["2026-01-01", "Buy MSFT"]
            mock_update_final_items.return_value = ["AAPL", "MSFT"]

            main()

            mock_setup_logging.assert_called_once()
            mock_load_dotenv.assert_called_once()
            mock_execution_window.assert_called_once()
            mock_validate.assert_called_once()
            mock_fetch_holdings.assert_called_once()
            mock_read_csv.assert_called_once()
            mock_finder_cls.assert_called_once_with(["AAPL", "MSFT"])
            mock_calculate_correlations.assert_called_once_with(mock_finder)
            mock_select_stocks.assert_called_once()
            mock_evaluate_sell.assert_called_once()
            mock_calculate_investment.assert_called_once()
            mock_generate_message.assert_called_once()
            mock_send_telegram.assert_called_once()
            mock_save_json.assert_called_once_with(["AAPL", "MSFT"], "data/data.json")

    def test_main_filters_cooldown_before_sell_evaluation(self):
        """Cooldown-filtered symbols should not be passed as selected_buy into sell evaluation."""
        with ExitStack() as stack:
            stack.enter_context(patch("main.setup_logging"))
            stack.enter_context(patch("main.load_dotenv"))
            mock_execution_window = stack.enter_context(patch("main.is_within_execution_window"))
            stack.enter_context(patch("main.EnvironmentConfig.validate"))
            stack.enter_context(patch("main.EnvironmentConfig.get", return_value=None))
            stack.enter_context(patch("main.fetch_us_stock_holdings", return_value=["AAPL"]))
            stack.enter_context(patch("main.read_csv_first_column", return_value=["AAPL", "MSFT"]))
            mock_finder_cls = stack.enter_context(patch("main.UsaStockFinder"))
            stack.enter_context(patch("main.calculate_correlations", return_value={"50": {"AAPL": 55.0, "MSFT": 55.0}}))
            stack.enter_context(patch("main.select_stocks", return_value=(["AAPL", "MSFT"], [])))
            mock_in_cooldown = stack.enter_context(patch("main.is_in_cooldown"))
            stack.enter_context(patch("main.fetch_holdings_detail", return_value=[{"symbol": "AAPL", "quantity": 1.0}]))
            mock_evaluate_sell = stack.enter_context(patch("main.evaluate_sell_decisions", return_value={}))
            stack.enter_context(patch("main.calculate_sell_quantities", return_value=None))
            stack.enter_context(patch("main.calculate_investment_per_stock", return_value={"AAPL": 500.0}))
            stack.enter_context(patch("main.calculate_share_quantities", return_value={"AAPL": {"shares_to_buy": 1}}))
            stack.enter_context(patch("main.generate_telegram_message", return_value=None))
            stack.enter_context(patch("main.update_final_items", return_value=["AAPL"]))
            stack.enter_context(patch("main.send_telegram_message"))
            stack.enter_context(patch("main.save_json"))

            mock_execution_window.return_value = True
            mock_in_cooldown.side_effect = lambda symbol, _today: symbol == "MSFT"

            mock_finder = MagicMock()
            mock_finder.is_data_valid.return_value = True
            mock_finder.check_avsl_sell_signal.return_value = {"AAPL": False}
            mock_finder.current_price = {"AAPL": 100.0, "MSFT": 200.0}
            mock_finder_cls.return_value = mock_finder

            main()

            self.assertTrue(mock_evaluate_sell.called)
            self.assertEqual(mock_evaluate_sell.call_args.kwargs["selected_buy"], ["AAPL"])

    def test_main_logs_end_of_run_summary(self):
        """Main should log a concise run summary at the end of orchestration."""
        with ExitStack() as stack:
            stack.enter_context(patch("main.setup_logging"))
            stack.enter_context(patch("main.load_dotenv"))
            stack.enter_context(patch("main.is_within_execution_window", return_value=True))
            stack.enter_context(patch("main.EnvironmentConfig.validate"))
            stack.enter_context(patch("main.EnvironmentConfig.get", return_value=None))
            stack.enter_context(patch("main.fetch_us_stock_holdings", return_value=["AAPL", "TSLA"]))
            stack.enter_context(patch("main.read_csv_first_column", return_value=["AAPL", "MSFT"]))
            mock_finder_cls = stack.enter_context(patch("main.UsaStockFinder"))
            stack.enter_context(patch("main.calculate_correlations", return_value={"50": {"AAPL": 60.0, "MSFT": 60.0}}))
            stack.enter_context(patch("main.select_stocks", return_value=(["MSFT"], ["AAPL"])))
            stack.enter_context(patch("main.is_in_cooldown", return_value=False))
            stack.enter_context(patch("main.fetch_holdings_detail", return_value=[{"symbol": "TSLA", "quantity": 2.0}]))
            stack.enter_context(
                patch(
                    "main.evaluate_sell_decisions",
                    return_value={"TSLA": SellDecision("TSLA", SellReason.TREND, 2.0)},
                )
            )
            stack.enter_context(
                patch(
                    "main.calculate_sell_quantities",
                    return_value={"TSLA": {"shares_to_sell": 2, "sell_amount": 500.0}},
                )
            )
            stack.enter_context(patch("main.calculate_investment_per_stock", return_value={"MSFT": 300.0}))
            stack.enter_context(patch("main.calculate_share_quantities", return_value={"MSFT": {"shares_to_buy": 1}}))
            stack.enter_context(patch("main.generate_telegram_message", return_value=None))
            stack.enter_context(patch("main.update_final_items", return_value=["AAPL", "MSFT"]))
            stack.enter_context(patch("main.save_json"))
            mock_logger = stack.enter_context(patch("main.logger"))

            mock_finder = MagicMock()
            mock_finder.is_data_valid.return_value = True
            mock_finder.current_price = {"AAPL": 100.0, "MSFT": 200.0}
            mock_finder_cls.return_value = mock_finder

            main()

            summary_calls = [
                call
                for call in mock_logger.info.call_args_list
                if call.args and isinstance(call.args[0], str) and call.args[0].startswith("RUN_SUMMARY")
            ]
            self.assertEqual(len(summary_calls), 1)
            summary_message = summary_calls[0].args[0]
            self.assertIn("prev_holdings=%d", summary_message)
            self.assertIn("buy_items=%d", summary_message)
            self.assertIn("final_saved_items=%d", summary_message)

    @patch("main.save_json")
    @patch("main.fetch_us_stock_holdings")
    @patch("main.EnvironmentConfig.validate")
    @patch("main.is_within_execution_window")
    @patch("main.load_dotenv")
    @patch("main.setup_logging")
    def test_main_returns_early_outside_execution_window(
        self,
        mock_setup_logging,
        mock_load_dotenv,
        mock_execution_window,
        mock_validate,
        mock_fetch_holdings,
        mock_save_json,
    ):
        """Main should exit before integration work when outside the allowed execution window."""
        mock_execution_window.return_value = False

        main()

        mock_setup_logging.assert_called_once()
        mock_load_dotenv.assert_called_once()
        mock_execution_window.assert_called_once()
        mock_validate.assert_not_called()
        mock_fetch_holdings.assert_not_called()
        mock_save_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
