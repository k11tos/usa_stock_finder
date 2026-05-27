from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yfinance as yf

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # pylint: disable=wrong-import-position,ungrouped-imports

DEFAULT_SNAPSHOTS = "data/live/account_snapshots.csv"
DEFAULT_CASH_FLOWS = "data/live/cash_flows.csv"
DEFAULT_TRADES = "data/live/trade_signals.csv"
DEFAULT_BENCHMARKS = ["SPY", "IWM"]
DEFAULT_OUTPUT = "outputs/performance"
REQUIRED_CASH_FLOW_COLUMNS = {"date", "amount", "currency", "type", "memo"}
VALID_CASH_FLOW_TYPES = {"deposit", "withdrawal", "dividend", "fee", "tax", "adjustment"}



def _fmt_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def _generate_kst_run_id() -> str:
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y%m%d_%H%M%S")


def _write_html_report(output_dir: Path, summary: dict[str, object], benchmarks: list[str]) -> None:
    chart_names = ["cumulative_return.png", "drawdown.png", "excess_return.png"]
    sections = []
    for chart in chart_names:
        chart_path = output_dir / "charts" / chart
        rel = f"charts/{chart}"
        if chart_path.exists() and chart_path.stat().st_size > 0:
            sections.append(f'<figure><img src="{rel}" alt="{chart}" style="max-width:100%;height:auto;"/></figure>')
        else:
            sections.append(f'<p><strong>Missing chart:</strong> {rel}</p>')

    benchmark_lines = []
    for symbol in benchmarks:
        benchmark_lines.append(
            f"<li>{symbol} cumulative return: {_fmt_pct(summary.get(f'cumulative_return_{symbol}_pct'))}</li>"
        )
        benchmark_lines.append(
            f"<li>Excess return vs {symbol}: {_fmt_pct(summary.get(f'excess_return_vs_{symbol}'))}</li>"
        )

    period = (
        f"{summary.get('start_date', 'N/A')} to {summary.get('end_date', 'N/A')}"
        f" ({summary.get('num_days', 0)} snapshot days)"
    )
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>usa_stock_finder Performance Report</title>
</head>
<body>
  <h1>usa_stock_finder Performance Report</h1>
  <ul>
    <li>Report period: {period}</li>
    <li>Strategy cumulative return: {_fmt_pct(summary.get('cumulative_return_pct'))}</li>
    <li>Strategy cash-flow-adjusted return: {_fmt_pct(summary.get('cash_flow_adjusted_return_pct'))}</li>
    <li>Max drawdown: {_fmt_pct(summary.get('max_drawdown_pct'))}</li>
    <li>Annualized volatility: {_fmt_pct(summary.get('annualized_volatility_pct'))}</li>
    {''.join(benchmark_lines)}
  </ul>
  <h2>Charts</h2>
  {''.join(sections)}
  <h2>Caveat</h2>
  <p>If external deposits/withdrawals occurred, simple equity-based returns may be distorted.</p>
