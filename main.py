"""
main.py

This module orchestrates the USA Stock Finder runtime flow.
It coordinates helper functions for stock analysis, buy/sell decision processing,
position sizing, and Telegram notifications. The trading logic is based on
Mark Minervini's principles and related technical analysis rules.

Key Features:
    - Stock data fetching and analysis
    - Price-volume correlation calculations
    - Trend analysis and stock selection
    - Investment amount calculation per stock
    - Telegram notifications for trading signals
    - Portfolio management and tracking

Dependencies:
    - asyncio: For asynchronous operations
    - logging: For structured logging
    - dotenv: For environment variable management
    - file_utils: For file operations
    - stock_analysis: For stock data analysis
    - stock_operations: For stock account operations
    - telegram_utils: For Telegram notifications

Author: Breadpig based on the theory from Mark Minervini
Date: 2024.05.19
"""

import asyncio
import logging
import os.path
import re
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
import yfinance as yf

from config import ConfigError, EnvironmentConfig, InvestmentConfig, ScheduleConfig, StrategyConfig
from file_utils import read_csv_first_column, save_json
from logging_setup import setup_logging
from sell_signals import SellDecision, SellReason, evaluate_sell_decisions, select_current_price
from stock_analysis import UsaStockFinder
from stock_operations import APIError, fetch_account_balance, fetch_holdings_detail, fetch_us_stock_holdings
from stop_loss_cooldown import is_in_cooldown
from telegram_utils import send_telegram_message

logger = logging.getLogger(__name__)

_ALLOWED_US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX"}


def normalize_exchange_name(raw_exchange: str | None) -> str | None:
    """Normalize raw exchange metadata into a conservative canonical value."""
    if not raw_exchange:
        return None

    normalized = re.sub(r"[^A-Z0-9]+", " ", str(raw_exchange).upper()).strip()
    collapsed = normalized.replace(" ", "")

    if normalized in {"NYSE", "NEW YORK STOCK EXCHANGE"}:
        return "NYSE"
    if normalized in {"NYSE AMERICAN", "NYSE MKT", "AMEX", "NYSE AMERICAN LLC"}:
        return "AMEX"
    if normalized in {"NASDAQ", "NASDAQ NMS"} or collapsed in {"NASDAQGS", "NASDAQGM", "NASDAQCM"}:
        return "NASDAQ"
    return normalized


def is_allowed_exchange(raw_exchange: str | None) -> bool:
    """Return True only for symbols listed on whitelisted core U.S. exchanges."""
    normalized = normalize_exchange_name(raw_exchange)
    return normalized in _ALLOWED_US_EXCHANGES


def _fetch_symbol_exchange(symbol: str) -> str | None:
    """Fetch exchange metadata for a symbol from yfinance with a cheap-first fallback."""
    ticker = yf.Ticker(symbol)
    fast_info = getattr(ticker, "fast_info", None)
    if fast_info:
        exchange = fast_info.get("exchange")
        if exchange:
            return str(exchange)

    info = getattr(ticker, "info", None)
    if isinstance(info, dict):
        exchange = info.get("exchange")
        if exchange:
            return str(exchange)
    return None


def _filter_entry_symbols_by_exchange(entry_symbols: list[str]) -> list[str]:
    """Filter entry symbols to conservative allowed exchanges before deeper analysis."""
    allowed_symbols: list[str] = []
    for symbol in entry_symbols:
        raw_exchange = _fetch_symbol_exchange(symbol)
        normalized_exchange = normalize_exchange_name(raw_exchange)

        if normalized_exchange is None:
            logger.info("Skipping %s: missing exchange metadata.", symbol)
            continue

        if normalized_exchange not in _ALLOWED_US_EXCHANGES:
            logger.info(
                "Skipping %s: exchange %s is not in allowed set %s.",
                symbol,
                normalized_exchange,
                sorted(_ALLOWED_US_EXCHANGES),
            )
            continue

        allowed_symbols.append(symbol)

    return allowed_symbols


def is_within_execution_window() -> bool:
    """
    Check if current time is within the execution window (KST 기준).

    The execution window is defined as:
    - Target time: EXECUTION_HOUR:EXECUTION_MINUTE (default: 20:00 KST)
    - Margin: EXECUTION_MARGIN_MINUTES (default: 10 minutes)
    - Window: (target_time - margin) ~ (target_time + margin)
    - Example: 19:50 ~ 20:10 KST for 20:00 with 10-minute margin

    Returns:
        bool: True if current time is within execution window, False otherwise
    """
    if not ScheduleConfig.TIME_CHECK_ENABLED:
        logger.debug("Time check is disabled, allowing execution")
        return True

    # 한국 시간(KST) 기준으로 현재 시간 가져오기
    try:
        kst = ZoneInfo(ScheduleConfig.TIMEZONE)
        now = datetime.now(kst)
    except Exception as e:
        # zoneinfo가 없는 경우 (Python < 3.9) 또는 타임존 설정 오류
        logger.warning("타임존 설정 실패, 시스템 로컬 시간 사용: %s", str(e))
        now = datetime.now()

    current_time = now.time()
    target_time = time(ScheduleConfig.EXECUTION_HOUR, ScheduleConfig.EXECUTION_MINUTE)

    # Calculate window boundaries
    target_datetime = datetime.combine(now.date(), target_time)
    margin_delta = timedelta(minutes=ScheduleConfig.EXECUTION_MARGIN_MINUTES)
    window_start = (target_datetime - margin_delta).time()
    window_end = (target_datetime + margin_delta).time()

    # Check if current time is within window
    # Handle case where window crosses midnight
    if window_start <= window_end:
        # Normal case: window is within same day (e.g., 7:50 ~ 8:10)
        is_within = window_start <= current_time <= window_end
    else:
        # Edge case: window crosses midnight (e.g., 23:50 ~ 00:10)
        is_within = current_time >= window_start or current_time <= window_end

    if is_within:
        logger.info(
            "현재 시간이 실행 시간 범위 내입니다 (KST) - 현재: %s, 목표: %s, 마진: ±%d분, 범위: %s ~ %s",
            current_time.strftime("%H:%M:%S"),
            target_time.strftime("%H:%M"),
            ScheduleConfig.EXECUTION_MARGIN_MINUTES,
            window_start.strftime("%H:%M"),
            window_end.strftime("%H:%M"),
        )
    else:
        logger.info(
            "현재 시간이 실행 시간 범위 밖입니다 (KST) - 현재: %s, 목표: %s, 마진: ±%d분, 범위: %s ~ %s (실행 건너뜀)",
            current_time.strftime("%H:%M:%S"),
            target_time.strftime("%H:%M"),
            ScheduleConfig.EXECUTION_MARGIN_MINUTES,
            window_start.strftime("%H:%M"),
            window_end.strftime("%H:%M"),
        )

    return is_within


