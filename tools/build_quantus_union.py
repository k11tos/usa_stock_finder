"""Build a deduplicated union CSV from multiple Quantus candidate snapshots."""

from __future__ import annotations

import argparse
import csv
from typing import Dict, List, Sequence, Tuple

from file_utils import read_csv_first_column


def normalize_symbol(symbol: str) -> str:
    """Normalize a symbol using project conventions."""
    return symbol.strip().upper().removesuffix("-US").replace("/", "-")


def load_snapshot_symbols(csv_path: str) -> List[str]:
    """Load normalized, non-blank symbols from one snapshot file."""
    symbols = read_csv_first_column(csv_path)
    return [normalize_symbol(symbol) for symbol in symbols if normalize_symbol(symbol)]


def build_union(input_paths: Sequence[str]) -> Tuple[List[str], List[Dict[str, int]], int]:
    """Build first-seen-order union and return union, per-file counts, duplicate count."""
    seen = set()
    union_symbols: List[str] = []
    per_file_counts: List[Dict[str, int]] = []
    total_candidates = 0

    for path in input_paths:
        symbols = load_snapshot_symbols(path)
        per_file_counts.append({"path": path, "count": len(symbols)})
        for symbol in symbols:
            total_candidates += 1
            if symbol in seen:
                continue
            seen.add(symbol)
            union_symbols.append(symbol)

    duplicate_count = total_candidates - len(union_symbols)
    return union_symbols, per_file_counts, duplicate_count


def write_union_csv(symbols: Sequence[str], output_path: str) -> None:
    """Write symbols to CSV using first-column Code format."""
    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Code"])
        for symbol in symbols:
            writer.writerow([symbol])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a deduplicated union CSV from Quantus snapshots")
    parser.add_argument("--inputs", nargs="+", required=True, help="Input candidate snapshot CSV paths")
    parser.add_argument("--output", required=True, help="Output CSV path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    union_symbols, per_file_counts, duplicate_count = build_union(args.inputs)
    write_union_csv(union_symbols, args.output)

    print(f"input_files: {len(args.inputs)}")
    for item in per_file_counts:
        print(f"candidates[{item['path']}]: {item['count']}")
    print(f"duplicate_count: {duplicate_count}")
    print(f"union_count: {len(union_symbols)}")
    print(f"output_path: {args.output}")


if __name__ == "__main__":
    main()
