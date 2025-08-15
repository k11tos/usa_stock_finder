"""
test_telegram_integration.py

Integration tests for Telegram notifications with stock selection.
Tests the interaction between Telegram messaging, stock analysis, and main workflow.
"""

import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from main import generate_telegram_message, select_stocks
from telegram_utils import send_telegram_message


class TestTelegramIntegration(unittest.TestCase):
    """Test Telegram integration with stock selection workflow"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.notification_file = os.path.join(self.temp_dir, "notifications.json")
        self.bot_token = "test_bot_token_12345"
        self.chat_id = "test_chat_id_67890"

        # Create test notification data
        notification_data = {"last_notification": "2024-01-01T10:00:00Z", "notification_count": 0, "sent_messages": []}

        with open(self.notification_file, "w", encoding="utf-8") as f:
            json.dump(notification_data, f)

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.notification_file):
            os.remove(self.notification_file)
        # Clean up temp directory and all contents
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch("telegram_utils.telegram.Bot")
    def test_stock_selection_to_telegram_integration(self, mock_bot_class):
        """Test integration from stock selection to Telegram notification"""
        # Mock Telegram bot
        mock_bot = MagicMock()
        mock_bot.sendMessage = AsyncMock()
        mock_bot_class.return_value = mock_bot

        # Mock stock finder for selection
        mock_finder = MagicMock()
        mock_finder.symbols = ["AAPL", "MSFT", "GOOGL", "TSLA"]

        # Mock correlations data
        correlations = {
            "200": {"AAPL": 75.5, "MSFT": 82.3, "GOOGL": 68.9, "TSLA": 45.2},
            "100": {"AAPL": 71.2, "MSFT": 78.9, "GOOGL": 65.4, "TSLA": 42.1},
            "50": {"AAPL": 68.7, "MSFT": 76.2, "GOOGL": 62.1, "TSLA": 38.5},
        }

        # Mock has_valid_trend_template method
        mock_finder.has_valid_trend_template.side_effect = [
            {"AAPL": True, "MSFT": True, "GOOGL": False, "TSLA": False},  # margin 0
            {"AAPL": True, "MSFT": True, "GOOGL": True, "TSLA": False},  # margin 0.1
        ]

        # Test stock selection
        buy_items, not_sell_items = select_stocks(mock_finder, correlations)

        # Verify selection results
        self.assertIn("AAPL", buy_items)  # High correlation + valid trend
        self.assertIn("MSFT", buy_items)  # High correlation + valid trend
        self.assertIn("GOOGL", not_sell_items)  # Medium correlation + valid trend with margin
        self.assertNotIn("TSLA", buy_items)  # Low correlation
        self.assertNotIn("TSLA", not_sell_items)  # Low correlation

        # Generate Telegram message
        prev_items = ["AAPL"]  # MSFT를 제거하여 새로운 구매 항목 생성
        message = generate_telegram_message(prev_items, buy_items, not_sell_items)

        # Verify message content
        self.assertIsNotNone(message)
        self.assertIn("Buy MSFT", message)  # MSFT가 새로운 구매 항목
        # GOOGL은 not_sell_items에만 있으므로 Buy 메시지가 생성되지 않음
        # 대신 not_sell_items에 포함되어 있는지 확인
        self.assertIn("GOOGL", not_sell_items)

        # Send Telegram notification
        async def test_send():
            await send_telegram_message(self.bot_token, self.chat_id, message)
            mock_bot.sendMessage.assert_called_once_with(chat_id=self.chat_id, text=message)

        asyncio.run(test_send())

    @patch("telegram_utils.telegram.Bot")
    def test_portfolio_changes_notification_integration(self, mock_bot_class):
        """Test portfolio changes notification integration"""
        # Mock Telegram bot
        mock_bot = MagicMock()
        mock_bot.sendMessage = AsyncMock()
        mock_bot_class.return_value = mock_bot

        # Test various portfolio change scenarios
        test_scenarios = [
            {
                "name": "new_buy_recommendations",
                "prev_items": ["AAPL", "MSFT"],
                "buy_items": ["AAPL", "MSFT", "GOOGL", "NVDA"],
                "not_sell_items": ["AAPL", "MSFT", "GOOGL"],
                "expected_messages": ["Buy GOOGL", "Buy NVDA"],
            },
            {
                "name": "sell_recommendations",
                "prev_items": ["AAPL", "MSFT", "GOOGL", "TSLA"],
                "buy_items": ["AAPL", "MSFT"],
                "not_sell_items": ["AAPL", "MSFT", "GOOGL"],
                "expected_messages": ["Sell TSLA"],
            },
            {
                "name": "mixed_changes",
                "prev_items": ["AAPL", "MSFT", "GOOGL"],
                "buy_items": ["AAPL", "MSFT", "NVDA"],
                "not_sell_items": ["AAPL", "MSFT", "GOOGL"],
                "expected_messages": ["Buy NVDA"],
            },
        ]

        for scenario in test_scenarios:
            with self.subTest(scenario=scenario["name"]):
                # Generate message for scenario
                message = generate_telegram_message(
                    scenario["prev_items"], scenario["buy_items"], scenario["not_sell_items"]
                )

                # Verify message contains expected content
                if message:  # Some scenarios might return None (no changes)
                    for expected_msg in scenario["expected_messages"]:
                        self.assertIn(expected_msg, message)

                # Send notification
                async def test_send():
                    if message:
                        await send_telegram_message(self.bot_token, self.chat_id, message)
                        mock_bot.sendMessage.assert_called_with(chat_id=self.chat_id, text=message)

                asyncio.run(test_send())

    def test_notification_logging_integration(self):
        """Test notification logging integration"""
        # Test notification data persistence
        from file_utils import load_json, save_json

        # Load existing notification data
        notification_data = load_json(self.notification_file)

        # Update notification data
        notification_data["notification_count"] += 1
        notification_data["sent_messages"].append(
            {"timestamp": "2024-01-01T10:30:00Z", "message": "Test notification message", "recipients": [self.chat_id]}
        )

        # Save updated data
        save_json(notification_data, self.notification_file)

        # Verify data persistence
        updated_data = load_json(self.notification_file)
        self.assertEqual(updated_data["notification_count"], 1)
        self.assertEqual(len(updated_data["sent_messages"]), 1)
        self.assertEqual(updated_data["sent_messages"][0]["message"], "Test notification message")

    @patch("telegram_utils.telegram.Bot")
    def test_error_handling_integration(self, mock_bot_class):
        """Test error handling integration in Telegram workflow"""
        from telegram.error import NetworkError, TelegramError

        # Test network error handling
        mock_bot = MagicMock()
        mock_bot.sendMessage = AsyncMock(side_effect=NetworkError("Network error"))
        mock_bot_class.return_value = mock_bot

        async def test_network_error():
            # Should not raise exception, should handle gracefully
            await send_telegram_message(self.bot_token, self.chat_id, "Test message")

        # Network error should be handled gracefully
        asyncio.run(test_network_error())

        # Test other Telegram errors
        mock_bot.sendMessage = AsyncMock(side_effect=TelegramError("Telegram error"))

        async def test_telegram_error():
            # Should raise TelegramError
            with self.assertRaises(TelegramError):
                await send_telegram_message(self.bot_token, self.chat_id, "Test message")

        asyncio.run(test_telegram_error())

    def test_message_formatting_integration(self):
        """Test message formatting integration across different scenarios"""
        # Test message generation with various data combinations
        test_cases = [
            {
                "name": "empty_portfolio",
                "prev_items": [],
                "buy_items": ["AAPL", "MSFT"],
                "not_sell_items": [],
                "expected_result": "not None",  # Should generate message for new portfolio
            },
            {
                "name": "no_changes",
                "prev_items": ["AAPL", "MSFT"],
                "buy_items": ["AAPL", "MSFT"],
                "not_sell_items": ["AAPL", "MSFT"],
                "expected_result": "None",  # Should return None for no changes
            },
            {
                "name": "large_portfolio",
                "prev_items": ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"],
                "buy_items": ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA", "META"],
                "not_sell_items": ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"],
                "expected_result": "not None",  # Should generate message for new stock
            },
        ]

        for test_case in test_cases:
            with self.subTest(test_case=test_case["name"]):
                message = generate_telegram_message(
                    test_case["prev_items"], test_case["buy_items"], test_case["not_sell_items"]
                )

                if test_case["expected_result"] == "None":
                    self.assertIsNone(message)
                else:
                    self.assertIsNotNone(message)

    @patch("telegram_utils.telegram.Bot")
    def test_concurrent_notification_integration(self, mock_bot_class):
        """Test concurrent notification sending integration"""
        # Mock Telegram bot
        mock_bot = MagicMock()
        mock_bot.sendMessage = AsyncMock()
        mock_bot_class.return_value = mock_bot

        # Test concurrent message sending
        async def send_multiple_messages():
            messages = ["Portfolio Update: AAPL +5.2%", "Portfolio Update: MSFT +3.1%", "Portfolio Update: GOOGL -1.2%"]

            # Send messages concurrently
            tasks = [send_telegram_message(self.bot_token, self.chat_id, msg) for msg in messages]

            await asyncio.gather(*tasks)

            # Verify all messages were sent
            self.assertEqual(mock_bot.sendMessage.call_count, 3)

            # Verify message content
            for msg in messages:
                mock_bot.sendMessage.assert_any_call(chat_id=self.chat_id, text=msg)

        asyncio.run(send_multiple_messages())

    def test_notification_data_consistency_integration(self):
        """Test notification data consistency across the system"""
        # Test that notification data flows correctly through the pipeline
        from file_utils import load_json, save_json

        # Simulate notification workflow
        workflow_steps = [
            {
                "step": "portfolio_analysis",
                "data": {"symbols": ["AAPL", "MSFT"], "correlations": {"AAPL": 75.5, "MSFT": 82.3}},
            },
            {"step": "stock_selection", "data": {"buy_items": ["AAPL", "MSFT"], "not_sell_items": ["AAPL", "MSFT"]}},
            {"step": "message_generation", "data": {"message": "Portfolio updated successfully"}},
            {"step": "notification_sent", "data": {"timestamp": "2024-01-01T11:00:00Z", "status": "sent"}},
        ]

        # Save workflow data
        workflow_file = os.path.join(self.temp_dir, "workflow.json")
        save_json(workflow_steps, workflow_file)

        # Load and verify workflow data
        loaded_workflow = load_json(workflow_file)

        self.assertEqual(len(loaded_workflow), 4)
        self.assertEqual(loaded_workflow[0]["step"], "portfolio_analysis")
        self.assertEqual(loaded_workflow[1]["step"], "stock_selection")
        self.assertEqual(loaded_workflow[2]["step"], "message_generation")
        self.assertEqual(loaded_workflow[3]["step"], "notification_sent")

    @patch("telegram_utils.telegram.Bot")
    def test_performance_integration(self, mock_bot_class):
        """Test performance characteristics of Telegram integration"""
        import time

        # Mock Telegram bot
        mock_bot = MagicMock()
        mock_bot.sendMessage = AsyncMock()
        mock_bot_class.return_value = mock_bot

        # Test message generation performance
        start_time = time.time()

        # Generate multiple messages
        messages = []
        for i in range(100):
            prev_items = [f"STOCK{j}" for j in range(i % 5 + 1)]
            buy_items = prev_items + [f"NEW{i}"]
            not_sell_items = prev_items

            message = generate_telegram_message(prev_items, buy_items, not_sell_items)
            if message:
                messages.append(message)

        generation_time = time.time() - start_time

        # Verify reasonable performance
        self.assertLess(generation_time, 1.0)  # Should complete within 1 second
        self.assertGreater(len(messages), 0)

        # Test message sending performance
        async def test_send_performance():
            start_time = time.time()

            # Send messages concurrently
            tasks = [
                send_telegram_message(self.bot_token, self.chat_id, msg)
                for msg in messages[:10]  # Test with first 10 messages
            ]

            await asyncio.gather(*tasks)

            send_time = time.time() - start_time

            # Verify reasonable performance
            self.assertLess(send_time, 2.0)  # Should complete within 2 seconds
            self.assertEqual(mock_bot.sendMessage.call_count, 10)

        asyncio.run(test_send_performance())


if __name__ == "__main__":
    unittest.main()
