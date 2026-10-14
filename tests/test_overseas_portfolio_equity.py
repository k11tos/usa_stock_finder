"""Deterministic, read-only KIS equity client regressions; no broker calls."""

from copy import deepcopy
from datetime import datetime
import pickle
import time
from unittest.mock import MagicMock

import pytest
import requests

import stock_operations
from stock_operations import APIError, fetch_overseas_portfolio_equity


ORIGINAL_GET_BROKER = stock_operations._get_broker  # pylint: disable=protected-access
AMOUNTS = {
    "tot_asst_amt": "6139950",
    "evlu_amt_smtl_amt": "4537263",
    "tot_dncl_amt": "358864",
    "frcr_evlu_tota": "1508022",
    "ustl_buy_amt_smtl": "264199",
    "ustl_sll_amt_smtl": "0",
}
QUERY = {
    "WCRC_FRCR_DVSN_CD": "01",
    "NATN_CD": "840",
    "TR_MKET_CD": "00",
    "INQR_DVSN_CD": "00",
}
PRIVATE_VALUES = ("private-token", "private-appkey", "private-secret", "12345678", "01-private")


@pytest.fixture
def equity_api(monkeypatch, tmp_path):
    """Mock authentication and every transport call, and isolate token state."""
    monkeypatch.chdir(tmp_path)
    broker = MagicMock(
        base_url="https://broker.invalid:9443",
        access_token=PRIVATE_VALUES[0],
        api_key=PRIVATE_VALUES[1],
        api_secret=PRIVATE_VALUES[2],
        acc_no_prefix=PRIVATE_VALUES[3],
        acc_no_postfix=PRIVATE_VALUES[4],
    )
    factory = MagicMock(return_value=broker)
    get = MagicMock()
    get.return_value.json.return_value = {"rt_cd": "0", "output3": deepcopy(AMOUNTS)}
    monkeypatch.setattr(stock_operations, "_get_broker", factory)
    monkeypatch.setattr(stock_operations.requests, "get", get)
    monkeypatch.setattr(stock_operations.requests, "post", MagicMock(side_effect=AssertionError("Unexpected POST")))
    monkeypatch.setattr(stock_operations.APIConfig, "MAX_RETRIES", 3)
    return factory, get, broker


@pytest.mark.parametrize("as_list", [False, True])
def test_verified_app_total_and_confirmed_request(equity_api, monkeypatch, as_list):
    factory, get, broker = equity_api
    if as_list:
        get.return_value.json.return_value["output3"] = [deepcopy(AMOUNTS)]
    clock = MagicMock()
    clock.now.return_value = datetime.fromisoformat("2026-10-14T09:30:00+09:00")
    monkeypatch.setattr(stock_operations, "datetime", clock)

    result = fetch_overseas_portfolio_equity()

    assert result == {
        "total_asset_krw": 6139950.0,
        "stock_evaluation_krw": 4537263.0,
        "cash_krw": 358864.0,
        "foreign_cash_krw": 1508022.0,
        "unsettled_buy_krw": 264199.0,
        "unsettled_sell_krw": 0.0,
        "fetched_at_kst": "2026-10-14T09:30:00+09:00",
        "source": {
            "provider": "KIS",
            "endpoint": "/uapi/overseas-stock/v1/trading/inquire-present-balance",
            "tr_id": "CTRP6504R",
        },
        "query_parameters": QUERY,
    }
    assert str(clock.now.call_args.args[0]) == "Asia/Seoul"
    factory.assert_called_once_with("나스닥", broker_class=stock_operations._EquityBroker)  # pylint: disable=protected-access
    get.assert_called_once_with(
        "https://broker.invalid:9443/uapi/overseas-stock/v1/trading/inquire-present-balance",
        headers={
            "content-type": "application/json",
            "authorization": PRIVATE_VALUES[0],
            "appKey": PRIVATE_VALUES[1],
            "appSecret": PRIVATE_VALUES[2],
            "tr_id": "CTRP6504R",
        },
        params={"CANO": PRIVATE_VALUES[3], "ACNT_PRDT_CD": PRIVATE_VALUES[4], **QUERY},
        timeout=(5, 10),
    )
    broker.fetch_present_balance.assert_not_called()
    assert broker.method_calls == []
    assert all(value not in str(result) for value in PRIVATE_VALUES)
    # The app-confirmed total is authoritative even when component sums differ.
    assert result["total_asset_krw"] != sum(result[key] for key in (
        "stock_evaluation_krw", "cash_krw", "foreign_cash_krw",
    ))


