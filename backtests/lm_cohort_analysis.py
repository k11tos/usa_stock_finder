"""Optional helpers for LM-review cohort analysis in backtest diagnostics.

This module is intentionally isolated from the core backtest engine. It only
operates on already-materialized DataFrames and structured LM review logs.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

import pandas as pd

LM_COHORT_ALL: Final[str] = "all"
LM_COHORT_PASSED: Final[str] = "passed"
LM_COHORT_REJECTED: Final[str] = "rejected"
LM_COHORT_SKIPPED: Final[str] = "skipped"
LM_COHORT_LABELS: Final[tuple[str, ...]] = (
    LM_COHORT_ALL,
    LM_COHORT_PASSED,
    LM_COHORT_REJECTED,
    LM_COHORT_SKIPPED,
)

_VALID_DECISIONS: Final[set[str]] = {
    LM_COHORT_PASSED,
    LM_COHORT_REJECTED,
    LM_COHORT_SKIPPED,
}


def _normalize_join_key(frame: pd.DataFrame, *, date_col: str, symbol_col: str) -> pd.DataFrame:
    missing_required = [column for column in (date_col, symbol_col) if column not in frame.columns]
    if missing_required:
        missing_list = ", ".join(sorted(missing_required))
        raise ValueError(f"Missing required columns for LM cohort join: {missing_list}")

    normalized = frame.copy(deep=True)
    normalized["_cohort_date"] = pd.to_datetime(normalized[date_col], errors="coerce").dt.normalize()
    normalized["_cohort_symbol"] = normalized[symbol_col].astype(str)
    return normalized


def join_frame_with_lm_reviews(
    frame: pd.DataFrame,
    lm_review_log: pd.DataFrame,
    *,
    date_col: str,
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Left-join frame rows with LM review records by date+symbol.

    Rows without a matching review record are treated as ``skipped`` by default,
    which keeps cohort definitions stable for historical runs that predate
    structured review logging.
    """

    normalized_frame = _normalize_join_key(frame, date_col=date_col, symbol_col=symbol_col)

    if lm_review_log.empty:
        normalized_reviews = pd.DataFrame(columns=["_cohort_date", "_cohort_symbol", "lm_decision"])
    else:
        normalized_reviews = _normalize_join_key(lm_review_log, date_col="date", symbol_col="symbol")
        if "decision" not in normalized_reviews.columns:
            raise ValueError("Missing required columns for LM cohort join: decision")

        normalized_reviews = normalized_reviews[["_cohort_date", "_cohort_symbol", "decision"]].copy(deep=True)
        normalized_reviews["lm_decision"] = normalized_reviews["decision"].astype(str).str.lower()
        normalized_reviews = normalized_reviews.drop(columns=["decision"])
        normalized_reviews = normalized_reviews.drop_duplicates(
            subset=["_cohort_date", "_cohort_symbol"],
            keep="last",
        )

    joined = normalized_frame.merge(
        normalized_reviews,
        on=["_cohort_date", "_cohort_symbol"],
        how="left",
    )

    joined["lm_decision"] = joined["lm_decision"].where(
        joined["lm_decision"].isin(_VALID_DECISIONS),
        LM_COHORT_SKIPPED,
    )
    joined["lm_cohort"] = joined["lm_decision"]

    return joined.drop(columns=["_cohort_date", "_cohort_symbol"])


def summarize_candidate_cohorts(
    candidates: pd.DataFrame,
    lm_review_log: pd.DataFrame,
    *,
    date_col: str = "asof_date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return compact cohort-level candidate counts.

    The summary always includes rows in stable label order:
    ``all``, ``passed``, ``rejected``, ``skipped``.
    """

    joined = join_frame_with_lm_reviews(
        candidates,
        lm_review_log,
        date_col=date_col,
        symbol_col=symbol_col,
    )

    records: list[dict[str, int | str]] = []
    for cohort in LM_COHORT_LABELS:
        subset = joined if cohort == LM_COHORT_ALL else joined.loc[joined["lm_cohort"] == cohort]
        records.append(
            {
                "cohort": cohort,
                "candidate_count": int(len(subset)),
                "symbol_count": int(subset[symbol_col].astype(str).nunique()) if symbol_col in subset.columns else 0,
            }
        )

    return pd.DataFrame.from_records(records)


def summarize_trade_cohorts(
    trades: pd.DataFrame,
    lm_review_log: pd.DataFrame,
    *,
    date_col_priority: Iterable[str] = ("entry_signal_date", "entry_date"),
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return compact cohort-level trade counts and total PnL."""

    available_date_cols = [column for column in date_col_priority if column in trades.columns]
    if not available_date_cols:
        options = ", ".join(date_col_priority)
        raise ValueError(f"Missing required columns for LM cohort join: one of [{options}]")

    resolved_dates = pd.Series(pd.NaT, index=trades.index, dtype="datetime64[ns]")
    for column in available_date_cols:
        column_dates = pd.to_datetime(trades[column], errors="coerce").dt.normalize()
        resolved_dates = resolved_dates.fillna(column_dates)

    trade_frame = trades.copy(deep=True)
    trade_frame["_lm_join_date"] = resolved_dates

    joined = join_frame_with_lm_reviews(
        trade_frame,
        lm_review_log,
        date_col="_lm_join_date",
        symbol_col=symbol_col,
    )
    joined = joined.drop(columns=["_lm_join_date"])

    if "pnl" in joined.columns:
        pnl_series = pd.to_numeric(joined["pnl"], errors="coerce").fillna(0.0)
    else:
        required = {"entry_price", "exit_price", "quantity"}
        missing = [column for column in sorted(required) if column not in joined.columns]
        if missing:
            missing_list = ", ".join(missing)
            raise ValueError(f"Missing required trade columns for PnL calculation: {missing_list}")
        pnl_series = (
            pd.to_numeric(joined["exit_price"], errors="coerce").fillna(0.0)
            - pd.to_numeric(joined["entry_price"], errors="coerce").fillna(0.0)
        ) * pd.to_numeric(joined["quantity"], errors="coerce").fillna(0.0)

    joined = joined.assign(_cohort_pnl=pnl_series)

    records: list[dict[str, int | float | str]] = []
    for cohort in LM_COHORT_LABELS:
        subset = joined if cohort == LM_COHORT_ALL else joined.loc[joined["lm_cohort"] == cohort]
        records.append(
            {
                "cohort": cohort,
                "trade_count": int(len(subset)),
                "total_pnl": float(pd.to_numeric(subset["_cohort_pnl"], errors="coerce").fillna(0.0).sum()),
            }
        )

    return pd.DataFrame.from_records(records)
