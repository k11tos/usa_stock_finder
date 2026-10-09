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

import math

import telegram


def _format_pct(value: object, suffix: str = "%") -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if not math.isfinite(numeric):
        return "N/A"
    return f"{numeric:+.2f}{suffix}"


def build_performance_summary_message(summary: dict, report_url: str | None) -> str:
    """Format computed performance metrics as a section of the daily report."""
    lines = [
        f"전략 성과 ({summary.get('start_date') or 'N/A'} ~ {summary.get('end_date') or 'N/A'})",
        f"전략: {_format_pct(summary.get('cumulative_return_pct'))}",
    ]

    benchmark_symbols = []
    for key in summary.keys():
        if key.startswith("cumulative_return_") and key.endswith("_pct") and key != "cumulative_return_pct":
            benchmark_symbols.append(key[len("cumulative_return_") : -len("_pct")])
    benchmark_symbols = sorted(set(benchmark_symbols), key=lambda symbol: (symbol != "SPY", symbol))

    for symbol in benchmark_symbols:
        benchmark_value = summary.get(f"cumulative_return_{symbol}_pct")
        if _format_pct(benchmark_value) != "N/A":
            lines.append(f"{symbol}: {_format_pct(benchmark_value)}")

    excess_lines = []
    for symbol in benchmark_symbols:
        excess_key = f"excess_return_vs_{symbol}"
        excess = _format_pct(summary.get(excess_key), "%p")
        if _format_pct(summary.get(f"cumulative_return_{symbol}_pct")) != "N/A" and excess != "N/A":
            excess_lines.append(f"{symbol} 대비 {excess}")

    if excess_lines:
        lines.extend(["", f"초과수익: {' / '.join(excess_lines)}"])

    lines.append(f"최대 낙폭(MDD): {_format_pct(summary.get('max_drawdown_pct'))}")

    if report_url:
        lines.extend(["", f"상세: {report_url}"])
    return "\n".join(lines)


def build_daily_report_message(
    report_date: str,
    final_buy_candidates: int,
    trade_lines: list[str] | None = None,
    performance_message: str | None = None,
) -> str:
    """Combine candidate status, optional performance, and existing trade details."""
    sections = [
        f"usa_stock_finder 일일 리포트\n{report_date}",
        f"매수 현황\n최종 매수 후보: {final_buy_candidates}종목",
    ]
    if performance_message:
        sections.append(performance_message)
    if trade_lines:
        # The trade formatter starts with its own date; the daily header supplies it.
        sections.append("\n".join(trade_lines[1:]).lstrip("\n"))
    return "\n\n".join(sections)


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
        # Keep ordinary daily reports in one message. Oversized trade lists must
        # be delivered in full rather than truncated at Telegram's 4096 limit.
        if not isinstance(message, str):
            await bot.sendMessage(chat_id=chat_id, text=message)
            return
        remaining = message
        while len(remaining.encode("utf-16-le")) > 8192:
            # Count emoji conservatively as two UTF-16 units, without splitting
            # surrogate pairs. Prefer a line boundary when one fits.
            fitting_text = remaining.encode("utf-16-le")[:8192].decode("utf-16-le", errors="ignore")
            split_at = fitting_text.rfind("\n") + 1
            if not split_at:
                split_at = len(fitting_text)
            await bot.sendMessage(chat_id=chat_id, text=remaining[:split_at])
            remaining = remaining[split_at:]
        await bot.sendMessage(chat_id=chat_id, text=remaining)
    except telegram.error.NetworkError:
        print("Network error occurred while sending the message.")
