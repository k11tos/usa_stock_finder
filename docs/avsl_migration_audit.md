# AVSL Migration Preflight Audit

Date: 2026-06-30

## Executive summary

- No functional trading changes are made in this audit.
- The current live AVSL sell signal is still the legacy/approximate VPCI/Bollinger-like implementation.
- The original AVSL path exists separately and is currently shadow/monitoring-only.
- The latest 2026-06-30 comparison artifact showed the same sell/hold signal for the observed 21 symbols (`BOTH_HOLD: 21`, no sell divergences, no insufficient data, no errors), but the AVSL values were not identical: the max absolute difference percentage was about 5.62% and the mean absolute difference percentage was about 1.67%.
- Therefore, the safe statement is: **Current sell/hold signals matched for the observed 21 symbols.** Do not claim that the legacy and original AVSL values are identical.

## 1. Current live AVSL call path

Live sell decision flow:

1. `main.py` calls `finder.check_avsl_sell_signal()` while evaluating sell candidates.
2. The returned `avsl_signals` map is passed to `evaluate_sell_decisions(...)`.
3. `sell_signals.evaluate_sell_decisions(...)` checks the AVSL tier after stop loss, special-situation take profit, and trailing stop, and creates an `AVSL` sell decision when the map contains `True` for the holding.

Current signal provider:

- `UsaStockFinder.check_avsl_sell_signal()` is the live function that returns `{symbol: bool}` AVSL signals.
- Its default path is `use_buff_avsl=True`, despite the historical parameter name.
- In that default path, it calls `get_latest_avsl(symbol)` and compares latest close with the returned AVSL stop using strict `current_price < latest_avsl`.

Current implementation used by live signals:

- `get_latest_avsl(symbol)` calls `calculate_avsl_series(symbol)`.
- `calculate_avsl_series(...)` is explicitly documented as the current live sell-signal implementation and as a legacy/approximate AVSL with VPCI and Bollinger-band concepts, not the exact original Buff Dormeier formula.
- The older threshold fallback remains reachable only if `check_avsl_sell_signal(use_buff_avsl=False)` is called; the live call in `main.py` does not pass that flag and therefore uses the default legacy/approximate VPCI AVSL path.

## 2. Current original AVSL call path

Imports and exposure:

- `stock_analysis.py` imports `calculate_original_avsl` from `original_avsl.py`.
- `original_avsl.py` exposes `calculate_original_avsl(...)`, which returns a monitoring DataFrame containing `VPC`, `VPR`, `VM`, `VPCI`, `dynamic_length`, `price_component`, and `original_avsl`.
- `UsaStockFinder.calculate_original_avsl_report(symbol)` is the finder-level wrapper. It builds an OHLCV DataFrame from already-loaded `self.stock_data` and calls `calculate_original_avsl(ohlcv)`.

Live trading impact:

- The original AVSL module says it is a separate shadow-only path and must not be used for live trading sell decisions until explicitly wired in a future change.
- `calculate_original_avsl(...)` says its result is for monitoring/comparison only, does not call network APIs, and does not affect `check_avsl_sell_signal()`.
- `calculate_original_avsl_report(...)` also states it is not used by `check_avsl_sell_signal()` and therefore cannot change current live trading behavior.
- The only current runtime consumer found is the comparison monitor, which reads original AVSL values for diagnostics.

## 3. Retired comparison artifacts and notifications

The former post-run comparison path has been retired after original AVSL became the live sell signal. Daily runs now continue from final item persistence to performance reporting and execution-summary logging without producing comparison artifacts or sending comparison-specific Telegram summaries. The old environment toggles for that path have been removed from active configuration and examples.

## 4. Migration risks

- **Value differences matter even when current signals match.** The 2026-06-30 sample matched sell/hold signals for 21 symbols, but the stop values differed by up to about 5.62% and averaged about 1.67% absolute difference. A future price move can cross one stop but not the other.
- **Original AVSL can be closer to current price than legacy AVSL.** In those cases, migration can create earlier sell triggers even if no signal divergence appeared in the latest artifact.
- **Close-to-stop holdings are highest risk.** SHIP-like cases where price is near the original AVSL stop can trigger earlier sells after migration if the original stop is tighter than the legacy stop.
- **Strict inequality boundary remains important.** Current live logic sells only when `current_price < latest_avsl`; equality is a hold. The migration should preserve this deterministic boundary unless intentionally changed and tested.
- **Data sufficiency and NaN handling may change behavior.** The original path has its own required OHLCV columns, required history, dynamic rolling logic, and positive/finite filtering. Symbols that have a valid legacy AVSL might be insufficient on original AVSL, or vice versa.
- **Config cleanup can unintentionally change behavior.** Removing legacy config must not accidentally remove parameters still needed by tests, docs, backtests, or non-live compatibility paths before those paths are intentionally updated.
- **Monitor removal loses observability.** Removing the comparison monitor in the same migration should be paired with tests and logs that make the new single live AVSL path auditable.
- **Keep the implementation price/OHLCV based.** Do not introduce nondeterministic, broker-state, order-history, sentiment, or external-news inputs into AVSL sell decisions.

## 5. Concrete file-level migration checklist for the next PR

Live sell path changes:

- `stock_analysis.py`
  - Update `UsaStockFinder.check_avsl_sell_signal()` so the default live AVSL signal uses `calculate_original_avsl_report(...)` or a direct original-AVSL helper and still returns `{symbol: bool}`.
  - Preserve deterministic strict `current_price < original_avsl` semantics unless there is an explicit decision to change the boundary.
  - Remove or retire `calculate_avsl_series(...)`, `get_latest_avsl(...)`, and `calculate_vpci_components(...)` if they are no longer used outside tests/docs/backtests.
  - Remove the older threshold fallback from the live AVSL API if it is no longer a supported behavior.
- `original_avsl.py`
  - Update module/function docstrings from shadow-only wording to live-source-of-truth wording after the live path is intentionally wired.
  - Keep the calculation pure and OHLCV based.
- `sell_signals.py`
  - No major routing change should be needed if `check_avsl_sell_signal()` continues to return the same `{symbol: bool}` contract, but update comments/docs if they still imply legacy AVSL.
- `main.py`
  - Keep the call to `finder.check_avsl_sell_signal()` if its contract remains unchanged.

Config cleanup:

- `config.py`
  - Remove `AVSLConfig.IMPLEMENTATION_MODE = "legacy_approximate"`, `ORIGINAL_BUFF_DORMEIER_ENABLED`, and legacy/approximate VPCI AVSL parameters once references are eliminated.
  - Promote original AVSL config names if desired, or keep `OriginalAVSLConfig` with clearer live semantics.
- `env.example` and `README.md`
  - Remove legacy/approximate wording.
  - Document the original AVSL live sell condition and required OHLCV inputs.
- `docs/original_avsl_migration_plan.md`
  - Mark the monitoring plan as superseded or update it to a post-migration validation note.

Tests to add/update:

- Update `tests/test_original_avsl.py` so it verifies `check_avsl_sell_signal()` uses original AVSL for live decisions after migration.
- Add a regression test for a close-to-stop / SHIP-like case where original AVSL is tighter than legacy AVSL and should trigger an earlier sell after migration.
- Add boundary tests proving equality holds and only `current_price < original_avsl` sells.
- Add insufficient-data tests for the new live original path to ensure it returns `False` safely without falling back to legacy AVSL.
- Update config/env tests to confirm removed legacy env vars no longer drive live sell behavior and original AVSL parameters do.
