# Trend Expansion Pool Design (Future Data Source)

## Status
- **Stage A snapshot plus Stage B research-only base-universe filtering**.
- **No production behavior changes**; the live candidate loader does not read
  these outputs.

## Stage A symbol snapshot

Build the research-only Nasdaq Trader directory snapshot explicitly:

```bash
python -m tools.build_trend_expansion_universe --refresh
```

The command writes immutable generations beneath
`data/trend_expansion/universe/generations/`. Each generation contains
`universe.csv` and an auditable `metadata.json` sidecar; the atomically replaced
`data/trend_expansion/universe/CURRENT` file selects the complete active
generation. This prevents an interrupted publication from mixing data and
metadata from different refreshes. Runtime data under `data/` is gitignored.
Without `--refresh`, the command only validates and reports the selected cache
and never uses the network; a missing or invalid cache fails with an instruction
to refresh. Use `--output-dir` for another location and
`--snapshot-date YYYY-MM-DD` when reproducing a dated source capture.

The stable CSV schema retains symbol and security name, normalized exchange,
market/financial status, round-lot size, ETF/test-issue/NextShares flags,
CQS/Nasdaq aliases, source directory, and snapshot date.

## Stage B deterministic base universe

Filter the selected cached snapshot without making a network request:

```bash
python -m tools.build_trend_expansion_universe --filter
```

By default this publishes `base_universe.csv` and `exclusions.json` as an
immutable generation beside the snapshot cache. A single atomically replaced
`FILTER_CURRENT` selector commits both files, so readers using
`load_filter_outputs()` cannot observe a CSV from one generation with a report
from another. `--filter-output` and `--exclusion-report` select the logical
artifact names, but both must share a directory so they can use one selector.
The filtered CSV preserves the Stage A columns and adds
`source_pool=trend_expansion`. The JSON report contains every rejected symbol
and its deterministic reason, plus input, allowed-exchange, exchange exclusion,
ETF/fund, warrant, unit, right, preferred, debt, test-issue, other-non-common,
duplicate, total-exclusion, and final-common-equity counts.

Only NASDAQ, NYSE, and NYSE American/AMEX listings pass. Reliable directory
flags and explicit security-name evidence remove ETFs/funds, ETNs and other
listed debt, CEFs explicitly identified as such, warrants, units, rights,
preferreds, test issues, and obvious SPAC or other non-common instruments.
Issuer names are not security-type evidence: neither `ETF=N`, `Common Stock`,
`Trust`, nor an asset-manager brand proves that a listing is ordinary common
equity. Legitimate common-equity REITs therefore remain eligible at this stage.
Missing optional metadata alone does not reject a listing. Output ordering and
duplicate precedence are stable for a fixed input.

Stage B is a **preliminary eligibility** filter, not authoritative common-equity
proof. In particular, ambiguous closed-end funds such as RMT/RVT-like listings
can survive a directory-only pass even with `ETF=N` and `Common Stock` in the
name. Stage C must verify every ambiguous finalist with suitable cached,
authoritative evidence before it is added to an expansion watch pool; missing
or insufficient evidence means exclude/defer the candidate and consider the
next ranked name. The legacy `final_common_equity_count` diagnostic name is
preserved for output compatibility, but it counts Stage B preliminary passes.

Compatibility risk for a later live integration: `main.py` currently has a
separate broad `Trust` metadata-name exclusion. This Stage B change does not
modify that live filter, so a Stage B-eligible FBRT-like listing would still
need the live rule to be reconciled in a separately reviewed rollout before it
could become a production candidate.

## Purpose
The Trend Expansion Pool is intended to **supplement** (not replace) the existing Core Quant Pool.

Today, the Core Quant Pool is sourced from externally generated Quantus-style candidates. A separate Trend Expansion Pool would allow the repository to capture strong trend/momentum stocks that are not present in that external input.

Key design intent:
- Keep Core Quant Pool and Trend Expansion Pool as separate, auditable sources.
- Tag candidates with `source_pool` metadata so performance can be measured independently.
- Make rollout conservative, with clear stage gates and backtest validation before any production use.

## Required Data for Trend Expansion Pool
To generate practical trend candidates from a broader U.S. universe, we will need:

1. **Listed ticker universe**
   - A broad set of U.S.-listed symbols (e.g., NASDAQ/NYSE/NYSE American and similar).

2. **Exchange/listing metadata**
   - Exchange, listing status, test issue flags, and security-type hints.

3. **Security-type filtering**
   - Exclude non-common-equity instruments where possible:
     - ETFs
     - Warrants
     - Units
     - Preferreds
     - Test issues

