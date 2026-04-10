from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from backtests.report import build_output_paths, build_run_tag, save_summary_metrics_json


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
