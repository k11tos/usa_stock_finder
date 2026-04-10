"""CLI entry point for running isolated backtests from CSV inputs."""

from __future__ import annotations

import argparse

import pandas as pd

from backtests import data_loader
from backtests.engine import BacktestEngineOptions, run_backtest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the backtesting engine from the command line.")
    parser.add_argument("--prices", required=True, help="Path to price history CSV.")
    parser.add_argument("--candidates", required=True, help="Path to candidate snapshots CSV.")
    parser.add_argument(
        "--universe",
        default="quantus",
        choices=["quantus", "quantus_minervini"],
        help="Universe builder to apply.",
    )
    parser.add_argument(
        "--entry",
        default="none",
        choices=["none", "trend_relaxed", "trend_basic", "trend_strict"],
        help="Entry filter layer to apply.",
    )
    parser.add_argument(
        "--exit",
        dest="exit_rule",
        default="hold_fixed",
        choices=["hold_fixed", "stop_loss", "trailing", "trend_exit"],
        help="Exit rule to apply.",
    )
    parser.add_argument("--start-date", help="Inclusive start date filter (YYYY-MM-DD).")
    parser.add_argument("--end-date", help="Inclusive end date filter (YYYY-MM-DD).")
    parser.add_argument("--top-n", type=int, default=5, help="Number of symbols selected per rebalance.")
    return parser.parse_args(argv)

def _to_utc_day(value: pd.Timestamp) -> object:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.date()


def _apply_date_filter(
    frame: pd.DataFrame,
    column: str,
    start_date: pd.Timestamp | None,
    end_date: pd.Timestamp | None,
) -> pd.DataFrame:
    filtered = frame.copy(deep=True)
    parsed_days = pd.to_datetime(filtered[column], errors="coerce", utc=True).dt.date

    if start_date is not None:
        start_day = _to_utc_day(start_date)
        filtered = filtered.loc[parsed_days >= start_day]
        parsed_days = parsed_days.loc[filtered.index]
    if end_date is not None:
        end_day = _to_utc_day(end_date)
        filtered = filtered.loc[parsed_days <= end_day]

    return filtered


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    start_date = pd.to_datetime(args.start_date, utc=True) if args.start_date else None
    end_date = pd.to_datetime(args.end_date, utc=True) if args.end_date else None

    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("--start-date must be less than or equal to --end-date.")

    prices_df = data_loader.load_price_history(args.prices)
    candidates_df = data_loader.load_candidate_snapshots(args.candidates)

    prices_df = _apply_date_filter(prices_df, "date", start_date, end_date)
    candidates_df = _apply_date_filter(candidates_df, "asof_date", start_date, end_date)

    result = run_backtest(
        candidates=candidates_df,
        price_history=prices_df,
        universe=args.universe,
        entry=args.entry,
        exit_rule=args.exit_rule,
        options=BacktestEngineOptions(
            top_n=args.top_n,
            rank_col="rs_score",
            starting_equity=100_000.0,
            hold_days=20,
            stop_loss_pct=0.08,
            trailing_pct=0.10,
            exit_rule=args.exit_rule,
        ),
    )

    metrics = result["metrics"]
    print(
        " ".join(
            [
                f"trades={metrics['total_trades']}",
                f"pnl={metrics['total_pnl']:.2f}",
                f"ending_equity={metrics['ending_equity']:.2f}",
                f"return={metrics['total_return']:.2%}",
                f"win_rate={metrics['win_rate']:.2%}",
                f"max_dd={metrics['max_drawdown']:.2%}",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