4. **OHLCV price history**
   - Daily bars for trend calculations and minimum price filters.

5. **Average dollar volume**
   - Liquidity filters using rolling average dollar volume (e.g., `close * volume`).

6. **Optional market cap/fundamental data**
   - Useful for additional safety filters, ranking, and diagnostics.
   - Should be optional in initial implementation to reduce dependency risk.

## Data Source Options and Tradeoffs

### A) Nasdaq Trader symbol directory (listed tickers)
**Role:** Base listed-symbol universe and listing metadata cache.

**Pros**
- Direct listing-oriented source.
- Good fit for creating an initial U.S. symbol universe.
- Supports offline cache snapshots in-repo or local data cache.

**Cons / Caveats**
- May still require extra logic to classify security types cleanly.
- Symbol directory alone does not provide full OHLCV history.

**Recommendation**
- Use as the primary Stage A source for universe bootstrap.

### B) SEC company tickers (CIK/company mapping)
**Role:** Entity-level mapping enrichment (ticker ↔ company/CIK).

**Pros**
- Helpful for normalization and entity diagnostics.
- Useful for future reporting, deduping checks, or fundamental joins.

**Cons / Caveats**
- Not designed as a complete listing-quality trading universe feed.
- Security-type filtering may still require other metadata sources.

**Recommendation**
- Use as optional enrichment, not as primary universe source.

### C) yfinance (historical OHLCV)
**Role:** Initial daily OHLCV provider for trend/liquidity calculations.

**Pros**
- Easy to integrate for prototyping.
- Broad coverage for U.S. equities.
- Good for low-cost validation and backtest experimentation.

**Cons / Caveats**
- Reliability/rate-limit behavior can vary.
- Data corrections and occasional symbol anomalies are possible.
- Requires robust caching/retry logic to avoid unstable pipeline runs.

**Recommendation**
- Use in controlled small batches with local caching and sanity checks.

### D) Paid/low-cost APIs (e.g., FMP or similar)
**Role:** Improved screener/fundamental coverage and potentially stronger metadata.

**Pros**
- Can provide cleaner market cap/fundamental fields.
- Often includes richer screener endpoints and better consistency SLAs.

**Cons / Caveats**
- Ongoing cost and vendor dependency.
- API terms/rate limits vary by plan.
- Requires vendor evaluation and integration maintenance.

**Recommendation**
- Defer to later stage after proving signal value with minimal-cost stack.

## Conservative Staged Implementation Plan

### Stage A: Nasdaq Trader listed-symbol cache only
- Build a scheduled/download-on-demand symbol universe cache.
- Store snapshot date and source metadata.
- Do not generate live candidates yet.

**Deliverable:** Reproducible listed-symbol baseline dataset.

### Stage B: security-type and quality filtering
- Add deterministic filters to remove ETFs, warrants, units, preferreds, and test issues.
- Produce filter diagnostics: counts in/out by reason.

**Deliverable:** Cleaner common-equity candidate universe with audit metrics.

### Stage C: bounded quarterly watch-pool construction and finalist verification
- Fetch and cache daily OHLCV in bounded batches, then apply price, history,
  liquidity, and coverage-diagnosed market-cap checks.
- Rank with coarse as-of 3M/6M momentum only; do not use a Minervini trend
  template, entry gate, or OHLCV buy screening here.
- Remove Core overlap with Core priority, select no more than the configured
  expansion cap, and verify ambiguous finalist instrument types using cached
  authoritative evidence. Unknown finalists are deferred/excluded.
- Produce immutable, provenance-rich artifacts for a **quarterly WATCH pool**.

**Deliverable:** A bounded, verified research watch-pool artifact.

### Stage D: research validation
- Compare Core-only and Core-plus-expansion quarterly watch pools with unchanged
  daily entry/exit/sizing behavior.
- The existing daily Minervini funnel evaluates buy eligibility only after the
  pools are combined; watch-list membership is never a buy recommendation.

**Deliverable:** Evidence for or against a later opt-in live rollout.

## Measurement and Safety Controls
- Preserve source isolation with `source_pool` metadata.
- Track counts, pass rates, and failure reasons per stage.
- Backtest Trend Expansion Pool standalone and in combination with Core Quant Pool.
- Require explicit configuration flag before any production activation.

## Non-goals for this PR
- No change to live signal generation.
- No change to production buy/sell logic.
- No change to current Core Quant Pool behavior.

This document is a planning artifact only and is intended to guide a conservative, test-first implementation path.
