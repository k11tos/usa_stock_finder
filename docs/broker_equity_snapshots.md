# Broker equity snapshot collection — Stage 2

Requires merged Stage 1 (PR #164, upstream merge `355f164`). This stage only
collects validated KIS account-level equity. It does not change strategy rules,
orders, investment sizing, Telegram content, or performance report inputs.

Set `PERFORMANCE_KRW_SNAPSHOT_ENABLED=false` in `.env` (the default when absent).
Keep collection disabled until rollout approval. Once approved, `true` enables
one fresh `fetch_overseas_portfolio_equity()` call after each successful daily
execution has saved tracking state and delivered its daily notifications.
It runs even on a day with no buy candidates. Early returns or failed state
persistence/notification do not collect a snapshot. The existing cron schedule
and single-execution Docker entrypoint remain unchanged; no new polling or job
is introduced. Stage 1 bounds API attempts; Stage 2 adds no API retry loop.

The sizing balance and holdings are never reused for this collection. Missing,
invalid, or failed equity responses produce no record; errors are logged using
only exception class names, and cannot suppress trades or daily notifications.
There is no synthetic zero fallback. Explicit broker-reported zero amounts are
valid under Stage 1's contract; only the total must be nonnegative. Components
are not summed or reconciled into the authoritative broker total.

## CSV contract

`data/live/broker_equity_snapshots.csv` is created on the first valid enabled
collection, relative to the repository working directory, with this header:

```csv
run_id,run_date,fetched_at_kst,total_asset_krw,stock_evaluation_krw,cash_krw,foreign_cash_krw,unsettled_buy_krw,unsettled_sell_krw,source,valuation_currency
```

`run_id` and `run_date` use the daily execution's existing KST metadata.
`fetched_at_kst` is the broker client's ISO 8601 timestamp with `+09:00`.
All six amounts must be present, numeric and finite. `source` is a quoted JSON
object containing KIS provider, endpoint and TR ID; `valuation_currency` is
`KRW`, verified from Stage 1's KRW/US/all-market query parameters. No raw broker
response or account credentials are persisted.

Rows are appended and flushed with `fsync`; old rows are never rewritten.
An exclusive POSIX file lock covers the duplicate check and append, including
concurrent writers. Already persisted `run_id`s are skipped before fetching on
sequential retries and checked again under the append lock. Multiple distinct
executions on the same date have distinct rows; this is per-run collection, not
date-based deduplication. Restarting the entire daily command generates a new
run ID. Concurrent collectors may both fetch but can persist only one row per
run ID. Invalid existing headers or incomplete records fail closed without
repairing or rewriting the CSV. A disk failure may leave an incomplete append;
inspect the file before resuming collection rather than deleting historical rows.

The existing `data/live/account_snapshots.csv` logger retains its behavior.
Stage 2 does not open, rewrite, migrate, or copy its history to the new format.
`performance_report_runner.py` still reads that existing CSV; switching reports
to KRW equity belongs to a later stage.

## Docker volume persistence

Docker's working directory is `/py_app`. Mount the host data directory so both
the new CSV and existing tracking/history files survive container replacement:

```bash
mkdir -p data
docker run --rm --env-file .env \
  --mount type=bind,src="$(pwd)/data",dst=/py_app/data \
  ghcr.io/k11tos/usa-stock-finder:latest
```

Run from the repository root and ensure the container user can write to the
mounted directory. For a named volume, use `--mount
type=volume,src=usa-stock-data,dst=/py_app/data` and seed any required existing
tracking/history files before the first execution. Back up the entire volume,
including `live/broker_equity_snapshots.csv`. An unmounted container filesystem
does not retain records after replacement. Use a filesystem supporting POSIX
file locks (the supported Linux/Docker runtime); separate unshared volumes do
not provide cross-container deduplication. No Dockerfile change is required.

## Verification

Tests mock broker and HTTP integrations and write only to temporary paths.
They cover valid single rows, append-only history, concurrent/duplicate writes,
repeated collection, missing/invalid fields, explicit zeros, API/disk failures,
the disabled default, and daily sizing/trade/Telegram equivalence.
