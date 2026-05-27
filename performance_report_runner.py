"""Safe orchestration wrapper for optional post-run performance reports."""

from __future__ import annotations

import argparse
import logging
import os

from tools.performance_report import build_report

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def run_performance_report_safely() -> bool:
    """Run performance report generation with failure isolation.

    Returns:
        bool: True when report generation succeeds, False when skipped or failed.
    """
    enabled = _env_bool("PERFORMANCE_REPORT_ENABLED", False)
    if not enabled:
        logger.info("Performance report generation skipped (PERFORMANCE_REPORT_ENABLED=false)")
        return False

    output_dir = os.getenv("PERFORMANCE_REPORT_OUTPUT_DIR", "outputs/performance")
    benchmarks = _env_list("PERFORMANCE_REPORT_BENCHMARKS", ["SPY", "IWM"])
    publish_latest = _env_bool("PERFORMANCE_REPORT_PUBLISH_LATEST", True)
    history = _env_bool("PERFORMANCE_REPORT_HISTORY", False)

    args = argparse.Namespace(
        snapshots="data/live/account_snapshots.csv",
        trades="data/live/trade_signals.csv",
        benchmarks=benchmarks,
        output=output_dir,
        start_date=None,
        end_date=None,
        publish_latest=publish_latest,
        history=history,
        report_run_id=None,
    )

    try:
        build_report(args)
        logger.info(
            "Performance report generated: output=%s benchmarks=%s publish_latest=%s history=%s",
            output_dir,
            benchmarks,
            publish_latest,
            history,
        )
    except Exception as exc:  # pragma: no cover - defensive safety wrapper
        logger.warning("Performance report generation failed (continuing main flow): %s", str(exc))
        return False

    return True
