# Quarterly watch integration: OFF, blocked for rollout

This change adds an opt-in read-only admission path before the existing daily
funnel. It does not execute orders or schedule refreshes. A watch name must pass
the same live exchange/tradability, daily Minervini/correlation, cooldown,
event-quarantine and pinned-price checks before sizing. Broker holdings remain
distinct from tracked-only symbols; holdings outside the watch still enter sell
analysis. Sell priorities, AVSL, stops, B-plan and whole-share arithmetic are
unchanged. The opt-in path only reports buy recommendations with positive actual
whole-share sizing. Disabled execution retains the legacy candidate/order path.

## Evidence and deployment blockers

The integration is rebased onto main `5ad3cb3153c914f4300825fad4f42d7dbf0a8b79`,
which includes merged [Stage C #172](https://github.com/k11tos/usa_stock_finder/pull/172)
and [Stage D #174](https://github.com/k11tos/usa_stock_finder/pull/174).
The current [issue #148](https://github.com/k11tos/usa_stock_finder/issues/148)
and its replacement Stage C/D/E prompts have been reviewed through the connected
GitHub tools. Earlier local work used an older checkout; Stage D is implemented.
Its [documented conclusion](expansion_watch_validation.md) is **INCONCLUSIVE**:
zero comparable genuine historical quarters and zero observed trading days.
The checked [comparison](research/expansion_watch_validation/comparison.md)
labels portfolio performance **NOT COMPARABLE**; capacity fixtures are not
actual positions, realized cash-day improvements or risk/benchmark evidence.
This is an explicit no-activation decision until genuine evidence is reviewed.

The Stage D no-bundle CLI was rerun twice on this integration; all nine generated
artifacts matched byte for byte and retained that INCONCLUSIVE conclusion.
[Current coverage/provenance](research/live_expansion_coverage.json) records the
implementation hashes for this integration without rewriting Stage D's historical
validation artifacts. No real archived Core CSV, published Stage C financial
generation or historical manifest is present. Do not treat synthetic CI fixtures
as financial validation or approval.

No deployment credentials/runtime variables are bound to this environment.
The actual operator job/container and its non-secret effective sizing settings
remain unverified. The separate blocking follow-up is
[fixed-$100 sizing reconciliation #175](https://github.com/k11tos/usa_stock_finder/issues/175).
No production settings have been changed.

Repository sizing is equal allocation, MIN_INVESTMENT=100, MAX_INVESTMENT=0.
A $100 minimum is not a fixed $100 target. Adding candidates can change equal
allocations and quantities of existing Core names. This is a blocking mismatch
with the operator's fixed-$100 policy; no sizing default is changed in this PR.
Track the separate narrowly reviewed sizing fix/reconciliation in #175: verify
the deployed configuration, define cash-constrained behavior, test exact $100
allocation, existing-position targets and integer rounding, then review it
separately. Merely setting MAX_INVESTMENT=100 must not be presented as a completed
sizing review. Runtime admission requires both min/max=100 and equal allocation;
otherwise it explicitly falls back to Core. Actual affordability remains decided
by the unchanged sizing function and `int(target_amount/current_price)`.

Stage D must compare frozen Core-only versus combined quarterly watches with the
same daily entry/exit/cash/sizing rules, source-tagged incremental trades, risk,
drawdown, coverage and forward/shadow limitations. Adverse or insufficient
results mean leave the flag OFF. An approved JSON review must identify the
operator, review date, evidence location, exact Stage C generation and Core hash:

```json
{
  "schema_version": 1,
  "decision": "approved",
  "operator": "<reviewing operator>",
  "reviewed_on": "YYYY-MM-DD",
  "stage_d_evidence": "<reviewed report location>",
  "snapshot_generation": "<Stage C metadata snapshot_generation>",
  "core_sha256": "<Stage C lineage.core.sha256>"
}
```

This is an explicit operator attestation, not a machine assessment of the report.
No approval file is shipped. Do not create one until evidence and deployment
configuration have been reviewed. Production remains OFF pending explicit review.

## Quarterly refresh and provenance

1. Manually capture Stage A/B and build Stage C following
   [the Stage C procedure](trend_expansion_pool.md#stage-c-quarterly-research-watch-pool).
   Use only the latest `portfolio/portfolio.csv`; never union historical snapshots.
   For live admission, attest `core-asof-date` equal to the rebalance `asof-date`.
   Freeze all raw inputs at that rebalance. Do not relabel old data with a new date.
2. Stage C now writes schema v2, certifying SEC operating common-equity finalist
   verification and retaining listing evidence in every audit row. Stage B alone
   is insufficient. RMT/RVT-like CEFs, shell companies and unknown/unverified
   finalists cannot be admitted. A verified common REIT's issuer-name `Trust`
   alone does not reject it; all other live defenses remain active. Legacy v1
   artifacts fail closed; rebuild from retained verified inputs rather than edit.
3. Inspect the explicit immutable directory with the Stage C CLI. Preserve
   `watch.csv`, `audit.json`, `metadata.json`, raw SEC/listing/price evidence and
   their SHA-256 checksums. Hashes establish integrity, not issuer authenticity;
   the operator must review the evidence provenance and Stage D report.
4. Review the exact generation and deployment sizing. Install the frozen directory
   read-only and supply the generation-bound activation review only after approval.
   There is no mutable CURRENT selector or daily broad-universe download.

Admission validates canonical metadata/path generation plus both artifact hashes,
source tags, dates/timestamps, selected counts <=50, per-finalist SEC classification,
non-shell operating status, source hashes and listing exchange/ETF/test/status.
Expiry is the rebalance date plus three calendar months (exclusive); weekends
use the explicitly captured completed session. This is not daily-bar freshness.
Future, malformed, stale, unknown, mismatched-Core or damaged artifacts produce
`EXPANSION_CORE_ONLY` structured warnings and zero Expansion additions. Missing
cache never stops the Core daily runner. Core CSV checksum must match exactly;
a changed Core snapshot requires a newly reviewed generation, never an old union.
The directory is checked again after reading to detect concurrent changes.

## Dry-run, enable, rollback and recovery

Offline admission dry-run (no market/broker APIs, Telegram or holding-state writes):

```bash
python -m tools.inspect_live_watch --core-csv portfolio/portfolio.csv
TREND_EXPANSION_ENABLED=True python -m tools.inspect_live_watch \
  --core-csv portfolio/portfolio.csv --today YYYY-MM-DD
pytest -q tests/test_live_watch.py
```

Use an isolated fixture Core CSV for CI. `--today` is an explicit dry-run date;
the daily runner uses its current date. Enabled dry-run also requires artifact
and review paths and compatible reviewed sizing. It prints sources, combined
symbols, counts and fallback reason, never recommended share quantities.

After explicit operator rollout review, configure the artifact/review paths and
set TREND_EXPANSION_ENABLED=True in the daily job's environment. Start with the
offline dry-run and a separately controlled no-order shadow execution. This PR
does not activate production or add an order path.

Rollback: set TREND_EXPANSION_ENABLED=False (or omit it) before the next daily
invocation. No CSV rewrite, database migration, holding/trade-state edit or cache
deletion is needed. A running process must be restarted to reload configuration.
Universe turnover never liquidates a holding merely because its source disappears.

Monitor `BUY_FUNNEL` JSON: core, expansion, overlap, combined_watch, Trend OK,
tradability/cooldown/event/special exclusions, final candidates and
`affordable_new_entries`, plus fallback reason, artifact path and generation.
Detailed candidate and buy trade records retain core_quant/trend_expansion tags;
normal Telegram remains concise. Final candidates and affordable new entries
are intentionally separate counts. On fallback, keep Core running, set OFF,
inspect source hashes/epochs and review the quarterly refresh. Never edit hashes
to make damaged data pass or refresh thousands of symbols inside the daily job.

## Local validation record (2026-10-25)

- Full pytest: **1666 passed, 35 subtests passed**, 46.09 seconds, on the merged Stage D base.
- New offline watch suite: 28 cases, including disabled/true/rollback, real daily
  trend/correlation and safety filters, Core ownership, finalist rejection,
  $100-compatible fixture sizing, integer shares and source-tagged trade output.
- CLI fixture: Core=1, Expansion=3, overlap=0, combined watch=4. The normal
  real daily run rejects one watch-only name on trend, producing Core=1 plus
  Expansion=2 buys, three whole shares each at $30 using a reviewed-policy
  **synthetic** $100 target. Pinned/event/cooldown variants suppress the affected
  Expansion name before sizing. No implication for actual production quantities.
- OFF→ON→OFF CLI output restores identical Core symbols/source metadata and
  preserves fixture holdings/trade files byte-for-byte.
- `compileall` and `git diff --check` passed. Repository-wide pylint checked all
  tracked Python files plus the three new Python files: exit 0, **10.00/10**.
- Local Docker amd64 build passed, including the final runtime import check.
  Image: `sha256:41352c48a1e45fefd00c75ebcc8a589bcb29b3afe2bfc2d15c92c1e1aaae6ec6`.
  Only a local review image was built; it was not deployed. Hosted PR CI also
  checks tests, lint and amd64/arm64 builds; its exact results are reported on
  the review PR.
- GitHub read/write access is available through the connected plugin. #148 and
  merged #174 were read; the deployment sizing blocker is tracked as #175.
  No merge, deployment or live activation is authorized or performed.