def calculate_correlations(finder: UsaStockFinder) -> dict[str, dict[str, float]]:
    """
    Calculate price-volume correlations for different time periods.

    This function computes the price-volume correlation percentages
    for 200, 100, and 50-day periods using the provided finder object.
    The correlation helps identify the strength of price-volume relationships
    in different timeframes.

    Args:
        finder (UsaStockFinder): An instance of the UsaStockFinder class with
                              methods to calculate price-volume correlations.

    Returns:
        dict[str, dict[str, float]]: A dictionary containing price-volume correlation percentages
              for 200, 100, and 50-day periods, organized by period and symbol.
    """
    return {str(days): finder.price_volume_correlation_percent(days) for days in [200, 100, 50]}


def select_stocks(finder: UsaStockFinder, correlations: dict[str, dict[str, float]]) -> tuple[list[str], list[str]]:
    """
    Select stocks based on trend validity and strength criteria.

    This function analyzes stocks using two main criteria:
    1. Trend validity (with and without margin)
    2. Price-volume correlation strength

    Args:
        finder (UsaStockFinder): Instance containing stock analysis methods
        correlations (dict[str, dict[str, float]]): Price-volume correlations for different periods

    Returns:
        tuple[list[str], list[str]]: Two lists containing:
            - List of stocks recommended for buying
            - List of stocks recommended to hold (not sell)
    """
    selected_buy, selected_not_sell = [], []
    valid_trend = finder.has_valid_trend_template(StrategyConfig.MARGIN)
    valid_trend_margin = finder.has_valid_trend_template(StrategyConfig.MARGIN_RELAXED)

    for symbol in finder.symbols:
        correlation_50 = correlations.get("50", {}).get(symbol, 0.0)
        if valid_trend[symbol] and correlation_50 >= StrategyConfig.CORRELATION_THRESHOLD_STRICT:
            selected_buy.append(symbol)
            logger.info(
                "Buy signal: %s (Trend: True, Correlation: %.2f%%)",
                symbol,
                correlation_50,
            )
        elif valid_trend_margin[symbol] and correlation_50 >= StrategyConfig.CORRELATION_THRESHOLD_RELAXED:
            selected_not_sell.append(symbol)
            logger.info(
                "Hold signal: %s (Trend(Margin): True, Correlation: %.2f%%)",
                symbol,
                correlation_50,
            )
        log_stock_info(symbol, correlations)

    return selected_buy, selected_not_sell


def log_stock_info(symbol: str, correlations: dict[str, dict[str, float]]) -> None:
    """
    Log debug information about a stock's price-volume correlations.

    Args:
        symbol (str): The stock symbol to log information for
        correlations (dict[str, dict[str, float]]): Dictionary containing correlation data
            for different time periods (200, 100, 50 days)
    """
    logger.debug(
        "%s : %s -> %s -> %s",
        symbol,
        correlations["200"][symbol],
        correlations["100"][symbol],
        correlations["50"][symbol],
    )


def _format_buy_entry(
    item: str,
    share_quantities: dict[str, dict[str, Any]] | None = None,
    finder: UsaStockFinder | None = None,
) -> str:
    """Format a single buy entry while preserving existing message wording."""
    if share_quantities and item in share_quantities:
        info = share_quantities[item]
        investment = info.get("investment_amount", 0)
        price = info.get("current_price", 0)
        shares = info.get("shares_to_buy", 0)
        current_qty = info.get("current_quantity", 0)
        total_qty = info.get("total_after_buy", 0)

        if current_qty > 0:
            msg = f"  🔄 추가 매수: {item}"
            msg += f"\n     현재 보유: {current_qty}주"
            msg += f"\n     추가 매수: {shares}주"
            msg += f"\n     매수 후 총 보유: {total_qty}주"
        else:
            msg = f"  ✅ 신규 매수: {item}"
            msg += f"\n     매수 수량: {shares}주"

        msg += f"\n     투자 금액: ${investment:,.2f}"
        msg += f"\n     현재가: ${price:.2f}"
        return msg

    # share_quantities가 없어도 최소한의 정보 표시
    msg = f"  ✅ 신규 매수: {item}"
    if finder and item in finder.current_price:
        current_price = finder.current_price.get(item, 0.0)
        if current_price > 0:
            msg += f"\n     현재가: ${current_price:.2f}"
    return msg


