# Stage 6: Docker production rollout and verification

Prerequisites: Stages 1–5 merged as PRs #164–#168, through `99a2120`.
This stage changes packaging, deployment safety and operational documentation.
Candidate selection, buy/sell decisions, allocation, share quantities, order
behavior and Telegram implementation are unchanged. Do not invoke `main.py`,
`docker start stock`, `compose up`, or a broker order API as a verification step.
The commands below have **not** been executed against the production Pi/account.

`stock` is a scheduled one-shot, not a continuously running service. `exited(0)`
can mean a completed run **or** an execution-window early return; it is not proof
of a successful strategy run, snapshot or notification. `created` is expected
after deployment without starting. A running job must finish before recreation.
Do not interrupt it or add restart policies/health checks that repeatedly run it.

## Configuration reviewed against implementation

| Environment variable | Default | Rollout condition |
| --- | --- | --- |
| `PERFORMANCE_KRW_SNAPSHOT_ENABLED` | `false` | Enable only after persistence and read-only broker checks. |
| `PERFORMANCE_REPORT_ENABLED` | `false` | Enable after flow coverage and standalone report verification. |
| `PERFORMANCE_REPORT_DATA_SOURCE` | `legacy_usd` | Change to `broker_krw` only after verified KRW history exists. |
| `PERFORMANCE_REPORT_OUTPUT_DIR` | `outputs/performance` | Persist `/py_app/outputs`, or the exact custom output path. |
| `PERFORMANCE_REPORT_BENCHMARKS` | `SPY,IWM` | KRW comparisons support these verified USD ETFs. |
| `PERFORMANCE_REPORT_PUBLISH_LATEST` | `true` | Effective only with report generation enabled. |
| `PERFORMANCE_REPORT_HISTORY` | `false` | Optional; enable with disk space and retention monitoring. |
| `PERFORMANCE_REPORT_TELEGRAM_ENABLED` | `false` | Optional performance summary, independent of daily trade alerts. |
| `PERFORMANCE_REPORT_URL` | empty | Required for optional performance Telegram summary; use a private URL. |

Use literal `true`/`false`. Collection/report flags accept `1,true,yes,on`
(case/whitespace normalized); performance Telegram accepts only `true`.
The flags are read directly from the environment, not `StrategyConfig`.
Compose's interpolation `.env` alone does not inject variables: retain the
service's existing `env_file` or explicit `environment` entries. Explicit Compose
environment entries override `env_file`; changing `.env` requires recreation,
not a restart. Verify effective values with the tool below, never dump env values.

Existing required credentials remain `ki_app_key`, `ki_app_secret_key`,
`account_number`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Legacy Telegram aliases
`telegram_api_key` / `telegram_manager_id` remain supported. `mojito2` imports as
`mojito`; `requests` is installed transitively; `python-telegram-bot` imports as
`telegram`. The final Docker layer now imports the daily workflow and all Stage
1–5 modules, broker/HTTP/Telegram dependencies and KST zone data during build.
`COPY .` includes their source. `.dockerignore` excludes account data, tokens,
portfolio inputs, `.env*`, outputs and backups. No runtime secrets belong in images.

## 1. Inventory, pause scheduling, and backup

Run on the Pi, in the **existing Compose project directory**, using Bash and
Python 3. Keep the existing project name and all `-f` arguments; using another
project can create empty volumes. The production Compose file/scheduler is not
tracked here: inspect locally and set `COMPOSE_FILE` below to the actual base
file, plus any existing override arguments in **every** Compose command.
Never print `docker inspect` or `docker compose config` unfiltered: they contain
credentials. Logs and backup files also contain private account information.

Read-only inventory (works for stopped containers):

```bash
set -euo pipefail
docker ps -a --filter name=^/stock$ --format '{{.Names}} {{.Status}} {{.Image}}'
docker inspect -f 'state={{.State.Status}} exit={{.State.ExitCode}} running={{.State.Running}} started={{.State.StartedAt}} finished={{.State.FinishedAt}}' stock
docker inspect stock | python3 tools/verify_rollout.py
docker inspect -f '{{range .Mounts}}{{println .Type .Source "->" .Destination "rw=" .RW}}{{end}}' stock
crontab -l
systemctl list-timers --all
```

