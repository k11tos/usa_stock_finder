"""Offline Stage D coverage and daily $100 cash-capacity comparison CLI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtests.watch_pool_inputs import load_bundle
from backtests.watch_pool_replay import empty_bundle, replay, write_outputs
from trend_expansion.research_cache import sha256

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, help="Frozen local replay JSON; paths relative to this file")
    parser.add_argument("--output", type=Path, required=True, help="Research output directory")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    for protected in (ROOT / "data", ROOT / "portfolio"):
        if output == protected or protected in output.parents:
            raise ValueError("Research results must not be written into live data/ or portfolio/.")
    provenance = {}
    if args.bundle:
        bundle, provenance = load_bundle(args.bundle)
    else:
        bundle = empty_bundle()
    result = replay(bundle)
    if not args.bundle:
        result["coverage"].append({'quarter': None, 'comparable_inputs': False,
                                       'reason': "no_replay_manifest_or_historical_inputs", 'requested_sessions': 0})
        result["input_inventory"] = {
            "current_core_csv_present": (ROOT / "portfolio/portfolio.csv").is_file(),
            "stage_c_generations_present": len(list((ROOT / "data/trend_expansion/research_watch").glob(
                "research-watch-*/metadata.json"))),
            "dated_quantus_history": "not supplied; no historical snapshots inferred from current CSV",
            "daily_account_metadata_ohlcv_history": "not supplied; live account state is not used",
        }
    result["input_sha256"] = provenance
    result["implementation_sha256"] = {
        str(path.relative_to(ROOT)): sha256(path.read_bytes()) for path in [
            ROOT / "backtests/watch_pool_replay.py", ROOT / "backtests/watch_pool_inputs.py", Path(__file__),
            ROOT / "main.py", ROOT / "config.py", ROOT / "stock_analysis.py", ROOT / "stop_loss_cooldown.py",
            ROOT / "trend_expansion/watch_pool.py", ROOT / "trend_expansion/security_evidence.py",
            ROOT / "trend_expansion/watch_prices.py", ROOT / "trend_expansion/research_cache.py",
        ]
    }
    write_outputs(result, args.output)
    print(json.dumps({"conclusion": result["conclusion"], "performance_comparable": False,
                      "daily_observations": len(result["daily"]), "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
