from __future__ import annotations

import csv
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

import sell_signals
from sell_signals import SellReason, evaluate_sell_decisions
from trailing_stop import get_observed_holding_since, reconstruct_highest_close
from trailing_stop import (
    ObservedHoldingSnapshot,
    get_observed_holding_history,
    reconstruct_activated_highest_close,
    state_matches_observed_segment,
)

HEADERS = ["run_id", "run_date", "symbol", "quantity", "avg_price", "current_price"]


def _write_snapshots(path, rows):
    with path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def _finder(symbol: str, dated_closes: dict[str, float], atr: float = 0.5):
    finder = MagicMock()
    index = pd.to_datetime(list(dated_closes))
    closes = list(dated_closes.values())
    finder.stock_data = pd.DataFrame({("Close", symbol): closes}, index=index)
    finder.current_price = {symbol: closes[-1]}
    finder.get_atr.return_value = atr
    finder.is_special_situation_price_pinned.return_value = False
    return finder


def _evaluate_recovery(
    symbol, finder, history, state, avg_price=100.0, current_price=105.0
):
    with (
        patch("sell_signals.load_trailing_state", return_value=state),
        patch("sell_signals.save_trailing_state"),
        patch("sell_signals.get_observed_holding_history", return_value=history),
        patch("sell_signals.record_stop_loss_event"),
        patch.object(sell_signals.StrategyConfig, "TRAILING_ENABLED", True),
        patch.object(sell_signals.StrategyConfig, "TRAILING_MIN_PROFIT_PCT", 0.10),
        patch.object(sell_signals.StrategyConfig, "TRAILING_ATR_MULTIPLIER", 5.0),
        patch.object(sell_signals.StrategyConfig, "TRAILING_ATR_PERIOD", 20),
    ):
        return evaluate_sell_decisions(
            finder,
            [
                {
                    "symbol": symbol,
                    "quantity": 10,
                    "avg_price": avg_price,
                    "current_price": current_price,
                }
            ],
            [symbol],
            [],
            {symbol: False},
        )


def test_observed_holding_since_uses_latest_segment_and_ignores_calendar_gaps(tmp_path):
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {"run_id": "1", "run_date": "2026-01-01", "symbol": "ABC", "quantity": 10},
            {"run_id": "2", "run_date": "2026-01-02", "symbol": "", "quantity": 0},
            # Missing calendar dates do not mean a sale; only recorded runs do.
            {"run_id": "3", "run_date": "2026-04-10", "symbol": "ABC", "quantity": 20},
            {"run_id": "4", "run_date": "2026-04-20", "symbol": "ABC", "quantity": 20},
        ],
    )
    assert get_observed_holding_since("ABC", path) == date(2026, 4, 10)


def test_latest_snapshot_without_current_symbol_is_not_guessed_as_holding_start(
    tmp_path,
):
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {"run_id": "1", "run_date": "2026-01-01", "symbol": "ABC", "quantity": 10},
            {"run_id": "2", "run_date": "2026-02-01", "symbol": "XYZ", "quantity": 1},
        ],
    )
    assert get_observed_holding_since("ABC", path) is None


def test_same_day_repurchase_has_a_distinct_run_level_segment_boundary(tmp_path):
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {"run_id": "20260827_090000", "run_date": "2026-08-27", "symbol": "REBUY", "quantity": 10},
            {"run_id": "20260827_120000", "run_date": "2026-08-27", "symbol": "", "quantity": 0},
            {"run_id": "20260827_150000", "run_date": "2026-08-27", "symbol": "REBUY", "quantity": 10},
        ],
    )

    history = get_observed_holding_history("REBUY", path)

    assert [(snapshot.run_id, snapshot.run_date) for snapshot in history] == [("20260827_150000", date(2026, 8, 27))]
    assert not state_matches_observed_segment(
        {
            "activated": True,
            "highest_close": 150.0,
            "observed_holding_since": "2026-08-27",
            "observed_holding_run_id": "20260827_090000",
        },
        history,
        "REBUY",
        path,
    )