The verifier rejects active/failed jobs, automatic restarts, missing writable
data/output mounts and mounts hiding image code. It reports only allowlisted
performance flags. Verify both snapshot and ledger resolve into the **same
existing** bind/named volume before and after replacement. A nested tmpfs or
read-only mount is not sufficient. Use an explicitly named volume in Compose;
anonymous volumes are not a safe recreation contract. Do not mount the entire
host checkout over `/py_app`, which can hide newly deployed code.

Pause **only the discovered stock schedule**, record how to restore it, and wait
for `Running=false`. For a user crontab, save it before `crontab -e`, then comment
only the stock entry. For a systemd timer use its actual name with
`sudo systemctl stop "$STOCK_TIMER"`; do not stop the running job's service.
Do not resume scheduling until the deployment gate passes.

Backup commands (write only a new private backup directory and a rollback tag):

```bash
test "$(docker inspect -f '{{.State.Running}}' stock)" = false
COMPOSE_FILE=compose.yml  # replace with the actual existing filename
stamp=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$PWD/backups/stage6-$stamp"
umask 077
mkdir -p "$BACKUP/data" "$BACKUP/outputs"
docker inspect stock > "$BACKUP/stock.inspect.json"
docker inspect -f '{{.Image}}' stock > "$BACKUP/previous-image-id"
docker tag "$(cat "$BACKUP/previous-image-id")" "stock-rollback:$stamp"
docker image save "stock-rollback:$stamp" | gzip > "$BACKUP/previous-image.tar.gz"
docker cp stock:/py_app/data/. "$BACKUP/data/"
cp -p .env "$COMPOSE_FILE" "$BACKUP/"
docker logs stock > "$BACKUP/stock.log" 2>&1
```

Also copy every existing Compose override, scheduler definition/crontab and
the current report output tree into this backup. For the default output path:
`docker cp stock:/py_app/outputs/. "$BACKUP/outputs/"`. If no output tree exists
yet, explicitly record that fact; do not ignore unexpected backup errors.
For cron: `crontab -l > "$BACKUP/crontab.before"` **before editing it**.
Confirm the backup includes `data.json`, `live/account_snapshots.csv`,
`trade_signals.csv`, any `cash_flows.csv`, `broker_equity_snapshots.csv` and
`krw_external_flows.csv` that exist. Archive any other writable state or mounted
token cache used by the actual deployment. Verify free space with `df -h`.
Keep `BACKUP`, `COMPOSE_FILE`, image IDs and the scheduling restore instructions.

If data currently exists only inside the container, **stop here before removing
it**. Seed a new empty persistent directory/explicitly named volume from the
backup, preserving ownership, and configure it as `/py_app/data`. Do not copy
over an existing dataset. Reconcile conflicting files manually without rewriting
or deleting legacy CSVs. Existing persistent deployments keep their current
source. The verifier cannot prove a backup is complete or the filesystem's
POSIX lock/fsync/durability semantics; check these operationally.

Required Compose shape (merge into the actual configuration; do not replace it):

```yaml
services:
  stock:
    container_name: stock
    restart: "no"
    env_file: .env
    volumes:
      - ./data:/py_app/data
      - ./outputs:/py_app/outputs
      - ./portfolio:/py_app/portfolio:ro
```

Keep the existing candidate file, credentials, command, network and strategy
configuration. Preserve the portfolio mount exactly; `portfolio/portfolio.csv`
is intentionally absent from the image. Bind sources must exist and be writable
by the container user. Retain the existing private static server's mapping to
the same output source; report generation does not start a web server.

## 2. Deploy a verified immutable image without execution

