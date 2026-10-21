"""Adapt checksum-verified Stage C generations to offline Stage D replay inputs."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pandas as pd

from file_utils import read_csv_first_column
from trend_expansion.research_cache import ResearchCache, sha256
from trend_expansion.security_evidence import SecVerifier
from trend_expansion.watch_pool import inspect_watch_pool
from trend_expansion.watch_prices import WatchParameters


def load_stage_c(directory: Path, cache_dir: Path | None = None) -> dict:
    """Reuse frozen ranking, optionally verifying additional research-only names.

    Stage C's hard max remains 50. Its full numeric ranking lives in audit.json;
    names outside capacity have NOT been verified. For the 100-cap experiment
    only, a supplied frozen cache can verify them, without any network access.
    Missing evidence fails closed and is reported, never certified from ETF=N.
    """
    metadata = inspect_watch_pool(directory)
    params = metadata["parameters"]
    expected = WatchParameters()
    for key in ("min_price", "max_price", "min_bars", "liquidity_sessions", "min_dollar_volume",
                "short_sessions", "long_sessions", "short_weight", "long_weight", "target_total"):
        if params[key] != getattr(expected, key):
            raise ValueError("Stage C hypotheses differ: " + key)
    audit = json.loads((directory / "audit.json").read_bytes())
    watch = list(csv.DictReader(io.StringIO((directory / "watch.csv").read_text(encoding="utf-8"))))
    core = sorted(row["symbol"] for row in watch if row["source_pool"] == "core_quant")
    if len(core) != metadata["lineage"]["core"]["unique_count"] or len(core) != len(set(core)):
        raise ValueError("Stage C Core count mismatch.")
    ranked = sorted((row for row in audit if row.get("rank") is not None), key=lambda row: row["rank"])
    if len(ranked) != metadata["counts"]["numeric_eligible"]:
        raise ValueError("Stage C numeric ranking count mismatch.")
    desired = max(100 - len(core), 0)
    selected, exclusions = [], []
    cache = ResearchCache(cache_dir, fetch=False) if cache_dir is not None else None
    verifier = SecVerifier(cache, metadata["asof_date"]) if cache else None
    complete = True
    attempts = 0
    for row in ranked:
        if len(selected) >= desired:
            break
        verification = row["verification"]
        if verification["status"] == "not_evaluated":
            if verifier is not None and attempts < 200:
                verification = verifier.verify(row["symbol"])
                attempts += 1
            else:
                complete = False
        if verification["status"] == "verified":
            selected.append({'symbol': row["symbol"], 'rank': row["rank"], 'verification': "verified_common_equity"})
        else:
            exclusions.append({'symbol': row["symbol"], 'reason': "security_" + verification["status"],
                               'verification': verification})
            if verification["status"] in {"unknown", "not_evaluated"}:
                complete = False
    observations = [row["observed_at_utc"] for row in metadata["raw_sources"].values()]
    observations += [row["observed_at_utc"] for row in cache.used.values()] if cache else []
    observations.append(metadata["lineage"]["stage_a"]["metadata"]["created_at_utc"])
    return {
        "reviewed": True, "sha256": metadata["snapshot_generation"],
        "core_snapshot_sha256": metadata["lineage"]["core"]["sha256"],
        "core_asof_date": metadata["lineage"]["core"]["asof_date"],
        "available_at": max(pd.Timestamp(value) for value in observations).isoformat(),
        "data_cutoff_at": metadata["asof_timestamp"],
        "listing_asof_at": metadata["lineage"]["stage_a"]["metadata"]["created_at_utc"],
        "asof_date": metadata["asof_date"], "ranked_coverage_complete": complete,
        "ranked_finalists": selected, "verification_exclusions": exclusions,
        "parameters": {"target_watch": 100, "price_min": 5, "price_max": 90,
                       "liquidity_sessions": 20, "min_dollar_volume": 2000000, "rank_weights": [.4, .6]},
        "stage_c_counts": metadata["counts"], "stage_c_limitations": metadata["point_in_time_limitations"],
        "price_convention": metadata["price_convention"], "core_symbols": core,
        "supplemental_cache_sources": cache.used if cache else {},
    }


def load_bundle(path: Path) -> tuple[dict, dict]:
    """Local files only. Core paths must be archived originals, never a union.

    All paths are relative to the manifest. Exact bytes are fingerprinted;
    Stage C's inspector validates its own artifact hashes and generation.
    """
    payload = path.read_bytes()
    bundle = json.loads(payload)
    provenance = {path.name: sha256(payload)}
    root = path.parent
    for snapshot in bundle["quantus_snapshots"]:
        core_path = root / snapshot["path"]
        try:
            core_bytes = core_path.read_bytes()
        except OSError:
            snapshot["input_error"] = "missing_quantus_file"
            continue
        symbols = sorted({s.upper().replace(".", "-") for s in read_csv_first_column(str(core_path))})
        snapshot.update(symbols=symbols, sha256=sha256(core_bytes))
        provenance[snapshot["path"]] = snapshot["sha256"]
    for quarter in bundle["quarters"]:
        if not quarter.get("stage_c_path"):
            quarter["stage_c"] = None
            continue
        directory = root / quarter["stage_c_path"]
        cache_dir = root / quarter["cache_path"] if quarter.get("cache_path") else None
        try:
            stage_c = load_stage_c(directory, cache_dir)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            quarter["stage_c"] = None
            quarter["stage_c_error"] = "invalid_or_missing_stage_c:" + type(exc).__name__
            continue
        published = pd.Timestamp(quarter["stage_c_available_at"])
        if published.tzinfo is None or published < pd.Timestamp(stage_c["available_at"]):
            raise ValueError("Stage C publication attestation precedes its source observations.")
        stage_c["available_at"] = published.isoformat()
        quarter["stage_c"] = stage_c
        provenance[quarter["stage_c_path"]] = stage_c["sha256"]
    return bundle, provenance