@pytest.mark.parametrize("output3", [None, {}, [], "invalid", 0, [None], [{}], [AMOUNTS, AMOUNTS]])
def test_invalid_output3_fails_without_guessing(equity_api, output3):
    _, get, _ = equity_api
    get.return_value.json.return_value["output3"] = output3
    with pytest.raises(APIError, match="output3"):
        fetch_overseas_portfolio_equity()
    assert get.call_count == 1


def test_missing_output3_fails(equity_api):
    _, get, _ = equity_api
    get.return_value.json.return_value = {"rt_cd": "0", "output2": [AMOUNTS]}
    with pytest.raises(APIError, match="output3"):
        fetch_overseas_portfolio_equity()


@pytest.mark.parametrize("payload", [None, [], "invalid", 0])
def test_invalid_top_level_response(equity_api, payload):
    _, get, _ = equity_api
    get.return_value.json.return_value = payload
    with pytest.raises(APIError, match="response shape"):
        fetch_overseas_portfolio_equity()


@pytest.mark.parametrize("status", ["1", "-1", None, 0, False])
def test_api_success_is_required_and_errors_are_sanitized(equity_api, caplog, status):
    _, get, _ = equity_api
    get.return_value.json.return_value = {
        "rt_cd": status, "msg1": " ".join(PRIVATE_VALUES), "output3": AMOUNTS,
    }
    with pytest.raises(APIError) as error:
        fetch_overseas_portfolio_equity()
    assert get.call_count == 3
    assert all(value not in str(error.value) + caplog.text for value in PRIVATE_VALUES)


@pytest.mark.parametrize("failure", [
    requests.Timeout, requests.ConnectTimeout, requests.ReadTimeout, requests.ConnectionError,
    requests.HTTPError, ValueError,
])
def test_transport_http_and_json_failures_are_bounded_and_sanitized(equity_api, caplog, failure):
    _, get, _ = equity_api
    error_message = " ".join(PRIVATE_VALUES)
    if failure is requests.HTTPError:
        get.return_value.raise_for_status.side_effect = failure(error_message)
    elif failure is ValueError:
        get.return_value.json.side_effect = failure(error_message)
    else:
        get.side_effect = failure(error_message)
    with pytest.raises(APIError) as error:
        fetch_overseas_portfolio_equity()
    assert get.call_count == 3
    assert all(call.kwargs["timeout"] == (5, 10) for call in get.call_args_list)
    assert all(value not in str(error.value) + caplog.text for value in PRIVATE_VALUES)


def test_transient_failure_recovers_without_deleting_token(equity_api, tmp_path):
    _, get, _ = equity_api
    token = tmp_path / "token.dat"
    cached = pickle.dumps({
        "access_token": "cached-token", "timestamp": int(time.time()) + 3600,
        "api_key": "cached-key", "api_secret": "cached-secret",
    })
    token.write_bytes(cached)
    response = get.return_value
    get.side_effect = [requests.Timeout("private-token"), response]
    assert fetch_overseas_portfolio_equity()["total_asset_krw"] == 6139950.0
    assert get.call_count == 2
    assert token.read_bytes() == cached


def test_api_failure_then_success(equity_api):
    _, get, _ = equity_api
    get.return_value.json.side_effect = [
        {"rt_cd": "1"}, {"rt_cd": "0", "output3": AMOUNTS},
    ]
    assert fetch_overseas_portfolio_equity()["total_asset_krw"] == 6139950.0
    assert get.call_count == 2


def test_authentication_failure_is_controlled(equity_api, caplog):
    factory, get, _ = equity_api
    factory.side_effect = RuntimeError(" ".join(PRIVATE_VALUES))
    with pytest.raises(APIError) as error:
        fetch_overseas_portfolio_equity()
    assert factory.call_count == 3
    get.assert_not_called()
    assert all(value not in str(error.value) + caplog.text for value in PRIVATE_VALUES)


@pytest.mark.parametrize("value, expected", [
    ("6,139,950", 6139950.0), (" 6139950.25 ", 6139950.25),
    (6139950, 6139950.0), (6139950.5, 6139950.5), ("6.13995e6", 6139950.0),
    ("0", 0.0), (0, 0.0), ("0.00", 0.0), ("-0", 0.0),
])
def test_numeric_parsing_including_real_zero(equity_api, value, expected):
    _, get, _ = equity_api
    get.return_value.json.return_value["output3"]["tot_asst_amt"] = value
    assert fetch_overseas_portfolio_equity()["total_asset_krw"] == expected


