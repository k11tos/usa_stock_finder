# Stage 2: persist optional validated KIS broker equity snapshots

The daily workflow currently records holdings and sizing-derived USD balances.
This change independently fetches fresh Stage 1 KIS KRW equity after a successful
daily execution and appends one validated account-level record to
`data/live/broker_equity_snapshots.csv`.

- Gate collection with `PERFORMANCE_KRW_SNAPSHOT_ENABLED`, default `false` until
  rollout approval.
- Persist run metadata, KST fetch time, all six broker KRW amounts, source and
  valuation currency. Reject missing, invalid, partial or non-finite results
  without creating an equity record or substituting zero values.
- Skip persisted run IDs before collection and protect duplicate checks/appends
  with a POSIX file lock. Flush new records with `fsync`.
- Isolate API, validation and filesystem failures with sanitized diagnostics.
  Collection runs after daily notifications and never feeds buy/sell sizing.
- Preserve existing account history and report inputs; no migration, report
  conversion, strategy changes, orders, or later-stage work.
- Add deterministic persistence and daily-flow regressions, the disabled
  configuration example, and Docker bind-mount/named-volume documentation.

Files changed: `main.py`, `live_performance_logger.py`, new
`broker_equity_snapshot_runner.py`, `tests/test_broker_equity_snapshots.py`,
`tests/test_daily_telegram_report.py`, `env.example`, `README.md`, and Stage 2
documentation.

## Validation

- Full offline pytest: **724 passed, 35 subtests passed**. HTTP transport was
  blocked with a mocked `requests.sessions.Session.request`; broker responses
  and daily integrations are mocked and persistence uses temporary paths.
- Pylint across tracked Python files plus new Python modules: **10.00/10**, exit
  0. Final changed-file check also passed.
- `python -m compileall -q .` and `git diff --check`: passed.
- Candidate selection, buy/sell decisions, quantities and Telegram content are
  unchanged; daily regressions compare collection off/on, including failures.
- No live broker calls or orders. GitHub CI was not triggered. Dockerfile and
  image build configuration are unchanged; no Docker build was run.

## Dependency and operational limits

Stage 1 PR #164 is merged at upstream `355f1645508205755d62697a5d256dc3628d8470`.
The provided checkout lacked it, and Git fetch failed because the workspace
proxy was unreachable. Its exact three merged files were synced through the
GitHub connector in a separate local baseline commit before Stage 2 edits.

Keep the flag disabled pending rollout approval. Persistence requires a shared
Linux filesystem supporting POSIX locks. Distinct daily executions get distinct
run IDs; successful sequential retries with the same run ID skip the API and
CSV write. A torn disk write fails subsequent collection closed for inspection.
The new CSV is collection-only and is not yet read by performance reports.
