# Stage 4 mathematical reconciliation and verification

## Objective and scope

Measure KRW investment performance inside the validated KIS overseas total-asset
boundary, separating external owner funding/withdrawals and domestic/overseas
capital transfers. Stage 1 #164, Stage 2 #165 and Stage 3 #166 were confirmed
merged on `origin/main` at `14c83f2` before implementation.

[Accounting boundary, ledger schema and timing convention](krw_time_weighted_return.md)
was written before implementation. The new manually verified KRW ledger is
independent of the unchanged legacy `cash_flows.csv` semantics.

## Single-interval reconciliation

All amounts below are synthetic KRW units; scale by any common positive factor
without changing returns. B is opening broker total, E closing broker total,
S signed contributions immediately after opening valuation, and F signed
contributions immediately before closing valuation.

`r = (E - F) / (B + S) - 1`.

| Case | B | S | E | F | Adjusted ratio | Daily TWR |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| Market gain, verified zero flows | 100 | 0 | 110 | 0 | 110 / 100 | 10% |
| Deposit only | 100 | 0 | 150 | +50 | (150 - 50) / 100 | 0% |
| Withdrawal only | 100 | 0 | 60 | -40 | (60 + 40) / 100 | 0% |
| End deposit plus gain | 100 | 0 | 160 | +50 | (160 - 50) / 100 | 10% |
| Start deposit plus gain | 100 | +50 | 165 | 0 | 165 / (100 + 50) | 10% |
| Domestic-to-overseas transfer | 100 | 0 | 150 | +50 | (150 - 50) / 100 | 0% |
| Overseas-to-domestic transfer | 100 | 0 | 60 | -40 | (60 + 40) / 100 | 0% |
| Two same-day deposits | 100 | 0 | 170 | +50 +20 | (170 - 70) / 100 | 0% |
| Verified offsetting flows | 100 | 0 | 100 | +50 -50 | 100 / 100 | 0% |
| Start deposit and end withdrawal | 100 | +50 | 125 | -40 | (125 + 40) / 150 | 10% |

Offsetting verified flows remain classified as `verified_nonzero`, despite zero
net flow. Distinct same-day events are aggregated; duplicate event IDs invalidate
the ledger instead of double counting. A missing or empty ledger, event rows
without a complete attestation, incomplete/pending reviews, or unverified events
produce unknown coverage and N/A performance.

No dividend/fee/tax rows are automatically external: opening 100, investment
income +10, investment costs -3, closing 107 with verified zero external flows
gives **7%**, preserving income and costs in investment performance.

For settlement, the broker total remains 1,000 while cash changes 400 → 200,
unsettled buys 200 → 0, and stock evaluation remains 800. The calculation uses
the authoritative totals, **1,000 / 1,000 - 1 = 0%**. It neither sums components
nor invents a contribution/withdrawal from settlement changes.

## Chained index and drawdown

| Observation | Broker total | End flow | Return factor | TWR index | Running peak | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Opening | 100 | — | — | 100 | 100 | 0% |
| Day 1 | 160 | +50 | (160 - 50) / 100 = 1.1 | 110 | 110 | 0% |
| Day 2 | 114 | -30 | (114 + 30) / 160 = 0.9 | 99 | 110 | -10% |
| Day 3 | 125.4 | 0 | 125.4 / 114 = 1.1 | 108.9 | 110 | -1% |

- Cumulative TWR: `1.1 × 0.9 × 1.1 - 1 = 8.9%`.
- Maximum drawdown: `99 / 110 - 1 = -10%`.
- Daily returns: `[0.1, -0.1, 0.1]`; sample variance: `0.04 / 3`.
- Calendar-day annualized volatility:
  `sqrt(0.04 / 3) × sqrt(365.25) × 100 = 220.6807649071%`.
  This intentionally extreme synthetic daily example checks the formula, not a
  prediction of real portfolio volatility.
- Reversing input snapshot/ledger row order yields identical selected curves and
  summary results. Fraction arithmetic chains decimal valuation/flow factors
  before conversion to display floats.

## Refusal and partial-coverage checks

Any intraday or untimed flow, including an offsetting intraday pair, produces
N/A rather than an exact daily TWR claim. Missing calendar observations do not
become a single daily return. A missing requested endpoint cannot shorten the
period silently. Zero/negative/nonfinite equity, wrong currency/source, rejected
broker rows, malformed ledger evidence or nonpositive adjusted capital prevent
return validation.

After a failed interval, the TWR index remains unavailable for all later dates.
Independently valid later daily returns are retained for a labeled
`valid_returns_only_incomplete_period` volatility sample, with its sample count.
Full-period cumulative return and maximum drawdown remain N/A with reasons.
No materiality threshold is used to disregard unvalued flows.

## Files and behavior

- `tools/krw_twr.py`: locked ledger reader, explicit completeness/timing
  validation, daily TWR, chained index, drawdown and valid-sample volatility.
- `tools/broker_equity.py`: expose rejected-record status to prevent a filtered
  input from creating misleading performance. Existing raw selection is retained.
- `tools/performance_report.py`: KRW TWR summaries, charts, `twr_curve.csv`,
  CLI ledger path, latest/history publishing and stale artifact removal.
- `telegram_utils.py`: optional KRW performance section shows validated TWR or
  unavailable status; no messages are sent by tests or by this implementation work.
- `tests/test_krw_twr.py`: deterministic synthetic accounting and full report
  publication regressions, plus explicit legacy sign/type compatibility.
- Documentation records the boundary, schema, math and Stage 3 → 4 extension.

Candidate selection, buy/sell decisions and investment quantities are unchanged.
The report/collection ordering and all production defaults are unchanged.
No actual account data was edited or queried. No production ledger, verification
attestation, migration, new dependency or Stage 5/6 feature was introduced.

## Executed validation

Using the existing `/workspace/venvs/usa_stock_finder` Python 3.12.14 environment:

- `python -m pytest -q`: **926 passed, 35 subtests passed**.
- `PYLINTHOME=/tmp/stage4-pylint python -m pylint $(git ls-files '*.py')`:
  **10.00/10**, exit 0 (installed pylint 4.1.1).
- `python -m compileall -q .`: exit 0.
- `git diff --cached --check`: exit 0.

Local verification is complete. GitHub CI is tracked on the PR separately.
Live broker reconciliation remains an operator task: boundary-timed events and
complete coverage must be supported by actual statements/valuation evidence.