@pytest.mark.parametrize("value", [
    None, "", " ", "invalid", "6,13,9950", "6139950 KRW", True, False, [], {},
    "NaN", "Infinity", "-Infinity", float("nan"), float("inf"), float("-inf"), "1e9999", 10 ** 400,
    -1, "-1", "-0.01",
])
def test_invalid_total_assets_never_become_zero(equity_api, value):
    _, get, _ = equity_api
    get.return_value.json.return_value["output3"]["tot_asst_amt"] = value
    with pytest.raises(APIError):
        fetch_overseas_portfolio_equity()


@pytest.mark.parametrize("field", list(AMOUNTS))
def test_every_amount_is_required(equity_api, field):
    _, get, _ = equity_api
    aggregate = get.return_value.json.return_value["output3"]
    del aggregate[field]
    aggregate["tot_evlu_amt"] = "6139950"  # Never fall back to a different field.
    with pytest.raises(APIError, match=field):
        fetch_overseas_portfolio_equity()


@pytest.mark.parametrize("field", list(AMOUNTS)[1:])
@pytest.mark.parametrize("value", ["invalid", None, "NaN", "Infinity"])
def test_component_amounts_must_be_valid(equity_api, field, value):
    _, get, _ = equity_api
    get.return_value.json.return_value["output3"][field] = value
    with pytest.raises(APIError, match=field):
        fetch_overseas_portfolio_equity()


def test_no_accounting_formula_or_component_sign_policy(equity_api):
    _, get, _ = equity_api
    get.return_value.json.return_value["output3"]["tot_dncl_amt"] = "-100.5"
    result = fetch_overseas_portfolio_equity()
    assert result["cash_krw"] == -100.5
    assert result["total_asset_krw"] == 6139950.0


def test_invalid_field_does_not_expose_raw_response(equity_api, caplog):
    _, get, _ = equity_api
    get.return_value.json.return_value["output3"]["tot_asst_amt"] = " ".join(PRIVATE_VALUES)
    with pytest.raises(APIError) as error:
        fetch_overseas_portfolio_equity()
    assert all(value not in str(error.value) + caplog.text for value in PRIVATE_VALUES)


def test_default_factory_retains_original_mojito(equity_api, monkeypatch):
    factory, _, _ = equity_api
    monkeypatch.setenv("ki_app_key", "configured-key")
    monkeypatch.setenv("ki_app_secret_key", "configured-secret")
    monkeypatch.setenv("account_number", "12345678-01")
    constructor = MagicMock(return_value=factory.return_value)
    monkeypatch.setattr(stock_operations.mojito, "KoreaInvestment", constructor)
    monkeypatch.setattr(stock_operations, "load_dotenv", MagicMock())
    assert ORIGINAL_GET_BROKER("뉴욕") is constructor.return_value
    constructor.assert_called_once_with(
        api_key="configured-key", api_secret="configured-secret", acc_no="12345678-01", exchange="뉴욕",
    )


def test_existing_authentication_configuration_is_reused(equity_api, monkeypatch):
    factory, _, _ = equity_api
    monkeypatch.setattr(stock_operations, "_get_broker", ORIGINAL_GET_BROKER)
    # Exercise the actual factory without invoking Mojito authentication/network.
    monkeypatch.setenv("ki_app_key", "configured-key")
    monkeypatch.setenv("ki_app_secret_key", "configured-secret")
    monkeypatch.setenv("account_number", "12345678-01")
    constructor = MagicMock(return_value=factory.return_value)
    monkeypatch.setattr(stock_operations, "_EquityBroker", constructor)
    dotenv = MagicMock()
    monkeypatch.setattr(stock_operations, "load_dotenv", dotenv)
    assert fetch_overseas_portfolio_equity()["total_asset_krw"] == 6139950.0
    dotenv.assert_called_once_with()
    constructor.assert_called_once_with(
        api_key="configured-key", api_secret="configured-secret", acc_no="12345678-01", exchange="나스닥",
    )


