"""
test_sell_signals.py

This module contains unit tests for the sell_signals module.
It tests the 3-tier sell decision system, including the EGAN case where
a -19% loss should trigger a stop loss sell regardless of other conditions.
"""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from config import StrategyConfig
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

    def test_egan_realistic_case(self):
        """
        Test EGAN case with realistic values from portfolio.
        Based on portfolio.csv: EGAN-US has 종가 (전일기준) = 6.3000002

        Scenario:
        - EGAN 평단가가 10.0이고 현재가가 6.3인 경우 (-37% loss)
        - 이는 STOP_LOSS_PCT (10%)를 크게 초과하므로 반드시 STOP_LOSS가 발생해야 함
        """
        symbol = "EGAN"
        avg_price = 10.0  # 평단가
        current_price = 6.3  # 현재가 (portfolio.csv 기준)
        quantity = 1.0  # 보유 수량

        # 손익률 계산
        loss_pct = (current_price - avg_price) / avg_price  # -0.37 (-37%)

        self.mock_finder.current_price = {symbol: current_price}

        holdings = [
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": avg_price,
                "current_price": current_price,
            }
        ]

        # 모든 조건을 만족해도 Stop Loss가 최우선
        selected_buy = [symbol]  # 매수 리스트에 있음
        selected_not_sell = [symbol]  # 매도 금지 리스트에도 있음
        avsl_signals = {symbol: False}  # AVSL 시그널 없음

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=selected_buy,
            selected_not_sell=selected_not_sell,
            avsl_signals=avsl_signals,
        )

        # Assert: Stop Loss가 발생해야 함
        self.assertIn(symbol, decisions)
        decision = decisions[symbol]
        self.assertEqual(
            decision.reason,
            SellReason.STOP_LOSS,
            f"EGAN should trigger STOP_LOSS with loss_pct={loss_pct:.2%}, " f"but got {decision.reason}",
        )
        self.assertEqual(decision.quantity, quantity)

        # 손익률 검증
        self.assertLess(loss_pct, -0.10, "Loss should exceed 10% threshold")
        self.assertLessEqual(loss_pct, -0.10, "Loss should be <= -10%")

    def test_price_validation_edge_cases(self):
        """Test edge cases for price validation"""
        symbol = "TEST"
        quantity = 100.0

        # Test case 1: avg_price = 0 (should skip stop loss check)
        self.mock_finder.current_price = {symbol: 100.0}
        holdings = [
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": 0.0,  # Invalid avg_price
                "current_price": 100.0,
            }
        ]

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[],
            selected_not_sell=[],
            avsl_signals={symbol: False},
        )

        # Should trigger trend sell (not stop loss due to invalid avg_price)
        self.assertEqual(decisions[symbol].reason, SellReason.TREND)

        # Test case 2: current_price = 0 (should skip stop loss check)
        self.mock_finder.current_price = {symbol: 0.0}
        holdings = [
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": 100.0,
                "current_price": 0.0,  # Invalid current_price
            }
        ]

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[],
            selected_not_sell=[],
            avsl_signals={symbol: False},
        )

        # Should trigger trend sell (not stop loss due to invalid current_price)
        self.assertEqual(decisions[symbol].reason, SellReason.TREND)

        # Test case 3: finder.current_price가 없고 holdings.current_price만 있는 경우
        # 코드는 holding.current_price를 fallback으로 사용하므로 Stop Loss가 정상 동작해야 함
        self.mock_finder.current_price = {}  # finder에 가격 없음
        holdings = [
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": 100.0,
                "current_price": 81.0,  # -19% loss
            }
        ]

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=[],
            selected_not_sell=[],
            avsl_signals={symbol: False},
        )

        # finder.current_price가 없어도 holding.current_price를 사용하므로
        # Stop Loss가 정상적으로 작동해야 함 (-19% loss > -10% STOP_LOSS_PCT)
        self.assertEqual(decisions[symbol].reason, SellReason.STOP_LOSS)
        self.assertEqual(decisions[symbol].quantity, quantity)

    def test_multiple_holdings_mixed_scenarios(self):
        """Test multiple holdings with different sell reasons"""
        holdings = [
            {
                "symbol": "STOP_LOSS_STOCK",
                "quantity": 100.0,
                "avg_price": 100.0,
                "current_price": 81.0,  # -19% loss
            },
            {
                "symbol": "AVSL_STOCK",
                "quantity": 50.0,
                "avg_price": 100.0,
                "current_price": 95.0,  # -5% loss
            },
            {
                "symbol": "TREND_STOCK",
                "quantity": 75.0,
                "avg_price": 100.0,
                "current_price": 95.0,  # -5% loss
            },
            {
                "symbol": "HOLD_STOCK",
                "quantity": 25.0,
                "avg_price": 100.0,
                "current_price": 105.0,  # +5% gain
            },
        ]

        self.mock_finder.current_price = {
            "STOP_LOSS_STOCK": 81.0,
            "AVSL_STOCK": 95.0,
            "TREND_STOCK": 95.0,
            "HOLD_STOCK": 105.0,
        }

        decisions = evaluate_sell_decisions(
            finder=self.mock_finder,
            holdings=holdings,
            selected_buy=["HOLD_STOCK"],
            selected_not_sell=[],
            avsl_signals={
                "STOP_LOSS_STOCK": False,
                "AVSL_STOCK": True,
                "TREND_STOCK": False,
                "HOLD_STOCK": False,
            },
        )

        # Verify all decisions
        self.assertEqual(decisions["STOP_LOSS_STOCK"].reason, SellReason.STOP_LOSS)
        self.assertEqual(decisions["STOP_LOSS_STOCK"].quantity, 100.0)

        self.assertEqual(decisions["AVSL_STOCK"].reason, SellReason.AVSL)
        self.assertEqual(decisions["AVSL_STOCK"].quantity, 50.0)

        self.assertEqual(decisions["TREND_STOCK"].reason, SellReason.TREND)
        self.assertEqual(decisions["TREND_STOCK"].quantity, 75.0)

        self.assertEqual(decisions["HOLD_STOCK"].reason, SellReason.NONE)
        self.assertEqual(decisions["HOLD_STOCK"].quantity, 0.0)


