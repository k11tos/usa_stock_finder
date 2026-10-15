# Stage 6 implementation review

Base: `99a2120`, merged Stage 5 #168. Stage 1–4 merges verified locally:
#164 `355f164`, #165 `baf80b1`, #166 `14c83f2`, #167 `fd83922`.
See [the operational runbook](production_rollout.md) for the deployment
checklist, manual commands, enablement gates and explicit image/config rollback.

## Review outcome

- The old deployment forcibly removed `stock`, immediately started its daily
  workflow and pruned images. Main CI now stages the exact build digest on the
  Pi without starting/replacing any container or pruning rollback images.
- Docker still copies all runtime code and installs the existing requirements.
  A final-layer import check now verifies daily orchestration, new broker/TWR/
  benchmark/report modules, broker HTTP and Telegram dependencies and KST data.
  An optional build-only CA secret supports managed builders without embedding
  their trust bundle. Account `.env*`, output and backup files stay out of images.
- `tools/verify_rollout.py` consumes Docker inspect JSON using host Python 3
  only. It exposes no credentials and performs no network, Docker mutation,
  strategy, notification, order or live CSV I/O. It rejects unsafe recreation
  states, missing data/output/portfolio mounts, code-shadowing mounts,
  automatic restarts, unknown sources and mistyped boolean flags.
- The runbook requires backup and persistent data/output sources before
  recreation. It activates collection before reporting, reconciles live KRW
  totals and complete external flows, validates preview HTML and currency
  consistency, and retains all current source data when rolling back images.
- Safe defaults remain collection/report/optional performance Telegram off,
  source `legacy_usd`. Existing report publishing defaults remain unchanged.
  Daily reporting still precedes end-of-run broker collection, so published
  performance may intentionally lag the latest collected snapshot.

## Trading invariants

No changes to candidate selection, buy/sell decisions, allocation, share
quantities, order behavior or existing Telegram implementation. `main.py`,
strategy/config/broker/notification modules, snapshot/report runners and
`requirements.txt` are unchanged from the merged base. No legacy or production
CSV was edited, deleted, migrated or used as a test fixture. No production
container/account was accessed and no order or Telegram send was executed.
Deployment timing changes intentionally: merging now stages an image and
requires the documented operator rollout before its normal scheduled use.

## Checks actually executed

- Full pytest with dummy credentials: **963 passed, 35 subtests passed**.
  Existing suites cover KIS request fields/totals, per-run collection and failure
  isolation, TWR/flow validation, historical-FX benchmarks, HTML/publishing,
  Telegram and strategy decisions/quantities. All broker/providers are mocked.
- 18 new operational cases: inspect guards plus the actual workflow remote
  shell executed with a fake Docker CLI. Staging pulls the exact digest and
  performs no run/start/remove/prune; missing targets/Compose files fail closed.
- Pylint on all tracked Python plus added Python files: **10.00/10**, exit 0.
- `python -m compileall .`, `git diff --check`: exit 0.
- Both workflow YAML files parsed; all workflow Bash blocks and runbook Bash/
  embedded Python syntax checked. `actionlint` 1.7.7: exit 0.
- Actual local **linux/amd64** Docker build including final-layer imports: success.
  Runtime imports also passed with no network, read-only root and no credentials.
  `python -m pip check` in the image: no broken requirements.
- Image source hashes checked against 27 runtime Python files.
- Two separate disposable containers with one new isolated named volume:
  synthetic snapshot survived recreation, the same run ID did not append again,
  and a synthetic legacy fixture's bytes stayed unchanged. The test volume was
  removed afterward; no production volume was used.

## CI evidence and remaining operator gates

Stage 5's [PR Check run 38680879598](https://github.com/k11tos/usa_stock_finder/actions/runs/38680879598)
was inspected through the GitHub connector: `syntax-and-tests`, `lint`, and
`docker-build` all completed successfully. Its Docker job built AMD64/ARM64.
This is prerequisite evidence, not this Stage 6 PR's result. Inspect the Stage 6
PR checks and the eventual merged-main publish/staging run separately; no new
production image can be claimed deployed before those and the manual rollout.

The [Stage 5 merged-main workflow 38681322803](https://github.com/k11tos/usa_stock_finder/actions/runs/38681322803)
also completed successfully at `99a2120`. This reports CI's build/deploy outcome,
not independent confirmation of live account data or notification delivery.

Local ARM64 execution was not performed. Live Pi Compose/scheduler state,
mount contents/permissions/durability, broker-app reconciliation, cash-flow
evidence, private HTML serving and Telegram receipt remain operator gates.
The read-only verifier reports mounts, not a guarantee of named-volume reuse,
complete backups or the correctness of account/flow evidence. Missing calendar
observations, intraday flows or unavailable historical price/FX data intentionally
produce incomplete/N/A performance. Mutable dependency ranges/base image tags
remain as before; pin the built production image by digest and retain the saved
old image for rollback.
