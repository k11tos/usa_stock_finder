# Trend Expansion Pool Design (Future Data Source)

## Status
- **Stages A/B plus Stage C research-only quarterly watch-pool construction**.
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
Likewise, a bare `Fund` in an explicitly common-stock issuer name is ambiguous,
not an automatic Stage B exclusion; explicit ETF/exchange-traded-fund and
closed-end/CEF wording remains excluded. Missing optional metadata alone does
not reject a listing. Output ordering and duplicate precedence are stable for a
fixed input.

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

## Stage C quarterly research watch pool

Stage C is implemented in `trend_expansion/watch_pool.py`, `watch_prices.py`,
`research_cache.py` and `security_evidence.py`. It is independent of `main.py`;
no daily process imports or consumes these artifacts. Refresh manually alongside
one current Quantus quarterly snapshot. There is no scheduler or live flag.
Stages D (validation) and E (opt-in integration) remain separate work.

### Build and inspect

Prepare Stage A/B with the existing CLI. It retains its formats and selectors.
Stage C checks the Stage A CSV checksum and recomputes Stage B to verify its
exact selected rows and exclusion report belong to that Stage A generation.
It records both generation identifiers, checksums and listing source metadata.
The listing date must be within seven days before as-of; a listing captured
after as-of is rejected, even if its manually supplied snapshot date is older.

```bash
python -m tools.build_trend_expansion_universe --refresh --filter
python -m tools.build_trend_expansion_watch_pool build \
  --asof-date 2026-10-19 --session-date 2026-10-19 \
  --core-asof-date 2026-10-19 --fetch \
  --sec-user-agent 'Research Organization research@example.org'
```

Run only after the chosen session has closed. `--session-date` explicitly
identifies the last completed U.S. session, including holidays; a weekend
quarter end may be up to four calendar days later. The reported price cutoff is
16:00 America/New_York (DST aware; conservative on half days). Yahoo price
observations must be captured at or after that full timestamp, including when
the as-of date falls on a later weekend. Earlier observations are rejected as
`source_observed_before_cutoff`, retained in source lineage, and never silently
refreshed. After-close collection on the same as-of calendar day is permitted.
Future bars, annual filings after as-of, and raw observations
from later New York calendar days are rejected. This deliberately prevents
backfilling a historical quarter with today's listed universe, SEC mapping or
split-adjusted prices. Capture inputs during the rebalance; retain them.

Omit `--fetch` for fully offline fixture/cache replay. Default paths are
`data/trend_expansion/universe`, `portfolio/portfolio.csv`,
`data/trend_expansion/research_cache/<asof-date>` and
`data/trend_expansion/research_watch`. Override `--listing-dir`, `--core-csv`,
`--cache-dir`, `--output-dir` for isolated fixtures. No historical-Core glob or
union is performed. `--core-asof-date` is an explicit operator attestation
because the production CSV does not embed an as-of date; it must be no more
than 100 calendar days old. The current CSV bytes and attested date are retained
in lineage; the builder never writes to that CSV.

```bash
python -m tools.build_trend_expansion_watch_pool build \
  --asof-date 2026-09-30 --session-date 2026-09-30 \
  --core-asof-date 2026-09-30 \
  --listing-dir /tmp/quarter-fixture/listing \
  --core-csv /tmp/quarter-fixture/current_core.csv \
  --cache-dir /tmp/quarter-fixture/cache \
  --output-dir /tmp/research-watch
python -m tools.build_trend_expansion_watch_pool inspect \
  /tmp/research-watch/research-watch-2026-09-30-<generation-sha256>
```

The cache is a URL-SHA256-named JSON file with `url`, raw UTF-8 `body`,
`sha256` of raw response bytes and `observed_at_utc`. Offline tests generate
complete A/B, Yahoo daily-response and SEC fixtures in temporary directories;
`tests/fixtures/watch_security_cases.json` contains synthetic security cases.
They are regression evidence, not real financial evidence or a published stock
recommendation. Corrupt cache entries fail explicitly and are never silently
refetched. Keep each quarterly cache directory frozen; choose a new directory
for a new capture rather than editing existing inputs.

### Admission and counting policies

Core is the normalized, deduplicated first column of **one current** Quantus
CSV, using the existing reader's header/suffix/slash conventions and uppercase
research normalization, with dot/dash class-share aliases deduplicated. It is counted **before** the existing live exchange /
tradability / buy filters. Core rows are preserved with
`ohlcv_validity=not_evaluated` and `verification_status=core_not_reverified`;
the expansion verifier does not claim Core is verified. A Core-overlapping
listing is excluded from expansion before OHLCV downloads or ranking. Core
always has priority. Ambiguous collisions between two listed symbols mapping
to the same Yahoo symbol are diagnosed and excluded before downloading.

