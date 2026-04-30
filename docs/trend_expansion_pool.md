# Trend Expansion Pool Design (Future Data Source)

## Status
- **Design only**.
- **No production behavior changes in this PR**.

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

### Stage C: small-batch yfinance OHLCV fetch with caching
- Fetch daily OHLCV in bounded batches.
- Cache results by symbol/date range with refresh policy.
- Add retry/backoff and data quality checks (missing bars, suspicious zeros, stale dates).

**Deliverable:** Stable trend-ready OHLCV cache for filtered symbols.

### Stage D: price/liquidity/trend-only candidate generation
- Compute minimal trend feature set (example: moving-average relationships, momentum windows).
- Apply minimum price and average dollar volume filters.
- Output candidates tagged with `source_pool = "trend_expansion"`.
- Keep this output separate from Core Quant Pool in both backtests and reporting.

**Deliverable:** Measurable Trend Expansion Pool candidate feed (research mode).

### Stage E: optional paid API evaluation for enrichment
- Pilot one paid/low-cost vendor (e.g., FMP-like) for market cap/fundamental fields.
- Compare data quality, coverage, cost, and operational stability versus current stack.
- Decide whether enrichment materially improves candidate quality or risk controls.

**Deliverable:** Go/no-go decision memo for paid enrichment.

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
