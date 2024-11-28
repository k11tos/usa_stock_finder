"""
telegram_utils.py

This module provides utility functions for interacting with the Telegram Bot API.
Specifically, it includes a function to send messages to a specified Telegram chat.

Functions:
- send_telegram_message(bot_token, chat_id, message): Sends a message to a specific chat using a Telegram bot.

Dependencies:
- Requires the `python-telegram-bot` library.
"""

import telegram


async def send_telegram_message(bot_token, chat_id, message):
    """Sends a telegram message to a pre-defined user."""
    bot = telegram.Bot(bot_token)
    try:
        await bot.sendMessage(chat_id=chat_id, text=message)
    except telegram.error.NetworkError:
        print("Network error occurred while sending the message.")
