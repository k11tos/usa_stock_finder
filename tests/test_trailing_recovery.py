from __future__ import annotations

import csv
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

import sell_signals
from sell_signals import SellReason, evaluate_sell_decisions
from trailing_stop import get_observed_holding_since, reconstruct_highest_close


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


def test_latest_snapshot_without_current_symbol_is_not_guessed_as_holding_start(tmp_path):
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {"run_id": "1", "run_date": "2026-01-01", "symbol": "ABC", "quantity": 10},
            {"run_id": "2", "run_date": "2026-02-01", "symbol": "XYZ", "quantity": 1},
        ],
    )
    assert get_observed_holding_since("ABC", path) is None


def test_reconstruction_excludes_prices_before_observed_holding_start():
    finder = _finder("VMD", {"2026-06-01": 30.0, "2026-06-08": 10.10, "2026-07-14": 13.51, "2026-08-26": 9.10})
    assert reconstruct_highest_close(finder, "VMD", date(2026, 6, 8)) == 13.51


def test_vmd_missing_state_recovers_activation_and_high_then_triggers(tmp_path, caplog):
    path = tmp_path / "account_snapshots.csv"
    _write_snapshots(
        path,
        [
            {"run_id": "1", "run_date": "2026-06-08", "symbol": "VMD", "quantity": 12, "avg_price": 7.96, "current_price": 10.10},
            {"run_id": "2", "run_date": "2026-07-14", "symbol": "VMD", "quantity": 12, "avg_price": 7.96, "current_price": 13.51},
            {"run_id": "3", "run_date": "2026-08-26", "symbol": "VMD", "quantity": 12, "avg_price": 7.96, "current_price": 9.10},
        ],
    )
    finder = _finder("VMD", {"2026-06-01": 30.0, "2026-06-08": 10.10, "2026-07-14": 13.51, "2026-08-26": 9.10})
    state = {}
    observed = get_observed_holding_since("VMD", path)

    with (
        patch("sell_signals.load_trailing_state", return_value=state),
        patch("sell_signals.save_trailing_state"),
        patch("sell_signals.get_observed_holding_since", return_value=observed),
        patch("sell_signals.record_stop_loss_event"),
        patch.object(sell_signals.StrategyConfig, "TRAILING_ENABLED", True),
        patch.object(sell_signals.StrategyConfig, "TRAILING_MIN_PROFIT_PCT", 0.10),
        patch.object(sell_signals.StrategyConfig, "TRAILING_ATR_MULTIPLIER", 5.0),
        patch.object(sell_signals.StrategyConfig, "TRAILING_ATR_PERIOD", 20),
        caplog.at_level("DEBUG"),
    ):
        decisions = evaluate_sell_decisions(
            finder,
            [{"symbol": "VMD", "quantity": 12, "avg_price": 7.96, "current_price": 9.10}],
            ["VMD"], [], {"VMD": False},
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
    with patch("sell_signals.get_observed_holding_since", return_value=None), patch(
        "sell_signals.reconstruct_highest_close"
    ) as reconstruct:
        # The caller cannot reconstruct at all without a trustworthy observed boundary.
        assert sell_signals.get_observed_holding_since("VMD") is None
        reconstruct.assert_not_called()
