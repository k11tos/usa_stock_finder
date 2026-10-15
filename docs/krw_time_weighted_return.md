# Cash-flow-aware KRW performance — Stage 4

Stage 5 adds historical-FX benchmark comparisons and report status contracts;
see [validated KRW charts](validated_krw_charts.md). Accounting and TWR validation
rules below are unchanged. Benchmark statements below describe Stage 4 only.

## Accounting boundary (defined before implementation)

Dependencies: merged Stage 1 #164 (`355f164`), Stage 2 #165 (`baf80b1`),
Stage 3 #166 (`14c83f2`). Implement Stage 4 only.

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
away intraday/unknown events. Exact daily TWR is available only under this
verified ordering. No materiality shortcut: **any intraday or untimed flow**
produces N/A, even when its amount offsets another event. Stage 4 does not have
pre/post-flow intraday valuations and does not substitute Modified Dietz or an
assumed end-of-day time for such events.

Daily means consecutive KST calendar observation dates, using the actual fetch
timestamps. Missing calendar dates (including weekends) break the daily series;
no US trading calendar or interpolation is inferred. Snapshot times can differ
slightly, so these are daily observation returns, not exchange close returns.

`I[0] = 100`; `I[t] = I[t-1] * (1+r[t])`.
`cumulative TWR = (I[last]/100 - 1)*100%`.
`drawdown[t] = (I[t]/max(I[0:t]) - 1)*100%`.
Annualized volatility uses sample standard deviation of valid daily returns,
`std(r, ddof=1)*sqrt(365.25)*100%` (calendar-day annualization); at least two
valid returns are required. Its sample count and partial-sample status are
reported; it is not described as full-period volatility if coverage is incomplete.

A gap/invalid return permanently breaks the index for the selected period.
Later independently valid daily returns may be displayed and used in explicitly
labeled valid-sample volatility, but are never joined across a gap. Full-period
TWR and maximum drawdown are N/A unless every interval and requested endpoint
is covered. Rejected broker records conservatively prevent all return validation,
including when they fall outside the requested period, so a rejected boundary
row cannot silently shorten the apparent history. Reconcile the input before
reporting; original rejected observations remain in the diagnostic artifact.
Empty/single-observation periods are N/A with a reason. CAGR, benchmark/FX
comparisons, production rollout and daily workflow reordering remain out of scope.

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
benchmark/excess return remains N/A. Legacy reports remove stale TWR artifacts.
Candidate selection, buy/sell decisions, sizing and notification ordering are
unchanged. Tests use synthetic data only; no broker queries or notifications.
