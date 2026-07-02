# AVSL Migration Preflight Audit

Date: 2026-06-30

> **Historical / superseded:** This document records the pre-migration audit from
> June 30, 2026. It is retained as historical context, not as current runtime
> documentation.

## Current post-migration state

- `main.py` calls `finder.check_avsl_sell_signal()` while evaluating sell candidates.
- `UsaStockFinder.check_avsl_sell_signal()` uses the original deterministic
  OHLCV-based AVSL calculation and compares the latest close against the latest
  positive finite AVSL value using strict `current_price < original_avsl`
  semantics.
- `UsaStockFinder.calculate_original_avsl_report(symbol)` builds an OHLCV
  DataFrame from already-loaded `self.stock_data` and calls
  `calculate_original_avsl(ohlcv)`; the calculation is pure and does not call
  network APIs.
- AVSL is evaluated after Stop Loss, Special Situation Take Profit, and Trailing
  Stop, and before Trend Exit.
- Daily runs continue from final item persistence to performance reporting and
  execution-summary logging without retired AVSL observation artifacts or
  AVSL-specific Telegram rollups.

## Historical pre-migration findings from 2026-06-30

The original audit was performed before original AVSL became the live sell
signal. At that time, an older approximation path was still live and original
AVSL was being evaluated separately. The June 30, 2026 sample showed matching
sell/hold signals for the observed 21 symbols (`BOTH_HOLD: 21`, no sell
differences, no insufficient data, no errors), but the stop values were not
identical: the max absolute difference percentage was about 5.62% and the mean
absolute difference percentage was about 1.67%. Those findings are retained only
as historical migration context.

## Historical risks considered during migration

- **Value differences mattered even when sample signals matched.** The
  2026-06-30 sample matched sell/hold signals for 21 symbols, but the stop
  values differed by up to about 5.62% and averaged about 1.67% absolute
  difference.
- **Original AVSL could be closer to current price than the older path.** Those
  cases were reviewed as possible earlier-sell triggers during migration.
- **Strict inequality boundary remained important.** The live logic sells only
  when `current_price < original_avsl`; equality is a hold.
- **Data sufficiency and NaN handling could change behavior.** The original path
  has its own required OHLCV columns, required history, dynamic rolling logic,
  and positive/finite filtering.
- **Keep the implementation price/OHLCV based.** AVSL sell decisions should not
  introduce nondeterministic broker-state, order-history, sentiment, or
  external-news inputs.
