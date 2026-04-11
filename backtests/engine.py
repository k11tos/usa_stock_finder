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
from backtests.metrics import build_summary_metrics, calculate_equity_curve
from backtests.models import BacktestTradeResult
from backtests.universe import build_quantus_minervini_universe, build_quantus_universe


UniverseBuilder = Callable[[pd.DataFrame, str], pd.DataFrame]
EntryFilter = Callable[[pd.DataFrame], pd.DataFrame]


@dataclass(slots=True)
class _OpenPosition:
    symbol: str
    entry_date: date
    entry_price: float
    quantity: float
    highest_close: float


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


def _choose_entry_price(candidate_row: pd.Series, daily_rows: pd.DataFrame) -> float:
    if "close" in candidate_row and pd.notna(candidate_row["close"]):
        return float(candidate_row["close"])

    first_close = daily_rows.iloc[0]["close"]
    return float(first_close)


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

    rebalance_dates = _rebalance_dates(candidate_df)
    all_trade_results: list[BacktestTradeResult] = []

    for rebalance_date in rebalance_dates:
        rebalance_iso = rebalance_date.isoformat()
        universe_df = builder(candidate_df, rebalance_iso)
        filtered_df = entry_filter(universe_df)

        if filtered_df.empty:
            continue

        if resolved_options.rank_col in filtered_df.columns:
            ranked_df = filtered_df.sort_values(by=resolved_options.rank_col, ascending=False)
        else:
            ranked_df = filtered_df.sort_values(by="symbol", ascending=True)

        selected_df = ranked_df.head(resolved_options.top_n).copy(deep=True)

        for _, candidate_row in selected_df.iterrows():
            symbol = candidate_row["symbol"]
            symbol_rows = price_df.loc[
                (price_df["symbol"] == symbol) & (price_df["trade_date"] >= rebalance_date)
            ].sort_values(by="trade_date")
            if symbol_rows.empty:
                continue

            entry_price = _choose_entry_price(candidate_row, symbol_rows)
            position = _OpenPosition(
                symbol=symbol,
                entry_date=rebalance_date,
                entry_price=entry_price,
                quantity=1.0,
                highest_close=entry_price,
            )

            trade_closed = False
            for _, daily_row in symbol_rows.iterrows():
                daily_close = float(daily_row["close"])
                position.highest_close = max(position.highest_close, daily_close)

                should_exit, _reason = _evaluate_exit(position, daily_row, resolved_options)
                if not should_exit:
                    continue

                all_trade_results.append(
                    BacktestTradeResult(
                        symbol=position.symbol,
                        entry_date=position.entry_date,
                        exit_date=daily_row["trade_date"],
                        entry_price=position.entry_price,
                        exit_price=daily_close,
                        quantity=position.quantity,
                    )
                )
                trade_closed = True
                break

            if trade_closed:
                continue

            final_row = symbol_rows.iloc[-1]
            all_trade_results.append(
                BacktestTradeResult(
                    symbol=position.symbol,
                    entry_date=position.entry_date,
                    exit_date=final_row["trade_date"],
                    entry_price=position.entry_price,
                    exit_price=float(final_row["close"]),
                    quantity=position.quantity,
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
                "pnl": trade.pnl,
            }
            for trade in ordered_trade_results
        ]
    )

    equity_curve = calculate_equity_curve(
        ordered_trade_results,
        starting_equity=resolved_options.starting_equity,
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
