"""Deterministic, research-only filtering for a Trend Expansion universe."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import tempfile
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

SOURCE_POOL = "trend_expansion"
FILTER_CURRENT = "FILTER_CURRENT"
FILTER_GENERATIONS = "filter_generations"
OUTPUT_COLUMNS = (
    "symbol",
    "security_name",
    "exchange",
    "market_category",
    "financial_status",
    "round_lot_size",
    "etf",
    "test_issue",
    "next_shares",
    "cqs_symbol",
    "nasdaq_symbol",
    "source",
    "snapshot_date",
    "source_pool",
)
_EXCHANGE_ALIASES = {
    "NASDAQ": "NASDAQ",
    "NYSE": "NYSE",
    "NEW YORK STOCK EXCHANGE": "NYSE",
    "AMEX": "NYSE AMERICAN",
    "NYSE AMERICAN": "NYSE AMERICAN",
    "NYSE MKT": "NYSE AMERICAN",
}
_EXPLICIT_COMMON_STOCK_PATTERN = re.compile(r"\bcommon stock\b", re.I)
_NAME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:etf|exchange[- ]traded fund|fund)\b", re.I), "etf_fund"),
    (re.compile(r"\bwarrants?\b", re.I), "warrant"),
    (re.compile(r"\bunits?\b", re.I), "unit"),
    (re.compile(r"\brights?\b", re.I), "right"),
    (
        re.compile(
            r"\bpreferred\b|\bdepositary shares?\b|\bpreference (?:shares?|stock)\b",
            re.I,
        ),
        "preferred",
    ),
    (
        re.compile(
            r"(?:\b\d+(?:\.\d+)?%\s+(?:senior\s+|subordinated\s+|convertible\s+)?"
            r"(?:notes?|bonds?|debentures?)\b|\b(?:senior|subordinated|convertible)\s+"
            r"(?:notes?|bonds?|debentures?)\b|\b(?:notes?|bonds?|debentures?)\s+due\b|"
            r"\betns?\b|\bexchange[- ]traded notes?\b)",
            re.I,
        ),
        "debt",
    ),
    (
        re.compile(
            r"\b(?:blank check|spac|acquisition (?:corp(?:oration)?|co(?:mpany)?))\b",
            re.I,
        ),
        "other_non_common",
    ),
    (
        re.compile(
            r"\b(?:shares?|units?)\s+of\s+beneficial interest\b|\btrust certificates?\b|\bclosed[- ]end\b",
            re.I,
        ),
        "other_non_common",
    ),
)


def normalize_symbol(value: Any) -> str:
    """Normalize a listing symbol without applying provider-specific rewrites."""
    return str(value or "").strip().upper()


def normalize_exchange(value: Any) -> str:
    """Normalize the exchange aliases present in listing snapshots."""
    normalized = re.sub(r"\s+", " ", str(value or "").strip().upper())
    return _EXCHANGE_ALIASES.get(normalized, normalized)


def _rejection_reason(record: dict[str, str]) -> str | None:
    if normalize_exchange(record.get("exchange")) not in {
        "NASDAQ",
        "NYSE",
        "NYSE AMERICAN",
    }:
        return "exchange_not_allowed"
    if str(record.get("etf", "")).strip().upper() == "Y":
        return "etf_fund"
    if str(record.get("test_issue", "")).strip().upper() == "Y":
        return "test_issue"
    if str(record.get("next_shares", "")).strip().upper() == "Y":
        return "etf_fund"
    security_name = str(record.get("security_name", "")).strip()
    for pattern, reason in _NAME_PATTERNS:
        match = pattern.search(security_name)
        if not match:
            continue
        if (
            reason == "unit"
            and match.group(0).lower() == "unit"
            and _EXPLICIT_COMMON_STOCK_PATTERN.search(security_name)
        ):
            continue
        return reason
    return None


def _record_sort_key(record: dict[str, str]) -> tuple[Any, ...]:
    """Define total ordering so duplicate selection is input-order independent."""
    return (
        normalize_symbol(record.get("symbol")),
        str(record.get("source", "")) != "nasdaqlisted",
        normalize_exchange(record.get("exchange")),
        *(str(record.get(column, "")).strip() for column in OUTPUT_COLUMNS),
    )


def filter_base_universe(
    records: Iterable[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, int]]:
    """Filter normalized snapshot rows and return output, audit rows, and counts."""
    materialized = [dict(record) for record in records]
    ordered = sorted(materialized, key=_record_sort_key)
    selected: dict[str, dict[str, str]] = {}
    rejected: list[dict[str, str]] = []
    duplicate_count = 0
    for record in ordered:
        symbol = normalize_symbol(record.get("symbol"))
        record["symbol"] = symbol
        record["exchange"] = normalize_exchange(record.get("exchange"))
        if symbol in selected:
            duplicate_count += 1
            rejected.append(
                {
                    "symbol": symbol,
                    "security_name": str(record.get("security_name", "")).strip(),
                    "exchange": record["exchange"],
                    "reason": "duplicate_symbol",
                }
            )
        else:
            selected[symbol] = record

    accepted: list[dict[str, str]] = []
    reason_counts: Counter[str] = Counter(row["reason"] for row in rejected)
    allowed_exchange_count = 0
    for symbol in sorted(selected):
        record = selected[symbol]
        reason = _rejection_reason(record)
        if reason != "exchange_not_allowed":
            allowed_exchange_count += 1
        if reason:
            reason_counts[reason] += 1
            rejected.append(
                {
                    "symbol": symbol,
                    "security_name": str(record.get("security_name", "")).strip(),
                    "exchange": record["exchange"],
                    "reason": reason,
                }
            )
            continue
        accepted.append(
            {
                column: SOURCE_POOL if column == "source_pool" else str(record.get(column, "")).strip()
                for column in OUTPUT_COLUMNS
            }
        )

    rejected.sort(key=lambda row: (row["symbol"], row["reason"], row["exchange"]))
    diagnostics = {
        "input_count": len(materialized),
        "allowed_exchange_count": allowed_exchange_count,
        "excluded_by_exchange_count": reason_counts["exchange_not_allowed"],
        "etf_fund_count": reason_counts["etf_fund"],
        "warrant_count": reason_counts["warrant"],
        "unit_count": reason_counts["unit"],
        "right_count": reason_counts["right"],
        "preferred_count": reason_counts["preferred"],
        "debt_count": reason_counts["debt"],
        "test_issue_count": reason_counts["test_issue"],
        "other_non_common_count": reason_counts["other_non_common"],
        "duplicate_symbol_count": duplicate_count,
        "excluded_count": len(rejected),
        "final_common_equity_count": len(accepted),
    }
    return accepted, rejected, diagnostics


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _artifact_layout(output_path: str | Path, report_path: str | Path) -> tuple[Path, str, str]:
    output = Path(output_path)
    report = Path(report_path)
    if output.parent.resolve() != report.parent.resolve():
        raise ValueError("filtered CSV and exclusion report must share a directory")
    if output.name == report.name:
        raise ValueError("filtered CSV and exclusion report must have distinct names")
    if {output.name, report.name}.intersection({FILTER_CURRENT, FILTER_GENERATIONS}):
        raise ValueError("artifact names conflict with generation control paths")
    return output.parent, output.name, report.name


def _current_selects_generation(directory: Path, generation_name: str) -> bool | None:
    """Return CURRENT's selection, or None when it cannot be observed safely."""
    try:
        selected = (directory / FILTER_CURRENT).read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError):
        return None
    return selected == generation_name


