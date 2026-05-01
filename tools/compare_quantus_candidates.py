"""Compare two Quantus candidate CSV files."""

from __future__ import annotations

import argparse
from typing import Dict, List, Set

from file_utils import read_csv_first_column


def load_unique_symbols(csv_path: str) -> Set[str]:
    """Load first-column symbols from a CSV as a deduplicated set."""
    symbols = read_csv_first_column(csv_path)
    normalized_symbols = {symbol.upper().removesuffix("-US") for symbol in symbols}
    return {symbol.replace("/", "-") for symbol in normalized_symbols}


def compare_symbol_sets(previous_symbols: Set[str], current_symbols: Set[str]) -> Dict[str, object]:
    """Compare previous/current symbol sets and return turnover metrics."""
    overlap_symbols = previous_symbols & current_symbols
    added_symbols = current_symbols - previous_symbols
    removed_symbols = previous_symbols - current_symbols
    union_symbols = previous_symbols | current_symbols

    previous_count = len(previous_symbols)
    current_count = len(current_symbols)
    overlap_count = len(overlap_symbols)
    added_count = len(added_symbols)
    removed_count = len(removed_symbols)
    union_count = len(union_symbols)

    retention_rate = overlap_count / previous_count if previous_count else 0.0
    added_rate = added_count / current_count if current_count else 0.0
    removed_rate = removed_count / previous_count if previous_count else 0.0

    return {
        "previous_count": previous_count,
        "current_count": current_count,
        "overlap_count": overlap_count,
        "added_count": added_count,
        "removed_count": removed_count,
        "union_count": union_count,
        "retention_rate": retention_rate,
        "added_rate": added_rate,
        "removed_rate": removed_rate,
        "added_symbols": sorted(added_symbols),
        "removed_symbols": sorted(removed_symbols),
    }


def format_comparison(comparison: Dict[str, object]) -> str:
    """Format comparison metrics for CLI output."""
    lines: List[str] = [
        f"previous_count: {comparison['previous_count']}",
        f"current_count: {comparison['current_count']}",
        f"overlap_count: {comparison['overlap_count']}",
        f"added_count: {comparison['added_count']}",
        f"removed_count: {comparison['removed_count']}",
        f"union_count: {comparison['union_count']}",
        f"retention_rate: {comparison['retention_rate']:.4f}",
        f"added_rate: {comparison['added_rate']:.4f}",
        f"removed_rate: {comparison['removed_rate']:.4f}",
        "added_symbols:",
    ]

    lines.extend(f"  - {symbol}" for symbol in comparison["added_symbols"])
    lines.append("removed_symbols:")
    lines.extend(f"  - {symbol}" for symbol in comparison["removed_symbols"])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two Quantus candidate CSV files")
    parser.add_argument("--previous", required=True, help="Path to previous candidate CSV")
    parser.add_argument("--current", required=True, help="Path to current candidate CSV")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    previous_symbols = load_unique_symbols(args.previous)
    current_symbols = load_unique_symbols(args.current)
    comparison = compare_symbol_sets(previous_symbols, current_symbols)
    print(format_comparison(comparison))


if __name__ == "__main__":
    main()
