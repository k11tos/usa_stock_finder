"""Dry-run special-situation/event-quarantine review helper.

This module is intentionally report-only. It does not execute or modify any
trading decisions, and it does not feed any review output back into buy/sell
logic.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from stock_analysis import UsaStockFinder


REASONS = {"event_quarantine", "pinned_price"}


def _parse_symbol_reason(items: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for item in items:
        if ":" in item:
            symbol, reason = item.split(":", 1)
        else:
            symbol, reason = item, "event_quarantine"
        symbol = symbol.strip().upper()
        reason = reason.strip().lower()
        if not symbol:
            raise ValueError(f"Invalid symbol entry: '{item}'")
        if reason not in REASONS:
            raise ValueError(
                f"Invalid reason '{reason}' for {symbol}. Allowed: {', '.join(sorted(REASONS))}"
            )
        parsed.append((symbol, reason))
    return parsed


def _external_review_placeholder(symbol: str) -> str:
    if os.getenv("NEWS_API_KEY"):
        return f"Optional external review can be added for {symbol} (not executed in dry-run)."
    return "No news API configured. Price-based review only."


def build_review_packet(finder: UsaStockFinder, symbol: str, reason: str) -> dict[str, Any]:
    if reason == "event_quarantine":
        metrics = finder.get_event_quarantine_metrics(symbol)
    else:
        metrics = finder.get_special_situation_price_pinned_metrics(symbol)

    return {
        "symbol": symbol,
        "price_based_reason": reason,
        "key_metrics": metrics,
        "external_review_placeholder": _external_review_placeholder(symbol),
        "decision_policy_note": "Explanation-only dry-run. Trading decisions remain price-based and deterministic.",
    }


def render_review_packets(packets: list[dict[str, Any]]) -> str:
    lines: list[str] = [
        "# Special-situation candidate dry-run review",
        "",
        "Explanation-only report. This output must not be used as a trading decision input.",
        "",
    ]
    for packet in packets:
        lines.extend(
            [
                f"## {packet['symbol']}",
                f"- Price-based reason: {packet['price_based_reason']}",
                f"- Key metrics: {json.dumps(packet['key_metrics'], sort_keys=True)}",
                f"- External review: {packet['external_review_placeholder']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate dry-run review packets for flagged symbols.")
    parser.add_argument(
        "--symbol-reason",
        nargs="+",
        required=True,
        help="Entries like 'AAPL:event_quarantine' or 'EWCZ:pinned_price'. If omitted reason, defaults to event_quarantine.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of markdown.")
    args = parser.parse_args()

    symbol_reasons = _parse_symbol_reason(args.symbol_reason)
    finder = UsaStockFinder()
    packets = [build_review_packet(finder, symbol, reason) for symbol, reason in symbol_reasons]

    if args.json:
        print(json.dumps(packets, indent=2, sort_keys=True))
    else:
        print(render_review_packets(packets), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