The main workflow builds AMD64/ARM64 and now **only pulls** its exact digest
onto the Pi. It no longer removes/starts `stock` or prunes previous images.
Non-main workflow dispatch cannot stage to production. A successful staging
job means neither container rollout nor a successful scheduled run.
Wait for the PR checks and the merged-main build; inspect the image digest and
`org.opencontainers.image.revision` from that run, not a moving `latest` tag.
The underscore repository name is `ghcr.io/k11tos/usa_stock_finder`.

```bash
IMAGE_REF=ghcr.io/k11tos/usa_stock_finder@sha256:REPLACE_WITH_VERIFIED_DIGEST
EXPECTED_REVISION=REPLACE_WITH_FULL_MERGED_MAIN_SHA
docker pull "$IMAGE_REF"
docker buildx imagetools inspect "$IMAGE_REF"
docker image inspect --format '{{.Os}}/{{.Architecture}} {{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE_REF"
test "$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE_REF")" = "$EXPECTED_REVISION"
docker run --rm --network none --read-only --tmpfs /tmp \
  -e MPLCONFIGDIR=/tmp/matplotlib --entrypoint python "$IMAGE_REF" -B -c \
  'import main, broker_equity_snapshot_runner, performance_report_runner; from tools import broker_equity, krw_twr, krw_benchmarks, performance_report; import mojito, requests, telegram; print("runtime imports OK")'
```

The isolated import check has no production mounts or credentials and cannot
place orders. Check ARM64 on a 64-bit Pi (`uname -m`: `aarch64`); 32-bit ARMv7
is not supported. Inspect both platform manifests. Build-time imports verify
availability, not successful broker/Telegram connectivity.

Keep collection/report disabled and source `legacy_usd` for initial deployment.
Preserve existing non-performance settings. Write a **new** reviewed image-only
override (back up any pre-existing file first):

```bash
printf 'services:\n  stock:\n    image: %s\n' "$IMAGE_REF" > compose.stage6-image.yml
test "$(docker inspect -f '{{.State.Running}}' stock)" = false
docker compose -f "$COMPOSE_FILE" -f compose.stage6-image.yml create --no-build --force-recreate stock
test "$(docker inspect -f '{{.Image}}' stock)" = "$(docker image inspect -f '{{.Id}}' "$IMAGE_REF")"
docker inspect stock | python3 tools/verify_rollout.py
```

Include any prior override files before the new image override above. Confirm
data hashes match the backup before the next scheduled run, for example copy
`stock:/py_app/data/.` into a **new empty** private directory:

```bash
CHECK=$(mktemp -d)
mkdir "$CHECK/data"
docker cp stock:/py_app/data/. "$CHECK/data/"
diff -qr "$BACKUP/data" "$CHECK/data"
```

Compare all existing CSVs. No CSV is
migrated as part of deployment. Retain the image override for future recreation
and ensure the scheduler uses the pinned configuration or starts the already
created `stock`. Never let a cron `compose up` resolve another image/config.
Resume only the original schedule, with no extra immediate run. After its next
normal execution, check exit status, full workflow logs and existing daily
Telegram alerts before enabling collection. Pause again for each recreation.

## 3. Enable broker equity collection and verify a live broker read

Read-only broker precheck: use a separate ephemeral container with an explicit
Python entrypoint and existing credential env file. It has **no data, output or
portfolio mounts**. It may issue/cache a token inside its disposable filesystem;
it does not append snapshots, send Telegram, run the strategy or submit orders.
Use the existing network settings if the production service requires them.

```bash
docker run --rm -i --env-file .env --entrypoint python "$IMAGE_REF" -B - <<'PY'
import json
from stock_operations import APIError, fetch_overseas_portfolio_equity
try:
    equity = fetch_overseas_portfolio_equity()
except APIError:
    raise SystemExit("Broker equity read failed; inspect sanitized diagnostics") from None
print(json.dumps(equity, indent=2, allow_nan=False))
PY
```

Review privately: endpoint `/uapi/overseas-stock/v1/trading/inquire-present-balance`,
TR `CTRP6504R`, parameters `WCRC_FRCR_DVSN_CD=01`, `NATN_CD=840`,
`TR_MKET_CD=00`, `INQR_DVSN_CD=00`. Compare `total_asset_krw` directly with the
broker app's US/all-market KRW total at `fetched_at_kst`. It is
`output3.tot_asst_amt`, **not** a component sum or USD sizing balance. No fixed
historical value is an acceptance target. Every component must be finite and
present. Explicit broker zero is collectible but cannot support positive-equity TWR.

