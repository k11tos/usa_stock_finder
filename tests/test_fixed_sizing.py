"""Offline regression coverage for issue #175; no broker or Telegram calls."""
# pylint: disable=protected-access
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import main
from config import InvestmentConfig


@pytest.fixture(autouse=True)
def offline():
    """Unexpected external reads fail immediately; all inputs are synthetic."""
    with patch.object(InvestmentConfig, "RESERVE_RATIO", 0.1), \
         patch("main.fetch_account_balance", side_effect=AssertionError("unexpected broker call")), \
         patch("main.fetch_holdings_detail", side_effect=AssertionError("unexpected holdings call")):
        yield


def plan(symbols, prices, cash, holdings=None, sale=0):
    balance = {"buyable_cash": cash, "available_cash": cash + 10000}
    with patch("main.fetch_account_balance", return_value=balance):
        return main._prepare_buy_sizing_inputs(
            symbols, SimpleNamespace(current_price=prices), sale, holdings or []
        )


@pytest.mark.parametrize("count", [1, 3, 10, 30])
@pytest.mark.parametrize("cash", [10000, 150, 50, 0])
def test_candidate_count_and_cash(count, cash):
    symbols = [f"S{i}" for i in range(count)]
    targets, quantities, _ = plan(symbols, dict.fromkeys(symbols, 30.0), cash)
    expected = min(count, int(cash * 0.9 // 90))
    assert list(quantities or {}) == symbols[:expected]
    assert list(targets or {}) == symbols[:expected]
    assert all(v == 100 for v in (targets or {}).values())
    assert all(q["shares_to_buy"] == 3 for q in (quantities or {}).values())
    assert sum(q["actual_investment"] for q in (quantities or {}).values()) <= cash * 0.9


def test_priority_skips_holdings_expensive_and_unaffordable_without_redistribution(caplog):
    symbols = ["HELD", "EXPENSIVE", "FIRST", "CANNOT", "CHEAPER", "FIRST"]
    prices = dict(zip(symbols, [10, 100.01, 30, 50, 60, 30]))
    with caplog.at_level("INFO"):
        targets, shares, _ = plan(symbols, prices, 170, [{"symbol": "HELD", "quantity": 0.5}], sale=10000)
    assert shares is not None
    assert list(targets) == ["FIRST", "CHEAPER"]
    assert shares["FIRST"]["shares_to_buy"] == 3
    assert shares["CHEAPER"]["shares_to_buy"] == 1
    assert shares["CHEAPER"]["remaining_cash"] == 3
    assert "existing holding" in caplog.text
    assert "zero whole shares" in caplog.text
    assert "exceeds remaining budget" in caplog.text
    # Tracking is not ownership; funded signals can reappear in Telegram.
    message = "\n".join(main.generate_telegram_message(["FIRST"], symbols, [], shares))
    assert message.count("신규 매수: FIRST") == 1
    assert "목표 투자금: $100.00" in message
    assert "예상 매수금액: $90.00" in message
    assert "유보금 제외): $3.00" in message
    for skipped in ["HELD", "EXPENSIVE", "CANNOT"]:
        assert f"신규 매수: {skipped}" not in message


@pytest.mark.parametrize("price,quantity", [(100, 1), (100.01, 0), (33.33, 3), (0, 0), (-1, 0),
                                         (float("nan"), 0), (float("inf"), 0)])
def test_whole_shares_and_zero_suppression(price, quantity):
    _, shares, _ = plan(["NEW"], {"NEW": price}, 1000)
    assert (shares or {}).get("NEW", {}).get("shares_to_buy", 0) == quantity
    message = main.generate_telegram_message([], ["NEW"], [], shares)
    assert bool(message) == bool(quantity)


@pytest.mark.parametrize("balance", [{}, {"available_cash": 10000}, {"buyable_cash": 0},
                                     {"buyable_cash": -1}, {"buyable_cash": float("nan")}])
def test_missing_or_invalid_confirmed_power_fails_closed(balance):
    with patch("main.fetch_account_balance", return_value=balance):
        targets, shares, _ = main._prepare_buy_sizing_inputs(
            ["NEW"], SimpleNamespace(current_price={"NEW": 10}), 10000, []
        )
    assert targets is None
    assert shares is None


def test_legacy_distribution_settings_cannot_override_fixed_target():
    with patch.object(InvestmentConfig, "DISTRIBUTION_STRATEGY", "proportional"), \
         patch.object(InvestmentConfig, "PROPORTIONAL_PERCENTAGE", 0.5), \
         patch.object(InvestmentConfig, "MIN_INVESTMENT", 1000), \
         patch.object(InvestmentConfig, "MAX_INVESTMENT", 20):
        targets, shares, _ = plan(["NEW"], {"NEW": 30}, 1000)
    assert targets == {"NEW": 100}
    assert shares is not None
    assert shares["NEW"]["actual_investment"] == 90


def test_broker_zero_buying_power_is_not_replaced_with_cash():
    import stock_operations

    broker = SimpleNamespace(fetch_present_balance=lambda: {
        "rt_cd": "0", "output2": [{"crcy_cd": "USD", "dnca_tot_amt": "1000", "ord_psbl_cash": "0"}]
    })
    with patch.object(stock_operations, "_get_broker", return_value=broker):
        balance = stock_operations.fetch_account_balance()
    assert balance["available_cash"] == 1000
    assert balance["buyable_cash"] == 0


@pytest.mark.parametrize("held_quantity", [0.5, 1, 2, 100])
def test_existing_holdings_never_topped_up_or_rebalanced(held_quantity):
    targets, shares, _ = plan(["HELD"], {"HELD": 20}, 10000,
                              [{"symbol": "HELD", "quantity": held_quantity}])
    assert targets is None
    assert shares is None


def test_empty_and_zero_quantity_maps_never_create_telegram_buy_signals():
    for shares in [None, {}, {"NEW": {"shares_to_buy": 0}}]:
        assert main.generate_telegram_message([], ["NEW"], [], shares) is None
