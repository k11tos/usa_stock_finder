# AVSL Migration Preflight Audit

Date: 2026-06-30

> Historical note: this audit captured the pre-migration state before original AVSL was promoted to live sell decisions. Current code now uses original AVSL for the live AVSL sell signal while retaining legacy/approximate AVSL for temporary comparison and rollback.

## Executive summary

- No functional trading changes are made in this audit.
- At the time of this audit, the live AVSL sell signal was still the legacy/approximate VPCI/Bollinger-like implementation.
- At the time of this audit, the original AVSL path existed separately as monitoring-only.
- The latest 2026-06-30 comparison artifact showed the same sell/hold signal for the observed 21 symbols (`BOTH_HOLD: 21`, no sell divergences, no insufficient data, no errors), but the AVSL values were not identical: the max absolute difference percentage was about 5.62% and the mean absolute difference percentage was about 1.67%.
- Therefore, the safe statement is: **Observed sell/hold signals matched for the 21 symbols reviewed on 2026-06-30.** Do not claim that the legacy and original AVSL values are identical.

## 1. Pre-migration live AVSL call path

Pre-migration live sell decision flow:

1. `main.py` calls `finder.check_avsl_sell_signal()` while evaluating sell candidates.
2. The returned `avsl_signals` map is passed to `evaluate_sell_decisions(...)`.
3. `sell_signals.evaluate_sell_decisions(...)` checks the AVSL tier after stop loss, special-situation take profit, and trailing stop, and creates an `AVSL` sell decision when the map contains `True` for the holding.

Pre-migration signal provider:

- At the time of the audit, `UsaStockFinder.check_avsl_sell_signal()` was the live function that returns `{symbol: bool}` AVSL signals.
- Its default path was `use_buff_avsl=True`, despite the historical parameter name.
- In that pre-migration default path, it called `get_latest_avsl(symbol)` and compared latest close with the returned AVSL stop using strict `current_price < latest_avsl`.

Pre-migration implementation used by live signals:

- At the time of the audit, `get_latest_avsl(symbol)` called `calculate_avsl_series(symbol)`.
- `calculate_avsl_series(...)` was then documented as the live sell-signal implementation and as a legacy/approximate AVSL with VPCI and Bollinger-band concepts, not the exact original Buff Dormeier formula.
- At the time of the audit, the older threshold fallback was reachable only if `check_avsl_sell_signal(use_buff_avsl=False)` was called; the live call in `main.py` did not pass that flag and therefore used the default legacy/approximate VPCI AVSL path.

## 2. Pre-migration original AVSL call path

Pre-migration imports and exposure:

- `stock_analysis.py` imports `calculate_original_avsl` from `original_avsl.py`.
- `original_avsl.py` exposes `calculate_original_avsl(...)`, which returns a monitoring DataFrame containing `VPC`, `VPR`, `VM`, `VPCI`, `dynamic_length`, `price_component`, and `original_avsl`.
- `UsaStockFinder.calculate_original_avsl_report(symbol)` is the finder-level wrapper. It builds an OHLCV DataFrame from already-loaded `self.stock_data` and calls `calculate_original_avsl(ohlcv)`.

Pre-migration live trading impact:

- The original AVSL module then described itself as a separate monitoring path pending explicit live wiring.
- `calculate_original_avsl(...)` then said its result was for monitoring/comparison only and did not call network APIs.
- At the time of the audit, `calculate_original_avsl_report(...)` also stated it was not used by `check_avsl_sell_signal()` and therefore could not change then-current live trading behavior.
- The only runtime consumer found at the time of the audit was the comparison monitor, which read original AVSL values for diagnostics.

## 3. Monitor artifacts and notifications

Invocation:

- `main.py` imports AVSL monitor helpers from `tools.compare_avsl`.
- After final items are saved and the performance report path runs, `main.py` invokes `_run_avsl_monitor_safely(...)`.
- `_run_avsl_monitor_safely(...)` exits immediately unless the monitor is enabled, builds the monitor symbol universe from then-current holdings plus buy/not-sell symbols, runs `compare_avsl_symbols(finder, symbols)`, writes monitor outputs, and logs summary counts.

Monitor implementation and artifacts:

- `tools/compare_avsl.py` is explicitly monitoring-only and says its output is not used for trading decisions.
- `compare_symbol(...)` reads legacy AVSL via `finder.get_latest_avsl(symbol)` and original AVSL via `finder.calculate_original_avsl_report(symbol)`.
- `write_monitor_outputs(...)` publishes latest artifacts under `outputs/avsl_monitor/latest/` and historical copies under `outputs/avsl_monitor/history/<run_date>/` by default.

Configuration and environment variables:

- `AVSL_MONITOR_ENABLED` controls whether `_run_avsl_monitor_safely(...)` runs; default is `False` through `AVSLConfig.MONITOR_ENABLED`.
- `AVSL_MONITOR_TELEGRAM_ENABLED` controls whether the compact Telegram summary is sent; default is `False` through `AVSLConfig.MONITOR_TELEGRAM_ENABLED`.
- `AVSL_MONITOR_OUTPUT_DIR` controls artifact root; default is `outputs/avsl_monitor`.
- `ORIGINAL_AVSL_ENABLED` controls whether `calculate_original_avsl_report(...)` returns original AVSL diagnostics; default is `True` through `OriginalAVSLConfig.ENABLED`.
- Original AVSL calculation parameters are `ORIGINAL_AVSL_FAST_PERIOD`, `ORIGINAL_AVSL_SLOW_PERIOD`, `ORIGINAL_AVSL_MIN_LENGTH`, `ORIGINAL_AVSL_MAX_LENGTH`, and `ORIGINAL_AVSL_STDDEV_MULT`.
- At the time of the audit, legacy/approximate live AVSL parameters were `AVSL_BARS`, `AVSL_STDDEV_MULT`, `AVSL_MIN_LENGTH`, `AVSL_MAX_LENGTH`, `AVSL_FAST_PERIOD`, `AVSL_SLOW_PERIOD`, and `AVSL_TIMEFRAME`; older threshold fallback vars were present but not used by the then-default live path.