Set only `PERFORMANCE_KRW_SNAPSHOT_ENABLED=true` in the actual service environment.
Keep reporting disabled/legacy initially. Pause scheduling, recreate with the
same `create` command in step 2, run the verifier, then resume the original
schedule. Do not manually call the collector. After the next **successful full**
scheduled execution, copy the CSV from stopped `stock` into a private temp folder:

```bash
umask 077
CHECK=$(mktemp -d)
docker cp stock:/py_app/data/live/broker_equity_snapshots.csv "$CHECK/broker_equity_snapshots.csv"
python3 - "$CHECK/broker_equity_snapshots.csv" <<'PY'
import csv, json, math, sys
from collections import Counter
with open(sys.argv[1], newline='', encoding='utf-8') as file:
    rows = list(csv.DictReader(file))
assert rows, 'No successful snapshot yet'
counts = Counter(row['run_id'] for row in rows)
assert all(count == 1 for count in counts.values()), 'Duplicate run IDs'
row = rows[-1]
assert row['valuation_currency'] == 'KRW'
assert json.loads(row['source']) == {
    'provider': 'KIS', 'endpoint': '/uapi/overseas-stock/v1/trading/inquire-present-balance', 'tr_id': 'CTRP6504R'}
for key in ('total_asset_krw', 'stock_evaluation_krw', 'cash_krw', 'foreign_cash_krw',
            'unsettled_buy_krw', 'unsettled_sell_krw'):
    assert math.isfinite(float(row[key])), key
assert float(row['total_asset_krw']) >= 0
print(json.dumps({key: row[key] for key in ('run_id', 'run_date', 'fetched_at_kst', 'total_asset_krw')}, indent=2))
PY
```

Match the new row's run ID/date and total with the scheduled execution and broker
app. Compare row counts before/after: exactly one new row for one successful
enabled collection; duplicate retries of that same ID append none. Separate
executions on the same day intentionally have separate IDs. No row is expected
for disabled collection, an early return, failed execution or failed broker read.
A snapshot failure must log `Broker equity snapshot skipped (continuing daily
flow)` and leave daily decisions/notifications intact. Do not simulate an outage
by breaking production credentials: failure isolation is covered offline.

## 4. Reconcile external cash-flow coverage

Use [the exact ledger contract and timing rules](krw_time_weighted_return.md).
The separate `data/live/krw_external_flows.csv` needs **one verified complete
attestation per selected interval**, even when there were zero flows, plus every
verified boundary contribution/withdrawal. Reconcile broker statements and
domestic/overseas boundary transfers. Do not infer zero from a missing file or
import/reclassify legacy `cash_flows.csv`. Purchases, sales, dividends, fees and
taxes within the boundary are internal, not automatically external flows.

Require exact selected fetch timestamps, correct KRW signs and boundary ordering.
Unknown/pending/incomplete coverage or any intraday/untimed flow means N/A.
Maintain the new ledger with an exclusive lock or atomic replacement only after
review; back it up first. No sample attestation in this repo is production evidence.
Multiple intraday valuations are not supported. Consecutive **calendar** dates
are required; weekends and other gaps break full-period TWR. Do not create
synthetic snapshots to fill gaps. You may explicitly select a genuinely covered
period with CLI dates, but label the period accurately.

## 5. Generate a preview, then enable KRW reporting

Use the image directly for **report-only** execution with live data read-only.
For a bind mount set `DATA_SOURCE` to its absolute host path; for an explicitly
named volume use `type=volume,src=ACTUAL_NAME,dst=/py_app/data,readonly` instead.
No credentials/env file are required; Yahoo benchmark/FX reads require egress.