if __name__ == "__main__":
    unittest.main()


class TestSellSignalsRegressionPriority(unittest.TestCase):
    """Regression-focused tests for sell priority and trailing state behavior."""

    def setUp(self):
        self.mock_finder = MagicMock()
        self.mock_finder.current_price = {}
        self.mock_finder.get_atr.return_value = 0.0

    @patch("sell_signals.save_trailing_state")
    @patch("sell_signals.load_trailing_state", return_value={})
    @patch("sell_signals.update_highest_close")
    @patch("sell_signals.record_stop_loss_event")
    def test_stop_loss_short_circuits_trailing_avsl_and_trend(
        self,
        mock_record,
        mock_update_highest_close,
        _mock_load_state,
        _mock_save_state,
    ):
        """Stop loss remains absolute priority, even when lower tiers are configured to trigger."""
        symbol = "STOP"
        self.mock_finder.current_price = {symbol: 80.0}  # -20%
        self.mock_finder.get_atr.return_value = 1.0

        with patch.object(StrategyConfig, "TRAILING_ENABLED", True), patch.object(
            StrategyConfig, "TRAILING_MIN_PROFIT_PCT", -1.0
        ):
            decisions = evaluate_sell_decisions(
                finder=self.mock_finder,
                holdings=[{"symbol": symbol, "quantity": 5.0, "avg_price": 100.0, "current_price": 80.0}],
                selected_buy=[],
                selected_not_sell=[],
                avsl_signals={symbol: True},
            )

        self.assertEqual(decisions[symbol].reason, SellReason.STOP_LOSS)
        self.assertEqual(decisions[symbol].quantity, 5.0)
        mock_record.assert_called_once_with(symbol, -0.2, unittest.mock.ANY)
        self.assertFalse(mock_update_highest_close.called)

    @patch("sell_signals.save_trailing_state")
    @patch("sell_signals.load_trailing_state", return_value={})
    @patch("sell_signals.record_stop_loss_event")
    def test_trailing_priority_over_avsl_and_trend(self, mock_record, _mock_load_state, _mock_save_state):
        """Trailing sell takes priority over AVSL/trend when stop loss is not triggered."""
        symbol = "TRAIL"
        self.mock_finder.current_price = {symbol: 110.0}  # +10%
        self.mock_finder.get_atr.return_value = 2.0

        with patch.object(StrategyConfig, "TRAILING_ENABLED", True), patch.object(
            StrategyConfig, "TRAILING_MIN_PROFIT_PCT", 0.10
        ), patch("sell_signals.update_highest_close", return_value=120.0):
            decisions = evaluate_sell_decisions(
                finder=self.mock_finder,
                holdings=[{"symbol": symbol, "quantity": 3.0, "avg_price": 100.0, "current_price": 110.0}],
                selected_buy=[],
                selected_not_sell=[],
                avsl_signals={symbol: True},
            )

        self.assertEqual(decisions[symbol].reason, SellReason.TRAILING)
        self.assertEqual(decisions[symbol].quantity, 3.0)
        self.assertEqual(mock_record.call_count, 1)

    @patch("sell_signals.save_trailing_state")
    @patch("sell_signals.load_trailing_state", return_value={})
    @patch("sell_signals.record_stop_loss_event")
    def test_avsl_priority_over_trend_when_higher_rules_not_triggered(
        self,
        mock_record,
        _mock_load_state,
        _mock_save_state,
    ):
        symbol = "AVSL"
        self.mock_finder.current_price = {symbol: 95.0}

        with patch.object(StrategyConfig, "TRAILING_ENABLED", False):
            decisions = evaluate_sell_decisions(
                finder=self.mock_finder,
                holdings=[{"symbol": symbol, "quantity": 4.0, "avg_price": 100.0, "current_price": 95.0}],
                selected_buy=[],
                selected_not_sell=[],
                avsl_signals={symbol: True},
            )

        self.assertEqual(decisions[symbol].reason, SellReason.AVSL)
        self.assertEqual(decisions[symbol].quantity, 4.0)
        mock_record.assert_called_once()

    @patch("sell_signals.save_trailing_state")
    @patch("sell_signals.load_trailing_state", return_value={})
    @patch("sell_signals.record_stop_loss_event")
    def test_trend_fallback_when_not_in_buy_and_not_in_not_sell(
        self,
        mock_record,
        _mock_load_state,
        _mock_save_state,
    ):
        symbol = "TREND"
        self.mock_finder.current_price = {symbol: 101.0}

        with patch.object(StrategyConfig, "TRAILING_ENABLED", False):
            decisions = evaluate_sell_decisions(
                finder=self.mock_finder,
                holdings=[{"symbol": symbol, "quantity": 7.0, "avg_price": 100.0, "current_price": 101.0}],
                selected_buy=[],
                selected_not_sell=[],
                avsl_signals={symbol: False},
            )

        self.assertEqual(decisions[symbol].reason, SellReason.TREND)
        self.assertEqual(decisions[symbol].quantity, 7.0)
        mock_record.assert_called_once()

    @patch("sell_signals.save_trailing_state")
    @patch("sell_signals.load_trailing_state", return_value={})
    @patch("sell_signals.record_stop_loss_event")
    def test_hold_returns_none_and_zero_quantity(self, mock_record, _mock_load_state, _mock_save_state):
        symbol = "HOLD"
        self.mock_finder.current_price = {symbol: 102.0}

        with patch.object(StrategyConfig, "TRAILING_ENABLED", False):
            decisions = evaluate_sell_decisions(
                finder=self.mock_finder,
                holdings=[{"symbol": symbol, "quantity": 2.0, "avg_price": 100.0, "current_price": 102.0}],
                selected_buy=[symbol],
                selected_not_sell=[],
                avsl_signals={symbol: False},
            )

        self.assertEqual(decisions[symbol].reason, SellReason.NONE)
        self.assertEqual(decisions[symbol].quantity, 0.0)
        self.assertFalse(mock_record.called)

    @patch("sell_signals.record_stop_loss_event")
    def test_sold_symbol_is_removed_from_trailing_state_before_save(self, _mock_record):
        symbol = "CLEANUP"
        trailing_state = {symbol: {"highest_close": 150.0, "last_update": date(2025, 1, 1).isoformat()}}
        self.mock_finder.current_price = {symbol: 95.0}

        with patch("sell_signals.load_trailing_state", return_value=trailing_state), patch(
            "sell_signals.save_trailing_state"
        ) as mock_save, patch.object(StrategyConfig, "TRAILING_ENABLED", False):
            decisions = evaluate_sell_decisions(
                finder=self.mock_finder,
                holdings=[{"symbol": symbol, "quantity": 1.0, "avg_price": 100.0, "current_price": 95.0}],
                selected_buy=[],
                selected_not_sell=[],
                avsl_signals={symbol: True},
            )

        self.assertEqual(decisions[symbol].reason, SellReason.AVSL)
        mock_save.assert_called_once()
        saved_state = mock_save.call_args.args[0]
        self.assertNotIn(symbol, saved_state)
