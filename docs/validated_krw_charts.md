# Validated KRW charts and benchmarks — Stage 5

Dependencies: Stage 1 #164, Stage 2 #165, Stage 3 #166 and Stage 4 #167 are
merged in `main` through `fd83922`. This change implements Stage 5 only.
Collection flags, production defaults, trading rules, quantities, Telegram
content and daily workflow ordering are unchanged.

The report reuses the validated broker observations and explicit external-flow
ledger described in [Stage 3](broker_equity_performance.md) and
[Stage 4](krw_time_weighted_return.md). Raw total assets in KRW remain distinct
from the cash-flow-adjusted TWR index. No legacy USD equity is joined to KRW
history: the first validated broker observation is the new base of 100.
Gaps or invalid intervals never restart or reconnect the TWR index. Full-period
TWR and drawdown require every interval and requested endpoint; volatility uses
only independently validated calendar-day returns, with its sample count and
incomplete-period scope shown explicitly.

## Historical benchmark valuation

KRW comparisons support the verified USD-listed SPY and IWM benchmarks. Other
configured symbols are N/A with an unverified-currency warning in KRW mode;
legacy mode keeps its existing symbol support.

Yahoo Finance supplies explicit dividend/split-adjusted ETF `Adj Close` prices
and historical `KRW=X` `Close` observations, expressed as KRW per USD. Requests
disable automatic adjustment, have a 10-second timeout each, and include seven
days before the selected period to cover prior closes and holidays. Missing
adjusted prices never fall back to unadjusted prices. Each source is fetched
independently so a failed benchmark does not hide another valid comparison.

For each actual broker timestamp, take the latest completed daily benchmark bar
and FX bar available **before** that timestamp. Conservatively, a date's bar is
eligible at 00:00 UTC the following day. This prevents using a US closing price
that is still in the future at a KST afternoon valuation. The quote date must be
at most four calendar days old (inclusive). Weekends/holidays can use a bounded
prior observation; there is no backfill, interpolation, or constant/current FX
substitution. Nonpositive/nonfinite values, duplicate source dates, stale quotes
and provider exceptions produce N/A. Exact source dates and amounts are retained
for audit. These are daily reference comparisons; intraday broker valuations
and daily reference prices do not claim identical execution times.

`benchmark_value_krw[t] = adjusted_close_usd[t] * historical_usdkrw[t]`

`benchmark_index[t] = benchmark_value_krw[t] / benchmark_value_krw[0] * 100`

`excess_return_pp[t] = portfolio_twr_index[t] - benchmark_index[t]`

Both endpoints and every portfolio observation must have valid price and FX
coverage, and full-period portfolio TWR must be validated. Otherwise that entire
benchmark comparison is N/A; partial-period rebasing is prohibited. Excess
return is an arithmetic difference in cumulative **percentage points**, with
both legs denominated in KRW. Benchmark failures do not invalidate otherwise
verified portfolio TWR; the report carries warnings and per-symbol statuses.

## Output contracts changed in Stage 5

Existing filenames, fixed broker input path, CLI source selection and
`latest/` / `history/<run-id>/` publishing remain. The following are additive
or clarified changes; legacy USD numeric and CSV contracts remain unchanged.

| Output | Stage 5 contract |
| --- | --- |
| `equity_curve.csv`, `broker_equity_observations.csv`, `twr_curve.csv` | Schemas unchanged; selected raw KRW, original input bytes and validated TWR remain separate. |
| `performance_summary.json` (KRW) | Existing benchmark/excess keys now contain validated KRW comparisons when available. New keys: `benchmark_methodology`, `benchmark_currency`, `benchmark_data_source`, `benchmark_status` (per symbol: `available`/`unavailable`), `valid_snapshot_count`, `performance_methodology`, `requested_start_date`, `requested_end_date`, `report_status`. `report_status` is `validated`, `validated_with_warnings`, or `invalid`; invalid reports include `error`. `returns_validated` continues to describe portfolio TWR. `best_benchmark` now identifies the best available KRW benchmark. |
| `benchmark_comparison.csv` (KRW) | Retains `asset,cumulative_return_pct`; adds `valuation_currency,excess_return_pp`. Missing values are blank. |
| `benchmark_curve.csv` (new; KRW only) | `date,asset,benchmark_date,fx_date,adjusted_close_usd,usdkrw,benchmark_value_krw,benchmark_index,excess_return_pp`. Records each aligned observation, including available source fields when a comparison fails. Header-only if portfolio TWR cannot be validated. |
| `charts/raw_equity_krw.png` | Raw broker total assets, labeled in KRW. |
| `charts/cumulative_return.png` | Portfolio TWR index and available KRW benchmark total-return indices, base 100. Incomplete TWR displays only its unbroken prefix. |
| `charts/drawdown.png` | Validated TWR drawdown only; full-period metric stays N/A if incomplete. |
| `charts/excess_return.png` | Currency-consistent cumulative excess returns in percentage points; N/A panel when unavailable. |
| `charts/twr_volatility.png` (new; KRW only) | Expanding sample TWR volatility, `std(ddof=1)*sqrt(365.25)*100`, at least two valid daily returns; full-period or incomplete valid-sample scope is labeled. No value is plotted on an invalid interval. |
| HTML / Markdown | Currency, actual/requested periods, valid snapshot count, methodology, flow verification, data gaps, warnings and benchmark source/alignment policy are visible. HTML uses responsive images, wrapping text and compact metric cards. Chart dimensions, labels and legends improve small-screen readability, including shared legacy chart rendering. |
| Python builder | `build_report(args)` now returns `True` for validated broker TWR, `False` for diagnostic-only broker output, and preserves legacy `None`. |
| Optional runner | Returns `False` and logs diagnostic-only status on failed KRW validation; never logs that case as successful validated generation. Benchmark N/A alone still permits verified portfolio success. |
| Standalone CLI | Exits 1 after writing diagnostic-only KRW output; exits 0 for validated KRW or the existing legacy path. |

All new artifacts are copied to latest/history and removed from refreshed
current/latest bundles when switching back to legacy. Distinct older history
runs are retained. Invalid new observations deliberately refresh latest with
explicitly invalid diagnostics, avoiding stale successful performance; they do
not silently become a successful validated report. Original rejected records
remain available for reconciliation. No live ledger is manufactured.

## Validation and limits

Tests use synthetic broker snapshots, explicit flow attestations, adjusted ETF
prices and time-varying historical FX. No broker requests, notifications or live
account state writes are required. Missing FX/benchmarks, provider failures,
currency uncertainty, invalid/gapped equity, boundary behavior, chart values,
labels, HTML resources, PNG generation and publishing are covered.

Live market data remains subject to provider availability, historical revisions
and reference-time differences. N/A with warnings is the intended response to
unusable data. CAGR, collection/report reordering, production enablement and
Stage 6 rollout remain outside this change.
