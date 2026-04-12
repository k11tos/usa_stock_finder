from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtests.engine import BacktestEngineOptions, run_backtest
from backtests.models import (
    LMCandidateReviewLog,
    LMReviewDecision,
    LMReviewFinalAction,
    LMReviewReasonCode,
)
from backtests.report import (
    COMPARISON_SUMMARY_COLUMNS,
    build_comparison_summary_row,
    build_output_paths,
    build_run_tag,
    save_comparison_summary_csv,
    save_backtest_outputs,
    save_lm_review_log_jsonl,
    save_summary_metrics_json,
)


def test_build_run_tag_is_readable_and_deterministic() -> None:
    run_tag = build_run_tag(
        universe="quantus_minervini",
        entry="trend_basic",
        exit_rule="hold_fixed",
        start_date=pd.Timestamp("2025-01-01", tz="UTC"),
        end_date=pd.Timestamp("2025-12-31", tz="UTC"),
    )

    assert run_tag == "u-quantus-minervini__e-trend-basic__x-hold-fixed__2025-01-01_to_2025-12-31"


def test_build_output_paths_uses_stable_file_names() -> None:
    paths = build_output_paths(
        run_tag="u-quantus__e-none__x-hold-fixed__start_to_end",
        output_root=Path("outputs/backtests"),
    )

    assert paths["run_dir"] == Path("outputs/backtests/u-quantus__e-none__x-hold-fixed__start_to_end")
    assert paths["trades_csv"] == paths["run_dir"] / "trades.csv"
    assert paths["equity_curve_csv"] == paths["run_dir"] / "equity_curve.csv"
    assert paths["summary_metrics_json"] == paths["run_dir"] / "summary_metrics.json"
    assert paths["candidate_snapshot_csv"] == paths["run_dir"] / "candidate_snapshot.csv"
    assert paths["candidate_snapshot_universe_csv"] == paths["run_dir"] / "candidate_snapshot_universe.csv"
    assert paths["candidate_snapshot_entry_csv"] == paths["run_dir"] / "candidate_snapshot_entry.csv"
    assert paths["candidate_snapshot_selected_csv"] == paths["run_dir"] / "candidate_snapshot_selected.csv"
    assert paths["lm_review_log_jsonl"] == paths["run_dir"] / "lm_review_log.jsonl"


def test_save_summary_metrics_json_normalizes_non_finite_values(tmp_path: Path) -> None:
    output_path = tmp_path / "summary_metrics.json"
    save_summary_metrics_json({"profit_factor": math.inf, "max_drawdown": 0.12}, output_path)

    raw_content = output_path.read_text(encoding="utf-8")
    assert "Infinity" not in raw_content

    strict_parsed = json.loads(
        raw_content,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"Unexpected constant: {token}")),
    )
    assert strict_parsed["profit_factor"] == "inf"
    assert strict_parsed["max_drawdown"] == 0.12


def test_save_lm_review_log_jsonl_uses_stable_schema(tmp_path: Path) -> None:
    output_path = tmp_path / "lm_review_log.jsonl"
    rows = [
        LMCandidateReviewLog(
            date=date(2026, 1, 5),
            symbol="NVDA",
            decision=LMReviewDecision.PASSED,
            confidence=0.91234567,
            reason_codes=(LMReviewReasonCode.MANUAL_OVERRIDE,),
            final_action=LMReviewFinalAction.KEEP,
        ),
        LMCandidateReviewLog(
            date=date(2026, 1, 5),
            symbol="XYZ",
            decision=LMReviewDecision.REJECTED,
            confidence=0.32,
            reason_codes=(
                LMReviewReasonCode.NEWS_RISK,
                LMReviewReasonCode.NO_CLEAR_EDGE,
            ),
            final_action=LMReviewFinalAction.DROP,
        ),
    ]

    save_lm_review_log_jsonl(rows, output_path)
    parsed_rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert parsed_rows == [
        {
            "confidence": 0.912346,
            "date": "2026-01-05",
            "decision": "passed",
            "final_action": "keep",
            "reason_codes": ["manual_override"],
            "symbol": "NVDA",
        },
        {
            "confidence": 0.32,
            "date": "2026-01-05",
            "decision": "rejected",
            "final_action": "drop",
            "reason_codes": ["news_risk", "no_clear_edge"],
            "symbol": "XYZ",
        },
    ]


def test_save_lm_review_log_jsonl_rejects_out_of_range_confidence(tmp_path: Path) -> None:
    output_path = tmp_path / "lm_review_log.jsonl"
    rows = [
        LMCandidateReviewLog(
            date=date(2026, 1, 5),
            symbol="ABC",
            decision=LMReviewDecision.SKIPPED,
            confidence=1.2,
            reason_codes=(LMReviewReasonCode.EVENT_RISK,),
            final_action=LMReviewFinalAction.DEFER,
        ),
    ]

    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        save_lm_review_log_jsonl(rows, output_path)