def test_token_issuance_is_bounded_and_cache_is_reused(equity_api, monkeypatch):
    """Run inherited Mojito auth with mocked token transport and a temporary cache."""
    monkeypatch.setattr(stock_operations, "_get_broker", ORIGINAL_GET_BROKER)
    monkeypatch.setenv("ki_app_key", "configured-key")
    monkeypatch.setenv("ki_app_secret_key", "configured-secret")
    monkeypatch.setenv("account_number", "12345678-01")
    monkeypatch.setattr(stock_operations, "load_dotenv", MagicMock())
    post = MagicMock()
    post.return_value.json.return_value = {"access_token": "mock-token", "expires_in": 86400}
    monkeypatch.setattr(stock_operations.requests, "post", post)

    assert fetch_overseas_portfolio_equity()["total_asset_krw"] == 6139950.0
    post.assert_called_once_with(
        "https://openapi.koreainvestment.com:9443/oauth2/tokenP",
        headers={"content-type": "application/json"},
        json={"grant_type": "client_credentials", "appkey": "configured-key", "appsecret": "configured-secret"},
        timeout=(5, 10),
    )
    post.return_value.raise_for_status.assert_called_once_with()
    # The next invocation must load the standard Mojito cache without another POST.
    assert fetch_overseas_portfolio_equity()["total_asset_krw"] == 6139950.0
    assert post.call_count == 1
    _, get, _ = equity_api
    assert get.call_args.kwargs["headers"]["authorization"] == "Bearer mock-token"


def test_token_timeout_is_bounded_and_sanitized(equity_api, monkeypatch, caplog):
    monkeypatch.setattr(stock_operations, "_get_broker", ORIGINAL_GET_BROKER)
    monkeypatch.setenv("ki_app_key", "configured-key")
    monkeypatch.setenv("ki_app_secret_key", "configured-secret")
    monkeypatch.setenv("account_number", "12345678-01")
    monkeypatch.setattr(stock_operations, "load_dotenv", MagicMock())
    post = MagicMock(side_effect=requests.Timeout(" ".join(PRIVATE_VALUES)))
    monkeypatch.setattr(stock_operations.requests, "post", post)
    with pytest.raises(APIError) as error:
        fetch_overseas_portfolio_equity()
    assert post.call_count == 3
    assert all(call.kwargs["timeout"] == (5, 10) for call in post.call_args_list)
    assert all(value not in str(error.value) + caplog.text for value in PRIVATE_VALUES)
    _, get, _ = equity_api
    get.assert_not_called()



AUTH_PRIVATE_VALUES = ("old-token", "fresh-token", "private-app-key", "private-secret", "12345678", "01")


