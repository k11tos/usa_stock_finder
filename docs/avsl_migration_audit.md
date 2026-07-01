# AVSL Migration Preflight Audit

Date: 2026-06-30

> **Historical / superseded note (post PR #125/#126):** This document records the
> pre-migration audit from June 30, 2026. It is no longer a description of the
> current runtime. Original AVSL is now the live sell signal used by
> `check_avsl_sell_signal()`, and the legacy-vs-original post-run comparison
> monitor has been removed. Daily runs no longer create `outputs/avsl_monitor`
> artifacts and no longer send AVSL monitor Telegram summaries. The retired
> monitor environment variables (`AVSL_MONITOR_ENABLED`,
> `AVSL_MONITOR_TELEGRAM_ENABLED`, and `AVSL_MONITOR_OUTPUT_DIR`) are not active
> configuration knobs.

## Current post-migration state

- `main.py` still calls `finder.check_avsl_sell_signal()` while evaluating sell candidates.
- `UsaStockFinder.check_avsl_sell_signal()` now uses the original AVSL path by default (`use_buff_avsl=True`) and compares the latest close against the latest positive finite `original_avsl` value using strict `current_price < original_avsl` semantics.
- `UsaStockFinder.calculate_original_avsl_report(symbol)` builds an OHLCV DataFrame from already-loaded `self.stock_data` and calls `calculate_original_avsl(ohlcv)`; the calculation is pure and does not call network APIs.
- The older threshold fallback remains reachable only through explicit compatibility calls with `check_avsl_sell_signal(use_buff_avsl=False)`.
- The legacy/approximate AVSL calculation remains in the codebase for compatibility, but it is not the default live AVSL sell signal.
- The retired post-run comparison monitor, local comparison artifacts, and monitor-specific Telegram summary path are no longer part of the daily run.

## Historical pre-migration findings from 2026-06-30

The original audit was performed before original AVSL became the live sell
signal. At that time, the legacy/approximate VPCI/Bollinger-like AVSL path was
still live and original AVSL was being evaluated separately. The comparison
sample from June 30, 2026 showed matching sell/hold signals for the observed 21
symbols (`BOTH_HOLD: 21`, no sell divergences, no insufficient data, no errors),
but the stop values were not identical: the max absolute difference percentage
was about 5.62% and the mean absolute difference percentage was about 1.67%.
Those findings are retained only as historical migration context.

## Retired comparison artifacts and notifications

The former post-run comparison path has been retired after original AVSL became
the live sell signal. Daily runs now continue from final item persistence to
performance reporting and execution-summary logging without producing comparison
artifacts or sending comparison-specific Telegram summaries. The old environment
toggles for that path have been removed from active configuration and examples.

## Historical risks considered during migration

- **Value differences mattered even when sample signals matched.** The 2026-06-30 sample matched sell/hold signals for 21 symbols, but the stop values differed by up to about 5.62% and averaged about 1.67% absolute difference.
- **Original AVSL could be closer to current price than legacy AVSL.** Those cases were reviewed as possible earlier-sell triggers during migration.
- **Strict inequality boundary remained important.** The live logic sells only when `current_price < original_avsl`; equality is a hold.
- **Data sufficiency and NaN handling could change behavior.** The original path has its own required OHLCV columns, required history, dynamic rolling logic, and positive/finite filtering.
- **Keep the implementation price/OHLCV based.** AVSL sell decisions should not introduce nondeterministic broker-state, order-history, sentiment, or external-news inputs.

## Completed cleanup notes

- Original AVSL has been connected to live sell decisions through `check_avsl_sell_signal()`.
- The legacy-vs-original post-run comparison monitor and `tools.compare_avsl` path were removed after the live migration.
- Monitor-specific tests, environment examples, and active documentation were removed or marked retired.