def _format_sell_entry(
    symbol: str,
    label: str,
    sell_quantities: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Format a single sell entry while preserving existing message wording."""
    if sell_quantities and symbol in sell_quantities:
        info = sell_quantities[symbol]
        shares = info.get("shares_to_sell", 0)
        price = info.get("current_price", 0)
        sell_amount = info.get("sell_amount", 0)
        profit_loss = info.get("profit_loss", 0.0)
        profit_rate = info.get("profit_loss_rate", 0.0)

        msg = f"  {label}: {symbol}"
        msg += f"\n     매도 수량: {shares}주"
        msg += f"\n     현재가: ${price:.2f}"
        msg += f"\n     매도 금액: ${sell_amount:,.2f}"

        if profit_loss != 0:
            profit_sign = "+" if profit_loss >= 0 else ""
            rate_sign = "+" if profit_rate >= 0 else ""
            msg += f"\n     손익: {profit_sign}${profit_loss:,.2f} ({rate_sign}{profit_rate:.2f}%)"

        return msg

    return f"  {label}: {symbol}"


def _append_sell_reason_section(
    message: list[str],
    sell_items: list[tuple[str, SellDecision]],
    reason: SellReason,
    label: str,
    sell_quantities: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Append reason-specific sell messages in the original order."""
    for symbol, _decision in sell_items:
        if _decision.reason == reason:
            message.append(_format_sell_entry(symbol, label, sell_quantities))


def _format_stale_holdings_line(stale_symbols: list[str], max_symbols: int = 5) -> str:
    """Return compact stale-holding summary line for Telegram."""
    if not stale_symbols:
        return ""
    shown = stale_symbols[:max_symbols]
    suffix = f" 외 {len(stale_symbols) - max_symbols}개" if len(stale_symbols) > max_symbols else ""
    return f"  🧊 B-Plan 유지(유니버스 제외): {', '.join(shown)}{suffix}"


def _collect_stale_holdings(
    sell_decisions: dict[str, SellDecision] | None,
    entry_symbol_set: set[str],
) -> list[str]:
    """Collect holdings that are outside entry universe but still held."""
    if not sell_decisions:
        return []
    stale_symbols = [
        symbol
        for symbol, decision in sell_decisions.items()
        if decision.reason == SellReason.NONE and decision.quantity == 0 and symbol not in entry_symbol_set
    ]
    return sorted(stale_symbols)


def generate_telegram_message(
    prev_items: list[str],
    buy_items: list[str],
    _not_sell_items: list[str],  # pylint: disable=unused-argument
    share_quantities: dict[str, dict[str, Any]] | None = None,
    sell_quantities: dict[str, dict[str, Any]] | None = None,
    sell_decisions: dict[str, SellDecision] | None = None,
    finder: UsaStockFinder | None = None,
    entry_symbol_set: set[str] | None = None,
) -> list[str] | None:
    """
    Generate a Telegram message with buy and sell recommendations.

    This function compares the current selection of stocks with the previous selection
    to determine which stocks should be bought or sold. It generates a message that
    includes the current date and specific buy/sell recommendations with investment
    amounts and share quantities.

    Args:
        prev_items (list[str]): List of previously selected stock symbols
        buy_items (list[str]): List of stock symbols recommended for buying
        _not_sell_items (list[str]): List of stock symbols not recommended for selling (currently unused)
        share_quantities (dict[str, dict[str, Any]] | None): Dictionary containing share
            quantity information for buy signals
        sell_quantities (dict[str, dict[str, Any]] | None): Dictionary containing share
            quantity information for sell signals
        sell_decisions (dict[str, SellDecision] | None): Dictionary of sell decisions with reasons

    Returns:
        list[str] | None: A list of strings containing the date and buy/sell recommendations
                         with investment amounts and share quantities, or None if there are
                         no changes to report
    """
    message = [str(date.today())]
    has_changes = False

    # Generate buy messages with investment details
    # new_buy_items (prev_items에 없는 것)만 표시하되, share_quantities가 있으면 상세 정보 표시
    # 매수 수량이 0인 종목은 share_quantities에 포함되지 않으므로 필터링
    new_buy_items = [
        item for item in buy_items if item not in prev_items and (not share_quantities or item in share_quantities)
    ]

    # buy_items 전체를 표시하되, 실제 변경사항(new_buy_items 또는 매도 신호)이 있을 때만 메시지 생성
    if new_buy_items:
        message.append("\n📈 매수 신호:")
        has_changes = True

        for item in new_buy_items:
            message.append(_format_buy_entry(item, share_quantities, finder))

    # Generate sell messages with quantity details and reasons
    sell_items_to_display = []
    if sell_decisions:
        # Get all sell decisions (excluding HOLD)
        for symbol, decision in sell_decisions.items():
            if decision.reason != SellReason.NONE and decision.quantity > 0:
                sell_items_to_display.append((symbol, decision))

    if sell_items_to_display:
        message.append("\n📉 매도 신호:")
        has_changes = True

        _append_sell_reason_section(
            message,
            sell_items_to_display,
            SellReason.STOP_LOSS,
            "🟥 매도 (절대 손절)",
            sell_quantities,
        )
        _append_sell_reason_section(
            message,
            sell_items_to_display,
            SellReason.TRAILING,
            "🟨 매도 (ATR 트레일링 스탑)",
            sell_quantities,
        )
        _append_sell_reason_section(
            message,
            sell_items_to_display,
            SellReason.AVSL,
            "🟧 매도 (AVSL 거래량 지지선 붕괴)",
            sell_quantities,
        )
        _append_sell_reason_section(
            message,
            sell_items_to_display,
            SellReason.TREND,
            "🟦 매도 (트렌드/전략 조건 이탈)",
            sell_quantities,
        )

    effective_entry_symbol_set = (
        entry_symbol_set if entry_symbol_set is not None else set(buy_items) | set(_not_sell_items)
    )
    stale_holdings = _collect_stale_holdings(sell_decisions, effective_entry_symbol_set)
    if stale_holdings:
        message.append("\n🧾 보유 유지:")
        message.append(_format_stale_holdings_line(stale_holdings))
        has_changes = True

    if has_changes:
        return message
    return None


def calculate_investment_per_stock(
    buy_items: list[str],
    reserve_ratio: float | None = None,
    min_investment: float | None = None,
    max_investment: float | None = None,
    additional_cash: float = 0.0,
) -> dict[str, float] | None:
    """
    Calculate investment amount per stock based on available cash and buy signals.

    This function:
    1. Fetches account balance and available cash
    2. Calculates investment amount per stock using configured distribution strategy
    3. Applies reserve ratio to keep some cash reserved
    4. Applies min/max investment constraints

    Args:
        buy_items (list[str]): List of stock symbols recommended for buying
        reserve_ratio (float | None): Ratio of cash to reserve (None = use config default)
        min_investment (float | None): Minimum investment amount per stock (None = use config default)
        max_investment (float | None): Maximum investment amount per stock (None = use config default)
        additional_cash (float): Additional cash to add to buyable_cash (e.g., from sell proceeds). Default: 0.0

    Returns:
        dict[str, float] | None: Dictionary mapping stock symbols to investment amounts,
                                 or None if account balance cannot be fetched or no buy signals

    Note:
        - Supports equal distribution or proportional distribution strategies
        - Applies reserve ratio to keep emergency funds
        - Respects min/max investment constraints
        - Returns None if account balance fetch fails
        - Automatically excludes stocks that cannot afford minimum investment
        - Additional cash (e.g., from sell proceeds) is added to buyable_cash before calculation
    """
    if not buy_items:
        logger.warning("No buy signals to calculate investment amounts")
        return None

    # Use config defaults if not provided
    if reserve_ratio is None:
        reserve_ratio = InvestmentConfig.RESERVE_RATIO
    if min_investment is None:
        min_investment = InvestmentConfig.MIN_INVESTMENT
    if max_investment is None or max_investment == 0:
        max_investment = InvestmentConfig.MAX_INVESTMENT if InvestmentConfig.MAX_INVESTMENT > 0 else None

    try:
        account_balance = fetch_account_balance()
    except APIError as e:
        logger.error("Failed to fetch account balance: %s", str(e))
        return None

    if not account_balance:
        logger.error("Failed to fetch account balance")
        return None

    available_cash = account_balance.get("available_cash", 0.0)
    original_buyable_cash = account_balance.get("buyable_cash", available_cash)
    buyable_cash = original_buyable_cash
    total_balance = account_balance.get("total_balance", available_cash)

    # 매도로 확보된 현금을 매수 가능 금액에 추가
    if additional_cash > 0:
        buyable_cash += additional_cash
        logger.info(
            "매도 금액을 매수 가능 금액에 반영 - 원래 buyable_cash=%.2f, 추가 현금=%.2f, 최종 buyable_cash=%.2f",
            original_buyable_cash,
            additional_cash,
            buyable_cash,
        )

    if buyable_cash <= 0:
        logger.warning(
            "No buyable cash available (Available cash: %.2f, Original buyable cash: %.2f, "
            "Additional cash: %.2f, Final buyable cash: %.2f)",
            available_cash,
            original_buyable_cash,
            additional_cash,
            buyable_cash,
        )
        return None

    # Calculate total investment amount (excluding reserve)
    total_investment = buyable_cash * (1 - reserve_ratio)
    num_stocks = len(buy_items)

    if num_stocks == 0:
        logger.warning("No stocks to invest in")
        return None

    # Calculate investment per stock based on distribution strategy
    if InvestmentConfig.DISTRIBUTION_STRATEGY == "proportional" and InvestmentConfig.PROPORTIONAL_PERCENTAGE > 0:
        # Proportional distribution: each stock gets a percentage of total balance
        investment_per_stock = total_balance * InvestmentConfig.PROPORTIONAL_PERCENTAGE
        logger.info(
            "Using proportional distribution: %.2f%% of total balance per stock",
            InvestmentConfig.PROPORTIONAL_PERCENTAGE * 100,
        )
    else:
        # Equal distribution: divide total investment equally among stocks
        investment_per_stock = total_investment / num_stocks
        logger.info("Using equal distribution strategy")

    # Apply min/max constraints and filter affordable stocks
    affordable_stocks = []
    for symbol in buy_items:
        stock_investment = investment_per_stock

        # Apply max constraint
        if max_investment and stock_investment > max_investment:
            stock_investment = max_investment

        # Check if meets minimum investment
        if stock_investment >= min_investment:
            affordable_stocks.append((symbol, stock_investment))
        else:
            logger.debug(
                "Excluding stock %s: Investment amount %.2f < Minimum investment %.2f",
                symbol,
                stock_investment,
                min_investment,
            )

    if not affordable_stocks:
        logger.warning(
            "Available cash (%s) is insufficient for minimum investment (%s) for any stock",
            total_investment,
            min_investment,
        )
        return None

    # Create investment mapping
    investment_map = {symbol: round(investment, 2) for symbol, investment in affordable_stocks}

    logger.info(
        "Investment calculation: Total: %s, Reserve: %s, Per stock: %s, Stocks: %d (original: %d)",
        buyable_cash,
        buyable_cash * reserve_ratio,
        investment_per_stock,
        len(investment_map),
        num_stocks,
    )

    return investment_map


def calculate_share_quantities(
    investment_map: dict[str, float],
    finder: UsaStockFinder,
    current_holdings: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]] | None:
    """
    Calculate share quantities to buy/sell based on investment amounts and current prices.

    This function:
    1. Calculates number of shares to buy for each stock based on investment amount and current price
    2. Compares with current holdings to determine additional buy or sell quantities
    3. Returns detailed information including buy/sell quantities and current holdings

    Args:
        investment_map (dict[str, float]): Dictionary mapping stock symbols to investment amounts
        finder (UsaStockFinder): Instance containing current stock prices
        current_holdings (list[dict[str, Any]] | None): Current holdings detail from account.
            If None, will fetch from account.

    Returns:
        dict[str, dict[str, Any]] | None: Dictionary mapping stock symbols to trading information.
            Each value contains:
            - "investment_amount": Investment amount for this stock
            - "current_price": Current market price
            - "shares_to_buy": Number of shares to buy
            - "current_quantity": Current number of shares held (0 if not held)
            - "additional_buy": Additional shares to buy (if already holding)
            - "total_after_buy": Total shares after buying
            Returns None if investment_map is empty or prices unavailable

    Note:
        - Uses current_price from finder
        - Rounds down shares to buy (cannot buy fractional shares)
        - If stock is already held, calculates additional buy quantity
        - Returns None if prices are unavailable
    """
    if not investment_map:
        logger.warning("No investment map provided")
        return None

    # Fetch current holdings if not provided
    if current_holdings is None:
        current_holdings = fetch_holdings_detail()

    # Create a mapping of current holdings for quick lookup
    holdings_map: dict[str, float] = {}
    if current_holdings:
        for holding in current_holdings:
            symbol = holding.get("symbol", "")
            quantity = holding.get("quantity", 0.0)
            if symbol:
                holdings_map[symbol] = quantity

    result: dict[str, dict[str, Any]] = {}

    for symbol, investment_amount in investment_map.items():
        current_price = finder.current_price.get(symbol, 0.0)

        if current_price <= 0:
            logger.warning("Invalid price for %s: %s", symbol, current_price)
            continue

        # Calculate target total quantity (목표 총 보유 수량)
        # 투자금으로 살 수 있는 최대 수량 (소수점 이하 절삭)
        target_total_quantity = int(investment_amount / current_price)

        if target_total_quantity <= 0:
            logger.warning(
                "Investment amount %s too small for %s at price %s", investment_amount, symbol, current_price
            )
            continue

        # Get current holding quantity
        current_quantity = holdings_map.get(symbol, 0.0)

        # Calculate actual shares to buy
        # 신규 매수: 현재 보유 없음 → 목표 수량 전체 매수
        # 추가 매수: 현재 보유 있음 → (목표 수량 - 현재 보유)만큼 추가 매수
        #            단, 이미 목표 수량 이상 보유 중이면 추가 매수 0
        if current_quantity == 0:
            shares_to_buy = target_total_quantity  # 신규 매수
            is_new_buy = True
        else:
            shares_to_buy = max(target_total_quantity - int(current_quantity), 0)  # 추가 매수
            is_new_buy = False

        total_after_buy = int(current_quantity) + shares_to_buy

        # Calculate actual investment amount (actual shares to buy * price)
        actual_investment = shares_to_buy * current_price

        # 매수 수량이 0인 경우 필터링 (이미 목표 수량 이상 보유 중인 경우)
        if shares_to_buy <= 0:
            logger.debug(
                "%s: 매수 수량 0 - 목표 수량=%d주, 현재 보유=%d주, 추가 매수 불필요",
                symbol,
                target_total_quantity,
                int(current_quantity),
            )
            continue

        result[symbol] = {
            "investment_amount": round(investment_amount, 2),
            "current_price": round(current_price, 2),
            "shares_to_buy": shares_to_buy,  # Actual shares to buy (신규 매수 or 추가 매수 수량)
            "current_quantity": int(current_quantity),
            "additional_buy": shares_to_buy,  # Same as shares_to_buy (kept for backward compatibility)
            "total_after_buy": total_after_buy,
            "actual_investment": round(actual_investment, 2),
        }

        # 명확한 로깅: 신규 매수 vs 추가 매수
        if is_new_buy:
            logger.debug(
                "%s: 신규 매수 계산 - 투자금=$%.2f, 현재가=$%.2f, 매수 수량=%d주, 실제 투자금=$%.2f",
                symbol,
                investment_amount,
                current_price,
                shares_to_buy,
                actual_investment,
            )
        else:
            logger.debug(
                "%s: 추가 매수 계산 - 투자금=$%.2f, 현재가=$%.2f, 목표 총 수량=%d주, 현재 보유=%d주, "
                "추가 매수=%d주, 매수 후 총=%d주, 실제 투자금=$%.2f",
                symbol,
                investment_amount,
                current_price,
                target_total_quantity,
                int(current_quantity),
                shares_to_buy,
                total_after_buy,
                actual_investment,
            )

    if not result:
        logger.warning("No valid share quantities calculated")
        return None

    return result


