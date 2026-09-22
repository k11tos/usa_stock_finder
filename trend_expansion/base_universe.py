"""Deterministic, research-only filtering for a Trend Expansion universe."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

SOURCE_POOL = "trend_expansion"
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
REJECTION_COLUMNS = ("symbol", "security_name", "exchange", "reason")

_EXCHANGE_ALIASES = {
    "NASDAQ": "NASDAQ",
    "NYSE": "NYSE",
    "NEW YORK STOCK EXCHANGE": "NYSE",
    "AMEX": "NYSE AMERICAN",
    "NYSE AMERICAN": "NYSE AMERICAN",
    "NYSE MKT": "NYSE AMERICAN",
}
_NAME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:etf|exchange[- ]traded fund|fund)\b", re.I), "etf_fund"),
    (re.compile(r"\bwarrants?\b", re.I), "warrant"),
    (re.compile(r"\bunits?\b", re.I), "unit"),
    (re.compile(r"\brights?\b", re.I), "right"),
    (re.compile(r"\bpreferred\b|\bdepositary shares?\b", re.I), "preferred"),
    (
        re.compile(
            r"\b(?:blank check|spac|acquisition (?:corp(?:oration)?|co(?:mpany)?))\b",
            re.I,
        ),
        "other_non_common",
    ),
    (
        re.compile(r"\b(?:beneficial interest|closed[- ]end|trust)\b", re.I),
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
        if pattern.search(security_name):
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
                column: SOURCE_POOL
                if column == "source_pool"
                else str(record.get(column, "")).strip()
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
        "test_issue_count": reason_counts["test_issue"],
        "other_non_common_count": reason_counts["other_non_common"],
        "duplicate_symbol_count": duplicate_count,
        "excluded_count": len(rejected),
        "final_common_equity_count": len(accepted),
    }
    return accepted, rejected, diagnostics


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}."
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def write_filter_outputs(
    records: Iterable[dict[str, str]], output_path: str | Path, report_path: str | Path
) -> dict[str, int]:
    """Write stable CSV output and a JSON diagnostics/rejection report."""
    accepted, rejected, diagnostics = filter_base_universe(records)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(accepted)
    _atomic_write(Path(output_path), buffer.getvalue().encode("utf-8"))
    report = {"diagnostics": diagnostics, "exclusions": rejected}
    _atomic_write(
        Path(report_path),
        (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return diagnostics
