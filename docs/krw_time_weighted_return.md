# Cash-flow-aware KRW performance — Stage 7

Stage 7 permits verified returns between consecutive actual observations across
weekends and holidays. Stage 5's historical-FX comparisons and report status
contracts remain; see [validated KRW charts](validated_krw_charts.md).

## Accounting boundary (defined before implementation)

Dependencies: merged Stage 1 #164 (`355f164`), Stage 2 #165 (`baf80b1`),
Stage 3 #166 (`14c83f2`). The accounting boundary originated in Stage 4.

The portfolio is **the assets represented by the validated KIS overseas total
asset response in KRW**, with Stage 1's US/all-market/KRW query scope.
`output3.tot_asst_amt` is authoritative. Do not reconstruct equity from cash,
holdings or unsettled components. KRW FX valuation changes belong to performance.

Capital entering this boundary is positive; capital leaving is negative.
Domestic-to-overseas transfers are contributions when they cross this boundary;
overseas-to-domestic transfers are withdrawals. Account labels or currency
conversion alone do not prove a boundary crossing: reconcile to broker evidence.
Ordinary stock purchases, sales and settlement within the boundary are internal.
Dividends, trading fees and investment taxes remain investment income/costs;
they are not automatically external contributions/withdrawals. A subsequent
owner withdrawal of dividend cash is a separate boundary-crossing event.

## Explicit ledger and verification

Read `data/live/krw_external_flows.csv` (override with `--krw-external-flows`).
This manually reconciled CSV is separate from legacy `cash_flows.csv`; no
automatic import, reclassification, currency conversion or inference occurs.
The legacy USD/Modified Dietz implementation and its original semantics remain.
No live ledger or attestations are created by this implementation.

Exact CSV header:

```csv
record_id,interval_start,interval_end,effective_at,amount_krw,currency,classification,timing,source,description,verification_status
```

- Unique `record_id` identifies an event/attestation. Repeated same-day events
  have distinct IDs and are all included. Duplicate IDs fail closed.
- `interval_start`/`interval_end` are timezone-aware ISO timestamps matching
  the two selected broker fetch timestamps exactly (instants, any UTC offset).
  Each event is assigned once to one interval; never repeat a boundary event
  in both adjacent intervals. Changing the selected snapshot requires review.
- `effective_at` preserves the known timezone-aware timestamp, ISO date only,
  or blank when unknown. Date-only/unknown times cannot validate a flow return.
- `amount_krw` is finite signed KRW; `currency` must be `KRW`.
- Flow `classification`: `deposit`, `withdrawal`, `domestic_to_overseas`,
  `overseas_to_domestic`. Inbound amounts must be positive, outbound negative.
  Internal trades, dividends, fees and taxes are deliberately not classifications.
- `timing`: `start`, `end`, `intraday`, or `unknown` for flows.
- `source` and `description` are mandatory evidence references/context (no
  credentials). `verification_status` is `verified` or `pending`.
- Each interval also needs exactly one attestation row: classification
  `complete` or `incomplete`, amount `0`, empty `effective_at`, timing `none`.
  `complete` + `verified` asserts the entire list of external flows in that
  interval has been reconciled, including that there are no omitted events.
  A verified complete row with no events means **verified zero flows**.
  One or more verified events means **verified nonzero flows**, even if net zero.
  Missing/pending/incomplete attestation or pending events means **unknown**.

For example, a synthetic end-boundary deposit of KRW 50 requires both rows below
(the matching broker opening/closing timestamps are at 16:00 KST). To verify
zero flows, retain only the complete attestation **after** reconciling evidence:

```csv
record_id,interval_start,interval_end,effective_at,amount_krw,currency,classification,timing,source,description,verification_status
review-2,2026-01-01T16:00:00+09:00,2026-01-02T16:00:00+09:00,,0,KRW,complete,none,synthetic statement,Full interval reconciled,verified
deposit-2,2026-01-01T16:00:00+09:00,2026-01-02T16:00:00+09:00,2026-01-02T16:00:00+09:00,50,KRW,deposit,end,synthetic statement,Deposit immediately before closing valuation,verified
```

An empty/missing/unreadable/malformed ledger is unknown, never zero. Invalid
rows, duplicate IDs, conflicting attestations or overlapping declared intervals
invalidate the ledger as a whole, with sanitized diagnostics. Readers lock the
file; manual maintenance should use an atomic file replacement or exclusive lock.

## Timing convention and mathematics

Use boundary-valued subperiod TWR. A `start` flow occurs immediately **after**
the opening snapshot and has exactly its timestamp. An `end` flow occurs
immediately **before** the closing snapshot and has exactly its timestamp.
The timing label attests this ordering; timestamp equality alone is insufficient.
Opening equity excludes start flows; closing equity includes end flows.

For opening equity B, closing equity E, signed start flows S and end flows F:

`r = (E - F) / (B + S) - 1`.

Require positive finite broker equity, positive invested capital B+S and positive
pre-end-flow equity E-F. Aggregate every event at each boundary, without netting
away intraday/unknown events. Exact interval TWR is available only under this
verified ordering. No materiality shortcut: **any intraday or untimed flow**
produces N/A, even when its amount offsets another event. The ledger does not provide
pre/post-flow intraday valuations and does not substitute Modified Dietz or an
assumed end-of-day time for such events.