def test_save_backtest_outputs_materializes_empty_lm_review_log_by_default(tmp_path: Path) -> None:
    paths = save_backtest_outputs(
        trades=pd.DataFrame([{"symbol": "AAPL", "entry_price": 100.0, "exit_price": 105.0}]),
        equity_curve=[100000.0, 100100.0],
        metrics={"total_return_pct": 0.1},
        candidates=pd.DataFrame([{"symbol": "AAPL", "asof_date": "2026-01-05"}]),
        run_tag="u-quantus__e-none__x-hold-fixed__2026-01-01_to_2026-01-31",
        output_root=tmp_path,
    )

    lm_log_path = paths["lm_review_log_jsonl"]
    assert lm_log_path.exists()
    assert lm_log_path.read_text(encoding="utf-8") == ""


def test_save_backtest_outputs_materializes_lm_review_log_with_rows(tmp_path: Path) -> None:
    rows = [
        LMCandidateReviewLog(
            date=date(2026, 2, 2),
            symbol="MSFT",
            decision=LMReviewDecision.PASSED,
            confidence=0.88,
            reason_codes=(LMReviewReasonCode.MANUAL_OVERRIDE,),
            final_action=LMReviewFinalAction.KEEP,
        )
    ]
    paths = save_backtest_outputs(
        trades=pd.DataFrame([{"symbol": "MSFT", "entry_price": 200.0, "exit_price": 210.0}]),
        equity_curve=[100000.0, 100300.0],
        metrics={"total_return_pct": 0.3},
        candidates=pd.DataFrame([{"symbol": "MSFT", "asof_date": "2026-02-02"}]),
        lm_review_rows=rows,
        run_tag="u-quantus__e-none__x-hold-fixed__2026-02-01_to_2026-02-28",
        output_root=tmp_path,
    )

    lines = paths["lm_review_log_jsonl"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "confidence": 0.88,
        "date": "2026-02-02",
        "decision": "passed",
        "final_action": "keep",
        "reason_codes": ["manual_override"],
        "symbol": "MSFT",
    }


def test_save_backtest_outputs_persists_enriched_trade_columns(tmp_path: Path) -> None:
    paths = save_backtest_outputs(
        trades=pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "entry_date": "2026-01-02",
                    "exit_date": "2026-01-05",
                    "entry_price": 100.0,
                    "exit_price": 110.0,
                    "quantity": 2.0,
                    "mfe_pct": 12.0,
                    "mae_pct": -3.0,
                    "universe": "quantus",
                    "entry_filter": "trend_basic",
                    "exit_rule": "stop_loss",
                    "exit_reason": "stop_loss",
                    "entry_signal_date": "2026-01-02",
                    "holding_days": 3,
                    "rank_value": 91.2,
                    "pnl": 20.0,
                }
            ]
        ),
        equity_curve=[100000.0, 100100.0],
        metrics={"total_return_pct": 0.1},
        candidates=pd.DataFrame([{"symbol": "AAPL", "asof_date": "2026-01-05"}]),
        run_tag="u-quantus__e-trend-basic__x-stop-loss__2026-01-01_to_2026-01-31",
        output_root=tmp_path,
    )

    saved = pd.read_csv(paths["trades_csv"])
    assert {
        "universe",
        "entry_filter",
        "exit_rule",
        "exit_reason",
        "entry_signal_date",
        "holding_days",
        "rank_value",
        "mfe_pct",
        "mae_pct",
    }.issubset(saved.columns)


def test_save_backtest_outputs_persists_stage_candidate_snapshots_with_subset_relationships(
    tmp_path: Path,
) -> None:
    stage_snapshots = {
        "universe": pd.DataFrame(
            [
                {"rebalance_date": "2026-01-05", "execution_date": "2026-01-05", "symbol": "AAPL"},
                {"rebalance_date": "2026-01-05", "execution_date": "2026-01-05", "symbol": "MSFT"},
                {"rebalance_date": "2026-01-05", "execution_date": "2026-01-05", "symbol": "NVDA"},
            ]
        ),
        "entry": pd.DataFrame(
            [
                {"rebalance_date": "2026-01-05", "execution_date": "2026-01-05", "symbol": "AAPL"},
                {"rebalance_date": "2026-01-05", "execution_date": "2026-01-05", "symbol": "NVDA"},
            ]
        ),
        "selected": pd.DataFrame(
            [
                {"rebalance_date": "2026-01-05", "execution_date": "2026-01-05", "symbol": "NVDA"},
            ]
        ),
    }

    paths = save_backtest_outputs(
        trades=pd.DataFrame([{"symbol": "NVDA", "entry_price": 100.0, "exit_price": 105.0}]),
        equity_curve=[100000.0, 100500.0],
        metrics={"total_return_pct": 0.5},
        candidates=pd.DataFrame([{"symbol": "NVDA", "asof_date": "2026-01-05"}]),
        candidate_stage_snapshots=stage_snapshots,
        run_tag="u-quantus__e-none__x-hold-fixed__2026-01-01_to_2026-01-31",
        output_root=tmp_path,
    )

    for stage_path in (
        paths["candidate_snapshot_universe_csv"],
        paths["candidate_snapshot_entry_csv"],
        paths["candidate_snapshot_selected_csv"],
    ):
        assert stage_path.exists()

    universe_saved = pd.read_csv(paths["candidate_snapshot_universe_csv"])
    entry_saved = pd.read_csv(paths["candidate_snapshot_entry_csv"])
    selected_saved = pd.read_csv(paths["candidate_snapshot_selected_csv"])

    universe_keys = set(zip(universe_saved["rebalance_date"], universe_saved["symbol"]))
    entry_keys = set(zip(entry_saved["rebalance_date"], entry_saved["symbol"]))
    selected_keys = set(zip(selected_saved["rebalance_date"], selected_saved["symbol"]))

    assert selected_keys.issubset(entry_keys)
    assert entry_keys.issubset(universe_keys)