`needed = min(max(target_total - unique_current_core_count, 0), max_expansion)`.
Initial target is 100, maximum expansion is 50 (hard upper bound). Core 40, 60,
100 produces at most 50, 40, 0 expansion names, hence 90, 100, 100 watch names.
Core itself is never truncated, even if it has more than 100 names. Shortfalls
are allowed. No expansion OHLCV is fetched when `needed=0`.

Expansion defaults are an inclusive $5–$90 as-of close, >=252 valid daily
bars and trailing 20-session mean of individual `close * volume` >=$2,000,000.
The Yahoo chart endpoint requests 550 calendar days of daily OHLCV through the
completed session only; it does not request intraday/fundamental data. We use
Yahoo `quote.close`: split-adjusted, dividend-unadjusted price returns, never
`adjclose` or yfinance's dividend-adjusted default. This differs from live
`stock_analysis.py`'s `auto_adjust=True` convention; Stage C never replaces
live data or its daily checks.

Every supplied bar must have finite, positive OHLC and volume, coherent OHLC,
a unique weekday date, and no date later than the session. Bars are sorted by
date; there is no fill/drop of invalid bars. Last bar must match the explicitly
supplied session. Null/missing/nonfinite/zero values, stale bars, insufficient
history, duplicate dates and >4-calendar-day gaps have distinct data reasons.
Gaps are labeled possible suspension/data loss; the source cannot establish
actual suspension status. Weekdays absent inside shorter gaps cannot be
distinguished from exchange holidays without a separate exchange calendar.
This limitation is recorded rather than inventing trading days. Non-normal
Nasdaq financial-status listings are separately excluded.

Cross-sectional ranking includes only nonoverlapping numeric-eligible symbols.
Returns are exactly `C[t]/C[t-63]-1` and `C[t]/C[t-126]-1`, using the final
completed-session close. Each percentile is average ordinal rank divided by
cross-section size (one member = 1); equal returns receive the same percentile.
Score is `0.4*pct_3m + 0.6*pct_6m`, sorted score DESC then symbol ASC. Security
verification follows ranking; a denied/unknown finalist does not change the
cross-section or cause reranking. No Minervini template, MA order, 52-week
entry check, correlation or `select_stocks()` is used for admission. A test
runs the actual production trend evaluator on declining FBRT-like data,
confirms failure, and still admits it to the research watch pool.

Use `--parameters params.json` for `WatchParameters` overrides. Defaults are
initial research choices, not optimized weights or trading recommendations.
Session/history/size parameters have finite bounds; history cannot be reduced
below 252 and expansion cannot exceed 50 in this implementation.

Market cap defaults to `market_cap_policy="diagnostic"`: missing coverage is
`unknown` and does not block admission; known below-threshold coverage is
labeled `below_minimum`. It is never silently described as verified/pass.
`"require_known"` excludes unknown and below-$300m coverage. Optional
`--market-caps caps.json` supplies reviewed as-of USD evidence, for example:

```json
{
  "EXAMPLE": {
    "value": 350000000,
    "currency": "USD",
    "asof_date": "2026-09-30",
    "source_url": "https://issuer.example/dated-market-cap-evidence",
    "coverage_verified": true
  }
}
```

The supplier must review credibility and set `coverage_verified`; this is an
attestation, not automatic credibility inference from an HTTPS URL. Evidence
must be positive, finite and dated within seven days before as-of. Unsupported,
unreviewed, future or absent coverage is unknown. The complete evidence and
input checksum are retained. No thousands-symbol current market-cap download
is introduced. Stage D must audit coverage before choosing a hard market-cap
gate.

### Finalist security verification and finite resources

Every selected expansion member needs independent SEC evidence. The verifier
loads one cached SEC ticker/CIK map, then for each considered finalist at most
one submissions response and one latest available 10-K/20-F cover page. It
checks CIK identity, `entityType=operating`, known SIC, a non-investment/non-shell
classification, and a cover-page `dei:TradingSymbol` matched to
`dei:Security12bTitle` in the **same class context**. The title must explicitly
identify common/ordinary shares, and `dei:EntityShellCompanyBoolean` must be
explicitly false. REIT SIC 6798 remains possible. Investment-company
classification or SIC 6722/6726, shell SIC 6770, a shell declaration, and explicit
non-common class titles deny admission. Class-title checks apply to the
filing's security class, never the issuer/manager name. ETF=N and Stage B's
legacy `final_common_equity_count` cannot certify finalists.

