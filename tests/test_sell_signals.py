"""
test_sell_signals.py

This module contains unit tests for the sell_signals module.
It tests the 3-tier sell decision system, including the EGAN case where
a -19% loss should trigger a stop loss sell regardless of other conditions.
"""

import unittest
from unittest.mock import MagicMock

from sell_signals import SellReason, evaluate_sell_decisions


class TestSellSignals(unittest.TestCase):
    """Test sell signals module"""

    def setUp(self):
        """Set up test fixtures"""
        # Mock UsaStockFinder instance
        self.mock_finder = MagicMock()
        self.mock_finder.current_price = {}

    def test_egan_case_stop_loss_priority(self):
        """
        Test EGAN case: -19% loss should trigger stop loss regardless of other conditions.

        Scenario:
        - EGAN has avg_price = 100, current_price = 81 (-19% loss)
        - STOP_LOSS_PCT = 0.10 (10%)
        - AVSL signal = False
        - Stock is in selected_buy or selected_not_sell (should still sell due to stop loss)
        """
        # Setup: EGAN with -19% loss
        symbol = "EGAN"
        avg_price = 100.0
        current_price = 81.0  # -19% loss
        quantity = 100.0

        # Mock finder with EGAN price
        self.mock_finder.current_price = {symbol: current_price}

        # Create holdings
        holdings = [
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": avg_price,
                "current_price": current_price,
            }
        ]

        # Test case 1: EGAN is in selected_buy but should still sell due to stop loss
        selected_buy = [symbol]  # EGAN is in buy list
        selected_not_sell = []
        avsl_signals = {symbol: False}  # No AVSL signal

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=selected_buy,
            selected_not_sell=selected_not_sell,
            avsl_signals=avsl_signals,
        )

        # Assert: Should sell due to stop loss (highest priority)
        self.assertIn(symbol, decisions)
        decision = decisions[symbol]
        self.assertEqual(decision.reason, SellReason.STOP_LOSS)
        self.assertEqual(decision.quantity, quantity)
        self.assertEqual(decision.symbol, symbol)

        # Test case 2: EGAN is in selected_not_sell but should still sell due to stop loss
        selected_buy = []
        selected_not_sell = [symbol]  # EGAN is in hold list

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=selected_buy,
            selected_not_sell=selected_not_sell,
            avsl_signals=avsl_signals,
        )

        # Assert: Should still sell due to stop loss (takes absolute priority)
        self.assertIn(symbol, decisions)
        decision = decisions[symbol]
        self.assertEqual(decision.reason, SellReason.STOP_LOSS)
        self.assertEqual(decision.quantity, quantity)

        # Test case 3: EGAN has AVSL signal but stop loss should take priority
        avsl_signals = {symbol: True}  # AVSL signal present

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=selected_buy,
            selected_not_sell=selected_not_sell,
            avsl_signals=avsl_signals,
        )

        # Assert: Stop loss should take priority over AVSL
        self.assertIn(symbol, decisions)
        decision = decisions[symbol]
        self.assertEqual(decision.reason, SellReason.STOP_LOSS, "Stop loss should take priority over AVSL")
        self.assertEqual(decision.quantity, quantity)

    def test_stop_loss_threshold(self):
        """Test stop loss threshold at exactly 10% loss"""
        symbol = "TEST"
        avg_price = 100.0
        quantity = 100.0

        # Test case 1: Exactly -10% loss (should trigger stop loss)
        current_price = 90.0  # Exactly -10%
        self.mock_finder.current_price = {symbol: current_price}

        holdings = [
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": avg_price,
                "current_price": current_price,
            }
        ]

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[],
            selected_not_sell=[],
            avsl_signals={symbol: False},
        )

        self.assertEqual(decisions[symbol].reason, SellReason.STOP_LOSS)

        # Test case 2: -9.9% loss (should NOT trigger stop loss)
        current_price = 90.1  # -9.9%
        self.mock_finder.current_price = {symbol: current_price}
        holdings[0]["current_price"] = current_price

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[],
            selected_not_sell=[],
            avsl_signals={symbol: False},
        )

        # Should trigger trend sell (not in buy/not_sell lists)
        self.assertEqual(decisions[symbol].reason, SellReason.TREND)

    def test_avsl_sell_signal(self):
        """Test AVSL sell signal (2nd tier)"""
        symbol = "TEST"
        avg_price = 100.0
        current_price = 95.0  # -5% loss (below stop loss threshold)
        quantity = 100.0

        self.mock_finder.current_price = {symbol: current_price}

        holdings = [
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": avg_price,
                "current_price": current_price,
            }
        ]

        # AVSL signal present, not in buy/not_sell lists
        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[],
            selected_not_sell=[],
            avsl_signals={symbol: True},
        )

        self.assertEqual(decisions[symbol].reason, SellReason.AVSL)
        self.assertEqual(decisions[symbol].quantity, quantity)

    def test_trend_sell_signal(self):
        """Test trend sell signal (3rd tier)"""
        symbol = "TEST"
        avg_price = 100.0
        current_price = 95.0  # -5% loss
        quantity = 100.0

        self.mock_finder.current_price = {symbol: current_price}

        holdings = [
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": avg_price,
                "current_price": current_price,
            }
        ]

        # No AVSL signal, not in buy/not_sell lists
        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[],
            selected_not_sell=[],
            avsl_signals={symbol: False},
        )

        self.assertEqual(decisions[symbol].reason, SellReason.TREND)
        self.assertEqual(decisions[symbol].quantity, quantity)

    def test_hold_decision(self):
        """Test hold decision when stock meets criteria"""
        symbol = "TEST"
        avg_price = 100.0
        current_price = 105.0  # +5% gain
        quantity = 100.0

        self.mock_finder.current_price = {symbol: current_price}

        holdings = [
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": avg_price,
                "current_price": current_price,
            }
        ]

        # Stock is in selected_buy, no AVSL signal
        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[symbol],
            selected_not_sell=[],
            avsl_signals={symbol: False},
        )

        self.assertEqual(decisions[symbol].reason, SellReason.NONE)
        self.assertEqual(decisions[symbol].quantity, 0.0)

        # Stock is in selected_not_sell, no AVSL signal
        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[],
            selected_not_sell=[symbol],
            avsl_signals={symbol: False},
        )

        self.assertEqual(decisions[symbol].reason, SellReason.NONE)
        self.assertEqual(decisions[symbol].quantity, 0.0)

    def test_zero_quantity_hold(self):
        """Test that stocks with zero quantity are held"""
        symbol = "TEST"
        avg_price = 100.0
        current_price = 81.0  # -19% loss
        quantity = 0.0  # No shares

        self.mock_finder.current_price = {symbol: current_price}

        holdings = [
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": avg_price,
                "current_price": current_price,
            }
        ]

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[],
            selected_not_sell=[],
            avsl_signals={symbol: False},
        )

        self.assertEqual(decisions[symbol].reason, SellReason.NONE)
        self.assertEqual(decisions[symbol].quantity, 0.0)

    def test_priority_order(self):
        """
        Test that the priority order is correct:
        1. Stop Loss (highest)
        2. AVSL
        3. Trend
        """
        symbol = "TEST"
        avg_price = 100.0
        quantity = 100.0

        # Test: Stop loss takes priority over AVSL
        current_price = 81.0  # -19% loss
        self.mock_finder.current_price = {symbol: current_price}

        holdings = [
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": avg_price,
                "current_price": current_price,
            }
        ]

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[symbol],  # In buy list
            selected_not_sell=[],
            avsl_signals={symbol: True},  # AVSL signal present
        )

        # Should be stop loss, not AVSL
        self.assertEqual(decisions[symbol].reason, SellReason.STOP_LOSS)

        # Test: AVSL takes priority over Trend
        current_price = 95.0  # -5% loss (below stop loss)
        self.mock_finder.current_price = {symbol: current_price}
        holdings[0]["current_price"] = current_price

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[symbol],  # In buy list
            selected_not_sell=[],
            avsl_signals={symbol: True},  # AVSL signal present
        )

        # Should be AVSL, not trend
        self.assertEqual(decisions[symbol].reason, SellReason.AVSL)

        # Test: Trend is last priority
        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[],  # Not in buy list
            selected_not_sell=[],  # Not in hold list
            avsl_signals={symbol: False},  # No AVSL signal
        )

        # Should be trend
        self.assertEqual(decisions[symbol].reason, SellReason.TREND)


if __name__ == "__main__":
    unittest.main()
