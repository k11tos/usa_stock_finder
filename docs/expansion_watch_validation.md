# Expansion Watch Pool: Stage D evidence and offline replay

**INCONCLUSIVE.** No genuine dated Quantus history, Stage C financial generations,
local point-in-time daily OHLCV/metadata, or replay manifests were supplied in this
workspace. Zero comparable historical quarters and zero observed trading days
support a performance claim. This does not establish either benefit or harm.
Collect forward shadow evidence; do not activate Stage E.

The checked coverage artifacts are in [research/expansion_watch_validation](research/expansion_watch_validation/comparison.md).
Their empty daily/source CSVs are intentional; null performance is not zero
return. Synthetic tests prove implementation behavior only.

## Inspected implementation and discrepancy

Updated the checkout from `f818260` to latest main `e6b5501`, including reviewed,
merged [Stage C #172](https://github.com/k11tos/usa_stock_finder/pull/172).
Inspected AGENTS.md, the revised [issue #148](https://github.com/k11tos/usa_stock_finder/issues/148)
and its replacement Stage D prompt, merged #152/#153, final Stage C builder,
price rules, cache, verifier, artifact inspector, tests and documentation.
Also traced run_backtest.py, backtests/{engine,universe,entry_filters,metrics},
main.py's selection/safety/sizing/B-plan/sell orchestration, config.py,
stock_analysis.py and stop_loss_cooldown.py.

| Path | Actual behavior | Suitable for the reported policy? |
|---|---|---|
| Generic backtester | Earliest monthly snapshot, top 5, entry filtering on snapshots, all cash equally split, fractional shares, one chosen exit rule | No; no daily safety/state replay |
| Generic metrics | Trade PnL sequence and trade-date window, rather than complete daily marked equity for all reported metrics | Cannot measure this daily cash/risk question |
| Live defaults | Equal allocation of buyable cash after 10% reserve, $100 **minimum**, maximum 0 (unlimited); optional proportional path | No evidence this is a fixed $100 target |
| Live quantity | `int(allocation/current_price)`; additional-buy target subtracts existing shares; sell proceeds can feed sizing | Whole shares, but dynamic amounts |
| New research replay | $100 target per **new** symbol, integer shares, explicit cash/reserve/fees/slippage, independent daily observed state | Conditional capacity only; no portfolio returns |

No live candidate selection, buy/sell decisions, quantities, Telegram, B-plan,
execution or schedules changed. The existing generic modes remain unchanged.
No broker or Telegram operation runs in this workflow. Current runtime account
files are not historical state and are never consumed by the CLI.

## Reproduce

Run the coverage-only audit when financial inputs are unavailable:

```bash
python -m tools.compare_expansion_watch_pool \
  --output /tmp/expansion-coverage
```

Replay a genuine captured manifest entirely offline:

```bash
python -m tools.compare_expansion_watch_pool \
  --bundle /archive/quarterly/replay.json \
  --output /tmp/expansion-comparison
```

No refresh/network flag exists. Output beneath repository `data/` or
`portfolio/` is rejected. Input bytes and all relevant implementation files are
SHA-256 fingerprinted. `resolved_strategy_config` records effective strategy
settings; `resolved_data_quality_config` records the effective
`DataQualityConfig.MIN_PRICE_THRESHOLD` used by the live trend checks, including
its environment override resolved at configuration import time. Other data-quality
settings are not consumed by the offline finder. No credentials or unrelated
environment variables are recorded. Files are stable for identical
inputs/configuration/code. Previously published immutable artifacts are not
rewritten; use a new output directory to capture the corrected provenance.

Outputs: `comparison.json`, `comparison.md`, `coverage.csv`, `cohorts.csv`,
`symbols.csv`, `daily.csv`, `source_daily.csv`, `quarterly.csv`, and
`source_quarterly.csv`. CSV dict/list values use deterministic JSON encoding.
Quarterly source statistics are daily means, never sums falsely interpreted as
invested capital over a continuously held portfolio. Cash belongs to the
portfolio; source spending/counts join to portfolio cash by quarter/cap/day.

## Frozen manifest contract (schema_version 1)

This is a collection contract, not a new historical universe generator. Preserve
real original files and their availability timestamps; do not fill gaps with
current constituents. File paths below are relative to the manifest. Supply
all requested quarters and sessions, including those with missing inputs, so
coverage reports retain the denominator. Bare timestamps without zones fail.
The Python API accepts normalized test fixtures; the CLI always loads and
checks actual archived Core files and published Stage C artifacts.

Top-level fields:

- `schema_version`: 1.
- `price_convention`: `asof_auto_adjusted` for daily analysis matching live
  `yf.download(auto_adjust=True)`, or `unadjusted` with a disclosed input mismatch.
  This is separate from Stage C's split-adjusted/dividend-unadjusted prices.
- `corporate_action_policy`: nonempty description of adjustment vintage,
  splits/dividends, delistings, missing/suspended prices and known limitations.
- `assumptions`: `reserve_ratio` in [0,1], `fee_per_order`, `slippage_bps`.
  $100 target is fixed for this hypothesis. Coverage-only defaults are zero
  reserve/fees/slippage, not estimates of deployed costs or account budget.
- `quantus_snapshots`: records with `asof_date`, `available_at`, `path` (archived
  original CSV including its header). Symbols/checksum come from file bytes.
- `quarters`: `rebalance_at`, `stage_c_path`, `stage_c_available_at` (operator
  attestation of publication time), optional `cache_path`. Omit `stage_c_path`
  to explicitly report missing inputs. One rebalance per UTC calendar quarter.
- `sessions`: `signal_at`, `bar_date` (explicit last completed U.S. session),
  `state`, `execution_quotes` (see below).
- `bars`: records `symbol`, `date`, `open`, `high`, `low`, `close`, `volume`,
  `available_at`. Data must be frozen as observed at that time; a modern
  back-adjusted download cannot be relabeled as an earlier observation.
- `metadata`: records `symbol`, `asof_at`, `available_at`, `values` containing
  captured Yahoo metadata used by live `is_tradable_common_stock()` (exchange,
  quote type, name, status, prices and volumes where available). Preserve raw
  evidence externally; the manifest hash alone cannot prove truthful timestamps.

Each session's `state` contains nonnegative `cash`, `holdings_value`, actual
`held_symbols`, `asof_at`, `available_at`, `cooldown_complete`, and `stop_losses`.
These are observed broker holdings, never persisted tracking-only symbols.
`stop_losses` contains `symbol`, `date`, signed decimal `loss_pct`; an empty list
is valid only when `cooldown_complete=true` attests a complete historical log.
Account state must have been available before the signal and be at most 24h old.
Account snapshots are supplied inputs, not fetched. All cohorts use precisely
the same state; a different portfolio's state cannot masquerade as an expansion
counterfactual.

`execution_quotes` contains `symbol`, positive unadjusted `price`, `asof_at`,
`available_at`. Only quotes available before the signal, at most 24h old, support
whole-share capacity. Missing quotes retain the buy signal but prevent a buy
allocation and enter data-quality diagnostics. The quote is an indicative fill
assumption, not a recorded execution. Historical adjusted closes are never used
as nominal execution prices.

Latest available Quantus **within that UTC quarter and before rebalance** is
selected once, never unioned with earlier snapshots. Declare a quarter's
rebalance after its actual Core collection; quarter-end snapshots from the
previous quarter are deliberately not carried forward implicitly. Stage C must
match the selected Core bytes, date and symbols. Stage C is no more than seven
days old at rebalance, and no source/cutoff/publication time may follow rebalance.
A later snapshot cannot retroactively replace an earlier decision. Missing or
ambiguous inputs exclude the quarter from **all** arms and explain why.

## Cohorts and daily evaluation

For each identical quarter, expansion count is
`min(max(100 - unique_current_core, 0), cap, verified_available)`, caps
0/30/50/100. Core counts are before live eligibility filtering. Core has dedupe
priority, including dot/dash class aliases; Core itself is never truncated.
`overlap` includes Stage C's preliminary Core-overlap exclusions; the manifest
retains Stage C counts and source failures for review. A target of 100 is a
hypothesis, not an obligation: Core 60 makes cap 50 and 100 both add at most 40.

The Stage C inspector verifies immutable metadata, watch and audit checksums.
The adapter and replay require the complete `WatchParameters()` schema and
default values, including market-cap policy/minimum, history/liquidity windows,
price bounds, momentum windows/weights, target size, expansion cap and verification
budget. Missing, unknown, invalid or nondefault parameters fail closed. The full
validated parameters are retained in quarter evidence; older abbreviated
normalized parameter summaries must be regenerated from the original Stage C
generation. Compatible default Stage C generations remain accepted.
The adapter reuses frozen **coarse** ranks; it never adds a quarterly Minervini
gate. Stage C's hard max 50 stays unchanged. Numeric candidates outside capacity
have unverified security types. For experimental 100, an optional **frozen**
cache is read with the existing SecVerifier (maximum 200 extra attempts; default
resource byte bounds). Unknown evidence remains excluded. Incomplete ranking or
unknown finalist coverage prevents the four-arm historical comparison rather
than treating the first 50 names as an uncensored 100-name experiment. All
original/supplemental source lineage and security failures are retained.

At each daily signal time, only bars at/before `bar_date`, available by the
signal, are used. Daily bars must predate the signal's UTC day (the production
scheduled run uses a previously completed U.S. session), with <=4 calendar days
between signal day and bar day. No same-close signal/fill is assumed. A one-year
window constructs a download-free UsaStockFinder. This replay fails closed on
nonfinite/zero/boolean/inconsistent OHLCV, duplicates, large unexplained history
gaps, insufficient MA history, stale final sessions, metadata older than seven
days or missing cooldown state. These conservative research data guards can
exclude observations live code might process; they are diagnosed, not silently
reported as failed trends. Short missing sessions can still be mistaken for
holidays; use a captured session calendar to review coverage.

The exact existing live trend/correlation selection, quarantine, pinned-price
functions and cooldown-day calculation run once per day/symbol for **both**
sources. Actual held symbols alone bypass event quarantine; existing holdings
cannot open duplicate new positions. Daily metadata retains the current live
broad Trust/name exclusions even though Stage C allows verified REITs. This is
an existing rollout mismatch, not a reason to weaken the daily funnel.

## Cash-capacity semantics and limits

Core symbol ASC has allocation priority, followed by frozen expansion rank.
Target budget includes fee and slippage. The day's reserve is
`starting_cash * reserve_ratio`, fixed for that one observation. Each signal's
quantity is `floor((min(100, remaining_deployable_cash) - fee) / slipped_quote)`;
it must be positive. Partial $100 targets are permitted when one share fits.
No top-ups or duplicate buys. This is an explicit research choice; confirm
whether the operator requires a full $100 budget before treating it as deployed
sizing. Rounding and unused budgets stay cash; they are never redistributed
into positions above $100.

`target_affordable_entries` ignores competition for cash; `affordable_new_entries`
and `capacity_entries` require enough remaining cash for at least one share.
`new_positions`, `actual_dollars_invested`, realized cash-day fractions and all
performance metrics stay **null**. Independent daily capacity is not a sequence
of actual purchases: shares never persist to another day and sell proceeds are
not manufactured. Reinvestment, exits, holding highs, trailing/AVSL state,
B-plan continuation, settlement, dividends and split quantities require a
separate validated lifecycle replay before portfolio claims become possible.

Capacity cash ratio is remaining cash / (observed starting cash + observed
holdings value), at starting capital/cost, not a post-fill marked equity return.
Intended reserve dollars are separate from nonreserve residual. Signal capacity
gap is the deployable budget exceeding the sum of qualified target-affordable
$100 opportunities; rounding/price constraints account for the rest. Missing
observations are `data_unavailable`, never evidence of genuine signal scarcity.
Cash-day fractions use **strict >50%** and only the intersection of complete,
nonzero-equity dates across all arms. Denominators and excluded dates remain
visible. There is no fabricated source-specific cash account.

Quarterly `mean_capacity_entries` and source-level `mean_affordable_new_entries`,
`mean_capacity_entries` and `mean_hypothetical_dollars_invested` use that same
`paired_complete_day` intersection. Their denominator is `capacity_days`, equal
to `cash_ratio_days` in the arm summary; no eligible paired dates means **null**,
including sources with no watched names. A genuinely empty source on a complete
paired day contributes zero. `days` still counts every observed session.
Source watch/trend/safety/new-buy-signal means retain their existing `days`
denominator and describe observed funnel diagnostics, not comparable capacity.
Daily and source-daily counts retain partial observations; the paired flag,
exclusion reasons, failure counts and coverage distinguish them from complete
observations. Missing data must not be read as zero qualified signals.

## Evidence gate for Stage E review

Register thresholds and intended reserve/budget/cost policies **before** forward
collection. Keep the 100 watch target, 30/50/100 caps, $5–90, 20-session $2m and
40/60 weights fixed; do not sweep alternatives to choose a favorable result.
Use at least four genuine out-of-sample quarters including adverse conditions,
with reported coverage and missing-day reasons. This is a proposed minimum,
not a statistically guaranteed sample size.

A future **SUPPORTED** decision requires repeated paired improvements in eligible
**cash-affordable** candidates and fewer realized >50% cash days under the
confirmed $100 policy, plus complete marked-to-market risk/return evidence.
Agree materiality limits before viewing outcomes; possible review thresholds
are maximum drawdown worsening <=2 percentage points and volatility <=10%
relative worsening. Examine worst quarter/day, loss tails, turnover, costs,
concentration and source attribution, not just average return or invested cash.
Compare SPY/IWM on exactly the same trading dates and compatible corporate-action
conventions. More exposure can improve return while worsening drawdowns.

A future **NOT SUPPORTED** decision is justified by adequate comparable evidence
showing no durable improvement in affordable entries/cash scarcity, or material
risk/tail regressions after costs. Missing history, unresolved deployed sizing,
incomplete exits/corporate actions, biased constituent coverage, or absent
benchmark data means **INCONCLUSIVE**. This diagnostic-only mode necessarily
remains INCONCLUSIVE about portfolio superiority because it has no validated
risk outcomes; it cannot emit a favorable activation verdict.

## Forward collection workflow

1. Archive the genuine current Quantus CSV with date and capture time at every
   quarterly refresh; keep a checksum and never overwrite/union it.
2. Capture Stage A/B, Stage C raw cache, optional dated market-cap coverage,
   SEC evidence and published generation at rebalance. Freeze source vintage;
   never repair old quarters with new listings or future market caps. For the
   100 experiment retain additional evidence; do not raise Stage C's hard cap.
3. In a separate operator-run shadow collection, save each completed-session
   bar vintage, metadata, actual account state, complete stop-loss log and
   indicative unadjusted quote before each intended signal time. Record provider
   errors, suspensions and delistings explicitly. Keep raw observations and
   actual fill/exit logs for later lifecycle validation. Do not add live hooks.
4. Append genuine observations to the manifest; record all requested dates,
   even data failures. Run the offline command and review coverage/count/cash
   diagnostics by source. Preserve input hashes, code/config and all artifacts.
5. Reconcile deployed sizing and validate full sell/B-plan/corporate-action
   lifecycle against actual logs before comparing returns, CAGR, drawdown,
   volatility, turnover, hit rate, concentration and SPY/IWM. No Stage E rollout
   until that evidence has been reviewed.

## Original implementation verification

Python: `/workspace/venvs/usa_stock_finder/bin/python` (3.12).

- Targeted replay, existing engine/universe/filter/metrics/CLI, Stage C watch/cache:
  **446 passed** (`python -m pytest -q tests/test_watch_pool_replay.py
  tests/test_backtest_engine.py tests/test_backtest_universe.py
  tests/test_backtest_entry_filters.py tests/test_backtest_metrics.py
  tests/test_run_backtest_cli.py tests/test_trend_expansion_watch_pool.py
  tests/test_trend_expansion_research_cache.py`).
- Full `python -m pytest -q`: **1,561 passed, 35 subtests passed** (45.84s).
  New replay tests account for 45 cases, including atomic output publication,
  offline cache verification, source parity, exact >50% threshold and no
  unintended live-state mutation or position carry-forward.
- Full pylint over all 94 tracked/new Python files: **10.00/10**, exit 0.
  Final touched-file pylint after the last additions: **10.00/10**, exit 0.
- `python -m compileall -q .` and `git diff --check`: passed. New files were
  also checked for whitespace errors with `git diff --no-index --check`.
- Actual coverage CLI completed with zero quarters/day observations, no
  Quantus CSV and no Stage C financial generations. It emitted all nine
  CSV/JSON/Markdown artifacts. No historical inputs were synthesized.
- Existing Stage C CI [run 39202048103](https://github.com/k11tos/usa_stock_finder/actions/runs/39202048103)
  was queried: syntax/tests, lint and multiarchitecture Docker build all
  **success**. These are baseline results, not hosted CI for these new local
  changes. Stage D hosted CI has not run.
- Local Docker daemon inspection was blocked by sandbox socket permissions;
  no local Docker build was claimed. No Docker files changed.

Files added: `backtests/watch_pool_inputs.py`, `backtests/watch_pool_replay.py`,
`tools/compare_expansion_watch_pool.py`, `tests/test_watch_pool_replay.py`, this
contract/report and the nine coverage artifacts. Documentation status and a
narrow CSV gitignore exception were updated. The generic backtest engine and
all production trading files remain unchanged.

## PR #174 review follow-up (2026-10-21)

Starting PR HEAD exactly matched reviewed commit `4b27a58327`; no intervening
changes or unrelated local edits were present. Independently verified findings:

- Review `5596108070` P1: **valid**. Completeness already excluded missing OHLCV,
  metadata and execution quotes from paired cash-day fractions, but quarterly
  capacity means still included their zero/partial counts. Capacity means now
  share that paired denominator, with explicit `capacity_days` and null means
  when no complete pairs exist. Raw diagnostics and other denominators remain.
- Review `5596108070` P2: **valid**. The documented no-bundle command reproduced
  stale input-adapter/replay hashes and missing `resolved_data_quality_config`.
  Regenerated all nine artifacts from the final implementation. Four changed:
  comparison JSON and the quarterly, source-daily and source-quarterly CSVs.
  The latter headers include the additive denominator/eligibility fields.
- Review `5595557278`: Stage C full parameter validation and effective
  data-quality provenance were **already fixed in code**, with existing
  regressions covering market-cap gates, schema/type failures, environment
  overrides and retained parameter evidence. No duplicate fixes were made.
  Regenerated artifacts now reflect those corrections too.

Validation using the documented Python environment and commands:

- Focused eight-file suite listed above: **483 passed**.
- Full `python -m pytest -q`: **1,598 passed, 35 subtests passed**.
- `pylint $(git ls-files '*.py')`: **10.00/10**, exit 0.
- `python -m compileall -q .` and `git diff --check`: passed.
- Added 32 deterministic two-session replay cases spanning complete pairs,
  missing Core/Expansion OHLCV, metadata or quotes, and partial/zero capacity.
  Extended no-complete-pair, zero-equity and CLI provenance/serialization tests.
- Ran the documented coverage CLI into two fresh directories; all nine files
  matched byte for byte and matched the checked-in outputs. All 11 implementation
  hashes were checked against source bytes; canonical sorted JSON retained
  schema version 1 and the resolved threshold `0.01`.
- Reviewed commit [PR Check run 39559074227](https://github.com/k11tos/usa_stock_finder/actions/runs/39559074227)
  passed syntax/tests, lint and linux/amd64 + linux/arm64 Docker builds. This is
  evidence for the reviewed commit, not hosted validation of this follow-up.
  Local Docker inspection failed on daemon-socket permissions, so no local
  image build was run. No Docker files changed.

The workspace still lacks genuine replay inputs. Coverage remains zero and
the conclusion remains **INCONCLUSIVE**; no historical data or metrics were
invented. Production candidate selection, entries/exits, quantities, Telegram,
B-plan, schedules, Stage C cap 50 and research $100/caps 30/50/100 contracts are
unchanged. Stage E remains inactive.
