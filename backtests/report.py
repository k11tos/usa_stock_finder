"""Helpers for persisting lightweight structured backtest artifacts."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

from backtests.models import LMCandidateReviewLog

DEFAULT_OUTPUT_ROOT = Path("outputs/backtests")


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower())
    return cleaned.strip("-") or "na"


def _date_part(start_date: pd.Timestamp | None, end_date: pd.Timestamp | None) -> str:
    start = "start" if start_date is None else pd.Timestamp(start_date).strftime("%Y-%m-%d")
    end = "end" if end_date is None else pd.Timestamp(end_date).strftime("%Y-%m-%d")
    return f"{start}_to_{end}"


def build_run_tag(
    *,
    universe: str,
    entry: str,
    exit_rule: str,
    start_date: pd.Timestamp | None,
    end_date: pd.Timestamp | None,
) -> str:
    """Build deterministic run tag for a backtest configuration."""
    return "__".join(
        [
            f"u-{_slugify(universe)}",
            f"e-{_slugify(entry)}",
            f"x-{_slugify(exit_rule)}",
            _date_part(start_date, end_date),
        ]
    )


def build_output_paths(run_tag: str, output_root: str | Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Path]:
    """Return deterministic output paths for persisted backtest artifacts."""
    run_dir = Path(output_root) / run_tag
    return {
        "run_dir": run_dir,
        "trades_csv": run_dir / "trades.csv",
        "equity_curve_csv": run_dir / "equity_curve.csv",
        "summary_metrics_json": run_dir / "summary_metrics.json",
        "candidate_snapshot_csv": run_dir / "candidate_snapshot.csv",
        "lm_review_log_jsonl": run_dir / "lm_review_log.jsonl",
    }


def save_trades_csv(trades: pd.DataFrame, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(output_path, index=False)
    return output_path


def save_equity_curve_csv(equity_curve: list[float], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    equity_df = pd.DataFrame(
        {
            "step": list(range(len(equity_curve))),
            "equity": [float(value) for value in equity_curve],
        }
    )
    equity_df.to_csv(output_path, index=False)
    return output_path


def save_summary_metrics_json(metrics: dict[str, Any], path: str | Path) -> Path:
    def _normalize_non_finite(value: Any) -> Any:
        if isinstance(value, float):
            if math.isinf(value):
                return "inf" if value > 0 else "-inf"
            if math.isnan(value):
                return "nan"
            return value
        if isinstance(value, dict):
            return {key: _normalize_non_finite(inner_value) for key, inner_value in value.items()}
        if isinstance(value, list):
            return [_normalize_non_finite(item) for item in value]
        if isinstance(value, tuple):
            return tuple(_normalize_non_finite(item) for item in value)
        return value

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_metrics = _normalize_non_finite(metrics)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(normalized_metrics, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    return output_path


def save_candidate_snapshot_csv(candidates: pd.DataFrame, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(output_path, index=False)
    return output_path


def _serialize_lm_review_row(row: LMCandidateReviewLog) -> dict[str, Any]:
    confidence = float(row.confidence)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("LM review confidence must be between 0.0 and 1.0.")

    return {
        "date": row.date.isoformat(),
        "symbol": row.symbol,
        "decision": row.decision.value,
        "confidence": round(confidence, 6),
        "reason_codes": [reason.value for reason in row.reason_codes],
        "final_action": row.final_action.value,
    }


def save_lm_review_log_jsonl(rows: list[LMCandidateReviewLog], path: str | Path) -> Path:
    """Persist structured LM review rows as JSONL for later cohort analysis."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            payload = _serialize_lm_review_row(row)
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    return output_path


def save_backtest_outputs(
    *,
    trades: pd.DataFrame,
    equity_curve: list[float],
    metrics: dict[str, Any],
    candidates: pd.DataFrame,
    run_tag: str,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, Path]:
    """Persist all backtest artifacts and return resolved output paths."""
    paths = build_output_paths(run_tag=run_tag, output_root=output_root)
    save_trades_csv(trades, paths["trades_csv"])
    save_equity_curve_csv(equity_curve, paths["equity_curve_csv"])
    save_summary_metrics_json(metrics, paths["summary_metrics_json"])
    save_candidate_snapshot_csv(candidates, paths["candidate_snapshot_csv"])
    return paths