```bash
DATA_SOURCE=/absolute/existing/data
PREVIEW="$PWD/stage6-preview-$stamp"
mkdir -p "$PREVIEW"
docker run --rm --entrypoint python \
  --mount "type=bind,src=$DATA_SOURCE,dst=/py_app/data,readonly" \
  --mount "type=bind,src=$PREVIEW,dst=/preview" \
  "$IMAGE_REF" -B tools/performance_report.py --data-source broker_krw \
  --output /preview --benchmarks SPY IWM --publish-latest --history
```

Exit 1 with diagnostic HTML is **not** verified performance. Resolve coverage
issues before enabling. A valid portfolio TWR with unavailable benchmarks may
exit 0 with warnings; N/A comparisons must remain visibly N/A. Once the preview
passes step 6, set `PERFORMANCE_REPORT_ENABLED=true`,
`PERFORMANCE_REPORT_DATA_SOURCE=broker_krw`, and the persisted output path.
Keep the optional performance Telegram flag false until its private report URL
is reachable. Recreate without starting, verify effective config/persistence,
then resume only the existing schedule. Do not change any strategy parameters.

## 6. Validate HTML, publishing, currencies and existing operation

Read-only preview verification (run the same checks on copied current/latest/
history bundles after a real scheduled report). These assertions intentionally
fail for incomplete performance:

```bash
python3 - "$PREVIEW" <<'PY'
import json, sys
from html.parser import HTMLParser
from pathlib import Path
root = Path(sys.argv[1])
summary = json.loads((root / 'performance_summary.json').read_text())
assert summary['data_source'] == 'broker_krw'
assert summary['valuation_currency'] == summary['benchmark_currency'] == 'KRW'
assert summary['returns_validated'] is True
assert summary['report_status'] in ('validated', 'validated_with_warnings')
print({key: summary.get(key) for key in (
    'report_status', 'start_date', 'end_date', 'valid_snapshot_count',
    'external_cash_flow_completeness', 'benchmark_status', 'data_quality_warnings')})
class Resources(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            image = root / dict(attrs)['src']
            assert image.is_file() and image.stat().st_size > 0, image
Resources().feed((root / 'index.html').read_text())
assert (root / 'index.html').read_bytes() == (root / 'latest/index.html').read_bytes()
assert list((root / 'history').glob('*/index.html'))
PY
```

Review HTML on phone/desktop through the **existing private static server**:

- Raw `total_asset_krw` is labeled KRW and separate from base-100 TWR. TWR,
  drawdown and volatility use verified flows; raw equity growth is not return.
- `twr_curve.csv` shows valid consecutive intervals and the intended coverage.
  For an offline synthetic example, 100 → 160 → 144 with a verified end deposit
  of 50 gives indices 100 → 110 → 99, not raw-equity growth of 44%.
- `benchmark_curve.csv` records adjusted SPY/IWM USD prices and historical KRW
  per USD (`KRW=X`), source dates and KRW indices. No future quote, constant FX,
  partial-period rebase or USD/KRW comparison is allowed. Excess is KRW
  cumulative percentage-point difference. Missing/stale FX remains N/A.
- Check raw equity, TWR, drawdown, excess and volatility PNGs, warning text,
  periods, currency and links in current, `latest/`, and the selected history
  run. Ensure the served URL points to this volume's `latest/`, not an old tree.
- The daily report is generated **before** the final broker collection. The
  report can therefore end at the prior snapshot; allow this documented lag.
  A fresh post-collection preview is possible with report-only execution. Do
  not reorder the daily workflow in Stage 6.
- Observe the next ordinary daily Telegram recommendation/sell alert: expected
  candidates, reasons and quantities remain present. The optional performance
  summary requires successful validated report generation, its flag and URL.
  With actionable trade lines the existing alert goes first and performance is
  a follow-up; without trade lines the existing combined path remains. Optional
  report/API failures must not suppress actionable alerts. Logs alone do not
  prove delivery: check the existing destination privately without sending a
  test message. No Telegram send is required by these verification commands.
