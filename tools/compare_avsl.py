"""Dry-run comparison helper for legacy AVSL versus original AVSL.

This module is intentionally monitoring-only. It does not place orders, execute
sells, or feed its output back into live trading decisions. Live sell logic now
uses original AVSL; this tool keeps comparing original against the temporary
legacy/approximate path during the transition.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# Allow direct script execution from repository root:
# `python tools/compare_avsl.py --symbols AAPL MSFT`
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from file_utils import read_csv_first_column  # pylint: disable=wrong-import-position
from stock_analysis import UsaStockFinder  # pylint: disable=wrong-import-position

MONITORING_NOTICE = (
    "MONITORING ONLY - AVSL comparison output is not used for trading decisions "
    "and does not place orders; live AVSL sell decisions now use original AVSL."
)
DEFAULT_PORTFOLIO_CSV = REPO_ROOT / "portfolio" / "portfolio.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "avsl_monitor"
STATUS_CATEGORIES = (
    "BOTH_HOLD",
    "BOTH_SELL",
    "LEGACY_ONLY_SELL",
    "ORIGINAL_ONLY_SELL",
    "INSUFFICIENT_DATA",
)
CSV_COLUMNS = (
    "symbol",
    "current_close",
    "legacy_avsl",
    "original_avsl",
    "legacy_sell_signal",
    "original_sell_signal",
    "difference_amount",
    "difference_percentage",
    "status",
    "error",
)


@dataclass(frozen=True)
class AVSLComparisonRow:  # pylint: disable=too-many-instance-attributes
    """Single-symbol AVSL comparison row for CSV/markdown rendering.

    The ten fields intentionally mirror the stable CSV/report schema.
    """

    symbol: str
    current_close: float | None
    legacy_avsl: float | None
    original_avsl: float | None
    legacy_sell_signal: bool | None
    original_sell_signal: bool | None
    difference_amount: float | None
    difference_percentage: float | None
    status: str
    error: str = ""


def normalize_symbol(symbol: str) -> str:
    """Normalize symbols from CLI, portfolio CSV, or brokerage-style suffixes."""
    return symbol.strip().upper().removesuffix("-US").replace("/", "-")


def unique_symbols(symbols: Iterable[str]) -> list[str]:
    """Return normalized symbols while preserving first-seen order."""
    seen: set[str] = set()
    normalized_symbols: list[str] = []
    for raw_symbol in symbols:
        symbol = normalize_symbol(raw_symbol)
        if symbol and symbol not in seen:
            normalized_symbols.append(symbol)
            seen.add(symbol)
    return normalized_symbols


def load_symbols_from_csv(csv_path: Path) -> list[str]:
    """Load symbols from the first column of a CSV file."""
    if not csv_path.exists():
        return []
    return unique_symbols(read_csv_first_column(str(csv_path)))


def resolve_symbols(cli_symbols: list[str] | None, input_csv: Path | None) -> list[str]:
    """Resolve symbols from explicit CLI input, a CSV, or the default portfolio CSV."""
    if cli_symbols:
        return unique_symbols(cli_symbols)
    csv_path = input_csv if input_csv is not None else DEFAULT_PORTFOLIO_CSV
    return load_symbols_from_csv(csv_path)


def is_valid_number(value: Any) -> bool:
    """Return True when value can be represented as a finite positive float."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def coerce_positive_float(value: Any) -> float | None:
    """Convert positive finite values to float; otherwise return None."""
    if not is_valid_number(value):
        return None
    return float(value)


def classify_avsl_status(
    current_close: float | None,
    legacy_avsl: float | None,
    original_avsl: float | None,
) -> tuple[str, bool | None, bool | None]:
    """Classify the comparison status for one symbol.

    Sell signals are calculated only for this dry-run report as ``close < AVSL``.
    They are not passed into live trading decision code.
    """
    if (
        not is_valid_number(current_close)
        or not is_valid_number(legacy_avsl)
        or not is_valid_number(original_avsl)
    ):
        return "INSUFFICIENT_DATA", None, None

    close = float(current_close)
    legacy = float(legacy_avsl)
    original = float(original_avsl)
    legacy_sell = close < legacy
    original_sell = close < original

    if legacy_sell and original_sell:
        return "BOTH_SELL", True, True
    if legacy_sell:
        return "LEGACY_ONLY_SELL", True, False
    if original_sell:
        return "ORIGINAL_ONLY_SELL", False, True
    return "BOTH_HOLD", False, False


def calculate_difference(
    legacy_avsl: float | None,
    original_avsl: float | None,
) -> tuple[float | None, float | None]:
    """Return original-minus-legacy difference amount and percentage."""
    if not is_valid_number(legacy_avsl) or not is_valid_number(original_avsl):
        return None, None
    legacy = float(legacy_avsl)
    original = float(original_avsl)
    amount = original - legacy
    percentage = (amount / legacy) * 100.0
    return amount, percentage