def test_same_day_repurchase_does_not_reuse_previous_trailing_state(tmp_path):
    symbol = "REBUY"
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {"run_id": "20260827_090000", "run_date": "2026-08-27", "symbol": symbol, "quantity": 10},
            {"run_id": "20260827_120000", "run_date": "2026-08-27", "symbol": "", "quantity": 0},
            {"run_id": "20260827_150000", "run_date": "2026-08-27", "symbol": symbol, "quantity": 10},
        ],
    )
    history = get_observed_holding_history(symbol, path)
    finder = _finder(symbol, {"2026-08-27": 105.0})
    state = {
        symbol: {
            "activated": True,
            "highest_close": 150.0,
            "observed_holding_since": "2026-08-27",
            "observed_holding_run_id": "20260827_090000",
        }
    }

    decisions = _evaluate_recovery(symbol, finder, history, state, current_price=105.0)

    assert decisions[symbol].reason is SellReason.NONE
    assert "activated" not in state[symbol]
    assert "highest_close" not in state[symbol]
    finder.get_atr.assert_not_called()


def test_same_day_continuous_runs_keep_the_same_segment_identity(tmp_path):
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {"run_id": "20260827_090000", "run_date": "2026-08-27", "symbol": "KEEP", "quantity": 10},
            {"run_id": "20260827_120000", "run_date": "2026-08-27", "symbol": "KEEP", "quantity": 10},
        ],
    )

    history = get_observed_holding_history("KEEP", path)

    assert [snapshot.run_id for snapshot in history] == [
        "20260827_090000",
        "20260827_120000",
    ]
    assert state_matches_observed_segment(
        {
            "activated": True,
            "highest_close": 120.0,
            "observed_holding_since": "2026-08-27",
            "observed_holding_run_id": "20260827_090000",
        },
        history,
        "KEEP",
        path,
    )


def test_same_day_continuous_runs_recover_valid_trailing_state(tmp_path):
    symbol = "KEEP"
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {"run_id": "20260827_090000", "run_date": "2026-08-27", "symbol": symbol, "quantity": 10},
            {"run_id": "20260827_120000", "run_date": "2026-08-27", "symbol": symbol, "quantity": 10},
        ],
    )
    history = get_observed_holding_history(symbol, path)
    finder = _finder(symbol, {"2026-08-27": 105.0})
    finder.get_atr.return_value = 100.0
    state = {
        symbol: {
            "activated": True,
            "highest_close": 120.0,
            "observed_holding_since": "2026-08-27",
            "observed_holding_run_id": "20260827_090000",
        }
    }

    decisions = _evaluate_recovery(symbol, finder, history, state, current_price=105.0)

    assert decisions[symbol].reason is SellReason.NONE
    assert state[symbol]["highest_close"] == 120.0
    assert state[symbol]["observed_holding_run_id"] == "20260827_090000"
    finder.get_atr.assert_called_once()


def test_legacy_date_only_state_is_reused_only_without_same_day_ambiguity(tmp_path):
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {"run_id": "20260827_150000", "run_date": "2026-08-27", "symbol": "LEGACY", "quantity": 10},
        ],
    )
    history = get_observed_holding_history("LEGACY", path)
    assert state_matches_observed_segment({"observed_holding_since": "2026-08-27"}, history, "LEGACY", path)

    ambiguous_path = tmp_path / "ambiguous_account_snapshots.csv"
    _write_snapshots(
        ambiguous_path,
        [
            {"run_id": "20260827_090000", "run_date": "2026-08-27", "symbol": "LEGACY", "quantity": 10},
            {"run_id": "20260827_120000", "run_date": "2026-08-27", "symbol": "", "quantity": 0},
            {"run_id": "20260827_150000", "run_date": "2026-08-27", "symbol": "LEGACY", "quantity": 10},
        ],
    )
    ambiguous_history = get_observed_holding_history("LEGACY", ambiguous_path)
    assert not state_matches_observed_segment(
        {"observed_holding_since": "2026-08-27"},
        ambiguous_history,
        "LEGACY",
        ambiguous_path,
    )


def test_reconstruction_excludes_prices_before_observed_holding_start():
    finder = _finder(
        "VMD",
        {
            "2026-06-01": 30.0,
            "2026-06-08": 10.10,
            "2026-07-14": 13.51,
            "2026-08-26": 9.10,
        },
    )
    assert reconstruct_highest_close(finder, "VMD", date(2026, 6, 8)) == 13.51


