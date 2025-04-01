"""
telegram_utils.py

This module provides utility functions for interacting with the Telegram Bot API.
It handles asynchronous communication with Telegram's messaging service and includes
error handling for network-related issues.

Required Environment Variables:
    - TELEGRAM_BOT_TOKEN: Your Telegram bot token from BotFather
    - TELEGRAM_CHAT_ID: The ID of the chat where messages will be sent

Dependencies:
    - python-telegram-bot: Asynchronous Telegram bot API client

Main Functions:
    - send_telegram_message(): Asynchronously sends a message to a specified Telegram chat
"""

import telegram


async def send_telegram_message(bot_token: str, chat_id: str, message: str) -> None:
    """
    Asynchronously sends a message to a specified Telegram chat using a bot token.

    Args:
        bot_token (str): The authentication token for the Telegram bot
        chat_id (str): The ID of the chat where the message will be sent
        message (str): The text message to be sent

    Raises:
        telegram.error.NetworkError: If there's a network-related issue while sending the message

    Note:
        - This is an async function and should be called with await
        - Network errors are caught and logged, but not propagated
    """
    bot = telegram.Bot(bot_token)
    try:
        await bot.sendMessage(chat_id=chat_id, text=message)
    except telegram.error.NetworkError:
        print("Network error occurred while sending the message.")