def _get_current_close(finder: Any, symbol: str) -> float | None:
    """Read the latest close from finder state without invoking trading logic."""
    current_price = getattr(finder, "current_price", {})
    if isinstance(current_price, dict):
        close = coerce_positive_float(current_price.get(symbol))
        if close is not None:
            return close

    try:
        close_series = finder.stock_data["Close"][symbol]
        if close_series.empty:
            return None
        return coerce_positive_float(close_series.dropna().iloc[-1])
    except (AttributeError, KeyError, IndexError):
        return None


def _get_latest_original_avsl(finder: Any, symbol: str) -> float | None:
    """Read the latest original AVSL value from the live calculation report."""
    report = finder.calculate_original_avsl_report(symbol)
    if report is None or report.empty or "original_avsl" not in report:
        return None
    valid_values = report["original_avsl"].dropna()
    if valid_values.empty:
        return None
    return coerce_positive_float(valid_values.iloc[-1])


def compare_symbol(finder: Any, symbol: str) -> AVSLComparisonRow:
    """Build one monitoring-only comparison row and keep symbol failures isolated."""
    try:
        current_close = _get_current_close(finder, symbol)
        legacy_avsl = coerce_positive_float(finder.get_latest_avsl(symbol))
        original_avsl = _get_latest_original_avsl(finder, symbol)
        status, legacy_sell, original_sell = classify_avsl_status(
            current_close, legacy_avsl, original_avsl
        )
        difference_amount, difference_percentage = calculate_difference(legacy_avsl, original_avsl)
        return AVSLComparisonRow(
            symbol=symbol,
            current_close=current_close,
            legacy_avsl=legacy_avsl,
            original_avsl=original_avsl,
            legacy_sell_signal=legacy_sell,
            original_sell_signal=original_sell,
            difference_amount=difference_amount,
            difference_percentage=difference_percentage,
            status=status,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return AVSLComparisonRow(
            symbol=symbol,
            current_close=None,
            legacy_avsl=None,
            original_avsl=None,
            legacy_sell_signal=None,
            original_sell_signal=None,
            difference_amount=None,
            difference_percentage=None,
            status="INSUFFICIENT_DATA",
            error=f"{type(exc).__name__}: {exc}",
        )


def compare_symbols(finder: Any, symbols: Iterable[str]) -> list[AVSLComparisonRow]:
    """Compare AVSL values for symbols without placing orders or changing decisions."""
    return [compare_symbol(finder, symbol) for symbol in unique_symbols(symbols)]


def summarize_status_counts(rows: Iterable[AVSLComparisonRow]) -> dict[str, int]:
    """Return stable summary counts for all AVSL monitor status categories."""
    counts = Counter(row.status for row in rows)
    return {status: counts.get(status, 0) for status in STATUS_CATEGORIES}


def _format_limited_symbols(symbols: Iterable[str], max_symbols: int) -> str:
    """Return a compact comma-separated symbol list with overflow count."""
    normalized_symbols = unique_symbols(symbols)
    if not normalized_symbols:
        return "(none)"
    visible_count = max(0, int(max_symbols))
    visible_symbols = normalized_symbols[:visible_count]
    remaining_count = len(normalized_symbols) - len(visible_symbols)
    compact = ", ".join(visible_symbols)
    if remaining_count > 0:
        suffix = f"+{remaining_count} more"
        return f"{compact}, {suffix}" if compact else suffix
    return compact


def build_telegram_monitor_summary(
    rows: Iterable[AVSLComparisonRow],
    artifact_path: Path | str | None = None,
    *,
    max_symbols_per_list: int = 8,
) -> str:
    """Build a compact Telegram-safe AVSL monitoring summary.

    The summary is intentionally monitoring-only: it reports counts for all
    comparison categories but only includes symbol lists for the two difference
    categories to avoid Telegram bloat.
    """
    row_list = list(rows)
    counts = summarize_status_counts(row_list)
    symbols_by_status: dict[str, list[str]] = defaultdict(list)
    for row in row_list:
        symbols_by_status[row.status].append(row.symbol)

    lines = [
        "[AVSL Monitor]",
        "MONITORING ONLY - not used for trading decisions.",
        (
            "Counts: "
            f"BOTH_HOLD={counts['BOTH_HOLD']} | "
            f"BOTH_SELL={counts['BOTH_SELL']} | "
            f"LEGACY_ONLY_SELL={counts['LEGACY_ONLY_SELL']} | "
            f"ORIGINAL_ONLY_SELL={counts['ORIGINAL_ONLY_SELL']} | "
            f"INSUFFICIENT_DATA={counts['INSUFFICIENT_DATA']}"
        ),
        (
            "LEGACY_ONLY_SELL: "
            f"{_format_limited_symbols(symbols_by_status['LEGACY_ONLY_SELL'], max_symbols_per_list)}"
        ),
        (
            "ORIGINAL_ONLY_SELL: "
            f"{_format_limited_symbols(symbols_by_status['ORIGINAL_ONLY_SELL'], max_symbols_per_list)}"
        ),
    ]
    if artifact_path is not None:
        lines.append(f"Artifact: {artifact_path}")

    return "\n".join(lines)


def _format_csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def write_csv(
    rows: list[AVSLComparisonRow], output_dir: Path, run_date: dt.date | None = None
) -> Path:
    """Write comparison rows under outputs/avsl_monitor/YYYYMMDD_avsl_comparison.csv."""
    run_date = run_date or dt.datetime.now(dt.UTC).date()
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{run_date:%Y%m%d}_avsl_comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {column: _format_csv_value(getattr(row, column)) for column in CSV_COLUMNS}
            )
    return csv_path