- Compare strategy settings and input files with the backup. Confirm the normal
  scheduled completion in private logs and existing Telegram output. Different
  market inputs across dates are not evidence of a strategy regression; use
  deterministic offline tests for decision/quantity equivalence.

## 7. Roll back on failed verification

Pause only the stock scheduler again; wait for the active one-shot to finish.
Record current diagnostics and take another **new** data/output backup before
rollback. Do not kill an active strategy job to perform a routine rollback.
First disable the optional functionality in the effective service environment:

```env
PERFORMANCE_KRW_SNAPSHOT_ENABLED=false
PERFORMANCE_REPORT_ENABLED=false
PERFORMANCE_REPORT_DATA_SOURCE=legacy_usd
PERFORMANCE_REPORT_TELEGRAM_ENABLED=false
```

For an image rollback use the recorded backup path, original Compose project
and all original override arguments. Retain the new disabled flags when editing
the environment; restoring the entire old `.env` could undo unrelated changes.

```bash
set -euo pipefail
BACKUP=/absolute/path/to/backups/stage6-TIMESTAMP
COMPOSE_FILE=compose.yml  # same actual base file and project as deployment
test "$(docker inspect -f '{{.State.Running}}' stock)" = false
PREVIOUS_IMAGE=$(cat "$BACKUP/previous-image-id")
if ! docker image inspect "$PREVIOUS_IMAGE" >/dev/null 2>&1; then
  gzip -dc "$BACKUP/previous-image.tar.gz" | docker image load
fi
printf 'services:\n  stock:\n    image: %s\n' "$PREVIOUS_IMAGE" > compose.stage6-image.yml
docker compose -f "$COMPOSE_FILE" -f compose.stage6-image.yml create --no-build --force-recreate stock
test "$(docker inspect -f '{{.Image}}' stock)" = "$PREVIOUS_IMAGE"
docker inspect stock | python3 tools/verify_rollout.py
```

Compare the mounted data sources and copied CSV hashes **immediately before and
after rollback**, and verify the scheduler still uses this pinned configuration.
Keep scheduling paused if any gate fails. Otherwise restore the original
schedule (for systemd `sudo systemctl start "$STOCK_TIMER"`; for cron re-enable
only its saved stock line with `crontab -e`, preserving unrelated edits). There
is no immediate strategy invocation in these rollback commands.

All existing data on the retained bind/named volumes remains: tracking state,
legacy account/trade/cash-flow CSVs, every appended broker snapshot, the explicit
KRW ledger, and report current/latest/history bundles. **Do not restore old data
over newer records.** Container replacement changes code/config only. No volume
removal, `down -v`, `rm -v`, prune, CSV deletion or schema downgrade is needed.
Disabling reports leaves the last HTML on disk; restrict the existing server or
clearly mark its timestamp/status while reports are paused. A later deliberately
generated legacy bundle refreshes current/latest and removes KRW-only generated
artifacts; distinct historical bundles and source CSVs remain preserved.

## Acceptance checklist and limitations

- [ ] Stages 1–5 merged; relevant PR CI and merged-main image build inspected.
- [ ] Backup verified, old image saved, original schedule recorded and paused.
- [ ] Digest/revision/ARM64 confirmed; runtime imports pass without credentials.
- [ ] Same persistent data/output sources before/after; no image-code shadowing.
- [ ] Existing scheduled strategy and daily Telegram behavior observed.
- [ ] Correct KIS scope/authoritative KRW total matches broker app privately.
- [ ] One snapshot per successful enabled run ID; failure isolation checked offline.
- [ ] Every selected flow interval reconciled; unsupported timing remains N/A.
- [ ] Preview passes TWR/currency/HTML/publishing gates before KRW enablement.
- [ ] Original schedule alone restored; rollback commands and image retained.

Actual host Compose, cron/timer, mounted state, broker app reconciliation,
private URL access and Telegram delivery require the operator's live evidence.
Neither CI nor this PR proves them. Missing calendar dates, incomplete flows,
invalid observations or unavailable historical prices/FX intentionally restrict
performance. No new polling, backfilled history, production orders, scheduler
cadence or automatic enablement is introduced.
