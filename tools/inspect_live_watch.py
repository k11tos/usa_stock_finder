"""Offline admission dry-run. Does not import daily runner or access broker/state."""

import argparse
import json
from datetime import date
from pathlib import Path

from file_utils import read_csv_first_column
from trend_expansion.live_watch import combine_watch


def main():
    """Print admission diagnostics; no orders, prices, notifications or writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-csv', type=Path, default=Path('portfolio/portfolio.csv'))
    parser.add_argument('--today', type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    symbols, sources, counts = combine_watch(read_csv_first_column(str(args.core_csv)),
                                            core_csv=args.core_csv, today=args.today)
    print(json.dumps({"symbols": symbols, "sources": sources, "counts": counts}, sort_keys=True))


if __name__ == '__main__':
    main()
