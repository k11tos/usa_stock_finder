"""Conservative backtest engine for comparing universe, entry, and exit layers.

This module is intentionally isolated from live trading runtime paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

import pandas as pd

from backtests.entry_filters import (
    apply_no_filter,
    apply_trend_basic,
    apply_trend_relaxed,
    apply_trend_strict,
)
from backtests.exit_rules import (
    should_exit_avsl,
    should_exit_hold_fixed,
    should_exit_stop_loss,
    should_exit_trailing,
    should_exit_trend,
)
from backtests.metrics import build_summary_metrics
from backtests.models import BacktestTradeResult
from backtests.universe import build_quantus_minervini_universe, build_quantus_universe


UniverseBuilder = Callable[[pd.DataFrame, str], pd.DataFrame]
EntryFilter = Callable[[pd.DataFrame], pd.DataFrame]


@dataclass(slots=True)
# Intentional state container for backtest position lifecycle.
# pylint: disable=too-many-instance-attributes
class _OpenPosition:
    symbol: str
    entry_date: date
    entry_price: float
    quantity: float
    highest_close: float
    last_close: float
    last_trade_date: date
    entry_signal_date: date | None
    rank_value: float | None


@dataclass(slots=True)
class BacktestEngineOptions:
    top_n: int
    rank_col: str
    starting_equity: float
    hold_days: int
    stop_loss_pct: float
    trailing_pct: float
    exit_rule: str


_UNIVERSE_BUILDERS: dict[str, UniverseBuilder] = {
    "quantus": build_quantus_universe,
    "quantus_minervini": build_quantus_minervini_universe,
}

_ENTRY_FILTERS: dict[str, EntryFilter] = {
    "none": apply_no_filter,
    "trend_relaxed": apply_trend_relaxed,
    "trend_basic": apply_trend_basic,
    "trend_strict": apply_trend_strict,
}

_SUPPORTED_EXITS = {"hold_fixed", "stop_loss", "trailing", "trend_exit", "avsl"}


def _normalize_trade_dates(price_history: pd.DataFrame) -> pd.DataFrame:
    normalized = price_history.copy(deep=True)
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    if normalized["date"].isna().any():
        raise ValueError("price_history contains invalid values in 'date'.")
    normalized["trade_date"] = normalized["date"].dt.date
    return normalized


def _rebalance_dates(candidates: pd.DataFrame) -> list[date]:
    snapshot_dates = pd.to_datetime(candidates["asof_date"], errors="coerce")
    if snapshot_dates.isna().any():
        raise ValueError("candidates contains invalid values in 'asof_date'.")

    date_df = pd.DataFrame({"snapshot_date": snapshot_dates.dt.date, "month": snapshot_dates.dt.to_period("M")})
    earliest_by_month = (
        date_df.groupby("month", sort=True)["snapshot_date"].min().sort_values().reset_index(drop=True)
    )
    return list(earliest_by_month)


def _evaluate_exit(
    position: _OpenPosition,
    row: pd.Series,
    options: BacktestEngineOptions,
) -> tuple[bool, str | None]:
    if options.exit_rule == "hold_fixed":
        return should_exit_hold_fixed(position, row, hold_days=options.hold_days)
    if options.exit_rule == "stop_loss":
        return should_exit_stop_loss(position, row, stop_loss_pct=options.stop_loss_pct)
    if options.exit_rule == "trailing":
        return should_exit_trailing(position, row, trailing_pct=options.trailing_pct)
    if options.exit_rule == "trend_exit":
        return should_exit_trend(position, row)
    if options.exit_rule == "avsl":
        return should_exit_avsl(position, row)

    raise ValueError(f"Unsupported exit strategy: {options.exit_rule!r}.")


def _resolve_rebalance_execution_dates(
    snapshot_dates: list[date],
    trade_dates: list[date],
) -> dict[date, list[date]]:
    execution_map: dict[date, list[date]] = {}
    snapshot_idx = 0

    for trade_date in trade_dates:
        while snapshot_idx < len(snapshot_dates) and snapshot_dates[snapshot_idx] <= trade_date:
            snapshot_date = snapshot_dates[snapshot_idx]
            execution_map.setdefault(trade_date, []).append(snapshot_date)
            snapshot_idx += 1

    return execution_map


def run_backtest(
    *,
    candidates: pd.DataFrame,
    price_history: pd.DataFrame,
    universe: str = "quantus",
    entry: str = "none",
    exit_rule: str = "hold_fixed",
    options: BacktestEngineOptions | None = None,
) -> dict[str, object]:
    """Run a conservative layered backtest and return core artifacts.

    Returns a dict with at least:
      - ``trades``: DataFrame with completed trade rows
      - ``equity_curve``: list[float]
      - ``metrics``: summary metrics dictionary
      - ``config``: resolved run configuration
    """
    if universe not in _UNIVERSE_BUILDERS:
        raise ValueError(f"Unsupported universe: {universe!r}.")
    if entry not in _ENTRY_FILTERS:
        raise ValueError(f"Unsupported entry filter: {entry!r}.")
    if exit_rule not in _SUPPORTED_EXITS:
        raise ValueError(f"Unsupported exit strategy: {exit_rule!r}.")
    resolved_options = options or BacktestEngineOptions(
        top_n=5,
        rank_col="rs_score",
        starting_equity=100_000.0,
        hold_days=20,
        stop_loss_pct=0.08,
        trailing_pct=0.10,
        exit_rule=exit_rule,
    )
    if resolved_options.top_n <= 0:
        raise ValueError("top_n must be positive.")
    resolved_options = BacktestEngineOptions(
        top_n=resolved_options.top_n,
        rank_col=resolved_options.rank_col,
        starting_equity=resolved_options.starting_equity,
        hold_days=resolved_options.hold_days,
        stop_loss_pct=resolved_options.stop_loss_pct,
        trailing_pct=resolved_options.trailing_pct,
        exit_rule=exit_rule,
    )

    candidate_df = candidates.copy(deep=True)
    price_df = _normalize_trade_dates(price_history)

    builder = _UNIVERSE_BUILDERS[universe]
    entry_filter = _ENTRY_FILTERS[entry]

    rebalance_snapshots = sorted(_rebalance_dates(candidate_df))
    all_trade_results: list[BacktestTradeResult] = []
    open_positions: dict[str, _OpenPosition] = {}
    cash = float(resolved_options.starting_equity)
    equity_curve: list[float] = [cash]

    sorted_price_df = price_df.sort_values(by=["trade_date", "symbol"]).reset_index(drop=True)
    trade_dates = list(sorted_price_df["trade_date"].drop_duplicates().sort_values())
    rebalance_execution_map = _resolve_rebalance_execution_dates(rebalance_snapshots, trade_dates)

    for trade_date in trade_dates:
        daily_rows = sorted_price_df.loc[sorted_price_df["trade_date"] == trade_date]
        daily_rows_by_symbol = {
            str(row["symbol"]): row for _, row in daily_rows.iterrows() if pd.notna(row["close"])
        }

        symbols_to_close: list[str] = []
        for symbol, position in open_positions.items():
            daily_row = daily_rows_by_symbol.get(symbol)
            if daily_row is None:
                continue

            daily_close = float(daily_row["close"])
            position.last_close = daily_close
            position.last_trade_date = trade_date
            position.highest_close = max(position.highest_close, daily_close)
            should_exit, _reason = _evaluate_exit(position, daily_row, resolved_options)
            if not should_exit:
                continue

            holding_days = (trade_date - position.entry_date).days
            all_trade_results.append(
                BacktestTradeResult(
                    symbol=position.symbol,
                    entry_date=position.entry_date,
                    exit_date=trade_date,
                    entry_price=position.entry_price,
                    exit_price=daily_close,
                    quantity=position.quantity,
                    universe=universe,
                    entry_filter=entry,
                    exit_rule=resolved_options.exit_rule,
                    exit_reason=_reason,
                    entry_signal_date=position.entry_signal_date,
                    holding_days=holding_days,
                    rank_value=position.rank_value,
                )
            )
            cash += position.quantity * daily_close
            symbols_to_close.append(symbol)

        for symbol in symbols_to_close:
            del open_positions[symbol]

        for snapshot_date in rebalance_execution_map.get(trade_date, []):
            rebalance_iso = snapshot_date.isoformat()
            universe_df = builder(candidate_df, rebalance_iso)
            filtered_df = entry_filter(universe_df)

            if filtered_df.empty:
                continue

            if resolved_options.rank_col in filtered_df.columns:
                ranked_df = filtered_df.sort_values(by=resolved_options.rank_col, ascending=False)
            else:
                ranked_df = filtered_df.sort_values(by="symbol", ascending=True)

            selected_df = ranked_df.head(resolved_options.top_n).copy(deep=True)
            selected_df = selected_df.drop_duplicates(subset=["symbol"], keep="first")
            new_entries = selected_df.loc[~selected_df["symbol"].isin(open_positions.keys())]

            entry_candidates: list[tuple[str, float, float | None, date]] = []
            for _, candidate_row in new_entries.iterrows():
                symbol = str(candidate_row["symbol"])
                daily_row = daily_rows_by_symbol.get(symbol)
                if daily_row is None:
                    continue

                entry_price = float(daily_row["close"])
                if entry_price <= 0:
                    continue
                rank_value: float | None = None
                if resolved_options.rank_col in candidate_row and pd.notna(candidate_row[resolved_options.rank_col]):
                    numeric_rank = pd.to_numeric(candidate_row[resolved_options.rank_col], errors="coerce")
                    if pd.notna(numeric_rank):
                        rank_value = float(numeric_rank)
                entry_candidates.append((symbol, entry_price, rank_value, snapshot_date))

            if entry_candidates and cash > 0:
                per_position_cash = cash / len(entry_candidates)
                for symbol, entry_price, rank_value, entry_signal_date in entry_candidates:
                    if cash <= 0:
                        break

                    alloc_cash = min(per_position_cash, cash)
                    quantity = alloc_cash / entry_price
                    if quantity <= 0:
                        continue

                    open_positions[symbol] = _OpenPosition(
                        symbol=symbol,
                        entry_date=trade_date,
                        entry_price=entry_price,
                        quantity=quantity,
                        highest_close=entry_price,
                        last_close=entry_price,
                        last_trade_date=trade_date,
                        entry_signal_date=entry_signal_date,
                        rank_value=rank_value,
                    )
                    cash -= quantity * entry_price

        open_market_value = sum(position.quantity * position.last_close for position in open_positions.values())
        equity_curve.append(cash + open_market_value)

    if trade_dates:
        for position in open_positions.values():
            holding_days = (position.last_trade_date - position.entry_date).days
            all_trade_results.append(
                BacktestTradeResult(
                    symbol=position.symbol,
                    entry_date=position.entry_date,
                    exit_date=position.last_trade_date,
                    entry_price=position.entry_price,
                    exit_price=position.last_close,
                    quantity=position.quantity,
                    universe=universe,
                    entry_filter=entry,
                    exit_rule=resolved_options.exit_rule,
                    exit_reason="end_of_data",
                    entry_signal_date=position.entry_signal_date,
                    holding_days=holding_days,
                    rank_value=position.rank_value,
                )
            )

    ordered_trade_results = sorted(
        all_trade_results,
        key=lambda trade: (trade.exit_date, trade.entry_date, trade.symbol),
    )

    trades_df = pd.DataFrame(
        [
            {
                "symbol": trade.symbol,
                "entry_date": trade.entry_date,
                "exit_date": trade.exit_date,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "quantity": trade.quantity,
                "universe": trade.universe,
                "entry_filter": trade.entry_filter,
                "exit_rule": trade.exit_rule,
                "exit_reason": trade.exit_reason,
                "entry_signal_date": trade.entry_signal_date,
                "holding_days": trade.holding_days,
                "rank_value": trade.rank_value,
                "pnl": trade.pnl,
            }
            for trade in ordered_trade_results
        ]
    )

    metrics = build_summary_metrics(
        ordered_trade_results,
        starting_equity=resolved_options.starting_equity,
    )

    return {
        "trades": trades_df,
        "equity_curve": equity_curve,
        "metrics": metrics,
        "config": {
            "universe": universe,
            "entry": entry,
            "exit_rule": resolved_options.exit_rule,
            "top_n": resolved_options.top_n,
            "rank_col": resolved_options.rank_col,
            "starting_equity": resolved_options.starting_equity,
            "hold_days": resolved_options.hold_days,
            "stop_loss_pct": resolved_options.stop_loss_pct,
            "trailing_pct": resolved_options.trailing_pct,
        },
    }
