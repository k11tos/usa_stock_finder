# Issue #175: fixed $100 new-position sizing

## Behavior and compatibility

New positions target $100 regardless of daily candidate count. For each unique
candidate in the existing input order, calculate `floor(100 / current_price)`
whole shares. Existing positive broker holdings (including fractional holdings),
invalid prices and zero-share targets are skipped. If the full resulting cost
cannot be funded, skip the candidate and continue in the same order. Do not buy
a reduced quantity just to exhaust cash. Each later target remains $100; no
unused allocation raises another target.

Budget is `buyable_cash * (1 - RESERVE_RATIO)`. The existing default 10% reserve
remains in effect. Expected sale proceeds are diagnostic only and never added.
Explicit zero broker buying power stays zero rather than falling back to cash.
Missing or invalid buyable cash in sizing inputs prevents buy recommendations.
The existing broker field interpretation is retained; deployed broker field
semantics and actual buying power still require operator verification.

`InvestmentConfig.TARGET_INVESTMENT` is $100, with no automatic adjustment or new
environment override. Existing `DISTRIBUTION_STRATEGY` (including explicit equal
or proportional), `MIN_INVESTMENT`, `MAX_INVESTMENT`, and
`PROPORTIONAL_PERCENTAGE` remain accepted for configuration compatibility but no
longer affect live sizing. The old helper arguments remain accepted, including
`additional_cash`, which is ignored. Reserve remains effective in the actual
allocation path.

`calculate_investment_per_stock` returns target values, not executable cash
allocations. `calculate_share_quantities` applies the shared confirmed budget to
actual whole-share costs. The orchestration returns only funded targets and
quantities; summing target values is not an estimate of actual spending.

Telegram shows funded positive quantities only, with target, estimated spend,
current price and remaining budget after each recommendation (reserve excluded).
Tracking state is not proof of ownership: a tracked-only symbol can be reported
again if broker holdings show no position. Duplicate signals are suppressed.
Logs retain `BUY_SKIP`, `BUY_SIZE`, and `BUY_BUDGET` diagnostics.

Candidate selection, sell rules/priority/quantities, Expansion Pool settings and
logic, and order placement are unchanged. No forced rebalance is introduced.
No real trades, production environment changes, or deployments were performed.

## Verification after a separately authorized production deployment

1. Record the reviewed commit/image and non-secret effective sizing configuration.
   Verify the target is $100 and record the existing reserve. Keep Expansion OFF;
   this sizing change is not approval to activate issue #148.
2. In a non-ordering analysis/alert run, compare broker-confirmed holdings and
   buyable cash to sizing inputs. Verify the broker's balance fields do not
   include unconfirmed expected proceeds. Do not expose account details in PRs.
3. Compare each funded alert to `floor(100 / price)`; verify integer shares,
   price <= $100, estimated spend <= $100, no held symbols or duplicates, and
   aggregate estimated spend <= reserve-adjusted confirmed buying power.
4. For insufficient funds, check existing candidate order, skip reasons, and
   that later targets stay $100. Verify unused funds and reserve stay as cash.
   Compare the Telegram running remainder with `BUY_BUDGET`'s final remainder.
5. Check existing stop-loss/trailing/AVSL/trend sell alerts and quantities against
   their unchanged rules. Expected sale amounts must not increase buy budgets.
6. Record operator sign-off with redacted safe-run evidence before declaring
   deployed sizing reconciled. This PR does not verify historical fills or
   authorize Expansion activation.
