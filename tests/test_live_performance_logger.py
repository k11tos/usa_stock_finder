import csv
from pathlib import Path

from live_performance_logger import (
    ACCOUNT_SNAPSHOT_HEADERS,
    TRADE_SIGNAL_HEADERS,
    append_account_snapshots,
    append_trade_signals,
    build_account_snapshot_rows,
    build_buy_signal_rows,
    build_sell_signal_rows,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_header_creation(tmp_path):
    out_dir = tmp_path / "live"
    rows = [
        {
            "run_id": "20260101_090000",
            "run_date": "2026-01-01",
            "side": "BUY",
            "symbol": "AAPL",
            "quantity": 1,
            "price": 10,
            "amount": 10,
            "reason": "buy_signal",
            "current_quantity_before": 0,
            "quantity_after": 1,
            "source": "core_quant",
        }
    ]
    append_trade_signals(rows, output_dir=str(out_dir))
    trade_path = out_dir / "trade_signals.csv"
    with trade_path.open("r", encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    assert header == TRADE_SIGNAL_HEADERS


def test_append_behavior(tmp_path):
    out_dir = tmp_path / "live"
    row = {
        "run_id": "20260101_090000",
        "run_date": "2026-01-01",
        "side": "BUY",
        "symbol": "AAPL",
        "quantity": 1,
        "price": 10,
        "amount": 10,
        "reason": "buy_signal",
        "current_quantity_before": 0,
        "quantity_after": 1,
        "source": "core_quant",
    }
    append_trade_signals([row], output_dir=str(out_dir))
    append_trade_signals([row | {"symbol": "MSFT"}], output_dir=str(out_dir))
    data = _read_csv(out_dir / "trade_signals.csv")
    assert len(data) == 2
    assert data[0]["symbol"] == "AAPL"
    assert data[1]["symbol"] == "MSFT"


def test_buy_signal_row_mapping():
    share_quantities = {
        "AAPL": {
            "shares_to_buy": 3,
            "current_price": 101.25,
            "actual_investment": 303.75,
            "current_quantity": 2,
            "total_after_buy": 5,
        }
    }
    rows = build_buy_signal_rows("20260101_090000", "2026-01-01", share_quantities, {"AAPL": "core_quant"})
    assert rows[0]["side"] == "BUY"
    assert rows[0]["reason"] == "buy_signal"
    assert rows[0]["quantity"] == 3
    assert rows[0]["amount"] == 303.75
    assert rows[0]["current_quantity_before"] == 2
    assert rows[0]["quantity_after"] == 5


def test_sell_signal_row_mapping():
    sell_quantities = {
        "TSLA": {"shares_to_sell": 4, "current_quantity": 6, "current_price": 50.0, "sell_amount": 200.0}
    }
    rows = build_sell_signal_rows(
        "20260101_090000", "2026-01-01", sell_quantities, {"TSLA": "trend_break"}
    )
    assert rows[0]["side"] == "SELL"
    assert rows[0]["reason"] == "trend_break"
    assert rows[0]["quantity"] == 4
    assert rows[0]["amount"] == 200.0
    assert rows[0]["current_quantity_before"] == 6
    assert rows[0]["quantity_after"] == 2


def test_snapshot_row_mapping(tmp_path):
    holdings = [
        {
            "symbol": "AAPL",
            "quantity": 10,
            "avg_price": 90,
            "current_price": 100,
            "evaluation_amount": 1000,
            "profit_loss": 100,
            "profit_loss_rate": 11.11,
            "exchange": "NASDAQ",
        }
    ]
    balance = {"available_cash": 5000, "total_balance": 12000}
    rows = build_account_snapshot_rows("20260101_090000", "2026-01-01", holdings, balance)
    assert rows[0]["cash"] == 5000.0
    assert rows[0]["total_equity"] == 12000.0
    assert rows[0]["market_value"] == 1000.0

    out_dir = tmp_path / "live"
    append_account_snapshots(rows, output_dir=str(out_dir))
    path = out_dir / "account_snapshots.csv"
    with path.open("r", encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    assert header == ACCOUNT_SNAPSHOT_HEADERS
