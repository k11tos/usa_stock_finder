# Original AVSL Migration Plan

> **Historical / completed:** This document records the completed migration from
> the older AVSL implementation to the original deterministic OHLCV-based AVSL
> calculation. It is retained as historical context, not as current operating
> guidance.

## Current state

- Original AVSL is the live AVSL sell path.
- The live signal is deterministic and uses OHLCV inputs.
- A sell signal is triggered only when the latest close is below the latest AVSL
  line: `latest_close < latest_avsl`.
- Sell decision priority is Stop Loss, Special Situation Take Profit, Trailing
  Stop, AVSL, then Trend Exit.
- Daily runs do not produce retired AVSL observation artifacts or AVSL-specific
  Telegram rollups.

## Historical plan summary

Before original AVSL was allowed to drive trading sell decisions, the migration
plan called for evaluating the new calculation beside the older path, reviewing
signal differences, and confirming stable behavior. That observation phase is
complete and should be treated as audit history.

Historical review criteria included:

1. Counting cases where the older path would sell but original AVSL would not.
2. Counting cases where original AVSL would sell but the older path would not.
3. Inspecting symbols where original AVSL was materially tighter or looser.
4. Reviewing realized behavior after differing signal dates.
5. Checking false-positive and false-negative examples, especially for thin or noisy stocks.
6. Confirming the strict live sell boundary: equality holds, and only `current_price < original_avsl` sells.
7. Keeping the AVSL calculation pure and based on OHLCV inputs.

## Completed cleanup state

- Original AVSL has been promoted from migration candidate to live sell signal.
- Retired migration observation artifacts and notification paths are not part of routine runs.
- Future work should focus on maintaining the live original AVSL path.