def calculate_sell_quantities(
    sell_items: list[str],
    finder: UsaStockFinder,
    current_holdings: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]] | None:
    """
    Calculate share quantities to sell for stocks that need to be sold.

    Args:
        sell_items (list[str]): List of stock symbols to sell
        finder (UsaStockFinder): Instance containing current stock prices
        current_holdings (list[dict[str, Any]] | None): Current holdings detail from account.
            If None, will fetch from account.

    Returns:
        dict[str, dict[str, Any]] | None: Dictionary mapping stock symbols to sell information.
            Each value contains:
            - "current_quantity": Current number of shares held
            - "current_price": Current market price
            - "shares_to_sell": Number of shares to sell (all if selling)
            - "sell_amount": Estimated sell amount (shares * price)
            Returns None if no sell items or holdings unavailable
    """
    if not sell_items:
        return None

    # Fetch current holdings if not provided
    if current_holdings is None:
        current_holdings = fetch_holdings_detail()

    if not current_holdings:
        logger.warning("No current holdings available for sell calculation")
        return None

    # Create a mapping of current holdings for quick lookup
    holdings_map: dict[str, dict[str, Any]] = {}
    for holding in current_holdings:
        symbol = holding.get("symbol", "")
        if symbol:
            holdings_map[symbol] = holding

    result: dict[str, dict[str, Any]] = {}

    for symbol in sell_items:
        holding = holdings_map.get(symbol)
        if not holding:
            logger.debug("%s not in current holdings, skipping sell calculation", symbol)
            continue

        current_quantity = holding.get("quantity", 0.0)
        if current_quantity <= 0:
            logger.debug("%s has no shares to sell", symbol)
            continue

        # 가격 검증: holdings의 current_price와 finder.current_price 비교
        holding_current_price = holding.get("current_price", 0.0)
        finder_current_price = finder.current_price.get(symbol, 0.0)
        avg_price = holding.get("avg_price", 0.0)
        profit_loss_rate = holding.get("profit_loss_rate", 0.0)

        # finder.current_price 우선 사용, 없으면 holdings의 current_price 사용
        current_price = select_current_price(finder_current_price, holding_current_price)

        logger.debug(
            "%s: 매도 수량 계산 - avg_price=%.4f, holding_current_price=%.4f, finder_current_price=%.4f, "
            "selected_price=%.4f, profit_loss_rate=%.4f%%, quantity=%.2f",
            symbol,
            avg_price,
            holding_current_price,
            finder_current_price,
            current_price,
            profit_loss_rate,
            current_quantity,
        )

        if current_price <= 0:
            logger.warning(
                "Invalid price for %s: current_price=%s (holding=%s, finder=%s)",
                symbol,
                current_price,
                holding_current_price,
                finder_current_price,
            )
            continue

        # 손익률 재계산 검증 (holdings의 profit_loss_rate와 비교)
        calculated_loss_pct = calculate_profit_loss_rate_safely(avg_price, current_price)
        if calculated_loss_pct is not None:
            logger.debug(
                "%s: 손익률 검증 - holdings.profit_loss_rate=%.4f%%, 계산된 loss_pct=%.4f%%",
                symbol,
                profit_loss_rate,
                calculated_loss_pct,
            )

            # 큰 차이가 있으면 경고
            if is_profit_loss_rate_mismatch(profit_loss_rate, calculated_loss_pct):  # 0.1% 이상 차이
                logger.warning(
                    "%s: 손익률 불일치 - holdings.profit_loss_rate=%.4f%%, 계산된 loss_pct=%.4f%%, 차이=%.4f%%",
                    symbol,
                    profit_loss_rate,
                    calculated_loss_pct,
                    abs(calculated_loss_pct - profit_loss_rate),
                )

        # Sell all shares
        shares_to_sell = int(current_quantity)
        sell_amount = shares_to_sell * current_price

        result[symbol] = {
            "current_quantity": int(current_quantity),
            "current_price": round(current_price, 2),
            "shares_to_sell": shares_to_sell,
            "sell_amount": round(sell_amount, 2),
            "avg_price": avg_price,
            "profit_loss": holding.get("profit_loss", 0.0),
            "profit_loss_rate": profit_loss_rate,
        }

        logger.info(
            "%s: 매도 수량 계산 완료 - %d주 @ $%.2f = $%.2f (avg_price=%.2f, 손익률=%.2f%%)",
            symbol,
            shares_to_sell,
            current_price,
            sell_amount,
            avg_price,
            profit_loss_rate,
        )

    if not result:
        logger.warning("No valid sell quantities calculated")
        return None

    return result


