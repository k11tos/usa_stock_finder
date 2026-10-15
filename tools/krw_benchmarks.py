"""Historical dividend-adjusted USD benchmarks valued in KRW, without lookahead."""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf

DOWNLOAD_TIMEOUT_SECONDS = 10.0
MAX_QUOTE_AGE_DAYS = 4
USD_BENCHMARKS = {"SPY", "IWM"}
AUDIT_COLUMNS = [
    "date", "asset", "benchmark_date", "fx_date", "adjusted_close_usd",
    "usdkrw", "benchmark_value_krw", "benchmark_index", "excess_return_pp",
]
METHODOLOGY = (
    "Yahoo Finance dividend/split-adjusted USD close × historical KRW=X close (KRW per USD). "
    "Each daily bar is eligible only after 00:00 UTC on the following date; use the latest "
    "completed observation at each broker timestamp, at most 4 calendar days old. "
    "No backfill or constant FX. Both series must cover every portfolio observation. "
    "These are daily reference valuations, not synchronized intraday executable prices."
)


def fetch_series(symbol: str, field: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Require an explicit adjusted close for ETFs; never substitute an unadjusted close."""
    data = yf.download(
        symbol, start=(start - pd.Timedelta(days=7)).date(),
        end=(end + pd.Timedelta(days=1)).date(), auto_adjust=False,
        progress=False, timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )
    if isinstance(data.columns, pd.MultiIndex):
        columns = [col for col in data.columns if field in col and symbol in col]
        if len(columns) != 1:
            return pd.Series(dtype=float)
        series = data[columns[0]]
    elif field in data.columns:
        series = data[field]
    else:
        return pd.Series(dtype=float)
    return series


def align_observations(series: pd.Series, fetched: pd.Series) -> pd.DataFrame:
    """Align dated daily bars conservatively to actual timestamps, including weekends.

    Invalid rows are retained as unavailable rather than skipped to a prior good
    quote. Duplicate dates make the whole series ambiguous and unavailable.
    """
    empty = pd.DataFrame({"quote_date": pd.NaT, "value": np.nan}, index=fetched.index)
    if series.empty:
        return empty
    # A provider's timezone-aware index labels a session date. Converting local
    # midnight to UTC first could move that date backward and allow lookahead.
    dates = pd.DatetimeIndex(pd.to_datetime(series.index, errors="coerce")).tz_localize(None).normalize()
    if dates.isna().any() or dates.has_duplicates:
        return empty
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    quotes = pd.DataFrame({"quote_date": dates, "value": values})
    quotes.loc[~np.isfinite(values) | (values <= 0), "value"] = np.nan
    quotes["available_at"] = quotes["quote_date"].dt.tz_localize("UTC") + pd.Timedelta(days=1)
    targets = pd.DataFrame({"fetched": pd.to_datetime(fetched, utc=True)}, index=fetched.index)
    targets["_order"] = range(len(targets))
    aligned = pd.merge_asof(
        targets.sort_values("fetched"), quotes.sort_values("available_at"),
        left_on="fetched", right_on="available_at", direction="backward",
    ).sort_values("_order")
    age = aligned["fetched"].dt.tz_localize(None).dt.normalize() - aligned["quote_date"]
    aligned.loc[age > pd.Timedelta(days=MAX_QUOTE_AGE_DAYS), "value"] = np.nan
    aligned.index = fetched.index
    return aligned[["quote_date", "value"]]


def compare_benchmarks(daily: pd.DataFrame, twr: pd.DataFrame, symbols: list[str],
                       returns_validated: bool) -> tuple[pd.DataFrame, pd.DataFrame, dict, list[str]]:
    """Return normalized KRW indices, auditable source dates, metrics and safe warnings."""
    index = pd.DatetimeIndex(daily["run_date"])
    normalized = pd.DataFrame(index=index)
    audit_rows = []
    metrics = {"benchmark_methodology": METHODOLOGY, "benchmark_currency": "KRW",
               "benchmark_data_source": "Yahoo Finance", "best_benchmark": None,
               "benchmark_status": {}}
    warnings = []
    for symbol in symbols:
        metrics[f"cumulative_return_{symbol}_pct"] = None
        metrics[f"excess_return_vs_{symbol}"] = None
        metrics["benchmark_status"][symbol] = "unavailable"
    if not returns_validated or not symbols:
        if symbols:
            warnings.append("Benchmark and excess returns: N/A; full-period portfolio TWR is not validated.")
        return normalized, pd.DataFrame(columns=AUDIT_COLUMNS), metrics, warnings

    def download(symbol, field):
        try:
            series = fetch_series(symbol, field, index.min(), index.max())
            return align_observations(series, daily["fetched_at_kst"])
        except Exception:  # Network/provider failures must not suppress the portfolio report or expose raw errors.
            return align_observations(pd.Series(dtype=float), daily["fetched_at_kst"])

    fx = download("KRW=X", "Close")
    if fx["value"].isna().any():
        warnings.append("Historical USD/KRW FX missing, invalid or stale on aligned dates; KRW comparisons are N/A.")
    strategy_index = twr["twr_index"].to_numpy(dtype=float)
    for symbol in symbols:
        if symbol not in USD_BENCHMARKS:
            warnings.append(f"{symbol}: USD valuation currency is not verified; KRW comparison is N/A.")
            continue
        prices = download(symbol, "Adj Close")
        if prices["value"].isna().any():
            warnings.append(f"{symbol}: dividend-adjusted benchmark data missing, invalid or stale; comparison is N/A.")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            krw = prices["value"].to_numpy() * fx["value"].to_numpy()
            normalized_values = krw / krw[0] * 100
        valid = bool(np.isfinite(krw).all() and (krw > 0).all()
                     and np.isfinite(normalized_values).all() and (normalized_values > 0).all())
        if valid:
            normalized[symbol] = normalized_values
            ret = float(normalized_values[-1] - 100)
            metrics[f"cumulative_return_{symbol}_pct"] = ret
            metrics[f"excess_return_vs_{symbol}"] = float(strategy_index[-1] - normalized_values[-1])
            metrics["benchmark_status"][symbol] = "available"
        else:
            warnings.append(f"{symbol}: full-period KRW benchmark/excess return unavailable; "
                            "no partial-period rebasing.")
        for pos, date in enumerate(index):
            audit_rows.append({
                "date": date, "asset": symbol, "benchmark_date": prices["quote_date"].iloc[pos],
                "fx_date": fx["quote_date"].iloc[pos], "adjusted_close_usd": prices["value"].iloc[pos],
                "usdkrw": fx["value"].iloc[pos], "benchmark_value_krw": krw[pos] if np.isfinite(krw[pos]) else None,
                "benchmark_index": normalized_values[pos] if valid else None,
                "excess_return_pp": float(strategy_index[pos] - normalized_values[pos]) if valid else None,
            })
    available = [symbol for symbol in symbols if metrics[f"cumulative_return_{symbol}_pct"] is not None]
    if available:
        metrics["best_benchmark"] = max(available, key=lambda symbol: metrics[f"cumulative_return_{symbol}_pct"])
    return normalized, pd.DataFrame(audit_rows, columns=AUDIT_COLUMNS), metrics, warnings
