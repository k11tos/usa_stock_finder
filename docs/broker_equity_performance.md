# Broker KRW performance source — Stage 3

Requires merged Stage 1 PR #164 (`355f164`) and Stage 2 PR #165 (`baf80b1`).
Stage 3 adds a report source and diagnostic output only. Candidate selection,
buy/sell decisions, sizing quantities, and snapshot collection are unchanged.

## Source selection and rollout

`PERFORMANCE_REPORT_DATA_SOURCE=legacy_usd` remains the default, including for
existing callers that construct an `argparse.Namespace` without `data_source`.
The existing `--snapshots` option and historical USD calculations retain their
behavior. Unknown source names fail before writing report outputs; the runner
isolates failures as before. The report source flag is independent of
`PERFORMANCE_KRW_SNAPSHOT_ENABLED`, whose disabled default is also unchanged.
Keep both production defaults until a controlled rollout is approved.

For a diagnostic report from already collected observations, from the repository
root with the project environment active:

```bash
python tools/performance_report.py --data-source broker_krw \
  --output outputs/performance_krw --publish-latest --history
```

Use a separate output directory for side-by-side USD/KRW inspection. To select
KRW in the optional daily report runner, set
`PERFORMANCE_REPORT_DATA_SOURCE=broker_krw` in the approved runtime configuration.
This document does not enable production collection or reporting.

KRW mode reads **only** `data/live/broker_equity_snapshots.csv`, relative to the
working directory. `--snapshots`, historical `broker_total_asset_krw`, USD
`total_equity_usd`, cash-flow CSVs and benchmark downloads are not used in this
mode. Missing or unusable input produces an empty diagnostic report, never a
fallback, interpolated observation, inferred total or synthetic zero.

## Validation and observation selection

The reader takes a shared POSIX lock compatible with the Stage 2 writer and
captures the original CSV without rewriting it. The full Stage 2 header and
field count are required. Each selected row requires:

- Source JSON exactly identifying KIS, the present-balance endpoint and `CTRP6504R`.
- `valuation_currency=KRW`, six present finite numeric amounts, and strictly
  positive `total_asset_krw`. Stage 2 can persist an explicit zero, but Stage 3
  does not use zero equity for performance diagnostics.
- An ISO `YYYY-MM-DD` run date, a nonempty run ID, and an ISO KST timestamp with
  `+09:00` on that same date, no later than report generation.

The CSV does not persist Stage 1 query parameters; source/KRW scope relies on
Stage 2's validation contract. Component amounts are not summed or reconciled
into the authoritative total.

Rows are sorted by date and KST fetch timestamp, and the latest **valid** run is
selected per date. Opaque run IDs supported by Stage 2 are accepted. Equal fetch
timestamps use lexical run ID as a deterministic tie-break and produce a
warning. Exact duplicate run records are selected once with a warning;
conflicting records sharing a run ID are all quarantined, including a conflict
with an invalid record. Superseded, duplicate and rejected input remains in the
original diagnostic CSV. Invalid records are described with row numbers and
sanitized warnings rather than private raw values.

Diagnostics flag missing **calendar dates**, including requested period
boundaries; they do not assume a US trading calendar or fill weekends. Latest
selected observations older than three calendar days are flagged stale but
retained. Timestamp/date mismatch is rejected as stale. Absolute changes of
at least 10% between selected observations are flagged as discontinuities and
retained unchanged. These thresholds are diagnostic policies, not trading rules.

## Outputs and publishing

Existing output names and `latest/` / `history/<report_run_id>/` copies remain
available. `PERFORMANCE_REPORT_URL` and hosting are unchanged. KRW bundles contain:

- `equity_curve.csv`: selected account observations in raw KRW, including run ID,
  date, timestamp and source. This CSV is not a normalized return curve.
- `broker_equity_observations.csv`: original input CSV, including all dates,
  superseded and rejected records; it is not a validated equity curve.
- `charts/raw_equity_krw.png`: selected raw KRW equity for diagnosis, preserving
  spikes without smoothing, interpolation or currency conversion.
- `performance_summary.json`: source/currency metadata,
  `report_kind=raw_equity_diagnostic`, `returns_validated=false`,
  `external_cash_flow_completeness=unknown`, latest observed equity and warnings.
- Markdown/HTML diagnostics and `benchmark_comparison.csv` with unavailable
  performance metrics. Existing return chart filenames contain N/A panels so
  publishing over a previous USD bundle cannot retain its old return plots.

Cumulative return, Modified Dietz return, CAGR, performance drawdown, annualized
volatility, benchmark returns and excess returns are `null` in JSON and N/A in
rendered reports. Raw equity changes are **not investment returns**. A cash-flow
file containing some rows does not establish completeness. The optional daily
Telegram performance section identifies KRW asset diagnostics and unavailable
returns, while keeping the configured report URL and trading messages.

Switching the same output directory back to legacy removes KRW-only diagnostic
artifacts from the current/latest bundles. Separate previous history runs are
retained. Collection and report generation do not change their order: Stage 2
collects after daily notifications, so the daily KRW report can use the previous
execution's observation. A standalone report after collection includes the new
observation. Reordering this workflow is outside Stage 3.

## Stage 4 readiness

The validated equity source, raw observations, source metadata and quality
warnings are ready for the next stage. Reliable investment returns remain gated
on a defined, complete KRW external cash-flow ledger and observation/flow timing
rules. Review funding/withdrawals, currency scope, unsettled amounts, gaps and
discontinuities against broker records before calculating adjusted returns or
comparing with currency-consistent benchmarks. Resolve conflicting records
explicitly; do not repair them by silently deleting historical observations.

The next stage should also decide the intended daily report/collection timing
and production rollout criteria. No Stage 4 return calculations, new trading
logic, live broker validation, or production flag changes are included here.