def calculate_profit_loss_rate_safely(avg_price: float, current_price: float) -> float | None:
    """
    Safely calculate profit/loss percentage.

    Returns None when avg_price is not positive to avoid division-by-zero or invalid rates.
    """
    if avg_price <= 0:
        return None
    return ((current_price - avg_price) / avg_price) * 100


def is_profit_loss_rate_mismatch(
    provided_rate: float, calculated_rate: float | None, threshold_pct: float = 0.1
) -> bool:
    """
    Check whether provided and calculated profit/loss rates differ more than threshold.
    """
    if calculated_rate is None:
        return False
    return abs(calculated_rate - provided_rate) > threshold_pct


def update_final_items(
    prev_items: list[str],
    buy_items: list[str],
    _not_sell_items: list[str],
    sell_decisions: dict[str, SellDecision] | None = None,
) -> list[str]:
    """
    Update the final saved holdings list with explicit B-plan semantics.

    B-plan persistence rules:
    1) Existing holdings remain unless there is an explicit sell decision.
    2) Newly bought symbols are appended.
    3) Symbols are removed only when a real sell decision is made
       (reason != HOLD and quantity > 0).

    Args:
        prev_items (list[str]): List of items previously selected
        buy_items (list[str]): List of items selected to buy
        _not_sell_items (list[str]): List of items selected not to sell
        sell_decisions (dict[str, SellDecision] | None): Evaluated sell decisions
            for current holdings.

    Returns:
        list[str]: Updated final list of items to keep in the portfolio
    """
    sold_items: set[str] = set()
    if sell_decisions:
        sold_items = {
            symbol
            for symbol, decision in sell_decisions.items()
            if decision.reason != SellReason.NONE and decision.quantity > 0
        }

    final_items = [symbol for symbol in prev_items if symbol not in sold_items]
    existing_symbols = set(final_items)

    for symbol in buy_items:
        if symbol in sold_items:
            continue
        if symbol not in existing_symbols:
            final_items.append(symbol)
            existing_symbols.add(symbol)

    return final_items


