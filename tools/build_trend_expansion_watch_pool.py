"""Build or inspect an immutable RESEARCH quarterly watch pool; never run live."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trend_expansion.research_cache import ResearchCache, ResourceLimits
from trend_expansion.watch_pool import build_watch_pool, inspect_watch_pool, publish_watch_pool
from trend_expansion.watch_prices import WatchParameters


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("snapshot", type=Path)
    build = commands.add_parser("build")
    build.add_argument("--asof-date", required=True)
    build.add_argument("--session-date", required=True, help="Last completed U.S. trading session, including holidays")
    build.add_argument("--core-asof-date", required=True, help="Attest the date of the one current Quantus CSV")
    build.add_argument("--listing-dir", type=Path, default=Path("data/trend_expansion/universe"))
    build.add_argument("--core-csv", type=Path, default=Path("portfolio/portfolio.csv"),
                       help="One current CSV, or isolated fixture")
    build.add_argument("--cache-dir", type=Path, help="Default: data/trend_expansion/research_cache/<asof-date>")
    build.add_argument("--output-dir", type=Path, default=Path("data/trend_expansion/research_watch"))
    build.add_argument("--parameters", type=Path,
                       help="JSON WatchParameters overrides; initial defaults are not optimized")
    build.add_argument("--market-caps", type=Path, help="Optional dated, sourced, verified USD coverage JSON")
    build.add_argument("--fetch", action="store_true", help="Explicitly permit bounded HTTP; default cache-only")
    build.add_argument("--sec-user-agent", help="SEC-compliant organization/contact User-Agent, required with --fetch")
    build.add_argument("--max-symbols", type=int, default=8000)
    build.add_argument("--max-requests", type=int, default=25000)
    build.add_argument("--batch-size", type=int, default=10)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.command == "inspect":
        metadata = inspect_watch_pool(args.snapshot)
    else:
        if args.fetch and (not args.sec_user_agent or "@" not in args.sec_user_agent):
            raise ValueError("--fetch requires SEC organization/contact --sec-user-agent")
        params = WatchParameters(**(json.loads(args.parameters.read_bytes()) if args.parameters else {}))
        cache_dir = args.cache_dir or Path("data/trend_expansion/research_cache") / args.asof_date
        cache = ResearchCache(cache_dir, fetch=args.fetch, user_agent=args.sec_user_agent,
                              limits=ResourceLimits(max_symbols=args.max_symbols, max_requests=args.max_requests,
                                                    batch_size=args.batch_size))
        result = build_watch_pool(listing_dir=args.listing_dir, core_csv=args.core_csv,
                                  core_asof_date=args.core_asof_date, asof_date=args.asof_date,
                                  session_date=args.session_date, cache=cache, params=params,
                                  market_caps=json.loads(args.market_caps.read_bytes()) if args.market_caps else None)
        snapshot = publish_watch_pool(args.output_dir, result)
        metadata = inspect_watch_pool(snapshot)
        print(f"research_snapshot: {snapshot}")
    print(json.dumps(metadata["counts"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
