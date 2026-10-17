"""Build or inspect the research-only Trend Expansion universe snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path

from trend_expansion.base_universe import write_filter_outputs
from trend_expansion.universe_source import build_snapshot, load_snapshot

DEFAULT_OUTPUT_DIR = Path("data/trend_expansion/universe")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Download sources and replace the snapshot",
    )
    parser.add_argument(
        "--filter",
        action="store_true",
        help="Filter the selected cached snapshot into a research base universe",
    )
    parser.add_argument(
        "--filter-output",
        type=Path,
        help="Filtered CSV path (default: <output-dir>/base_universe.csv)",
    )
    parser.add_argument(
        "--exclusion-report",
        type=Path,
        help="JSON audit report path (default: <output-dir>/exclusions.json)",
    )
    parser.add_argument("--snapshot-date", help="Snapshot date (YYYY-MM-DD); defaults to today")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.refresh:
        build_snapshot(args.output_dir, snapshot_date=args.snapshot_date)
        mode = "refreshed"
    else:
        mode = "cached"
    records, metadata = load_snapshot(args.output_dir)

    print(f"snapshot_mode: {mode}")
    print(f"snapshot_date: {metadata['snapshot_date']}")
    print(f"record_count: {metadata['record_count']}")
    print(f"duplicate_symbol_count: {metadata['duplicate_symbol_count']}")
    print(f"schema_version: {metadata['schema_version']}")
    for source, details in metadata["sources"].items():
        print(f"source[{source}]: {details['url']} sha256={details['sha256']}")
    print(f"output_dir: {args.output_dir}")
    if args.filter:
        filter_output = args.filter_output or args.output_dir / "base_universe.csv"
        report_output = args.exclusion_report or args.output_dir / "exclusions.json"
        diagnostics = write_filter_outputs(records, filter_output, report_output)
        for name, count in diagnostics.items():
            print(f"filter[{name}]: {count}")
        print(f"filter_output: {filter_output}")
        print(f"exclusion_report: {report_output}")


if __name__ == "__main__":
    main()
