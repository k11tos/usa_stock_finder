"""Optional, isolated collection of fresh broker equity after daily execution."""

import logging
import os

from live_performance_logger import append_broker_equity_snapshot, broker_equity_snapshot_exists
from stock_operations import fetch_overseas_portfolio_equity

logger = logging.getLogger(__name__)


def collect_broker_equity_snapshot_safely(
    run_id: str, run_date: str, output_dir: str = "data/live",
) -> bool:
    """Return True only for a new persisted record; optional failures stay local."""
    if os.getenv("PERFORMANCE_KRW_SNAPSHOT_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        return False
    try:
        if broker_equity_snapshot_exists(run_id, output_dir):
            return False
        # Stage 1 owns bounded API retries. Never reuse the sizing balance here.
        equity = fetch_overseas_portfolio_equity()
        return append_broker_equity_snapshot(run_id, run_date, equity, output_dir)
    except Exception as exc:
        # Exception payloads may contain broker data or credentials.
        logger.warning("Broker equity snapshot skipped (continuing daily flow): %s", type(exc).__name__)
        return False