def _load_and_validate_runtime_prerequisites() -> bool:
    """Load runtime prerequisites and validate startup conditions."""
    setup_logging()
    load_dotenv()

    if not is_within_execution_window():
        logger.info("현재 시간이 실행 시간 범위 밖이므로 프로그램을 종료합니다.")
        return False

    try:
        EnvironmentConfig.validate()
        logger.info("Environment variables validated successfully")
    except ConfigError as e:
        logger.error("Environment variable validation failed: %s", str(e))
        raise

    return True


def _prepare_finder_and_candidates(
    current_holding_symbols: list[str],
) -> tuple[UsaStockFinder, list[str], list[str], set[str]] | None:
    """Prepare stock finder and initial buy/hold candidates."""
    entry_symbols = read_csv_first_column(os.path.join(".", "portfolio/portfolio.csv"))
    entry_symbols = _filter_entry_symbols_by_exchange(entry_symbols)

    seen_symbols: set[str] = set()
    analysis_symbols: list[str] = []
    for symbol in [*entry_symbols, *current_holding_symbols]:
        if symbol not in seen_symbols:
            seen_symbols.add(symbol)
            analysis_symbols.append(symbol)

    logger.info(
        "Universe counts - entry=%d holdings=%d analysis=%d",
        len(entry_symbols),
        len(current_holding_symbols),
        len(analysis_symbols),
    )

    finder = UsaStockFinder(analysis_symbols)

    if not finder.is_data_valid():
        logger.error("Invalid data in UsaStockFinder")
        return None

    correlation = calculate_correlations(finder)
    buy_items, not_sell_items = select_stocks(finder, correlation)
    entry_symbol_set = set(entry_symbols)
    buy_items = [symbol for symbol in buy_items if symbol in entry_symbol_set]
    not_sell_items = [symbol for symbol in not_sell_items if symbol in entry_symbol_set]
    return finder, buy_items, not_sell_items, entry_symbol_set


def _filter_buy_candidates_by_cooldown(buy_items: list[str]) -> list[str]:
    """Filter buy candidates that are in stop-loss cooldown period."""
    today = date.today()
    original_buy_count = len(buy_items)
    filtered_buy_items = []
    for symbol in buy_items:
        if is_in_cooldown(symbol, today):
            logger.info("Symbol %s is in stop-loss cooldown. Skipping buy signal.", symbol)
        else:
            filtered_buy_items.append(symbol)

    if len(filtered_buy_items) < original_buy_count:
        logger.info(
            "Stop Loss 쿨다운 필터링 완료 - 원래: %d개, 필터링 후: %d개",
            original_buy_count,
            len(filtered_buy_items),
        )

    return filtered_buy_items


def _log_holdings_details_for_sell_evaluation(
    current_holdings_detail: list[dict[str, Any]], finder: UsaStockFinder
) -> None:
    """Log holdings detail and finder price consistency before sell evaluation."""
    logger.info("매도 평가 시작 - 보유 종목 수: %d", len(current_holdings_detail))

    for holding in current_holdings_detail:
        symbol = holding.get("symbol", "")
        avg_price = holding.get("avg_price", 0.0)
        current_price_holding = holding.get("current_price", 0.0)
        quantity = holding.get("quantity", 0.0)
        profit_loss_rate = holding.get("profit_loss_rate", 0.0)
        finder_price = finder.current_price.get(symbol, 0.0)

        logger.debug(
            "%s: 보유 정보 - avg_price=%.4f, holding.current_price=%.4f, finder.current_price=%.4f, "
            "quantity=%.2f, profit_loss_rate=%.4f%%",
            symbol,
            avg_price,
            current_price_holding,
            finder_price,
            quantity,
            profit_loss_rate,
        )

        if finder_price > 0 and current_price_holding > 0:
            price_diff_pct = abs((finder_price - current_price_holding) / current_price_holding) * 100
            if price_diff_pct > 1.0:
                logger.warning(
                    "%s: 가격 불일치 - holding.current_price=%.4f, finder.current_price=%.4f, 차이=%.2f%%",
                    symbol,
                    current_price_holding,
                    finder_price,
                    price_diff_pct,
                )


