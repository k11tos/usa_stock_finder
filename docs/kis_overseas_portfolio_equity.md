# KIS overseas portfolio equity — Stage 1

`stock_operations.fetch_overseas_portfolio_equity()` independently reads the
US portfolio's broker-reported total assets in KRW. It is not connected to the
daily workflow, sizing, account snapshots, or Telegram messages in this stage.
Existing `fetch_account_balance()` behavior remains unchanged.

The request uses `/uapi/overseas-stock/v1/trading/inquire-present-balance`,
TR ID `CTRP6504R`, and these confirmed parameters:

| Parameter | Value |
| --- | --- |
| WCRC_FRCR_DVSN_CD | 01 |
| NATN_CD | 840 |
| TR_MKET_CD | 00 |
| INQR_DVSN_CD | 00 |

Credentials and account identifiers come from the existing `_get_broker()`
configuration (`ki_app_key`, `ki_app_secret_key`, `account_number`, and `.env`).
The new path uses a small Mojito subclass to bound token issuance; Mojito 0.1.6
does not provide a timeout hook. It retains inherited account setup, token
validation/loading, and the existing `token.dat` format. Existing factory callers
continue using the original Mojito class. Balance GET and token POST requests
have connect/read timeouts of 5/10 seconds, with attempts limited by
`APIConfig.MAX_RETRIES`, following this module's immediate-retry convention.

A locally unexpired cached token is bypassed once only after a confirmed HTTP
401 response or KIS's documented expired-token code `EGW00123`. The next
bounded attempt obtains a replacement using the existing token-issuance path
and retries the balance read. Transport failures and unrelated nonzero
`rt_cd` responses preserve the cache. Repeated authentication rejections do
not trigger another cache bypass or refresh cycle.

An empty, truncated, invalid-pickle, or decoded cache that is not Mojito's
expected dictionary (`access_token`, integer `timestamp`, `api_key`, and
`api_secret`) is removed once during broker construction, then retried within
the same request budget. Cache removal is refused for a symlink, non-regular,
non-owned, or hard-linked path; removal failures fail closed. Other
construction, transport, HTTP, rate-limit, and API failures do not invalidate a
valid cache.

| Result | Required output3 field | Supplied app-verified example (2026-10-14) |
| --- | --- | ---: |
| total_asset_krw | tot_asst_amt | 6,139,950 |
| stock_evaluation_krw | evlu_amt_smtl_amt | 4,537,263 |
| cash_krw | tot_dncl_amt | 358,864 |
| foreign_cash_krw | frcr_evlu_tota | 1,508,022 |
| unsettled_buy_krw | ustl_buy_amt_smtl | 264,199 |
| unsettled_sell_krw | ustl_sll_amt_smtl | 0 |

The result also contains an ISO 8601 `fetched_at_kst` timestamp with `+09:00`,
`source` (provider, endpoint, TR ID), and `query_parameters` (the four parameters
above). Account identifiers and the raw response are excluded from the result.
Amounts are floats, consistent with existing account helpers.

API success requires `rt_cd == "0"`. `output3` must be an object or a singleton
list containing an object. All six fields must be numeric and finite; missing
values never default to zero. A genuinely reported zero total is accepted,
while negative or non-finite totals raise `APIError`. Malformed successful
responses fail immediately; transport, HTTP, JSON decoding, authentication,
and unsuccessful API responses fail after bounded attempts with sanitized
diagnostics. Neither API messages nor exception payloads are logged.

`output3.tot_asst_amt` is authoritative. Component sums need not equal it:
this stage imposes no accounting formula, reconciliation adjustment, or
component sign policy.

## Manual read-only validation

From the repository root, with the existing environment configured and the
project's virtual environment activated, run exactly:

```bash
python - <<'PY'
import json
from stock_operations import APIError, fetch_overseas_portfolio_equity

try:
    equity = fetch_overseas_portfolio_equity()
except APIError as error:
    raise SystemExit(str(error)) from None
print(json.dumps(equity, ensure_ascii=False, indent=2, allow_nan=False))
PY
```

Compare `total_asset_krw` to the mobile app's total assets at the recorded time
using the same US/all-market/KRW scope. The historical example is not an
expected current account value. This command queries balance and may obtain
or cache an authentication token; it does not place orders or run the daily
workflow. Automated tests use mocked broker/HTTP responses only. Manual live
validation has not been run as part of this implementation.
