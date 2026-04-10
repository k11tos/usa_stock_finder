"""Utility functions for compact backtest performance metrics.

The helpers in this module are intentionally small and dependency-free so they can
be reused across future backtest variants (universe, entry, and exit logic).
"""

from __future__ import annotations

import math
from datetime import date
from typing import Iterable

from backtests.models import BacktestTradeResult


def calculate_equity_curve(
    trades: Iterable[BacktestTradeResult], starting_equity: float = 1.0
) -> list[float]:
    """Build a simple cumulative equity curve from sequential trade PnL.

    The returned curve always includes the starting equity as the first point.
    For each trade, we append the previous equity plus the trade's absolute PnL.
    """
    equity = float(starting_equity)
    curve = [equity]

    for trade in trades:
        equity += trade.pnl
        curve.append(equity)

    return curve


def calculate_cagr(
    equity_curve: list[float], start_date: date | None, end_date: date | None
) -> float:
    """Calculate compound annual growth rate (CAGR) from equity and dates.

    Returns ``0.0`` when there is insufficient information (empty curve,
    non-positive starting equity, missing dates, or non-positive time window).
    Returns ``-1.0`` for wiped-out runs where ending equity is exactly zero.
    """
    if not equity_curve:
        return 0.0

    start_equity = equity_curve[0]
    end_equity = equity_curve[-1]

    if start_equity <= 0 or start_date is None or end_date is None:
        return 0.0

    days = (end_date - start_date).days
    if days <= 0:
        return 0.0

    years = days / 365.25
    if years <= 0:
        return 0.0

    growth_ratio = end_equity / start_equity
    if growth_ratio == 0:
        return -1.0
    if growth_ratio < 0:
        return 0.0

    return growth_ratio ** (1.0 / years) - 1.0


def calculate_max_drawdown(equity_curve: list[float]) -> float:
    """Return maximum peak-to-trough drawdown as a decimal fraction.

    Example: a 20% maximum drawdown is returned as ``0.20``.
    """
    if not equity_curve:
        return 0.0

    peak = equity_curve[0]
    max_drawdown = 0.0

    for equity in equity_curve:
        peak = max(peak, equity)
        if peak <= 0:
            continue
        drawdown = (peak - equity) / peak
        max_drawdown = max(max_drawdown, drawdown)

    return max_drawdown


def calculate_win_rate(trades: Iterable[BacktestTradeResult]) -> float:
    """Return fraction of trades with strictly positive PnL.

    Returns ``0.0`` when no trades are provided.
    """
    trade_list = list(trades)
    if not trade_list:
        return 0.0

    wins = sum(1 for trade in trade_list if trade.pnl > 0)
    return wins / len(trade_list)


def calculate_profit_factor(trades: Iterable[BacktestTradeResult]) -> float:
    """Calculate profit factor as gross profits divided by gross losses.

    Returns:
      * ``0.0`` for empty trades or no winning trades.
      * ``math.inf`` when there are winning trades and zero gross losses.
    """
    gross_profit = 0.0
    gross_loss = 0.0

    for trade in trades:
        if trade.pnl > 0:
            gross_profit += trade.pnl
        elif trade.pnl < 0:
            gross_loss += abs(trade.pnl)

    if gross_loss == 0:
        return math.inf if gross_profit > 0 else 0.0

    return gross_profit / gross_loss


def build_summary_metrics(
    trades: Iterable[BacktestTradeResult], starting_equity: float = 1.0
) -> dict[str, float | int]:
    """Build a compact dictionary of commonly used backtest metrics.

    Supported keys:
      * ``total_trades``
      * ``total_pnl``
      * ``ending_equity``
      * ``total_return``
      * ``cagr``
      * ``max_drawdown``
      * ``win_rate``
      * ``profit_factor``
    """
    trade_list = list(trades)
    equity_curve = calculate_equity_curve(trade_list, starting_equity=starting_equity)

    if trade_list:
        start_date = min(trade.entry_date for trade in trade_list)
        end_date = max(trade.exit_date for trade in trade_list)
    else:
        start_date = None
        end_date = None

    total_pnl = sum(trade.pnl for trade in trade_list)
    ending_equity = equity_curve[-1]

    if starting_equity > 0:
        total_return = (ending_equity / starting_equity) - 1.0
    else:
        total_return = 0.0

    return {
        "total_trades": len(trade_list),
        "total_pnl": total_pnl,
        "ending_equity": ending_equity,
        "total_return": total_return,
        "cagr": calculate_cagr(equity_curve, start_date, end_date),
        "max_drawdown": calculate_max_drawdown(equity_curve),
        "win_rate": calculate_win_rate(trade_list),
        "profit_factor": calculate_profit_factor(trade_list),
    }
