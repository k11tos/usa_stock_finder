from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


DEFAULT_SNAPSHOTS = "data/live/account_snapshots.csv"
DEFAULT_TRADES = "data/live/trade_signals.csv"
DEFAULT_BENCHMARKS = ["SPY", "IWM"]
DEFAULT_OUTPUT = "outputs/performance"


def _clean_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def load_strategy_equity_curve(
    snapshots_path: str | Path,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    snapshots_path = Path(snapshots_path)
    if not snapshots_path.exists() or snapshots_path.stat().st_size == 0:
        return pd.DataFrame(columns=["run_date", "strategy_equity"])

    df = pd.read_csv(snapshots_path)
    if df.empty or "run_date" not in df.columns:
        return pd.DataFrame(columns=["run_date", "strategy_equity"])

    df["run_date"] = pd.to_datetime(df["run_date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["run_date"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["run_date", "strategy_equity"])

    if start_date:
        df = df[df["run_date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["run_date"] <= pd.to_datetime(end_date)]
    if df.empty:
        return pd.DataFrame(columns=["run_date", "strategy_equity"])

    run_ids = pd.to_datetime(df.get("run_id", pd.Series(index=df.index, dtype=object)), format="%Y%m%d_%H%M%S", errors="coerce")
    if "run_id" in df.columns:
        df = df.assign(_run_id_dt=run_ids).sort_values(["run_date", "_run_id_dt"], na_position="last")
        daily = df.groupby("run_date", as_index=False).tail(1).copy()
    else:
        daily = df.sort_values(["run_date"]).groupby("run_date", as_index=False).tail(1).copy()

    daily["total_equity"] = _clean_numeric(daily.get("total_equity", np.nan))
    daily["cash"] = _clean_numeric(daily.get("cash", np.nan)).fillna(0.0)
    daily["market_value"] = _clean_numeric(daily.get("market_value", np.nan)).fillna(0.0)

    has_valid_total = daily["total_equity"].notna() & (daily["total_equity"] > 0)
    daily["strategy_equity"] = np.where(has_valid_total, daily["total_equity"], daily["cash"] + daily["market_value"])
    daily = daily[["run_date", "strategy_equity"]].dropna().sort_values("run_date").reset_index(drop=True)
    return daily


def fetch_benchmark_prices(symbols: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    prices = pd.DataFrame()
    for symbol in symbols:
        data = yf.download(symbol, start=start.date(), end=(end + pd.Timedelta(days=1)).date(), progress=False, auto_adjust=False)
        if data.empty:
            continue
        col = "Adj Close" if "Adj Close" in data.columns else "Close"
        s = data[col].rename(symbol)
        s.index = pd.to_datetime(s.index).normalize()
        prices = prices.join(s, how="outer") if not prices.empty else s.to_frame()
    return prices.sort_index()


def normalize_series(series: pd.Series) -> pd.Series:
    s = series.dropna()
    if s.empty:
        return series * np.nan
    base = s.iloc[0]
    if pd.isna(base) or base == 0:
        return series * np.nan
    return series / base


def cumulative_return_pct(series: pd.Series) -> float | None:
    s = series.dropna()
    if len(s) < 2 or s.iloc[0] == 0:
        return None
    return float((s.iloc[-1] / s.iloc[0] - 1.0) * 100.0)


def max_drawdown_pct(series: pd.Series) -> float | None:
    s = series.dropna()
    if s.empty:
        return None
    rolling_peak = s.cummax()
    drawdowns = (s - rolling_peak) / rolling_peak
    return float(drawdowns.min() * 100.0)


def annualized_volatility_pct(daily_returns: pd.Series) -> float | None:
    r = daily_returns.dropna()
    if len(r) < 2:
        return None
    return float(r.std(ddof=1) * np.sqrt(252) * 100.0)


def cagr_pct(series: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    s = series.dropna()
    days = (end - start).days
    if len(s) < 2 or days < 30 or s.iloc[0] <= 0:
        return None
    growth = s.iloc[-1] / s.iloc[0]
    return float((growth ** (365.25 / days) - 1.0) * 100.0)


def build_report(args: argparse.Namespace) -> None:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    strategy = load_strategy_equity_curve(args.snapshots, args.start_date, args.end_date)
    equity_curve_path = output_dir / "equity_curve.csv"

    if strategy.empty:
        strategy.to_csv(equity_curve_path, index=False)
        summary = {
            "error": "No valid account snapshots found for the selected period.",
            "benchmarks": args.benchmarks,
        }
        (output_dir / "performance_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (output_dir / "benchmark_comparison.csv").write_text("", encoding="utf-8")
        (output_dir / "performance_report.md").write_text("# Performance Report\n\nNo valid snapshots found.\n", encoding="utf-8")
        return

    start, end = strategy["run_date"].min(), strategy["run_date"].max()
    benchmarks = fetch_benchmark_prices(args.benchmarks, start, end)

    df = strategy.set_index("run_date").copy()
    if not benchmarks.empty:
        benchmarks = benchmarks.reindex(df.index).ffill()
        for symbol in args.benchmarks:
            if symbol in benchmarks.columns:
                df[symbol] = benchmarks[symbol]

    norm_df = pd.DataFrame(index=df.index)
    norm_df["Strategy"] = normalize_series(df["strategy_equity"])
    for symbol in args.benchmarks:
        if symbol in df.columns:
            norm_df[symbol] = normalize_series(df[symbol])

    norm_df.to_csv(equity_curve_path, index_label="date")

    summary: dict[str, object] = {
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "num_days": int(len(norm_df)),
        "cumulative_return_pct": cumulative_return_pct(df["strategy_equity"]),
        "cagr_pct": cagr_pct(df["strategy_equity"], start, end),
        "max_drawdown_pct": max_drawdown_pct(df["strategy_equity"]),
        "annualized_volatility_pct": annualized_volatility_pct(df["strategy_equity"].pct_change()),
    }

    benchmark_rows = []
    for symbol in args.benchmarks:
        if symbol not in df.columns:
            continue
        ret = cumulative_return_pct(df[symbol])
        benchmark_rows.append({"asset": symbol, "cumulative_return_pct": ret})
        summary[f"excess_return_vs_{symbol}"] = None if ret is None or summary["cumulative_return_pct"] is None else summary["cumulative_return_pct"] - ret

    if benchmark_rows:
        best = max((r for r in benchmark_rows if r["cumulative_return_pct"] is not None), key=lambda x: x["cumulative_return_pct"], default=None)
        summary["best_benchmark"] = best["asset"] if best else None
    else:
        summary["best_benchmark"] = None

    benchmark_comparison = pd.DataFrame([
        {"asset": "Strategy", "cumulative_return_pct": summary["cumulative_return_pct"]},
        *benchmark_rows,
    ])
    benchmark_comparison.to_csv(output_dir / "benchmark_comparison.csv", index=False)
    (output_dir / "performance_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Performance Report",
        "",
        f"- Period: {summary['start_date']} to {summary['end_date']} ({summary['num_days']} snapshot days)",
        f"- Strategy cumulative return: {summary['cumulative_return_pct']:.2f}%" if summary["cumulative_return_pct"] is not None else "- Strategy cumulative return: N/A",
        f"- Strategy CAGR: {summary['cagr_pct']:.2f}%" if summary["cagr_pct"] is not None else "- Strategy CAGR: N/A (< 30 days or insufficient data)",
        f"- Strategy max drawdown: {summary['max_drawdown_pct']:.2f}%" if summary["max_drawdown_pct"] is not None else "- Strategy max drawdown: N/A",
        f"- Strategy annualized volatility: {summary['annualized_volatility_pct']:.2f}%" if summary["annualized_volatility_pct"] is not None else "- Strategy annualized volatility: N/A",
        "",
        "## Benchmark Comparison",
        "",
    ]
    for row in benchmark_rows:
        lines.append(f"- {row['asset']} cumulative return: {row['cumulative_return_pct']:.2f}%" if row["cumulative_return_pct"] is not None else f"- {row['asset']} cumulative return: N/A")
        excess_key = f"excess_return_vs_{row['asset']}"
        excess = summary.get(excess_key)
        lines.append(f"  - Excess return vs {row['asset']}: {excess:.2f}%" if excess is not None else f"  - Excess return vs {row['asset']}: N/A")

    lines.extend([
        "",
        f"- Best benchmark by cumulative return: {summary['best_benchmark']}",
        "",
        "## Caveat",
        "",
        "If external deposits/withdrawals occurred, simple equity-based returns may be distorted.",
        "A future cash-flow log can improve accuracy.",
        "",
        "This report is for decision support only and does not place trades.",
    ])
    (output_dir / "performance_report.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build live performance report vs benchmarks.")
    parser.add_argument("--snapshots", default=DEFAULT_SNAPSHOTS)
    parser.add_argument("--trades", default=DEFAULT_TRADES)
    parser.add_argument("--benchmarks", nargs="+", default=DEFAULT_BENCHMARKS)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    return parser.parse_args()


if __name__ == "__main__":
    build_report(parse_args())