def _publish_generation(
    directory: Path,
    output_name: str,
    csv_bytes: bytes,
    report_name: str,
    report_bytes: bytes,
) -> None:
    """Publish both artifacts, using FILTER_CURRENT as the commit point."""
    generations = directory / FILTER_GENERATIONS
    generations.mkdir(parents=True, exist_ok=True)
    generation_name = uuid.uuid4().hex
    staging = Path(tempfile.mkdtemp(dir=generations, prefix=".staging-"))
    generation = generations / generation_name
    committed = False
    try:
        _atomic_write(staging / output_name, csv_bytes)
        _atomic_write(staging / report_name, report_bytes)
        os.replace(staging, generation)
        _atomic_write(directory / FILTER_CURRENT, f"{generation_name}\n".encode("ascii"))
        committed = True
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if not committed and generation.exists():
            selected = _current_selects_generation(directory, generation_name)
            if selected is False:
                shutil.rmtree(generation)


def write_filter_outputs(
    records: Iterable[dict[str, str]], output_path: str | Path, report_path: str | Path
) -> dict[str, int]:
    """Publish stable CSV/report bytes as one selectable generation.

    The two logical paths must share a directory. Readers must use
    :func:`load_filter_outputs`, which resolves both files through the same
    atomic FILTER_CURRENT selector.
    """
    accepted, rejected, diagnostics = filter_base_universe(records)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(accepted)
    csv_bytes = buffer.getvalue().encode("utf-8")
    report = {"diagnostics": diagnostics, "exclusions": rejected}
    report_bytes = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    directory, output_name, report_name = _artifact_layout(output_path, report_path)
    _publish_generation(directory, output_name, csv_bytes, report_name, report_bytes)
    return diagnostics


def load_filter_outputs(output_path: str | Path, report_path: str | Path) -> tuple[bytes, dict[str, Any]]:
    """Resolve and load a coherent filtered CSV/report generation."""
    directory, output_name, report_name = _artifact_layout(output_path, report_path)
    try:
        generation_name = (directory / FILTER_CURRENT).read_text(encoding="ascii").strip()
        if not generation_name or Path(generation_name).name != generation_name:
            raise ValueError("invalid generation name")
        generation = directory / FILTER_GENERATIONS / generation_name
        csv_bytes = (generation / output_name).read_bytes()
        report = json.loads((generation / report_name).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError(f"Invalid base-universe generation: {exc}") from exc
    return csv_bytes, report