Telegram path:

- When `_is_avsl_monitor_telegram_enabled()` returns true, `_run_avsl_monitor_safely(...)` calls `_send_avsl_monitor_telegram_summary(rows, artifact_path)`.
- `_send_avsl_monitor_telegram_summary(...)` reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, builds the message with `build_telegram_monitor_summary(...)`, and sends it through `send_telegram_message(...)`.
- `build_telegram_monitor_summary(...)` includes monitoring-only text and counts for `BOTH_HOLD`, `BOTH_SELL`, `LEGACY_ONLY_SELL`, `ORIGINAL_ONLY_SELL`, and `INSUFFICIENT_DATA`.

## 4. Migration risks

- **Value differences matter even when current signals match.** The 2026-06-30 sample matched sell/hold signals for 21 symbols, but the stop values differed by up to about 5.62% and averaged about 1.67% absolute difference. A future price move can cross one stop but not the other.
- **Original AVSL can be closer to current price than legacy AVSL.** In those cases, migration can create earlier sell triggers even if no signal divergence appeared in the latest artifact.
- **Close-to-stop holdings are highest risk.** SHIP-like cases where price is near the original AVSL stop can trigger earlier sells after migration if the original stop is tighter than the legacy stop.
- **Strict inequality boundary remains important.** Current live logic sells only when `current_price < latest_avsl`; equality is a hold. The migration should preserve this deterministic boundary unless intentionally changed and tested.
- **Data sufficiency and NaN handling may change behavior.** The original path has its own required OHLCV columns, required history, dynamic rolling logic, and positive/finite filtering. Symbols that have a valid legacy AVSL might be insufficient on original AVSL, or vice versa.
- **Config cleanup can unintentionally change behavior.** Removing legacy config must not accidentally remove parameters still needed by tests, docs, backtests, or non-live compatibility paths before those paths are intentionally updated.
- **Monitor removal loses observability.** Removing the comparison monitor in the same migration should be paired with tests and logs that make the new single live AVSL path auditable.
- **Keep the implementation price/OHLCV based.** Do not introduce nondeterministic, broker-state, order-history, sentiment, or external-news inputs into AVSL sell decisions.

## 5. Historical file-level migration checklist for the promotion PR

Live sell path changes planned at the time of the audit:

- `stock_analysis.py`
  - Update `UsaStockFinder.check_avsl_sell_signal()` so the default live AVSL signal uses `calculate_original_avsl_report(...)` or a direct original-AVSL helper and still returns `{symbol: bool}`.
  - Preserve deterministic strict `current_price < original_avsl` semantics unless there is an explicit decision to change the boundary.
  - Remove or retire `calculate_avsl_series(...)`, `get_latest_avsl(...)`, and `calculate_vpci_components(...)` if they are no longer used outside tests/docs/backtests.
  - Remove the older threshold fallback from the live AVSL API if it is no longer a supported behavior.
- `original_avsl.py`
  - Update module/function docstrings from monitoring-only wording to live-source-of-truth wording after the live path is intentionally wired.
  - Keep the calculation pure and OHLCV based.
- `sell_signals.py`
  - No major routing change should be needed if `check_avsl_sell_signal()` continues to return the same `{symbol: bool}` contract, but update comments/docs if they still imply legacy AVSL.
- `main.py`
  - Keep the call to `finder.check_avsl_sell_signal()` if its contract remains unchanged.
  - Remove imports and invocation for the AVSL comparison monitor once the monitor is intentionally retired.

Monitor/config cleanup planned at the time of the audit:

- `tools/compare_avsl.py`
  - Remove the legacy-vs-original comparison CLI/monitor when no longer needed, or replace it with a one-path original AVSL diagnostic if operational visibility is still desired.
- `config.py`
  - Remove `AVSLConfig.IMPLEMENTATION_MODE = "legacy_approximate"`, `ORIGINAL_BUFF_DORMEIER_ENABLED`, legacy/approximate VPCI AVSL parameters, and monitor toggles once references are eliminated.
  - Promote original AVSL config names if desired, or keep `OriginalAVSLConfig` with clearer live semantics.
- `env.example` and `README.md`
  - Remove monitor env var examples and legacy/approximate wording.
  - Document the original AVSL live sell condition and required OHLCV inputs.
- `docs/original_avsl_migration_plan.md`
  - Mark the monitoring plan as superseded or update it to a post-migration validation note.

Tests planned at the time of the audit:

- Update `tests/test_original_avsl.py` so it verifies `check_avsl_sell_signal()` uses original AVSL for live decisions after migration.
- Add a regression test for a close-to-stop / SHIP-like case where original AVSL is tighter than legacy AVSL and should trigger an earlier sell after migration.
- Add boundary tests proving equality holds and only `current_price < original_avsl` sells.
- Add insufficient-data tests for the new live original path to ensure it returns `False` safely without falling back to legacy AVSL.
- Update or remove tests for `tools.compare_avsl` and AVSL monitor Telegram summaries when the monitor is retired.
- Update config/env tests to confirm removed legacy env vars no longer drive live sell behavior and original AVSL parameters do.