def _authentication_response(payload=None, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload or {"rt_cd": "0", "output3": deepcopy(AMOUNTS)}
    return response


@pytest.fixture
def cached_equity_client(monkeypatch, tmp_path):
    """Use Mojito's real cache loader while mocking every HTTP request."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stock_operations, "_get_broker", ORIGINAL_GET_BROKER)
    monkeypatch.setenv("ki_app_key", AUTH_PRIVATE_VALUES[2])
    monkeypatch.setenv("ki_app_secret_key", AUTH_PRIVATE_VALUES[3])
    monkeypatch.setenv("account_number", f"{AUTH_PRIVATE_VALUES[4]}-{AUTH_PRIVATE_VALUES[5]}")
    monkeypatch.setattr(stock_operations, "load_dotenv", MagicMock())
    monkeypatch.setattr(stock_operations.APIConfig, "MAX_RETRIES", 3)
    with open("token.dat", "wb") as token_file:
        pickle.dump({
            "access_token": AUTH_PRIVATE_VALUES[0], "timestamp": int(time.time()) + 3600,
            "api_key": AUTH_PRIVATE_VALUES[2], "api_secret": AUTH_PRIVATE_VALUES[3],
        }, token_file)
    get = MagicMock()
    post = MagicMock()
    post.return_value = _authentication_response({"access_token": AUTH_PRIVATE_VALUES[1], "expires_in": 3600})
    monkeypatch.setattr(stock_operations.requests, "get", get)
    monkeypatch.setattr(stock_operations.requests, "post", post)
    return get, post, tmp_path / "token.dat"


def test_http_401_rejected_cached_token_refreshes_once_and_recovers(cached_equity_client):
    get, post, token_path = cached_equity_client
    get.side_effect = [_authentication_response(status_code=401), _authentication_response()]

    assert fetch_overseas_portfolio_equity()["total_asset_krw"] == 6139950.0

    assert [call.kwargs["headers"]["authorization"] for call in get.call_args_list] == [
        f"Bearer {AUTH_PRIVATE_VALUES[0]}", f"Bearer {AUTH_PRIVATE_VALUES[1]}",
    ]
    post.assert_called_once()
    with open(token_path, "rb") as token_file:
        assert pickle.load(token_file)["access_token"] == AUTH_PRIVATE_VALUES[1]


def test_documented_kis_token_rejection_refreshes_and_recovers(cached_equity_client):
    get, post, _ = cached_equity_client
    get.side_effect = [
        _authentication_response({"rt_cd": "1", "msg_cd": "EGW00123"}),
        _authentication_response(),
    ]

    assert fetch_overseas_portfolio_equity()["cash_krw"] == 358864.0
    assert get.call_count == 2
    post.assert_called_once()


def test_transient_failure_retains_cached_token_without_post(cached_equity_client):
    get, post, token_path = cached_equity_client
    cached = token_path.read_bytes()
    get.side_effect = [requests.Timeout(AUTH_PRIVATE_VALUES[0]), _authentication_response()]

    assert fetch_overseas_portfolio_equity()["total_asset_krw"] == 6139950.0
    post.assert_not_called()
    assert token_path.read_bytes() == cached


def test_unrelated_kis_api_error_does_not_refresh_token(cached_equity_client):
    get, post, token_path = cached_equity_client
    cached = token_path.read_bytes()
    get.return_value = _authentication_response({"rt_cd": "1", "msg_cd": "EGW99999"})

    with pytest.raises(APIError):
        fetch_overseas_portfolio_equity()
    assert get.call_count == 3
    post.assert_not_called()
    assert token_path.read_bytes() == cached


def test_repeated_authentication_rejection_uses_one_cache_bypass(cached_equity_client):
    get, post, _ = cached_equity_client
    get.side_effect = [
        _authentication_response(status_code=401),
        _authentication_response(status_code=401),
        _authentication_response(status_code=401),
    ]

    with pytest.raises(APIError):
        fetch_overseas_portfolio_equity()
    assert get.call_count == 3
    post.assert_called_once()


def test_token_refresh_failure_is_bounded_and_sanitized(cached_equity_client, caplog):
    get, post, _ = cached_equity_client
    secret_text = " ".join(AUTH_PRIVATE_VALUES)
    get.side_effect = [_authentication_response(status_code=401)]
    post.side_effect = requests.Timeout(secret_text)

    with pytest.raises(APIError) as error:
        fetch_overseas_portfolio_equity()
    assert post.call_count == 2
    assert all(value not in str(error.value) + caplog.text for value in AUTH_PRIVATE_VALUES)


def test_valid_cached_token_is_reused_without_token_post(cached_equity_client):
    get, post, _ = cached_equity_client
    get.return_value = _authentication_response()

    assert fetch_overseas_portfolio_equity()["total_asset_krw"] == 6139950.0
    post.assert_not_called()


@pytest.mark.parametrize(
    "malformed_cache",
    [b"", pickle.dumps({"access_token": "partial"})[:-1]],
    ids=["empty", "truncated"],
)
def test_malformed_token_cache_is_replaced_with_a_fresh_token(
    cached_equity_client, malformed_cache,
):
    get, post, token_path = cached_equity_client
    unrelated_file = token_path.with_name("unrelated.txt")
    unrelated_file.write_text("must remain", encoding="utf-8")
    token_path.write_bytes(malformed_cache)
    get.return_value = _authentication_response()

    assert fetch_overseas_portfolio_equity()["total_asset_krw"] == 6139950.0

    post.assert_called_once()
    assert get.call_count == 1
    assert unrelated_file.read_text(encoding="utf-8") == "must remain"
    with open(token_path, "rb") as token_file:
        assert pickle.load(token_file)["access_token"] == AUTH_PRIVATE_VALUES[1]


def test_invalid_pickle_token_cache_is_replaced_with_a_fresh_token(cached_equity_client):
    get, post, token_path = cached_equity_client
    token_path.write_bytes(b"not a pickle")
    get.return_value = _authentication_response()

    assert fetch_overseas_portfolio_equity()["cash_krw"] == 358864.0

    post.assert_called_once()
    assert get.call_count == 1
    with open(token_path, "rb") as token_file:
        assert pickle.load(token_file)["access_token"] == AUTH_PRIVATE_VALUES[1]


@pytest.mark.parametrize(
    "malformed_cache",
    [
        {},
        {"access_token": AUTH_PRIVATE_VALUES[0], "timestamp": int(time.time()) + 3600,
         "api_key": AUTH_PRIVATE_VALUES[2]},
        {"timestamp": int(time.time()) + 3600, "api_key": AUTH_PRIVATE_VALUES[2],
         "api_secret": AUTH_PRIVATE_VALUES[3]},
        None,
        [],
        {"access_token": AUTH_PRIVATE_VALUES[0], "timestamp": "future",
         "api_key": AUTH_PRIVATE_VALUES[2], "api_secret": AUTH_PRIVATE_VALUES[3]},
    ],
    ids=["empty-dict", "missing-check-key", "missing-load-key", "none", "list", "invalid-timestamp"],
)
def test_decoded_malformed_token_cache_is_replaced_with_a_fresh_token(
    cached_equity_client, malformed_cache,
):
    get, post, token_path = cached_equity_client
    token_path.write_bytes(pickle.dumps(malformed_cache))
    get.return_value = _authentication_response()

    assert fetch_overseas_portfolio_equity()["total_asset_krw"] == 6139950.0

    post.assert_called_once()
    assert get.call_count == 1
    with open(token_path, "rb") as token_file:
        assert pickle.load(token_file)["access_token"] == AUTH_PRIVATE_VALUES[1]


@pytest.mark.parametrize("broker_error", [KeyError, TypeError])
def test_unrelated_broker_schema_errors_do_not_invalidate_token_cache(
    cached_equity_client, monkeypatch, broker_error,
):
    get, post, token_path = cached_equity_client
    cached = token_path.read_bytes()
    factory = MagicMock(side_effect=broker_error("unrelated"))
    remove = MagicMock(wraps=stock_operations.os.remove)
    monkeypatch.setattr(stock_operations, "_get_broker", factory)
    monkeypatch.setattr(stock_operations.os, "remove", remove)

    with pytest.raises(APIError):
        fetch_overseas_portfolio_equity()

    assert factory.call_count == 3
    remove.assert_not_called()
    post.assert_not_called()
    get.assert_not_called()
    assert token_path.read_bytes() == cached


def test_malformed_token_cache_removal_failure_fails_closed(cached_equity_client, monkeypatch):
    get, post, token_path = cached_equity_client
    token_path.write_bytes(b"")
    monkeypatch.setattr(stock_operations.os, "remove", MagicMock(side_effect=PermissionError))

    with pytest.raises(APIError, match="Unable to refresh overseas equity authentication"):
        fetch_overseas_portfolio_equity()

    post.assert_not_called()
    get.assert_not_called()
    assert token_path.read_bytes() == b""


def test_malformed_symlink_cache_fails_closed_without_deleting_its_target(cached_equity_client):
    get, post, token_path = cached_equity_client
    unrelated_file = token_path.with_name("unrelated.txt")
    unrelated_file.write_bytes(b"not a pickle")
    token_path.unlink()
    token_path.symlink_to(unrelated_file)

    with pytest.raises(APIError, match="Unable to refresh overseas equity authentication"):
        fetch_overseas_portfolio_equity()

    post.assert_not_called()
    get.assert_not_called()
    assert token_path.is_symlink()
    assert unrelated_file.read_bytes() == b"not a pickle"


def test_malformed_cache_recovery_uses_only_the_remaining_retry_budget(cached_equity_client):
    get, post, token_path = cached_equity_client
    token_path.write_bytes(b"not a pickle")
    post.side_effect = requests.Timeout("private-token")

    with pytest.raises(APIError):
        fetch_overseas_portfolio_equity()

    assert post.call_count == 2
    get.assert_not_called()


def test_output3_total_and_legacy_factory_behavior_remain_unchanged(cached_equity_client, monkeypatch):
    get, post, _ = cached_equity_client
    get.return_value = _authentication_response({"rt_cd": "0", "output3": [deepcopy(AMOUNTS)]})

    result = fetch_overseas_portfolio_equity()

    assert result["total_asset_krw"] == 6139950.0
    assert result["stock_evaluation_krw"] == 4537263.0
    post.assert_not_called()
    constructor = MagicMock()
    monkeypatch.setattr(stock_operations.mojito, "KoreaInvestment", constructor)
    stock_operations._get_broker("뉴욕")  # pylint: disable=protected-access
    constructor.assert_called_once_with(
        api_key=AUTH_PRIVATE_VALUES[2], api_secret=AUTH_PRIVATE_VALUES[3],
        acc_no=f"{AUTH_PRIVATE_VALUES[4]}-{AUTH_PRIVATE_VALUES[5]}", exchange="뉴욕",
    )
