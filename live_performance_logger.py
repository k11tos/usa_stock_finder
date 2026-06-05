"""Utilities for append-only live-operation CSV logging."""

from __future__ import annotations

from csv import DictWriter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

TRADE_SIGNAL_HEADERS = [
    "run_id",
    "run_date",
    "side",
    "symbol",
    "quantity",
    "price",
    "amount",
    "reason",
    "current_quantity_before",
    "quantity_after",
    "source",
]

ACCOUNT_SNAPSHOT_HEADERS = [
    "run_id",
    "run_date",
    "symbol",
    "quantity",
    "avg_price",
    "current_price",
    "market_value",
    "profit_loss",
    "profit_loss_rate",
    "exchange",
    # Legacy columns retained as USD aliases for existing report readers.
    "cash",
    "total_equity",
    # Explicit post-migration columns.
    "cash_usd",
    "market_value_usd",
    "total_equity_usd",
    "cash_krw",
    "broker_total_asset_krw",
    "exchange_rate_krw_per_usd",
    "broker_raw_total_balance",
]


def generate_run_metadata(now: datetime | None = None) -> tuple[str, str]:
    """Generate deterministic run metadata in KST for one runtime execution."""
    current = now.astimezone(KST) if now else datetime.now(KST)
    return current.strftime("%Y%m%d_%H%M%S"), current.strftime("%Y-%m-%d")


def _append_rows(csv_path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as file_obj:
        writer = DictWriter(file_obj, fieldnames=headers)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def build_buy_signal_rows(
    run_id: str,
    run_date: str,
    share_quantities: dict[str, dict[str, Any]] | None,
    source_pool_by_symbol: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not share_quantities:
        return []

    rows: list[dict[str, Any]] = []
    for symbol, info in share_quantities.items():
        quantity = int(info.get("shares_to_buy", 0) or 0)
        price = float(info.get("current_price", 0.0) or 0.0)
        amount = float(info.get("actual_investment", quantity * price) or 0.0)
        current_before = int(info.get("current_quantity", 0) or 0)
        quantity_after = int(info.get("total_after_buy", current_before + quantity) or 0)
        rows.append(
            {
                "run_id": run_id,
                "run_date": run_date,
                "side": "BUY",
                "symbol": symbol,
                "quantity": quantity,
                "price": round(price, 4),
                "amount": round(amount, 2),
                "reason": "buy_signal",
                "current_quantity_before": current_before,
                "quantity_after": quantity_after,
                "source": (source_pool_by_symbol or {}).get(symbol, "unknown"),
            }
        )
    return rows


def build_sell_signal_rows(
    run_id: str,
    run_date: str,
    sell_quantities: dict[str, dict[str, Any]] | None,
    sell_reasons: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not sell_quantities:
        return []

    rows: list[dict[str, Any]] = []
    for symbol, info in sell_quantities.items():
        quantity = int(info.get("shares_to_sell", 0) or 0)
        before_qty = int(info.get("current_quantity", 0) or 0)
        price = float(info.get("current_price", 0.0) or 0.0)
        amount = float(info.get("sell_amount", quantity * price) or 0.0)
        rows.append(
            {
                "run_id": run_id,
                "run_date": run_date,
                "side": "SELL",
                "symbol": symbol,
                "quantity": quantity,
                "price": round(price, 4),
                "amount": round(amount, 2),
                "reason": (sell_reasons or {}).get(symbol, "sell_signal"),
                "current_quantity_before": before_qty,
                "quantity_after": max(before_qty - quantity, 0),
                "source": "runtime",
            }
        )
    return rows


def build_account_snapshot_rows(
    run_id: str,
    run_date: str,
    holdings_detail: list[dict[str, Any]] | None,
    account_balance: dict[str, float] | None,
) -> list[dict[str, Any]]:
    holdings = holdings_detail or []
    balance = account_balance or {}
    cash_usd = float(balance.get("available_cash_usd", balance.get("available_cash", 0.0)) or 0.0)
    total_equity_usd = float(balance.get("total_equity_usd", balance.get("total_balance", cash_usd)) or 0.0)
    account_market_value_usd = float(balance.get("holdings_market_value_usd", 0.0) or 0.0)
    cash_krw = float(balance.get("currency_cash_krw", 0.0) or 0.0)
    broker_total_asset_krw = float(balance.get("broker_total_asset_krw", 0.0) or 0.0)
    exchange_rate = float(balance.get("exchange_rate_krw_per_usd", 0.0) or 0.0)
    broker_raw_total_balance = float(balance.get("broker_raw_output2_frcr_evlu_amt2", 0.0) or 0.0)

    rows: list[dict[str, Any]] = []

    def base_row(market_value_usd: float) -> dict[str, Any]:
        return {
            "cash": cash_usd,
            "total_equity": total_equity_usd,
            "cash_usd": cash_usd,
            "market_value_usd": market_value_usd,
            "total_equity_usd": total_equity_usd,
            "cash_krw": cash_krw,
            "broker_total_asset_krw": broker_total_asset_krw,
            "exchange_rate_krw_per_usd": exchange_rate,
            "broker_raw_total_balance": broker_raw_total_balance,
        }

    if not holdings:
        return [
            {
                "run_id": run_id,
                "run_date": run_date,
                "symbol": "",
                "quantity": 0.0,
                "avg_price": 0.0,
                "current_price": 0.0,
                "market_value": 0.0,
                "profit_loss": 0.0,
                "profit_loss_rate": 0.0,
                "exchange": "",
                **base_row(account_market_value_usd),
            }
        ]

    for holding in holdings:
        market_value_usd = float(holding.get("evaluation_amount", 0.0) or 0.0)
        rows.append(
            {
                "run_id": run_id,
                "run_date": run_date,
                "symbol": holding.get("symbol", ""),
                "quantity": float(holding.get("quantity", 0.0) or 0.0),
                "avg_price": float(holding.get("avg_price", 0.0) or 0.0),
                "current_price": float(holding.get("current_price", 0.0) or 0.0),
                "market_value": market_value_usd,
                "profit_loss": float(holding.get("profit_loss", 0.0) or 0.0),
                "profit_loss_rate": float(holding.get("profit_loss_rate", 0.0) or 0.0),
                "exchange": holding.get("exchange", ""),
                **base_row(market_value_usd),
            }
        )
    return rows

def append_trade_signals(rows: list[dict[str, Any]], output_dir: str = "data/live") -> None:
    _append_rows(Path(output_dir) / "trade_signals.csv", TRADE_SIGNAL_HEADERS, rows)


def append_account_snapshots(rows: list[dict[str, Any]], output_dir: str = "data/live") -> None:
    _append_rows(Path(output_dir) / "account_snapshots.csv", ACCOUNT_SNAPSHOT_HEADERS, rows)