def test_save_backtest_outputs_keeps_empty_stage_snapshot_files_readable(tmp_path: Path) -> None:
    candidates = pd.DataFrame(
        [
            {
                "asof_date": "2026-01-05",
                "symbol": "AAA",
                "close": 100.0,
                "rs_score": 75.0,
                "sma50": 100.0,
                "sma150": 100.0,
                "sma200": 100.0,
                "high_52w": 130.0,
                "low_52w": 80.0,
            }
        ]
    )
    price_history = pd.DataFrame(
        [
            {"date": "2026-01-05", "symbol": "AAA", "close": 100.0},
            {"date": "2026-01-06", "symbol": "AAA", "close": 101.0},
        ]
    )
    result = run_backtest(
        candidates=candidates,
        price_history=price_history,
        universe="quantus",
        entry="trend_strict",
        exit_rule="hold_fixed",
        options=BacktestEngineOptions(
            top_n=1,
            rank_col="rs_score",
            starting_equity=100_000.0,
            hold_days=5,
            stop_loss_pct=0.08,
            trailing_pct=0.10,
            exit_rule="hold_fixed",
        ),
    )

    paths = save_backtest_outputs(
        trades=result["trades"],
        equity_curve=result["equity_curve"],
        metrics=result["metrics"],
        candidates=candidates,
        candidate_stage_snapshots=result["candidate_stage_snapshots"],
        run_tag="u-quantus__e-trend-strict__x-hold-fixed__2026-01-01_to_2026-01-31",
        output_root=tmp_path,
    )

    entry_saved = pd.read_csv(paths["candidate_snapshot_entry_csv"])
    selected_saved = pd.read_csv(paths["candidate_snapshot_selected_csv"])

    assert entry_saved.empty
    assert selected_saved.empty
    expected_columns = {
        "rebalance_date",
        "execution_date",
        "stage",
        "universe",
        "entry_filter",
        "exit_rule",
        "rank_col",
        "top_n",
    }
    assert expected_columns.issubset(entry_saved.columns)
    assert expected_columns.issubset(selected_saved.columns)


def test_build_comparison_summary_row_has_expected_flat_fields() -> None:
    result = {
        "config": {"universe": "quantus", "entry": "trend_basic", "exit_rule": "trailing"},
        "metrics": {
            "total_trades": 2,
            "total_return": 0.15,
            "cagr": 0.12,
            "max_drawdown": 0.08,
            "win_rate": 0.5,
            "profit_factor": 1.8,
        },
        "trades": pd.DataFrame(
            [
                {"symbol": "AAA", "mfe_pct": 10.0, "mae_pct": -4.0},
                {"symbol": "BBB", "mfe_pct": 6.0, "mae_pct": -2.0},
            ]
        ),
    }

    row = build_comparison_summary_row(result=result)

    assert set(row.keys()) == set(COMPARISON_SUMMARY_COLUMNS)
    assert row["universe"] == "quantus"
    assert row["entry"] == "trend_basic"
    assert row["exit_rule"] == "trailing"
    assert row["total_trades"] == 2
    assert row["avg_mfe"] == pytest.approx(8.0)
    assert row["avg_mae"] == pytest.approx(-3.0)


def test_save_comparison_summary_csv_enforces_deterministic_columns(tmp_path: Path) -> None:
    output_path = tmp_path / "comparison_summary.csv"
    row = {
        "exit_rule": "hold_fixed",
        "entry": "none",
        "universe": "quantus",
        "total_trades": 10,
        "total_return": 0.2,
        "cagr": 0.1,
        "max_drawdown": 0.05,
        "win_rate": 0.6,
        "profit_factor": 1.5,
        "avg_mfe": 4.0,
        "avg_mae": -2.0,
        "unexpected_col": "ignored",
    }

    save_comparison_summary_csv([row], output_path)
    saved = pd.read_csv(output_path)

    assert list(saved.columns) == COMPARISON_SUMMARY_COLUMNS
