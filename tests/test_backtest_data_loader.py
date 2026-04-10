"""Tests for backtest CSV loading and validation helpers."""

import pandas as pd
import pytest

from backtests.data_loader import (
    load_candidate_snapshots,
    load_price_history,
    validate_candidate_snapshots,
    validate_price_history,
)


def test_load_price_history_valid_input(tmp_path) -> None:
    csv_file = tmp_path / "price_history.csv"
    csv_file.write_text("date,symbol,close\n2025-01-02,AAPL,190.2\n")

    df = load_price_history(str(csv_file))

    assert list(df.columns) == ["date", "symbol", "close"]
    assert pd.api.types.is_datetime64_any_dtype(df["date"])


def test_load_candidate_snapshots_valid_input(tmp_path) -> None:
    csv_file = tmp_path / "candidate_snapshots.csv"
    csv_file.write_text("asof_date,symbol,universe_type\n2025-01-02,MSFT,momentum\n")

    df = load_candidate_snapshots(str(csv_file))

    assert list(df.columns) == ["asof_date", "symbol", "universe_type"]
    assert pd.api.types.is_datetime64_any_dtype(df["asof_date"])


def test_validate_price_history_missing_required_columns() -> None:
    df = pd.DataFrame({"date": ["2025-01-02"], "symbol": ["AAPL"]})

    with pytest.raises(ValueError, match="missing required columns"):
        validate_price_history(df)


def test_validate_candidate_snapshots_missing_required_columns() -> None:
    df = pd.DataFrame({"asof_date": ["2025-01-02"], "symbol": ["AAPL"]})

    with pytest.raises(ValueError, match="missing required columns"):
        validate_candidate_snapshots(df)


def test_validate_price_history_empty_dataframe() -> None:
    df = pd.DataFrame(columns=["date", "symbol", "close"])

    with pytest.raises(ValueError, match="empty"):
        validate_price_history(df)


def test_validate_candidate_snapshots_empty_dataframe() -> None:
    df = pd.DataFrame(columns=["asof_date", "symbol", "universe_type"])

    with pytest.raises(ValueError, match="empty"):
        validate_candidate_snapshots(df)


def test_load_price_history_empty_file(tmp_path) -> None:
    csv_file = tmp_path / "empty_price.csv"
    csv_file.write_text("")

    with pytest.raises(ValueError, match="CSV is empty"):
        load_price_history(str(csv_file))


def test_load_candidate_snapshots_empty_file(tmp_path) -> None:
    csv_file = tmp_path / "empty_candidates.csv"
    csv_file.write_text("")

    with pytest.raises(ValueError, match="CSV is empty"):
        load_candidate_snapshots(str(csv_file))
