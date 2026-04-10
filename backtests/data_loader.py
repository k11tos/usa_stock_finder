"""CSV loading and validation helpers for backtesting inputs."""

from __future__ import annotations

import pandas as pd


_PRICE_HISTORY_REQUIRED_COLUMNS = ("date", "symbol", "close")
_CANDIDATE_SNAPSHOT_REQUIRED_COLUMNS = ("asof_date", "symbol", "universe_type")


def _missing_columns(df: pd.DataFrame, required_columns: tuple[str, ...]) -> list[str]:
    return [column for column in required_columns if column not in df.columns]


def _normalize_datetime_column(df: pd.DataFrame, column_name: str) -> None:
    original_values = df[column_name]
    parsed_values = pd.to_datetime(original_values, errors="coerce")

    invalid_mask = original_values.notna() & parsed_values.isna()
    if invalid_mask.any():
        bad_examples = sorted({str(value) for value in original_values[invalid_mask].head(5)})
        raise ValueError(
            f"Column '{column_name}' contains invalid date values: {bad_examples}."
        )

    df[column_name] = parsed_values


def validate_price_history(df: pd.DataFrame) -> None:
    """Validate backtest price history input data."""
    missing = _missing_columns(df, _PRICE_HISTORY_REQUIRED_COLUMNS)
    if missing:
        raise ValueError(
            "Price history is missing required columns: "
            f"{missing}. Required columns: {list(_PRICE_HISTORY_REQUIRED_COLUMNS)}."
        )

    if df.empty:
        raise ValueError("Price history input is empty.")

    _normalize_datetime_column(df, "date")


def validate_candidate_snapshots(df: pd.DataFrame) -> None:
    """Validate backtest candidate snapshot input data."""
    missing = _missing_columns(df, _CANDIDATE_SNAPSHOT_REQUIRED_COLUMNS)
    if missing:
        raise ValueError(
            "Candidate snapshots are missing required columns: "
            f"{missing}. Required columns: {list(_CANDIDATE_SNAPSHOT_REQUIRED_COLUMNS)}."
        )

    if df.empty:
        raise ValueError("Candidate snapshots input is empty.")

    _normalize_datetime_column(df, "asof_date")


def load_price_history(csv_path: str) -> pd.DataFrame:
    """Load and validate a price history CSV for backtests."""
    try:
        df = pd.read_csv(csv_path)
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"Price history CSV is empty: {csv_path}") from exc

    validate_price_history(df)
    return df


def load_candidate_snapshots(csv_path: str) -> pd.DataFrame:
    """Load and validate a candidate snapshot CSV for backtests."""
    try:
        df = pd.read_csv(csv_path)
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"Candidate snapshots CSV is empty: {csv_path}") from exc

    validate_candidate_snapshots(df)
    return df
