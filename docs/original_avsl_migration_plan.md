# Original AVSL Migration Plan

> **Superseded / completed:** This was the historical plan for migrating from
> legacy AVSL to original AVSL. It is no longer an active implementation plan.
> Original AVSL is now the live sell signal used by `check_avsl_sell_signal()`,
> and the legacy-vs-original post-run comparison monitor has been removed. Daily
> runs no longer create `outputs/avsl_monitor` artifacts and no longer send AVSL
> monitor Telegram summaries.

## Current state

- Original AVSL is the default live AVSL sell path.
- The older threshold fallback remains available only for explicit compatibility calls.
- The retired comparison monitor should not be restored as part of routine daily runs.
- The former monitor environment variables (`AVSL_MONITOR_ENABLED`,
  `AVSL_MONITOR_TELEGRAM_ENABLED`, and `AVSL_MONITOR_OUTPUT_DIR`) are not active
  runtime controls.

## Historical plan summary

Before original AVSL was allowed to drive trading sell decisions, the migration
plan called for evaluating original AVSL beside the legacy AVSL path, reviewing
signal divergences, and confirming that original AVSL behavior was stable and
understandable. That observation phase is complete and should be treated as audit
history rather than current operating guidance.

Historical review criteria included:

1. Counting cases where legacy AVSL would sell but original AVSL would not.
2. Counting cases where original AVSL would sell but legacy AVSL would not.
3. Inspecting symbols where original AVSL was materially tighter or looser.
4. Reviewing realized behavior after divergence dates.
5. Checking false-positive and false-negative examples, especially for thin or noisy stocks.
6. Confirming the strict live sell boundary: equality holds, and only `current_price < original_avsl` sells.
7. Keeping the AVSL calculation pure and based on OHLCV inputs.

## Completed cleanup state

- Original AVSL has been promoted from migration candidate to live sell signal.
- The post-run comparison artifact and monitor Telegram paths have been retired.
- The comparison tool and monitor-specific tests have been removed.
- Future work should focus on maintaining the live original AVSL path and only removing legacy compatibility code when that is explicitly in scope.