def _evaluate_and_log_sell_decisions(
    finder: UsaStockFinder,
    current_holdings_detail: list[dict[str, Any]],
    buy_items: list[str],
    not_sell_items: list[str],
    entry_symbol_set: set[str],
) -> dict[str, SellDecision]:
    """Evaluate sell decisions and keep existing diagnostics/logging unchanged."""
    avsl_signals = finder.check_avsl_sell_signal()
    avsl_count = sum(1 for v in avsl_signals.values() if v)
    logger.info("AVSL 시그널 확인 완료 - AVSL=True인 종목: %d개", avsl_count)
    holding_trend_diagnostics = finder.get_trend_template_diagnostics(StrategyConfig.MARGIN_RELAXED)
    holding_trend_template = {
        symbol: bool(diagnostics["final_result"]) for symbol, diagnostics in holding_trend_diagnostics.items()
    }
    holding_symbols = {holding.get("symbol", "") for holding in current_holdings_detail}
    holding_trend_exit_signals = {
        symbol: symbol in holding_trend_template and not holding_trend_template[symbol]
        for symbol in holding_symbols
        if symbol
    }
    trend_exit_count = sum(1 for should_exit in holding_trend_exit_signals.values() if should_exit)
    logger.info("보유종목 TREND exit 시그널 확인 완료 - trend_exit=True인 종목: %d개", trend_exit_count)
    for symbol, should_exit in sorted(holding_trend_exit_signals.items()):
        if should_exit:
            diagnostics = holding_trend_diagnostics.get(symbol, {})
            logger.info(
                "%s: TREND exit diagnostics - relaxed_trend=%s, failed_conditions=%s",
                symbol,
                diagnostics.get("final_result", False),
                ",".join(diagnostics.get("failed_conditions", [])),
            )

    sell_decisions = evaluate_sell_decisions(
        finder=finder,
        holdings=current_holdings_detail,
        selected_buy=buy_items,
        selected_not_sell=not_sell_items,
        avsl_signals=avsl_signals,
        holding_trend_exit_signals=holding_trend_exit_signals,
    )

    stop_loss_count = sum(1 for d in sell_decisions.values() if d.reason == SellReason.STOP_LOSS)
    trailing_count = sum(1 for d in sell_decisions.values() if d.reason == SellReason.TRAILING)
    avsl_count = sum(1 for d in sell_decisions.values() if d.reason == SellReason.AVSL)
    trend_count = sum(1 for d in sell_decisions.values() if d.reason == SellReason.TREND)
    hold_count = sum(1 for d in sell_decisions.values() if d.reason == SellReason.NONE)
    stale_holdings = _collect_stale_holdings(sell_decisions, entry_symbol_set)

    logger.info(
        "매도 결정 평가 완료 - Stop Loss=%d, Trailing=%d, AVSL=%d, Trend=%d, Hold=%d, StaleHold=%d",
        stop_loss_count,
        trailing_count,
        avsl_count,
        trend_count,
        hold_count,
        len(stale_holdings),
    )
    if stale_holdings:
        logger.info("B-plan stale holding 유지 종목: %s", ", ".join(sorted(stale_holdings)))

    for symbol, decision in sell_decisions.items():
        if decision.reason != SellReason.NONE:
            holding_info = next((h for h in current_holdings_detail if h.get("symbol") == symbol), None)
            if holding_info:
                avg_price = holding_info.get("avg_price", 0.0)
                current_price = finder.current_price.get(symbol, holding_info.get("current_price", 0.0))
                profit_loss_rate = holding_info.get("profit_loss_rate", 0.0)

                logger.info(
                    "매도 결정: %s - 이유=%s, 수량=%.2f, avg_price=%.4f, current_price=%.4f, 손익률=%.2f%%",
                    symbol,
                    decision.reason.value,
                    decision.quantity,
                    avg_price,
                    current_price,
                    profit_loss_rate,
                )
            else:
                logger.warning(
                    "매도 결정: %s - 이유=%s, 수량=%.2f (보유 정보 없음)",
                    symbol,
                    decision.reason.value,
                    decision.quantity,
                )

    return sell_decisions


def _derive_sell_quantities(
    sell_decisions: dict[str, SellDecision],
    finder: UsaStockFinder,
    current_holdings_detail: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]] | None:
    """Derive sell symbols and calculate detailed sell quantities."""
    all_sell_items = [
        symbol
        for symbol, decision in sell_decisions.items()
        if decision.reason != SellReason.NONE and decision.quantity > 0
    ]

    logger.debug(
        "매도 대상 종목 필터링 - 전체 결정=%d개, 매도 결정=%d개, quantity>0인 매도 결정=%d개",
        len(sell_decisions),
        sum(1 for d in sell_decisions.values() if d.reason != SellReason.NONE),
        len(all_sell_items),
    )

    if not all_sell_items:
        logger.info("매도 대상 종목 없음")
        return None

    logger.info("매도 수량 계산 시작 - 대상 종목: %s", ", ".join(all_sell_items))
    sell_quantities = calculate_sell_quantities(all_sell_items, finder, current_holdings_detail)
    if sell_quantities:
        logger.info("매도 수량 계산 완료 - %d개 종목", len(sell_quantities))
        for symbol, sell_info in sell_quantities.items():
            decision = sell_decisions.get(symbol)
            if decision:
                logger.debug(
                    "%s: 매도 수량 검증 - decision.quantity=%.2f, sell_info.shares_to_sell=%d, "
                    "sell_info.current_quantity=%d",
                    symbol,
                    decision.quantity,
                    sell_info.get("shares_to_sell", 0),
                    sell_info.get("current_quantity", 0),
                )
    else:
        logger.warning("매도 수량 계산 실패 - sell_quantities가 None 반환됨")

    return sell_quantities


def _sum_expected_sell_proceeds(sell_quantities: dict[str, dict[str, Any]] | None) -> float:
    """Sum expected sell proceeds from calculated sell quantities."""
    additional_cash_from_sell = 0.0
    if sell_quantities:
        additional_cash_from_sell = sum(info.get("sell_amount", 0.0) for info in sell_quantities.values())
        if additional_cash_from_sell > 0:
            logger.info(
                "매도로 확보될 현금 계산 완료 - 총 매도 금액: $%.2f (%d개 종목)",
                additional_cash_from_sell,
                len(sell_quantities),
            )
    return additional_cash_from_sell


