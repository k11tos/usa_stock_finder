"""Build or inspect the research-only Trend Expansion universe snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path

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
        "--snapshot-date", help="Snapshot date (YYYY-MM-DD); defaults to today"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.refresh:
        metadata = build_snapshot(args.output_dir, snapshot_date=args.snapshot_date)
        mode = "refreshed"
    else:
        _, metadata = load_snapshot(args.output_dir)
        mode = "cached"

    print(f"snapshot_mode: {mode}")
    print(f"snapshot_date: {metadata['snapshot_date']}")
    print(f"record_count: {metadata['record_count']}")
    print(f"duplicate_symbol_count: {metadata['duplicate_symbol_count']}")
    print(f"schema_version: {metadata['schema_version']}")
    for source, details in metadata["sources"].items():
        print(f"source[{source}]: {details['url']} sha256={details['sha256']}")
    print(f"output_dir: {args.output_dir}")


if __name__ == "__main__":
    main()
