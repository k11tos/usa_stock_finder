from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtests.models import (
    LMCandidateReviewLog,
    LMReviewDecision,
    LMReviewFinalAction,
    LMReviewReasonCode,
)
from backtests.report import (
    build_output_paths,
    build_run_tag,
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