def _prepare_sell_decisions_and_quantities(
    finder: UsaStockFinder, buy_items: list[str], not_sell_items: list[str], entry_symbol_set: set[str]
) -> tuple[dict[str, SellDecision], dict[str, dict[str, Any]] | None, float]:
    """Evaluate sell decisions and calculate sell quantities/cash."""
    sell_decisions: dict[str, SellDecision] = {}
    current_holdings_detail = fetch_holdings_detail()
    if current_holdings_detail:
        _log_holdings_details_for_sell_evaluation(current_holdings_detail, finder)
        sell_decisions = _evaluate_and_log_sell_decisions(
            finder,
            current_holdings_detail,
            buy_items,
            not_sell_items,
            entry_symbol_set,
        )

    sell_quantities = _derive_sell_quantities(sell_decisions, finder, current_holdings_detail)
    additional_cash_from_sell = _sum_expected_sell_proceeds(sell_quantities)
    return sell_decisions, sell_quantities, additional_cash_from_sell


def _prepare_buy_sizing_inputs(
    buy_items: list[str], finder: UsaStockFinder, additional_cash_from_sell: float
) -> tuple[dict[str, float] | None, dict[str, dict[str, Any]] | None]:
    """Prepare investment map and share quantities for buy candidates."""
    investment_map = None
    share_quantities = None

    if buy_items:
        investment_map = calculate_investment_per_stock(buy_items, additional_cash=additional_cash_from_sell)
        if investment_map:
            logger.info(
                "Investment amounts calculated: %d stocks, total investment: %s",
                len(investment_map),
                sum(investment_map.values()),
            )
            share_quantities = calculate_share_quantities(investment_map, finder)
            if share_quantities:
                logger.info("Share quantities calculated for %d stocks", len(share_quantities))
                filtered_count = len(investment_map) - len(share_quantities)
                if filtered_count > 0:
                    logger.info(
                        "매수 수량 0인 종목 필터링 완료 - 원래: %d개, 필터링 후: %d개 (제외: %d개)",
                        len(investment_map),
                        len(share_quantities),
                        filtered_count,
                    )
        else:
            logger.warning("Failed to calculate investment amounts")

    return investment_map, share_quantities


def _prepare_buy_side_orchestration(
    buy_items: list[str], finder: UsaStockFinder, additional_cash_from_sell: float
) -> tuple[list[str], dict[str, float] | None, dict[str, dict[str, Any]] | None]:
    """Apply buy-side sizing steps for already-filtered buy candidates."""
    investment_map, share_quantities = _prepare_buy_sizing_inputs(buy_items, finder, additional_cash_from_sell)
    return buy_items, investment_map, share_quantities


def _log_execution_summary(
    prev_items: list[str],
    buy_items: list[str],
    not_sell_items: list[str],
    sell_decisions: dict[str, SellDecision],
    sell_quantities: dict[str, dict[str, Any]] | None,
    additional_cash_from_sell: float,
    final_items: list[str],
    entry_symbol_set: set[str],
) -> None:
    """Log a concise, grep-friendly end-of-run summary."""
    sell_counts_by_reason = {
        reason.value: sum(
            1
            for decision in sell_decisions.values()
            if decision.reason == reason and decision.quantity > 0
        )
        for reason in SellReason
        if reason != SellReason.NONE
    }
    sell_counts_text = ",".join(f"{reason}={count}" for reason, count in sell_counts_by_reason.items() if count > 0)
    if not sell_counts_text:
        sell_counts_text = "none=0"
    stale_holdings = _collect_stale_holdings(sell_decisions, entry_symbol_set)

    logger.info(
        "RUN_SUMMARY prev_holdings=%d buy_items=%d not_sell_items=%d sell_decisions=%s "
        "sell_quantities=%d stale_holdings=%d expected_sell_cash=%.2f final_saved_items=%d",
        len(prev_items),
        len(buy_items),
        len(not_sell_items),
        sell_counts_text,
        len(sell_quantities or {}),
        len(stale_holdings),
        additional_cash_from_sell,
        len(final_items),
    )


def main() -> None:
    """
    Orchestrate the end-to-end daily analysis and notification flow.

    This function:
    1. Sets up logging and loads environment variables
    2. Validates runtime/config prerequisites
    3. Loads holdings and candidate symbols, then computes buy/hold candidates
    4. Evaluates sell decisions and estimates sell proceeds
    5. Calculates buy sizing (investment map/share quantities)
    6. Sends Telegram notifications when there are portfolio changes
    7. Saves the final symbol state to `data/data.json`

    Note:
        - Requires environment variables for Telegram API and account information
        - Expects a portfolio.csv file in the portfolio directory
        - Saves the final portfolio to data/data.json

    Raises:
        ConfigError: If required environment variables are missing
    """
    if not _load_and_validate_runtime_prerequisites():
        return

    try:
        us_stock_holdings = fetch_us_stock_holdings()
        if not us_stock_holdings:
            logger.warning("No stock holdings found in account")
            us_stock_holdings = []
    except APIError as e:
        logger.error("Failed to fetch holdings due to API error: %s", str(e))
        return

    finder_and_candidates = _prepare_finder_and_candidates(us_stock_holdings)
    if not finder_and_candidates:
        return

    finder, buy_items, not_sell_items, entry_symbol_set = finder_and_candidates
    buy_items = _filter_buy_candidates_by_cooldown(buy_items)

    sell_decisions, sell_quantities, additional_cash_from_sell = _prepare_sell_decisions_and_quantities(
        finder, buy_items, not_sell_items, entry_symbol_set
    )
    buy_items, _investment_map, share_quantities = _prepare_buy_side_orchestration(
        buy_items, finder, additional_cash_from_sell
    )

    telegram_message = generate_telegram_message(
        us_stock_holdings,
        buy_items,
        not_sell_items,
        share_quantities,
        sell_quantities,
        sell_decisions,
        finder,
        entry_symbol_set,
    )

    if telegram_message:
        bot_token = EnvironmentConfig.get("TELEGRAM_BOT_TOKEN")
        chat_id = EnvironmentConfig.get("TELEGRAM_CHAT_ID")

        if bot_token and chat_id:
            asyncio.run(
                send_telegram_message(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    message="\n".join(telegram_message),
                )
            )
            logger.debug(telegram_message)
        else:
            logger.error("Missing Telegram API credentials")

    final_items = update_final_items(us_stock_holdings, buy_items, not_sell_items, sell_decisions)
    save_json(final_items, "data/data.json")
    _log_execution_summary(
        prev_items=us_stock_holdings,
        buy_items=buy_items,
        not_sell_items=not_sell_items,
        sell_decisions=sell_decisions,
        sell_quantities=sell_quantities,
        additional_cash_from_sell=additional_cash_from_sell,
        final_items=final_items,
        entry_symbol_set=entry_symbol_set,
    )


if __name__ == "__main__":
    main()
