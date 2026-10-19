"""Auditable, bounded, research-only quarterly Expansion Watch Pool builder."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from file_utils import read_csv_first_column
from trend_expansion.base_universe import filter_base_universe, load_filter_outputs
from trend_expansion.research_cache import ResearchCache, ResearchDataError, canonical_bytes, sha256
from trend_expansion.security_evidence import SecVerifier
from trend_expansion.universe_source import _atomic_write, load_snapshot
from trend_expansion.watch_prices import (
    PRICE_CONVENTION, WatchParameters, asof_cutoff, chart_url, decode_chart, rank_momentum, screen_bars,
)

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,19}")
_COLUMNS = ("asof_date", "symbol", "source_pool", "universe_type", "asof_timestamp", "rank",
            "price", "return_3m", "return_6m", "score", "ohlcv_validity", "verification_status", "core_overlap")


def _csv_bytes(rows, columns):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def load_inputs(listing_dir: Path, core_csv: Path, *, asof_date: str, core_asof_date: str) -> tuple:
    """Validate A checksum and B against a fresh deterministic filter of A.

    Stage B has no source checksum field, so exact recomputation establishes its
    lineage without changing the published A/B formats. Selectors must remain
    unchanged across the read. Never glob or union historical Core snapshots.
    """
    if not 0 <= (date.fromisoformat(asof_date) - date.fromisoformat(core_asof_date)).days <= 100:
        raise ValueError("Core snapshot must be current (0..100 calendar days old)")
    selectors = {name: (listing_dir / name).read_bytes() for name in ("CURRENT", "FILTER_CURRENT")}
    records, metadata = load_snapshot(listing_dir)
    base_bytes, report = load_filter_outputs(listing_dir / "base_universe.csv", listing_dir / "exclusions.json")
    if any((listing_dir / name).read_bytes() != value for name, value in selectors.items()):
        raise ValueError("source generation changed while reading")
    if not 0 <= (date.fromisoformat(asof_date) - date.fromisoformat(metadata["snapshot_date"])).days <= 7:
        raise ValueError("listing snapshot must be within 7 days before asof_date")
    captured = datetime.fromisoformat(metadata["created_at_utc"])
    if (captured.tzinfo is None
            or captured.astimezone(ZoneInfo("America/New_York")).date() > date.fromisoformat(asof_date)):
        raise ValueError("listing source observed after asof_date")
    if any(row["snapshot_date"] != metadata["snapshot_date"] for row in records):
        raise ValueError("listing row date mismatch")
    accepted, rejected, counts = filter_base_universe(records)
    parsed = list(csv.DictReader(io.StringIO(base_bytes.decode())))
    if parsed != accepted or report != {"diagnostics": counts, "exclusions": rejected}:
        raise ValueError("Stage B does not match verified Stage A")
    core_bytes = core_csv.read_bytes()
    core = sorted({symbol.upper().replace(".", "-")
                   for symbol in read_csv_first_column(str(core_csv))})
    if core_csv.read_bytes() != core_bytes:
        raise ValueError("Core changed while reading")
    for symbol in [*core, *(row["symbol"] for row in accepted)]:
        if not _SYMBOL.fullmatch(symbol):
            raise ValueError("unsupported symbol format")
    lineage = {"stage_a": {"metadata": metadata, "generation": selectors["CURRENT"].decode().strip()},
               "stage_b": {"csv_sha256": sha256(base_bytes), "report_sha256": sha256(canonical_bytes(report)),
                           "generation": selectors["FILTER_CURRENT"].decode().strip(), "counts": counts},
               "core": {"sha256": sha256(core_bytes), "asof_date": core_asof_date,
                        "count_semantics": "unique_current_symbols_before_live_eligibility_filter",
                        "unique_count": len(core), "eligibility_filter_applied": False}}
    return accepted, core, lineage


def _market_cap(symbol: str, caps: dict, asof_date: str, params: WatchParameters) -> dict:
    """Optional supplied coverage must explicitly carry USD, date and a source.

    No Yahoo current market-cap lookup is substituted for an as-of measurement.
    The supplier is responsible for source credibility; record it for review.
    """
    row = caps.get(symbol)
    output = {"market_cap_status": "unknown", "market_cap": None, "market_cap_evidence": row}
    if isinstance(row, dict):
        try:
            value = float(row["value"])
            valid_date = date.fromisoformat(row["asof_date"])
            if (row["currency"] == "USD" and str(row["source_url"]).startswith("https://")
                    and row.get("coverage_verified") is True
                    and 0 <= (date.fromisoformat(asof_date) - valid_date).days <= 7
                    and 0 < value < float("inf")):
                output.update(market_cap=value, market_cap_status="above_minimum" if value >= params.min_market_cap
                              else "below_minimum")
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
    output["market_cap_gate_reason"] = (
        "market_cap_unknown" if output["market_cap_status"] == "unknown"
        else "market_cap_below_minimum" if output["market_cap_status"] == "below_minimum" else None
    ) if params.market_cap_policy == "require_known" else None
    return output


def build_watch_pool(*, listing_dir: Path, core_csv: Path, core_asof_date: str,
                     asof_date: str, session_date: str, cache: ResearchCache,
                     params: WatchParameters | None = None, market_caps: dict | None = None) -> dict:
    """Build entirely in research memory; raw cache is the only write side effect."""
    params = params or WatchParameters()
    cutoff = asof_cutoff(asof_date, session_date)
    base, core, lineage = load_inputs(Path(listing_dir), Path(core_csv),
                                      asof_date=asof_date, core_asof_date=core_asof_date)
    if len(base) > cache.limits.max_symbols:
        raise ValueError("preliminary symbol count exceeds resource bound")
    cache.used.clear()
    caps = market_caps or {}
    # Validate optional evidence can be serialized without nonfinite numbers.
    caps_checksum = sha256(canonical_bytes(caps))
    core_set = set(core)
    provider_counts = Counter(row["symbol"].replace(".", "-") for row in base)
    needed = min(max(params.target_total - len(core), 0), params.max_expansion)
    audit = []
    eligible = []
    # Deterministic batches, one symbol held at a time; no thousands-wide frame.
    for start in range(0, len(base), cache.limits.batch_size):
        for listing in base[start:start + cache.limits.batch_size]:
            symbol = listing["symbol"]
            row = {"symbol": symbol, "source_pool": "trend_expansion", "asof_timestamp": cutoff,
                   "core_overlap": symbol.replace(".", "-") in core_set, "ohlcv_validity": "not_evaluated",
                   "verification": {"status": "not_evaluated"}, "reason": None}
            audit.append(row)
            if row["core_overlap"]:
                row["reason"] = "core_overlap"
                continue
            if provider_counts[symbol.replace(".", "-")] > 1:
                row["reason"] = "provider_symbol_collision"
                continue
            if needed == 0:
                row["reason"] = "no_expansion_needed"
                continue
            if listing.get("financial_status") not in {"", "N"}:
                row["reason"] = "listing_financial_status"
                continue
            try:
                url = chart_url(symbol, session_date)
                payload = cache.get_asof(url, asof_date, not_before=session_date,
                                         observed_not_before=datetime.fromisoformat(cutoff))
                row["ohlcv_source"] = {"url": url, "sha256": sha256(payload)}
                bars = decode_chart(payload, symbol)
                row.update(screen_bars(bars, session_date, params))
            except ResearchDataError as exc:
                row.update(ohlcv_validity="unavailable", reason=exc.reason)
            row.update(_market_cap(symbol, caps, asof_date, params))
            if row["reason"] is None:
                row["reason"] = row["market_cap_gate_reason"]
            if row["reason"] is None:
                eligible.append(row)
    ranked = rank_momentum(eligible, params)
    by_symbol = {row["symbol"]: row for row in audit}
    verifier = SecVerifier(cache, asof_date)
    selected = []
    verified_count = 0
    for ranked_row in ranked:
        row = by_symbol[ranked_row["symbol"]]
        row.update(ranked_row)
        if len(selected) >= needed:
            row["reason"] = "outside_watch_capacity"
        elif verified_count >= params.max_verifications:
            row["reason"] = "verification_budget_exhausted"
        else:
            verified_count += 1
            row["verification"] = verifier.verify(row["symbol"])
            if row["verification"]["status"] == "verified":
                row["reason"] = "selected"
                selected.append(row)
            else:
                row["reason"] = "security_" + row["verification"]["status"]
    watch = [{"asof_date": asof_date, "symbol": symbol, "source_pool": "core_quant",
              "universe_type": "quarterly_watch", "asof_timestamp": cutoff, "core_overlap": False,
              "ohlcv_validity": "not_evaluated", "verification_status": "core_not_reverified"} for symbol in core]
    watch.extend({**{key: row[key] for key in _COLUMNS if key in row}, "asof_date": asof_date,
                  "universe_type": "quarterly_watch", "verification_status": "verified"} for row in selected)
    reasons = dict(sorted(Counter(row["reason"] for row in audit).items()))
    metadata = {"schema_version": 1, "research_only": True, "asof_date": asof_date,
                "session_date": session_date, "asof_timestamp": cutoff, "rebalance_cadence": "quarterly_manual",
                "parameters": asdict(params), "resource_limits": asdict(cache.limits),
                "lineage": lineage, "raw_sources": dict(sorted(cache.used.items())),
                "market_cap_input_sha256": caps_checksum,
                "price_convention": PRICE_CONVENTION,
                "return_arithmetic": "C[t]/C[t-N]-1; N=short_sessions,long_sessions; price returns",
                "percentile_method": ("average rank / N; nonoverlapping numeric-eligible cross-section; "
                                      "score DESC,symbol ASC"),
                "point_in_time_limitations": [
                    "retrieved Yahoo history may contain later split adjustments/revisions; not PIT total returns",
                    "current listing/SEC maps are frozen observations, not a historical security master",
                    "Core asof_date is an operator attestation; CSV has no embedded snapshot date",
                    "historical missing sessions <=4 calendar days cannot be distinguished from holidays",
                ],
                "counts": {"preliminary": len(base), "core_unique_before_eligibility": len(core),
                           "needed": needed, "numeric_eligible": len(ranked), "verification_attempted": verified_count,
                           "expansion": len(selected), "watch": len(watch),
                           "excluded": len(audit) - len(selected), "reasons": reasons,
                           "ohlcv_validity": dict(sorted(Counter(r["ohlcv_validity"] for r in audit).items())),
                           "market_cap_status": dict(sorted(Counter(r.get("market_cap_status", "not_evaluated")
                                                                      for r in audit).items()))}}
    assert sum(reasons.values()) == len(base)
    return {"watch": watch, "audit": audit, "metadata": metadata}


def publish_watch_pool(output_dir: Path, result: dict) -> Path:
    """Content-addressed dated generation; atomic directory rename is commit point.

    No mutable CURRENT needed: inspection requires an explicit immutable path.
    Repeats validate existing bytes; never repair/overwrite a damaged artifact.
    """
    artifacts = {"watch.csv": _csv_bytes(result["watch"], _COLUMNS),
                 "audit.json": canonical_bytes(result["audit"])}
    metadata = {**result["metadata"], "artifact_sha256": {k: sha256(v) for k, v in artifacts.items()}}
    generation = sha256(canonical_bytes(metadata))
    artifacts["metadata.json"] = canonical_bytes({**metadata, "snapshot_generation": generation})
    directory = Path(output_dir) / f"research-watch-{metadata['asof_date']}-{generation}"
    if directory.exists():
        if any((directory / name).read_bytes() != content for name, content in artifacts.items()):
            raise ValueError("immutable snapshot integrity failure")
        return directory
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".watch-staging-", dir=directory.parent))
    try:
        for name, content in artifacts.items():
            _atomic_write(staging / name, content)
        try:
            os.rename(staging, directory)
        except OSError:
            if not directory.exists() or any((directory / name).read_bytes() != content
                                              for name, content in artifacts.items()):
                raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return directory


def inspect_watch_pool(directory: Path) -> dict:
    """Validate every published byte plus the metadata generation checksum."""
    directory = Path(directory)
    payload = (directory / "metadata.json").read_bytes()
    metadata = json.loads(payload)
    generation = metadata.pop("snapshot_generation")
    if canonical_bytes({**metadata, "snapshot_generation": generation}) != payload:
        raise ValueError("metadata canonical integrity failure")
    if sha256(canonical_bytes(metadata)) != generation:
        raise ValueError("metadata checksum failure")
    if directory.name != f"research-watch-{metadata['asof_date']}-{generation}":
        raise ValueError("snapshot path/generation mismatch")
    if set(metadata["artifact_sha256"]) != {"watch.csv", "audit.json"}:
        raise ValueError("invalid artifact manifest")
    for name, checksum in metadata["artifact_sha256"].items():
        if sha256((directory / name).read_bytes()) != checksum:
            raise ValueError("artifact checksum failure")
    return {**metadata, "snapshot_generation": generation}