Returns use consecutive actual validated broker observations, preserving their
fetch timestamps and dates. Friday-to-Monday, holidays and longer gaps are valid
only with complete verified flow evidence matching **both exact timestamps for
the entire interval**. Separate shorter ledger intervals cannot substitute for
that evidence. No snapshots, daily paths or zero flows are inferred.

Missing weekdays produce diagnostics (they may be holidays or failed runs; no
trading-calendar API is used). Gaps exceeding four KST calendar days also produce
an unusually-long-gap diagnostic. These warnings alone neither invalidate a
verified interval nor establish flow completeness. Requested endpoints must still
have actual valuations, including explicitly requested weekend dates. Python does
not filter weekend execution or observations; production Cron remains unchanged.

`interval_return` is the full boundary-adjusted return. `interval_days` is actual
elapsed time in 24-hour days; `calendar_days` is the difference in KST dates.
The retained `daily_return` compatibility column is populated only for valid
intervals with `calendar_days == 1`. A multi-day return is never labeled daily.

`I[0] = 100`; `I[t] = I[t-1] * (1+r[t])`.
`cumulative TWR = (I[last]/100 - 1)*100%`.
`drawdown[t] = (I[t]/max(I[0:t]) - 1)*100%`.
Annualized volatility uses sample standard deviation of verified **interval**
returns, `std(r, ddof=1)*sqrt(365.25 / d)*100%`, only if all observed intervals
have exactly the same positive elapsed duration `d` (in 24-hour days) and at
least two returns are valid. This is the conventional equal-period arithmetic
return estimator, assuming independent, stationary increments. `d=1` preserves
the previous daily result; equal two-day intervals use `sqrt(365.25/2)`.
Mixed durations, including ordinary weekday/weekend mixtures or differing fetch
times, produce **N/A with an explicit reason**. No root-of-return daily estimates,
daily-only subset, duration rounding or 252-session assumption is introduced.
Invalid intervals' durations are included in this eligibility check so excluding
their returns cannot conceal mixed sampling. Unknown/nonpositive durations and
insufficient/nonfinite samples also produce N/A. Chart and summary share this
rule; the entire volatility chart is N/A when duration eligibility fails.
Otherwise expanding volatility is shown only on valid intervals, with its sample
count and incomplete-period scope. Valid-sample volatility can remain available
when TWR is incomplete; it is not a full-period metric in that case.

A return invalidated by timestamps, equity or flow evidence permanently breaks
the index for the selected period. Later independently valid interval returns may
be displayed and used in eligible valid-sample volatility, but are never joined
across an invalid interval. Full-period
TWR and maximum drawdown are N/A unless every interval and requested endpoint
is covered. Rejected broker records conservatively prevent all return validation,
including when they fall outside the requested period, so a rejected boundary
row cannot silently shorten the apparent history. Reconcile the input before
reporting; original rejected observations remain in the diagnostic artifact.
Empty/single-observation periods are N/A with a reason. MDD is measured only at
actual observations; unobserved intrainterval drawdowns cannot be recovered.
CAGR, production rollout and daily workflow reordering remain out of scope.

Synthetic reconciliation examples (Friday opening to Monday closing):

| Opening B | Closing E | Start S | End F | Interval return |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 105 | 0 | 0 | 5% |
| 100 | 150 | 0 | 50 | 0% |
| 100 | 60 | 0 | -40 | 0% |
| 100 | 165 | 50 | 0 | 10% |

Every example requires explicit complete verification. Without it, the result
is N/A. Chaining +10%, -10%, +10% gives indices 100, 110, 99, 108.9, cumulative
TWR +8.9% and observed MDD -10%, even when one interval spans a weekend.

## Operation and outputs

```bash
python tools/performance_report.py --data-source broker_krw \
  --krw-external-flows data/live/krw_external_flows.csv \
  --output outputs/performance_krw --publish-latest --history
```

The optional runner uses the default ledger path. Existing source/collection
defaults remain unchanged. Raw observation artifacts remain; `twr_curve.csv`
adds per-interval verification, signed boundary sums, return/rejection reason,
index and drawdown. Summary JSON and HTML/Markdown distinguish flow completeness
from return validity. Return charts show the validated unbroken index prefix;
benchmarks retain Stage 5's actual-timestamp alignment and missing-data policy.
`valid_interval_return_count` counts valid intervals; `expected_interval_return_count`
is `max(selected actual snapshot count - 1, 0)`, never elapsed calendar days.
The retained `valid_daily_return_count` / `expected_daily_return_count` count only
valid / actual adjacent intervals spanning one KST calendar day. They are not
estimates of scheduled executions or ledger completeness. `num_days` remains the
legacy-compatible selected snapshot count; reports label it as snapshots.
`observation_gap_warnings` is separate from `twr_unavailable_reasons`.
Volatility exposes `volatility_interval_days`, `volatility_convention`,
`volatility_unavailable_reason`, sample count and scope. Legacy reports remove
stale TWR artifacts; legacy USD calculations are unchanged.
Candidate selection, buy/sell decisions, sizing and notification ordering are
unchanged. Tests use synthetic data only; no broker queries or notifications.