def test_vmd_missing_state_recovers_activation_and_high_then_triggers(tmp_path, caplog):
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {
                "run_id": "1",
                "run_date": "2026-06-08",
                "symbol": "VMD",
                "quantity": 12,
                "avg_price": 7.96,
                "current_price": 10.10,
            },
            {
                "run_id": "2",
                "run_date": "2026-07-14",
                "symbol": "VMD",
                "quantity": 12,
                "avg_price": 7.96,
                "current_price": 13.51,
            },
            {
                "run_id": "3",
                "run_date": "2026-08-26",
                "symbol": "VMD",
                "quantity": 12,
                "avg_price": 7.96,
                "current_price": 9.10,
            },
        ],
    )
    finder = _finder(
        "VMD",
        {
            "2026-06-01": 30.0,
            "2026-06-08": 10.10,
            "2026-07-14": 13.51,
            "2026-08-26": 9.10,
        },
    )
    state = {}
    observed = get_observed_holding_since("VMD", path)
    history = get_observed_holding_history("VMD", path)

    with (
        patch("sell_signals.load_trailing_state", return_value=state),
        patch("sell_signals.save_trailing_state"),
        patch("sell_signals.get_observed_holding_history", return_value=history),
        patch("sell_signals.record_stop_loss_event"),
        patch.object(sell_signals.StrategyConfig, "TRAILING_ENABLED", True),
        patch.object(sell_signals.StrategyConfig, "TRAILING_MIN_PROFIT_PCT", 0.10),
        patch.object(sell_signals.StrategyConfig, "TRAILING_ATR_MULTIPLIER", 5.0),
        patch.object(sell_signals.StrategyConfig, "TRAILING_ATR_PERIOD", 20),
        caplog.at_level("DEBUG"),
    ):
        decisions = evaluate_sell_decisions(
            finder,
            [
                {
                    "symbol": "VMD",
                    "quantity": 12,
                    "avg_price": 7.96,
                    "current_price": 9.10,
                }
            ],
            ["VMD"],
            [],
            {"VMD": False},
        )

    assert observed == date(2026, 6, 8)  # observed start, not claimed purchase date
    assert decisions["VMD"].reason is SellReason.TRAILING
    assert "activation_source=account_snapshot_reconstruction" in caplog.text
    assert "reconstructed_highest_close=13.51" in caplog.text
    assert "effective_highest_close=13.5100" in caplog.text
    assert "triggered=True" in caplog.text


def test_no_snapshot_does_not_use_unbounded_ohlcv_history():
    finder = _finder("VMD", {"2026-06-01": 30.0, "2026-08-26": 9.10})
    assert reconstruct_highest_close(finder, "VMD", date(2026, 8, 26)) == 9.10
    assert reconstruct_activated_highest_close(finder, "VMD", [], 0.10) is None


def test_average_down_does_not_retroactively_activate_from_old_high(tmp_path):
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {
                "run_id": "1",
                "run_date": "2026-01-02",
                "symbol": "AVG",
                "quantity": 10,
                "avg_price": 100,
                "current_price": 105,
            },
            {
                "run_id": "2",
                "run_date": "2026-02-02",
                "symbol": "AVG",
                "quantity": 20,
                "avg_price": 80,
                "current_price": 85,
            },
        ],
    )
    finder = _finder("AVG", {"2026-01-02": 105, "2026-01-15": 106, "2026-02-02": 85})
    history = get_observed_holding_history("AVG", path)

    assert reconstruct_activated_highest_close(finder, "AVG", history, 0.10) is None


def test_unchanged_cost_basis_recovers_genuine_activation_between_snapshots(tmp_path):
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {
                "run_id": "1",
                "run_date": "2026-01-02",
                "symbol": "FLAT",
                "quantity": 10,
                "avg_price": 100,
            },
            {
                "run_id": "2",
                "run_date": "2026-02-02",
                "symbol": "FLAT",
                "quantity": 10,
                "avg_price": 100,
            },
        ],
    )
    finder = _finder("FLAT", {"2026-01-02": 101, "2026-01-15": 112, "2026-02-02": 108})

    assert (
        reconstruct_activated_highest_close(
            finder, "FLAT", get_observed_holding_history("FLAT", path), 0.10
        )
        == 112
    )


def test_activation_after_cost_basis_change_is_recovered(tmp_path):
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {
                "run_id": "1",
                "run_date": "2026-01-02",
                "symbol": "AVG",
                "quantity": 10,
                "avg_price": 100,
            },
            {
                "run_id": "2",
                "run_date": "2026-02-02",
                "symbol": "AVG",
                "quantity": 20,
                "avg_price": 80,
            },
        ],
    )
    finder = _finder("AVG", {"2026-01-02": 105, "2026-02-02": 90, "2026-02-10": 95})

    assert (
        reconstruct_activated_highest_close(
            finder, "AVG", get_observed_holding_history("AVG", path), 0.10
        )
        == 95
    )


