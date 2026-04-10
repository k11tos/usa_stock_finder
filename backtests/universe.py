"""Universe construction helpers for backtest candidate snapshots."""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

_ASOF_DATE_COLUMN = "asof_date"
_SYMBOL_COLUMN = "symbol"
_DIGIT_DATE_PATTERN = re.compile(r"^\d{8}$")


def _parse_date_value(value: object) -> pd.Timestamp | pd.NaTType:
    if pd.isna(value):
        return pd.NaT

    text = str(value).strip()
    if _DIGIT_DATE_PATTERN.fullmatch(text):
        return pd.to_datetime(text, format="%Y%m%d", errors="coerce")

    return pd.to_datetime(value, errors="coerce")


def _normalize_asof_dates(df: pd.DataFrame) -> pd.Series:
    return df[_ASOF_DATE_COLUMN].apply(_parse_date_value)


def _to_calendar_day(value: object) -> date | pd.NaTType:
    parsed = _parse_date_value(value)
    if pd.isna(parsed):
        return pd.NaT

    return parsed.date()


def _filter_candidates_for_date(candidates: pd.DataFrame, asof_date: str) -> pd.DataFrame:
    required_columns = [_ASOF_DATE_COLUMN, _SYMBOL_COLUMN]
    missing_required = [column for column in required_columns if column not in candidates.columns]
    if missing_required:
        raise ValueError(
            "Candidates are missing required columns for universe construction: "
            f"{missing_required}."
        )

    filtered = candidates.copy(deep=True)
    filtered[_ASOF_DATE_COLUMN] = _normalize_asof_dates(filtered)

    if filtered[_ASOF_DATE_COLUMN].isna().any():
        bad_examples = sorted(
            {
                str(value)
                for value in candidates.loc[
                    filtered[_ASOF_DATE_COLUMN].isna(), _ASOF_DATE_COLUMN
                ].head(5)
            }
        )
        raise ValueError(
            f"Column '{_ASOF_DATE_COLUMN}' contains invalid date values: {bad_examples}."
        )

    target_day = _to_calendar_day(asof_date)
    if pd.isna(target_day):
        raise ValueError(f"Invalid asof_date value: {asof_date!r}.")

    candidate_days = filtered[_ASOF_DATE_COLUMN].apply(lambda timestamp: timestamp.date())
    selected = filtered.loc[candidate_days == target_day].copy(deep=True)
    return selected.reset_index(drop=True)


def build_quantus_universe(candidates: pd.DataFrame, asof_date: str) -> pd.DataFrame:
    """Return the raw Quantus-like candidate set for the given date.

    The function performs only required validation and date filtering.
    """
    return _filter_candidates_for_date(candidates, asof_date)


def build_quantus_minervini_universe(
    candidates: pd.DataFrame,
    asof_date: str,
    *,
    min_market_cap: float = 300_000_000,
    min_avg_dollar_volume: float = 5_000_000,
    min_rs_score: float = 70,
    max_pct_below_52w_high: float = 25,
    market_cap_col: str = "market_cap",
    avg_dollar_volume_col: str = "avg_dollar_volume",
    rs_score_col: str = "rs_score",
    pct_below_52w_high_col: str = "pct_below_52w_high",
) -> pd.DataFrame:
    """Return a Minervini-friendly subset of the Quantus-like date snapshot.

    The subset is built conservatively using liquidity, size, relative strength,
    and proximity-to-high columns when they are present and required.
    """
    universe = _filter_candidates_for_date(candidates, asof_date)

    required_filter_columns = [
        market_cap_col,
        avg_dollar_volume_col,
        rs_score_col,
        pct_below_52w_high_col,
    ]
    missing_filter_columns = [
        column for column in required_filter_columns if column not in universe.columns
    ]
    if missing_filter_columns:
        raise ValueError(
            "Minervini universe requires columns that are missing from candidates: "
            f"{missing_filter_columns}."
        )

    mask = (
        (universe[market_cap_col] >= min_market_cap)
        & (universe[avg_dollar_volume_col] >= min_avg_dollar_volume)
        & (universe[rs_score_col] >= min_rs_score)
        & (universe[pct_below_52w_high_col] <= max_pct_below_52w_high)
    )

    filtered = universe.loc[mask].copy(deep=True)
    return filtered.reset_index(drop=True)
