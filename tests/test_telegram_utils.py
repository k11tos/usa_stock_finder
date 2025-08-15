"""
test_telegram_utils.py

This module contains unit tests for the telegram_utils module.
It tests Telegram message sending functionality and error handling.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram_utils import send_telegram_message


class TestTelegramUtils(unittest.TestCase):
    """Test telegram_utils module functions"""

    def setUp(self):
        """Set up test fixtures"""
        self.bot_token = "test_bot_token_12345"
        self.chat_id = "test_chat_id_67890"
        self.test_message = "Test message from USA Stock Finder"

    def test_send_telegram_message_success(self):
        """Test successful Telegram message sending"""

        async def run_test():
            with patch("telegram_utils.telegram.Bot") as mock_bot_class:
                # Mock the bot instance and its sendMessage method
                mock_bot = MagicMock()
                mock_bot.sendMessage = AsyncMock()
                mock_bot_class.return_value = mock_bot

                # Call the function
                await send_telegram_message(self.bot_token, self.chat_id, self.test_message)

                # Verify the bot was created with correct token
                mock_bot_class.assert_called_once_with(self.bot_token)

                # Verify sendMessage was called with correct parameters
                mock_bot.sendMessage.assert_called_once_with(chat_id=self.chat_id, text=self.test_message)

        asyncio.run(run_test())

    def test_send_telegram_message_network_error(self):
        """Test Telegram message sending with network error"""

        async def run_test():
            with patch("telegram_utils.telegram.Bot") as mock_bot_class, patch("telegram_utils.print") as mock_print:
                from telegram.error import NetworkError

                # Mock the bot instance and its sendMessage method to raise NetworkError
                mock_bot = MagicMock()
                mock_bot.sendMessage = AsyncMock(side_effect=NetworkError("Network error"))
                mock_bot_class.return_value = mock_bot

                # Call the function - should not raise exception
                await send_telegram_message(self.bot_token, self.chat_id, self.test_message)

                # Verify error message was printed
                mock_print.assert_called_once_with("Network error occurred while sending the message.")

        asyncio.run(run_test())

    def test_send_telegram_message_other_telegram_error(self):
        """Test Telegram message sending with other Telegram errors"""

        async def run_test():
            with patch("telegram_utils.telegram.Bot") as mock_bot_class, patch("telegram_utils.print") as mock_print:
                from telegram.error import TelegramError

                # Mock the bot instance and its sendMessage method to raise TelegramError
                mock_bot = MagicMock()
                mock_bot.sendMessage = AsyncMock(side_effect=TelegramError("Telegram error"))
                mock_bot_class.return_value = mock_bot

                # Call the function - should raise the exception
                with self.assertRaises(TelegramError):
                    await send_telegram_message(self.bot_token, self.chat_id, self.test_message)

                # Verify error message was not printed (only NetworkError is caught)
                mock_print.assert_not_called()

        asyncio.run(run_test())

    def test_send_telegram_message_empty_message(self):
        """Test Telegram message sending with empty message"""

        async def run_test():
            with patch("telegram_utils.telegram.Bot") as mock_bot_class:
                mock_bot = MagicMock()
                mock_bot.sendMessage = AsyncMock()
                mock_bot_class.return_value = mock_bot

                empty_message = ""
                await send_telegram_message(self.bot_token, self.chat_id, empty_message)

                mock_bot.sendMessage.assert_called_once_with(chat_id=self.chat_id, text=empty_message)

        asyncio.run(run_test())

    def test_send_telegram_message_long_message(self):
        """Test Telegram message sending with long message"""

        async def run_test():
            with patch("telegram_utils.telegram.Bot") as mock_bot_class:
                mock_bot = MagicMock()
                mock_bot.sendMessage = AsyncMock()
                mock_bot_class.return_value = mock_bot

                long_message = "A" * 4096  # Telegram message limit is 4096 characters
                await send_telegram_message(self.bot_token, self.chat_id, long_message)

                mock_bot.sendMessage.assert_called_once_with(chat_id=self.chat_id, text=long_message)

        asyncio.run(run_test())

    def test_send_telegram_message_special_characters(self):
        """Test Telegram message sending with special characters"""

        async def run_test():
            with patch("telegram_utils.telegram.Bot") as mock_bot_class:
                mock_bot = MagicMock()
                mock_bot.sendMessage = AsyncMock()
                mock_bot_class.return_value = mock_bot

                special_message = "한국 주식 시장 📈 AAPL +5.2% MSFT -2.1% 🚀"
                await send_telegram_message(self.bot_token, self.chat_id, special_message)

                mock_bot.sendMessage.assert_called_once_with(chat_id=self.chat_id, text=special_message)

        asyncio.run(run_test())

    def test_send_telegram_message_multiple_calls(self):
        """Test multiple Telegram message sending calls"""

        async def run_test():
            with patch("telegram_utils.telegram.Bot") as mock_bot_class:
                mock_bot = MagicMock()
                mock_bot.sendMessage = AsyncMock()
                mock_bot_class.return_value = mock_bot

                messages = [
                    "First message: AAPL analysis",
                    "Second message: MSFT analysis",
                    "Third message: Portfolio update",
                ]

                for message in messages:
                    await send_telegram_message(self.bot_token, self.chat_id, message)

                # Verify sendMessage was called for each message
                self.assertEqual(mock_bot.sendMessage.call_count, 3)

                # Verify all calls were made with correct parameters
                # Use a simpler assertion that checks the calls were made
                self.assertEqual(len(mock_bot.sendMessage.mock_calls), 3)

                # Check that each message was sent
                for message in messages:
                    mock_bot.sendMessage.assert_any_call(chat_id=self.chat_id, text=message)

        asyncio.run(run_test())

    def test_send_telegram_message_async_function(self):
        """Test that send_telegram_message is an async function"""
        import inspect

        self.assertTrue(inspect.iscoroutinefunction(send_telegram_message))


if __name__ == "__main__":
    unittest.main()
