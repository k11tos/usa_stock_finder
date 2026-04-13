"""Tests for optional LM cohort analysis helpers."""

import pandas as pd

from backtests.lm_cohort_analysis import (
    LM_COHORT_LABELS,
    join_frame_with_lm_reviews,
    summarize_candidate_cohorts,
    summarize_trade_cohorts,
)


def test_join_frame_with_lm_reviews_matches_on_date_and_symbol() -> None:
    candidates = pd.DataFrame(
        [
            {"asof_date": "2026-01-05", "symbol": "AAPL", "rank": 1},
            {"asof_date": "2026-01-05", "symbol": "MSFT", "rank": 2},
        ]
    )
    logs = pd.DataFrame(
        [
            {"date": "2026-01-05", "symbol": "AAPL", "decision": "passed"},
            {"date": "2026-01-05", "symbol": "MSFT", "decision": "rejected"},
        ]
    )

    joined = join_frame_with_lm_reviews(candidates, logs, date_col="asof_date")

    assert list(joined["lm_decision"]) == ["passed", "rejected"]
    assert list(joined["lm_cohort"]) == ["passed", "rejected"]


def test_join_frame_with_lm_reviews_defaults_missing_rows_to_skipped() -> None:
    candidates = pd.DataFrame(
        [
            {"asof_date": "2026-01-05", "symbol": "AAPL"},
            {"asof_date": "2026-01-05", "symbol": "NVDA"},
        ]
    )
    logs = pd.DataFrame(
        [
            {"date": "2026-01-05", "symbol": "AAPL", "decision": "passed"},
        ]
    )

    joined = join_frame_with_lm_reviews(candidates, logs, date_col="asof_date")

    assert list(joined["lm_decision"]) == ["passed", "skipped"]
    assert list(joined["lm_cohort"]) == ["passed", "skipped"]


def test_join_frame_with_lm_reviews_accepts_completely_empty_log_dataframe() -> None:
    candidates = pd.DataFrame(
        [
            {"asof_date": "2026-01-05", "symbol": "AAPL"},
            {"asof_date": "2026-01-05", "symbol": "MSFT"},
        ]
    )

    joined = join_frame_with_lm_reviews(candidates, pd.DataFrame(), date_col="asof_date")

    assert list(joined["lm_decision"]) == ["skipped", "skipped"]
    assert list(joined["lm_cohort"]) == ["skipped", "skipped"]


def test_summarize_trade_cohorts_falls_back_row_wise_to_entry_date() -> None:
    trades = pd.DataFrame(
        [
            {
                "entry_signal_date": "2026-01-05",
                "entry_date": "2026-01-06",
                "symbol": "AAPL",
                "entry_price": 100.0,
                "exit_price": 110.0,
                "quantity": 1.0,
            },
            {
                "entry_signal_date": None,
                "entry_date": "2026-01-07",
                "symbol": "MSFT",
                "entry_price": 200.0,
                "exit_price": 180.0,
                "quantity": 1.0,
            },
        ]
    )
    logs = pd.DataFrame(
        [
            {"date": "2026-01-05", "symbol": "AAPL", "decision": "passed"},
            {"date": "2026-01-07", "symbol": "MSFT", "decision": "rejected"},
        ]
    )

    summary = summarize_trade_cohorts(trades, logs)
    trade_counts = dict(zip(summary["cohort"], summary["trade_count"], strict=True))

    assert trade_counts == {
        "all": 2,
        "passed": 1,
        "rejected": 1,
        "skipped": 0,
    }


def test_cohort_summaries_keep_stable_labels_and_support_candidate_and_trade_comparison() -> None:
    candidates = pd.DataFrame(
        [
            {"asof_date": "2026-01-05", "symbol": "AAPL"},
            {"asof_date": "2026-01-05", "symbol": "MSFT"},
            {"asof_date": "2026-01-05", "symbol": "NVDA"},
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "entry_signal_date": "2026-01-05",
                "symbol": "AAPL",
                "entry_price": 100.0,
                "exit_price": 110.0,
                "quantity": 1.0,
            },
            {
                "entry_signal_date": "2026-01-05",
                "symbol": "MSFT",
                "entry_price": 100.0,
                "exit_price": 90.0,
                "quantity": 1.0,
            },
        ]
    )
    logs = pd.DataFrame(
        [
            {"date": "2026-01-05", "symbol": "AAPL", "decision": "passed"},
            {"date": "2026-01-05", "symbol": "MSFT", "decision": "rejected"},
        ]
    )

    candidate_summary = summarize_candidate_cohorts(candidates, logs)
    trade_summary = summarize_trade_cohorts(trades, logs)

    assert tuple(candidate_summary["cohort"]) == LM_COHORT_LABELS
    assert tuple(trade_summary["cohort"]) == LM_COHORT_LABELS

    candidate_counts = dict(zip(candidate_summary["cohort"], candidate_summary["candidate_count"], strict=True))
    assert candidate_counts == {
        "all": 3,
        "passed": 1,
        "rejected": 1,
        "skipped": 1,
    }

    trade_counts = dict(zip(trade_summary["cohort"], trade_summary["trade_count"], strict=True))
    assert trade_counts == {
        "all": 2,
        "passed": 1,
        "rejected": 1,
        "skipped": 0,
    }
