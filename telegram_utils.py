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


def _format_pct(value: object, suffix: str = "%") -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"{numeric:+.2f}{suffix}"


def build_performance_summary_message(summary: dict, report_url: str | None) -> str:
    """Build a compact Telegram message for performance summary notifications."""
    lines = [
        "usa_stock_finder 성과 리포트",
        "",
        f"기간: {summary.get('start_date', 'N/A')} ~ {summary.get('end_date', 'N/A')}",
        f"전략: {_format_pct(summary.get('cumulative_return_pct'))}",
    ]

    if summary.get("cumulative_return_SPY_pct") is not None:
        lines.append(f"SPY: {_format_pct(summary.get('cumulative_return_SPY_pct'))}")
    if summary.get("cumulative_return_IWM_pct") is not None:
        lines.append(f"IWM: {_format_pct(summary.get('cumulative_return_IWM_pct'))}")

    lines.extend(
        [
            "",
            "초과수익:",
            f"vs SPY: {_format_pct(summary.get('excess_return_vs_SPY'), 'p')}",
            f"vs IWM: {_format_pct(summary.get('excess_return_vs_IWM'), 'p')}",
            "",
            "MDD:",
            f"전략: {_format_pct(summary.get('max_drawdown_pct'))}",
        ]
    )

    if report_url:
        lines.extend(["", "상세:", report_url])
    return "\n".join(lines)


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