The annual filing must be filed by as-of and no more than 550 calendar days old.
Raw observations must be captured by the as-of New York calendar date and no
more than seven days old; OHLCV cannot predate the requested final session's
16:00 New York cutoff. SEC observations retain calendar-date validation,
including the filing-date lower bound, without a price-session cutoff.
Unmatched classes, unavailable/blocked SEC responses, missing SIC/entity/shell
facts, transformed/continued inline facts, and unsupported formats produce
`unknown`; skip/defer them and consider the next ranked symbol. This intentionally
sacrifices coverage rather than guessing. No ticker blocklist, brand rule,
licensed master, LLM, companyfacts crawl or historical-submissions pagination
is used. SEC throttling/blocking or unfamiliar inline markup can cause a short
or empty expansion pool; inspect the audit before treating it as usable.

Defaults: 8,000 preliminary symbols (configurable to <=12,000), batches of 10
(<=25), one HTTP response / one symbol history in memory at a time, 25,000
HTTP attempts total (<=40,000), 3 attempts/request (<=4), 15-second request
timeouts (<=30), 8 MB/response (<=16 MB), 512 MB total downloaded bytes
(<=1,024 MB), 0.25-second minimum request pause,
1s/2s retry backoff, and a 7,200-second network budget (<=14,400). The byte
limit also bounds cached inputs. The budget includes retries and evidence;
exhaustion is an explicit diagnostic. Finalist verifications default to 150
(hard ceiling 200), so requests remain bounded even if every candidate is
unknown. Individual symbol failures stay in audit and do not pass screening.
Invalid A/B lineage or an oversized universe aborts before OHLCV collection.
No automatic background refresh runs in the daily process.

Truncated HTTP bodies and response protocol failures use the same bounded
retry/backoff path as network errors; exhaustion records `network_failed`.
Partial bytes consume response/total byte budgets and never become cached input.
URL-addressed cache entries are published with an atomic same-directory hard
link, which requires filesystem hard-link support and never replaces an existing
entry. A concurrent loser validates and reuses the winning body, checksum, and
observation timestamp together. Invalid winners record `cache_invalid`; other
publication failures record `cache_write_failed`. Private temporary files are
removed after success or failure. The completed-session timestamp checks apply
to the winning observation, just as for any existing cache entry.

### Immutable artifacts and repeatability

One `research-watch-YYYY-MM-DD-<sha256>/` directory contains:

- `watch.csv`: Core symbol ASC followed by selected expansion rank order,
  source attribution, as-of date/timestamp, price/returns/score, ranking and
  verification status. `universe_type=quarterly_watch` and `asof_date` permit
  existing backtest loaders to read it; no Stage D evaluation is implemented.
- `audit.json`: one row for every Stage B preliminary symbol, Core overlap,
  OHLCV source/checksum/validity, numeric metrics, market-cap evidence, rank,
  security verification URL/checksum/class facts, and one terminal reason.
- `metadata.json`: research-only schema, dated source/generation lineage,
  source observation timestamps, parameters/weights, price convention, resource
  limits, market-cap checksum and concise counts. Terminal reason counts sum
  exactly to Stage B preliminary count; selected count equals expansion count.
  Stage A/B counts are retained separately.

Files are first completed in a private staging directory, then published by a
single atomic directory rename. There is no mutable live selector. A generation
is the SHA-256 of canonical metadata including artifact checksums; identical
fixed inputs yield identical file bytes and generation. Wall-clock build times
and request/cache-hit counters are excluded from deterministic artifact content;
actual source capture timestamps remain part of the input. Repeating a build
validates existing bytes and never overwrites an immutable snapshot. `inspect`
checks canonical metadata, generation/path and both artifact checksums. A
failed publication cannot select a mixed or partial result.

Yahoo history can still contain provider corrections/split adjustments made
before capture, and current listing/SEC maps are not a historical security
master. Captured observations do not prove survivorship-free historical
coverage. Stage D must use comparable frozen snapshots or forward shadow
observations and report these limitations; no fabricated historical coverage.

### Unchanged production and next stage

`main.py`, `config.py`, `stock_analysis.py`, daily CSV loading, sell priority,
B-plan, sizing, Telegram and orders are unchanged. Live sizing defaults to
**equal allocation**, with `MIN_INVESTMENT=100` and no default maximum; this
is not proof of a deployed fixed-$100-per-stock policy. Live whole-share
quantity remains `int(investment_amount/current_price)` and excludes zero
quantities. The $90 research ceiling only provides a snapshot affordability
proxy, not a future buy/quantity guarantee. Stage D must validate the operator's
actual $100 policy, cash ratio and source-aware incremental trades before
Stage E can activate anything. The existing live broad Trust-name exclusion
also remains a separate rollout compatibility issue.

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