def render_markdown_summary(rows: list[AVSLComparisonRow], csv_path: Path | None = None) -> str:
    """Render a compact markdown summary with counts and symbol lists by status."""
    counts = summarize_status_counts(rows)
    symbols_by_status: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        symbols_by_status[row.status].append(row.symbol)

    lines = [
        "# AVSL comparison dry-run summary",
        "",
        MONITORING_NOTICE,
        "",
    ]
    if csv_path is not None:
        lines.extend([f"CSV output: `{csv_path}`", ""])

    lines.append("## Counts by status")
    for status in STATUS_CATEGORIES:
        lines.append(f"- {status}: {counts.get(status, 0)}")

    lines.extend(["", "## Symbols by status"])
    for status in STATUS_CATEGORIES:
        status_symbols = symbols_by_status.get(status, [])
        compact = ", ".join(status_symbols) if status_symbols else "(none)"
        lines.append(f"- {status}: {compact}")

    error_rows = [row for row in rows if row.error]
    if error_rows:
        lines.extend(["", "## Errors"])
        for row in error_rows:
            lines.append(f"- {row.symbol}: {row.error}")

    return "\n".join(lines).rstrip() + "\n"


def write_markdown_summary(
    rows: list[AVSLComparisonRow],
    output_dir: Path,
    csv_path: Path,
    run_date: dt.date | None = None,
) -> Path:
    """Write optional markdown summary next to the CSV output."""
    run_date = run_date or dt.datetime.now(dt.UTC).date()
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / f"{run_date:%Y%m%d}_avsl_comparison.md"
    markdown_path.write_text(render_markdown_summary(rows, csv_path), encoding="utf-8")
    return markdown_path


def coerce_run_date(run_date: str | dt.date | None = None) -> dt.date:
    """Coerce live-run metadata dates into a date for AVSL artifact names."""
    if run_date is None:
        return dt.datetime.now(dt.UTC).date()
    if isinstance(run_date, dt.date):
        return run_date
    return dt.date.fromisoformat(run_date)


def write_monitor_outputs(
    rows: list[AVSLComparisonRow],
    base_output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_date: str | dt.date | None = None,
    *,
    write_history: bool = True,
) -> dict[str, Path]:
    """Write latest and optional history artifacts for the post-run AVSL monitor.

    The latest path is always published under ``outputs/avsl_monitor/latest/`` by
    default.  Historical copies are written under
    ``outputs/avsl_monitor/history/<run_date>/`` when enabled.
    """
    artifact_date = coerce_run_date(run_date)
    paths: dict[str, Path] = {}

    latest_dir = base_output_dir / "latest"
    latest_csv = write_csv(rows, latest_dir, artifact_date)
    latest_markdown = write_markdown_summary(rows, latest_dir, latest_csv, artifact_date)
    paths["latest_csv"] = latest_csv
    paths["latest_markdown"] = latest_markdown

    if write_history:
        history_dir = base_output_dir / "history" / artifact_date.isoformat()
        history_csv = write_csv(rows, history_dir, artifact_date)
        history_markdown = write_markdown_summary(rows, history_dir, history_csv, artifact_date)
        paths["history_csv"] = history_csv
        paths["history_markdown"] = history_markdown

    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run monitor comparing legacy/approximate AVSL against original AVSL."
    )
    parser.add_argument("--symbols", nargs="+", help="Symbols to compare, e.g. AAPL MSFT NVDA.")
    parser.add_argument(
        "--input-csv",
        type=Path,
        help=(
            "Optional CSV whose first column contains symbols. If neither --symbols nor "
            "--input-csv is supplied, portfolio/portfolio.csv is used when present."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for CSV/markdown output (default: outputs/avsl_monitor).",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Also write a markdown summary with counts and compact symbol lists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = resolve_symbols(args.symbols, args.input_csv)
    if not symbols:
        print(MONITORING_NOTICE)
        print("No symbols supplied and no portfolio CSV symbols found.", file=sys.stderr)
        return 2

    finder = UsaStockFinder(symbols)
    rows = compare_symbols(finder, symbols)
    csv_path = write_csv(rows, args.output_dir)
    print(MONITORING_NOTICE)
    print(f"Wrote CSV: {csv_path}")

    if args.markdown:
        markdown_path = write_markdown_summary(rows, args.output_dir, csv_path)
        print(f"Wrote markdown summary: {markdown_path}")
    else:
        print(render_markdown_summary(rows, csv_path), end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