</body>
</html>"""
    (output_dir / "index.html").write_text(html, encoding="utf-8")


def _copy_report_bundle(source_dir: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    files = [
        "index.html",
        "performance_report.md",
        "performance_summary.json",
        "equity_curve.csv",
        "benchmark_comparison.csv",
    ]
    for name in files:
        src = source_dir / name
        if src.exists():
            shutil.copy2(src, destination_dir / name)
    for chart in ["cumulative_return.png", "drawdown.png", "excess_return.png"]:
        src = source_dir / "charts" / chart
        dst = destination_dir / "charts" / chart
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.copy2(src, dst)


def _publish_report_bundles(output_dir: Path, args: argparse.Namespace) -> None:
    publish_latest = getattr(args, "publish_latest", False)
    history = getattr(args, "history", False)

    if publish_latest:
        _copy_report_bundle(output_dir, output_dir / "latest")
    if history:
        report_run_id = getattr(args, "report_run_id", None)
        run_id = report_run_id or _generate_kst_run_id()
        _copy_report_bundle(output_dir, output_dir / "history" / run_id)


def _clean_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _load_cash_flows(cash_flows_path: str | Path) -> tuple[pd.DataFrame, list[str]]:
    path = Path(cash_flows_path)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=["date", "external_flow"]), []

    raw = pd.read_csv(path)
    missing = REQUIRED_CASH_FLOW_COLUMNS - set(raw.columns)
    if missing:
        return pd.DataFrame(columns=["date", "external_flow"]), [
            f"Missing required cash-flow columns: {', '.join(sorted(missing))}"
        ]

    df = raw.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["type"] = df["type"].astype(str).str.strip().str.lower()

    valid_type_mask = df["type"].isin(VALID_CASH_FLOW_TYPES)
    valid_row_mask = df["date"].notna() & df["amount"].notna() & valid_type_mask
    invalid_rows = int((~valid_row_mask).sum())
    warnings = []
    if invalid_rows:
        warnings.append(f"Skipped {invalid_rows} invalid cash-flow row(s).")

    cleaned = df.loc[valid_row_mask, ["date", "amount", "type"]].copy()
    if cleaned.empty:
        return pd.DataFrame(columns=["date", "external_flow"]), warnings

    sign = np.where(cleaned["type"] == "withdrawal", -1.0, 1.0)
    cleaned["external_flow"] = cleaned["amount"] * sign
    daily = cleaned.groupby("date", as_index=False)["external_flow"].sum()
    return daily, warnings


def _calculate_modified_dietz_return_pct(
    strategy_df: pd.DataFrame,
    daily_cash_flows: pd.DataFrame,
) -> float | None:
    if strategy_df.empty or len(strategy_df) < 2:
        return None

    start = float(strategy_df["strategy_equity"].iloc[0])
    end = float(strategy_df["strategy_equity"].iloc[-1])
    if start <= 0:
        return None

    flow_series = (
        daily_cash_flows.set_index("date")["external_flow"]
        if not daily_cash_flows.empty
        else pd.Series(dtype=float)
    )
    if flow_series.empty:
        return float(((end - start) / start) * 100.0)
    flow_series.index = pd.to_datetime(flow_series.index, errors="coerce").normalize()
    flow_series = flow_series[flow_series.index.notna()]

    start_date = pd.Timestamp(strategy_df["run_date"].iloc[0]).normalize()
    end_date = pd.Timestamp(strategy_df["run_date"].iloc[-1]).normalize()
    period_flows = flow_series[(flow_series.index >= start_date) & (flow_series.index <= end_date)]
    if period_flows.empty:
        return float(((end - start) / start) * 100.0)
    total_days = max((end_date - start_date).days, 1)

    weighted_flows = 0.0
    net_flows = 0.0
    for flow_date, flow_amount in period_flows.items():
        day_flow = float(flow_amount)
        days_from_start = (pd.Timestamp(flow_date).normalize() - start_date).days
        weight = (total_days - days_from_start) / total_days
        weighted_flows += day_flow * weight
        net_flows += day_flow

    denominator = start + weighted_flows
    if denominator == 0:
        return None
    return float(((end - start - net_flows) / denominator) * 100.0)


def _select_latest_run_rows(df: pd.DataFrame) -> pd.DataFrame:
    if "run_id" not in df.columns:
        return df.copy()

    run_id_dt = pd.to_datetime(
        df["run_id"],
        format="%Y%m%d_%H%M%S",
        errors="coerce",
    )
    candidates = df.assign(_run_id_dt=run_id_dt)
    latest = (
        candidates.sort_values(["run_date", "_run_id_dt"], na_position="last")
        .groupby("run_date", as_index=False)
        .tail(1)[["run_date", "run_id"]]
    )
    return df.merge(latest, on=["run_date", "run_id"], how="inner")


def _compute_run_equity(run_rows: pd.DataFrame) -> float:
    total_equity = _clean_numeric(run_rows.get("total_equity", pd.Series(dtype=float)))
    valid_total = total_equity[(total_equity > 0) & total_equity.notna()]
    if not valid_total.empty:
        return float(valid_total.iloc[0])

    cash_series = _clean_numeric(run_rows.get("cash", pd.Series(dtype=float))).dropna()
    cash_value = float(cash_series.iloc[0]) if not cash_series.empty else 0.0
    market_value = _clean_numeric(run_rows.get("market_value", pd.Series(dtype=float))).fillna(0.0)
    return cash_value + float(market_value.sum())


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

    selected = _select_latest_run_rows(df)
    daily = (
        selected.groupby("run_date", as_index=False)
        .apply(lambda group: pd.Series({"strategy_equity": _compute_run_equity(group)}))
        .reset_index(drop=True)
    )

    return daily[["run_date", "strategy_equity"]].sort_values("run_date").reset_index(drop=True)


def fetch_benchmark_prices(symbols: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    prices = pd.DataFrame()
    for symbol in symbols:
        data = yf.download(
            symbol,
            start=start.date(),
            end=(end + pd.Timedelta(days=1)).date(),
            progress=False,
            auto_adjust=False,
        )
        if data.empty:
            continue
        col = "Adj Close" if "Adj Close" in data.columns else "Close"
        benchmark_series = data[col].rename(symbol)
        benchmark_series.index = pd.to_datetime(benchmark_series.index).normalize()
        prices = (
            prices.join(benchmark_series, how="outer")
            if not prices.empty
            else benchmark_series.to_frame()
        )
    return prices.sort_index()


def align_benchmarks_to_strategy_dates(
    benchmarks: pd.DataFrame,
    strategy_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    if benchmarks.empty:
        return benchmarks

    union_index = benchmarks.index.union(strategy_index)
    aligned = benchmarks.reindex(union_index).sort_index().ffill()
    return aligned.reindex(strategy_index)


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


def calculate_drawdown_series(series: pd.Series) -> pd.Series:
    s = series.copy()
    rolling_peak = s.cummax()
    return ((s / rolling_peak) - 1.0) * 100.0


def build_chart_data(norm_df: pd.DataFrame, benchmarks: list[str]) -> dict[str, pd.DataFrame]:
    cumulative = pd.DataFrame(index=norm_df.index)
    if "Strategy" in norm_df.columns:
        cumulative["Strategy"] = norm_df["Strategy"] * 100.0
    for symbol in benchmarks:
        if symbol in norm_df.columns:
            cumulative[symbol] = norm_df[symbol] * 100.0

    drawdown = pd.DataFrame(index=norm_df.index)
    for column in cumulative.columns:
        drawdown[column] = calculate_drawdown_series(cumulative[column])

    excess = pd.DataFrame(index=norm_df.index)
    if "Strategy" in norm_df.columns:
        for symbol in benchmarks:
            if symbol in cumulative.columns:
                excess[f"Strategy - {symbol}"] = (norm_df["Strategy"] - norm_df[symbol]) * 100.0

    return {"cumulative": cumulative, "drawdown": drawdown, "excess": excess}


def _save_line_chart(
    data: pd.DataFrame,
    output_path: Path,
    title: str,
    y_label: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    if not data.empty:
        for column in data.columns:
            ax.plot(data.index, data[column], label=column, linewidth=2)
        ax.legend()
    else:
        ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel(y_label)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def write_performance_charts(chart_data: dict[str, pd.DataFrame], output_dir: Path) -> None:
    charts_dir = output_dir / "charts"
    _save_line_chart(
        chart_data["cumulative"],
        charts_dir / "cumulative_return.png",
        "Cumulative Return",
        "Growth of $100",
    )
    _save_line_chart(
        chart_data["drawdown"],
        charts_dir / "drawdown.png",
        "Drawdown",
        "Drawdown (%)",
    )
    _save_line_chart(
        chart_data["excess"],
        charts_dir / "excess_return.png",
        "Excess Return",
        "Excess Return (%)",
    )


def annualized_volatility_pct(daily_returns: pd.Series) -> float | None:
    returns = daily_returns.dropna()
    if len(returns) < 2:
        return None
    return float(returns.std(ddof=1) * np.sqrt(252) * 100.0)


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
    cash_flows, cash_flow_warnings = _load_cash_flows(getattr(args, "cash_flows", DEFAULT_CASH_FLOWS))
    equity_curve_path = output_dir / "equity_curve.csv"

    if strategy.empty:
        strategy.to_csv(equity_curve_path, index=False)
        summary = {
            "start_date": None,
            "end_date": None,
            "num_days": 0,
            "error": "No valid account snapshots found for the selected period.",
            "benchmarks": args.benchmarks,
            "cumulative_return_pct": None,
            "max_drawdown_pct": None,
            "annualized_volatility_pct": None,
            "cash_flow_adjusted_return_pct": None,
            "cash_flow_warnings": cash_flow_warnings,
        }
        (output_dir / "performance_summary.json").write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8",
        )
        (output_dir / "benchmark_comparison.csv").write_text("", encoding="utf-8")
        (output_dir / "performance_report.md").write_text(
            "# Performance Report\n\nNo valid snapshots found.\n",
            encoding="utf-8",
        )
        _write_html_report(output_dir, summary, args.benchmarks)
        _publish_report_bundles(output_dir, args)
        return

    start, end = strategy["run_date"].min(), strategy["run_date"].max()
    benchmarks = fetch_benchmark_prices(args.benchmarks, start, end)

    df = strategy.set_index("run_date").copy()
    if not benchmarks.empty:
        benchmarks = align_benchmarks_to_strategy_dates(benchmarks, df.index)
        for symbol in args.benchmarks:
            if symbol in benchmarks.columns:
                df[symbol] = benchmarks[symbol]

    norm_df = pd.DataFrame(index=df.index)
    norm_df["Strategy"] = normalize_series(df["strategy_equity"])
    for symbol in args.benchmarks:
        if symbol in df.columns:
            norm_df[symbol] = normalize_series(df[symbol])

    norm_df.to_csv(equity_curve_path, index_label="date")
    chart_data = build_chart_data(norm_df, args.benchmarks)
    write_performance_charts(chart_data, output_dir)

    summary: dict[str, object] = {
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "num_days": int(len(norm_df)),
        "cumulative_return_pct": cumulative_return_pct(df["strategy_equity"]),
        "cagr_pct": cagr_pct(df["strategy_equity"], start, end),
        "max_drawdown_pct": max_drawdown_pct(df["strategy_equity"]),
        "annualized_volatility_pct": annualized_volatility_pct(
            df["strategy_equity"].pct_change()
        ),
        "cash_flow_adjusted_return_pct": _calculate_modified_dietz_return_pct(strategy, cash_flows),
        "cash_flow_warnings": cash_flow_warnings,
    }

    benchmark_rows = []
    for symbol in args.benchmarks:
        if symbol not in df.columns:
            continue
        ret = cumulative_return_pct(df[symbol])
        summary[f"cumulative_return_{symbol}_pct"] = ret
        benchmark_rows.append({"asset": symbol, "cumulative_return_pct": ret})
        strat_ret = summary["cumulative_return_pct"]
        summary[f"excess_return_vs_{symbol}"] = (
            None if ret is None or strat_ret is None else strat_ret - ret
        )

    if benchmark_rows:
        best = max(
            (row for row in benchmark_rows if row["cumulative_return_pct"] is not None),
            key=lambda row: row["cumulative_return_pct"],
            default=None,
        )
        summary["best_benchmark"] = best["asset"] if best else None
    else:
        summary["best_benchmark"] = None

    benchmark_comparison = pd.DataFrame(
        [{"asset": "Strategy", "cumulative_return_pct": summary["cumulative_return_pct"]}]
        + benchmark_rows
    )
    benchmark_comparison.to_csv(output_dir / "benchmark_comparison.csv", index=False)
    (output_dir / "performance_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Performance Report",
        "",
        (
            f"- Period: {summary['start_date']} to {summary['end_date']} "
            f"({summary['num_days']} snapshot days)"
        ),
        (
            f"- Strategy cumulative return: {summary['cumulative_return_pct']:.2f}%"
            if summary["cumulative_return_pct"] is not None
            else "- Strategy cumulative return: N/A"
        ),
        (
            f"- Strategy cash-flow-adjusted return: {summary['cash_flow_adjusted_return_pct']:.2f}%"
            if summary["cash_flow_adjusted_return_pct"] is not None
            else "- Strategy cash-flow-adjusted return: N/A (no valid cash-flow data)"
        ),
        (
            f"- Strategy CAGR: {summary['cagr_pct']:.2f}%"
            if summary["cagr_pct"] is not None
            else "- Strategy CAGR: N/A (< 30 days or insufficient data)"
        ),
        (
            f"- Strategy max drawdown: {summary['max_drawdown_pct']:.2f}%"
            if summary["max_drawdown_pct"] is not None
            else "- Strategy max drawdown: N/A"
        ),
        (
            f"- Strategy annualized volatility: {summary['annualized_volatility_pct']:.2f}%"
            if summary["annualized_volatility_pct"] is not None
            else "- Strategy annualized volatility: N/A"
        ),
        "",
        "## Benchmark Comparison",
        "",
    ]

    for row in benchmark_rows:
        lines.append(
            f"- {row['asset']} cumulative return: {row['cumulative_return_pct']:.2f}%"
            if row["cumulative_return_pct"] is not None
            else f"- {row['asset']} cumulative return: N/A"
        )
        excess_key = f"excess_return_vs_{row['asset']}"
        excess = summary.get(excess_key)
        lines.append(
            f"  - Excess return vs {row['asset']}: {excess:.2f}%"
            if excess is not None
            else f"  - Excess return vs {row['asset']}: N/A"
        )

    lines.extend(
        [
            "",
            "## Charts",
            "",
            "![Cumulative Return](charts/cumulative_return.png)",
            "",
            "![Drawdown](charts/drawdown.png)",
            "",
            "![Excess Return](charts/excess_return.png)",
            "",
            f"- Best benchmark by cumulative return: {summary['best_benchmark']}",
            "",
            "## Caveat",
            "",
            "If external deposits/withdrawals occurred, simple equity-based returns may be distorted.",
            "A future cash-flow log can improve accuracy.",
            "",
            "This report is for decision support only and does not place trades.",
        ]
    )
    (output_dir / "performance_report.md").write_text("\n".join(lines), encoding="utf-8")
    _write_html_report(output_dir, summary, args.benchmarks)
    _publish_report_bundles(output_dir, args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build live performance report vs benchmarks.",
    )
    parser.add_argument("--snapshots", default=DEFAULT_SNAPSHOTS)
    parser.add_argument("--trades", default=DEFAULT_TRADES)
    parser.add_argument("--cash-flows", default=DEFAULT_CASH_FLOWS)
    parser.add_argument("--benchmarks", nargs="+", default=DEFAULT_BENCHMARKS)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--publish-latest", action="store_true", default=False)
    parser.add_argument("--history", action="store_true", default=False)
    parser.add_argument("--report-run-id")
    return parser.parse_args()


if __name__ == "__main__":
    build_report(parse_args())