def test_missing_contemporaneous_basis_does_not_activate(tmp_path):
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {
                "run_id": "1",
                "run_date": "2026-01-02",
                "symbol": "GAP",
                "quantity": 10,
                "avg_price": "",
            },
            {
                "run_id": "2",
                "run_date": "2026-02-02",
                "symbol": "GAP",
                "quantity": 20,
                "avg_price": 80,
            },
        ],
    )
    finder = _finder("GAP", {"2026-01-02": 120, "2026-02-02": 85})

    assert (
        reconstruct_activated_highest_close(
            finder, "GAP", get_observed_holding_history("GAP", path), 0.10
        )
        is None
    )


def test_repurchase_rejects_legacy_high_from_previous_holding_segment():
    symbol = "REBUY"
    history = [ObservedHoldingSnapshot(date(2026, 4, 10), 10, 100.0, "20260410_090000")]
    finder = _finder(symbol, {"2026-01-10": 150, "2026-04-10": 105})
    finder.get_atr.return_value = 100.0
    state = {
        symbol: {
            "highest_close": 150.0,
            "last_update": "2026-01-10",
            "observed_holding_since": "2026-01-01",
            "observed_holding_run_id": "20260110_090000",
        }
    }

    decisions = _evaluate_recovery(symbol, finder, history, state)

    assert decisions[symbol].reason is SellReason.NONE
    assert "activated" not in state[symbol]
    assert "highest_close" not in state[symbol]
    finder.get_atr.assert_not_called()


def test_legacy_high_with_current_segment_provenance_remains_usable():
    symbol = "CURRENT"
    history = [ObservedHoldingSnapshot(date(2026, 4, 10), 10, 100.0, "20260410_090000")]
    finder = _finder(symbol, {"2026-04-10": 105})
    finder.get_atr.return_value = 100.0
    state = {
        symbol: {
            "highest_close": 120.0,
            "last_update": "2026-04-11",
            "observed_holding_since": "2026-04-10",
            "observed_holding_run_id": "20260410_090000",
        }
    }

    _evaluate_recovery(symbol, finder, history, state)

    assert state[symbol]["activated"] is True
    assert state[symbol]["highest_close"] == 120.0


def test_persisted_activation_without_high_recovers_current_segment_maximum():
    symbol = "ACTIVE"
    history = [
        ObservedHoldingSnapshot(date(2026, 4, 10), 10, 100.0, "20260410_090000"),
        ObservedHoldingSnapshot(date(2026, 4, 20), 10, 100.0, "20260420_090000"),
    ]
    finder = _finder(symbol, {"2026-04-10": 104, "2026-04-15": 108, "2026-04-20": 105})
    finder.get_atr.return_value = 100.0
    state = {
        symbol: {
            "activated": True,
            "last_update": "2026-04-20",
            "observed_holding_since": "2026-04-10",
            "observed_holding_run_id": "20260410_090000",
        }
    }

    _evaluate_recovery(symbol, finder, history, state)

    assert state[symbol]["highest_close"] == 108.0
    assert state[symbol]["activated"] is True


def test_persisted_activation_reconstruction_excludes_old_segment_high():
    symbol = "SEGMENT"
    history = [ObservedHoldingSnapshot(date(2026, 4, 10), 10, 100.0, "20260410_090000")]
    finder = _finder(symbol, {"2026-01-10": 200, "2026-04-10": 104, "2026-04-15": 108})
    finder.get_atr.return_value = 100.0
    state = {
        symbol: {
            "activated": True,
            "last_update": "2026-04-15",
            "observed_holding_since": "2026-04-10",
            "observed_holding_run_id": "20260410_090000",
        }
    }

    _evaluate_recovery(symbol, finder, history, state, current_price=108.0)

    assert state[symbol]["highest_close"] == 108.0


def test_complete_persisted_state_with_current_provenance_is_unchanged():
    symbol = "COMPLETE"
    history = [ObservedHoldingSnapshot(date(2026, 4, 10), 10, 100.0, "20260410_090000")]
    finder = _finder(symbol, {"2026-04-10": 105})
    finder.get_atr.return_value = 100.0
    state = {
        symbol: {
            "activated": True,
            "highest_close": 120.0,
            "last_update": "2026-04-10",
            "observed_holding_since": "2026-04-10",
            "observed_holding_run_id": "20260410_090000",
        }
    }

    _evaluate_recovery(symbol, finder, history, state)

    assert state[symbol]["highest_close"] == 120.0
    assert state[symbol]["activated"] is True
