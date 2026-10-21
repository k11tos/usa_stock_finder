"""Offline Stage D signal/cash-capacity replay, never a portfolio simulator.

Uses the live analysis/selection functions on explicitly cut off local bars.
Independent daily account observations are shared across all four arms. They
cannot establish counterfactual holdings, exits, returns, or realized cash days.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR
import json
import math
import os
from pathlib import Path
import shutil
import tempfile

import numpy as np
import pandas as pd

from config import StrategyConfig
from main import (
    _filter_buy_candidates_by_event_quarantine,
    _filter_buy_candidates_by_special_situation,
    calculate_correlations,
    is_tradable_common_stock,
    select_stocks,
)
from stock_analysis import UsaStockFinder
from stop_loss_cooldown import calculate_cooldown_days

CAPS = (0, 30, 50, 100)
SOURCES = ("core_quant", "trend_expansion")
PERFORMANCE_KEYS = (
    "total_return", "cagr", "max_drawdown", "volatility", "turnover", "trade_count",
    "hit_rate", "portfolio_concentration", "spy_return", "iwm_return",
)
LIMITATIONS = [
    "Capacity diagnostics only; independent daily states are not a counterfactual portfolio.",
    "No simulated or executed positions, exits, reinvestment, B-plan, or realized cash-day improvement.",
    "Performance NOT COMPARABLE: sell/holding/corporate-action history and deployed sizing are unverified.",
    "Stage C reviewed artifacts and real multi-quarter Quantus history are prerequisites for evidence review.",
    "Current listings or current metadata cannot reconstruct delisted or historical constituents.",
]


def _timestamp(value: str) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if pd.isna(parsed) or parsed.tzinfo is None:
        raise ValueError("Timestamps must have explicit time zones.")
    return parsed.tz_convert("UTC")


def _quarter(value: str | pd.Timestamp) -> pd.Period:
    return pd.Timestamp(value).tz_localize(None).to_period("Q")


def _number(value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a numeric observation.")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0 or (positive and parsed == 0):
        raise ValueError("Expected a finite nonnegative number.")
    return parsed


def _symbols(values: list[str]) -> list[str]:
    normalized = [str(value).strip().upper().replace(".", "-") for value in values]
    if any(not value or value == "NONE" for value in normalized):
        raise ValueError("Empty/invalid symbol.")
    return sorted(set(normalized))


def build_cohort(core: list[str], expansion: list[dict], cap: int, target: int = 100) -> dict:
    """Core priority; rank is the frozen Stage C order, never a daily buy gate."""
    if cap not in CAPS:
        raise ValueError("Research caps are 0, 30, 50, 100.")
    core_symbols = _symbols(core)
    ranked = sorted(expansion, key=lambda row: (_number(row["rank"], positive=True), row["symbol"]))
    seen = set(core_symbols)
    selected = []
    overlap = set()
    for row in ranked:
        symbol = _symbols([row["symbol"]])[0]
        if symbol in core_symbols:
            overlap.add(symbol)
        if symbol in seen:
            continue
        seen.add(symbol)
        if row.get("verification") != "verified_common_equity":
            raise ValueError("Unverified expansion finalist: " + symbol)
        selected.append(symbol)
    selected = selected[:min(max(target - len(core_symbols), 0), cap)]
    return {
        "core_count": len(core_symbols), "expansion_count": len(selected),
        "overlap": len(overlap), "watch_names": core_symbols + selected,
        "source_by_symbol": {**dict.fromkeys(core_symbols, SOURCES[0]), **dict.fromkeys(selected, SOURCES[1])},
    }


def fixed_dollar_capacity(signals: list[dict], state: dict, assumptions: dict) -> dict:
    """One-day whole-share hypothetical allocation; no buys persist to another day.

    Target includes fees; partial targets are allowed when available cash is
    below $100, if at least one whole share fits. Reserve is frozen at the day's
    starting cash * reserve_ratio. Core first, then original Stage C rank order.
    """
    cash = Decimal(str(_number(state["cash"])))
    holdings_value = Decimal(str(_number(state["holdings_value"])))
    reserve_ratio = Decimal(str(_number(assumptions["reserve_ratio"])))
    if reserve_ratio > 1:
        raise ValueError("reserve_ratio must be in [0, 1].")
    target = Decimal("100")
    fee = Decimal(str(_number(assumptions["fee_per_order"])))
    slip = Decimal(str(_number(assumptions["slippage_bps"]))) / 10000
    reserve = cash * reserve_ratio
    available = cash - reserve
    allocations = []
    held = set(_symbols(state["held_symbols"]))
    seen = set()
    affordable = 0
    for signal in signals:
        symbol = signal["symbol"]
        item = {**signal, "quantity": 0, "dollars": 0.0, "capacity_reason": ""}
        if symbol in held or symbol in seen:
            item["capacity_reason"] = "existing_holding_or_duplicate"
        else:
            seen.add(symbol)
            try:
                price = Decimal(str(_number(signal["price"], positive=True))) * (1 + slip)
                if price + fee > target:
                    item["capacity_reason"] = "whole_share_exceeds_target"
                else:
                    affordable += 1  # affordability under target before competition for cash
                    budget = min(target, available)
                    quantity = max(0, int(((budget - fee) / price).to_integral_value(rounding=ROUND_FLOOR)))
                    if quantity:
                        cost = quantity * price + fee
                        available -= cost
                        item.update(quantity=quantity, dollars=float(cost))
                    else:
                        item["capacity_reason"] = "reserve_or_cash_constraint"
            except (ValueError, TypeError):
                item["capacity_reason"] = "invalid_execution_price"
        allocations.append(item)
    invested = sum(Decimal(str(row["dollars"])) for row in allocations)
    remaining = cash - invested
    equity = cash + holdings_value
    # This is a capacity cash ratio at cost, not marked-to-market performance.
    return {
        "allocations": allocations, "target_affordable_entries": affordable,
        "affordable_new_entries": sum(row["quantity"] > 0 for row in allocations),
        "capacity_entries": sum(row["quantity"] > 0 for row in allocations),
        "hypothetical_dollars_invested": float(invested), "cash_before": float(cash),
        "capacity_cash_dollars": float(remaining),
        "capacity_cash_ratio": float(remaining / equity) if equity else None,
        "intended_reserve_dollars": float(reserve),
        "unallocated_nonreserve_cash": float(remaining - reserve),
        "signal_capacity_gap_dollars": float(max(Decimal(0), cash - reserve - target * affordable)),
        "rounding_or_price_constraint_dollars": float(
            remaining - reserve - max(Decimal(0), cash - reserve - target * affordable)),
        "cash_constrained_signals": sum(row["capacity_reason"] == "reserve_or_cash_constraint"
                                        for row in allocations),
        "signal_scarcity": not signals,
        "new_positions": None, "actual_dollars_invested": None,
    }


def _offline_finder(bars: list[dict], symbol: str, session: dict) -> tuple[UsaStockFinder | None, str]:
    # pylint: disable=too-many-return-statements
    cutoff = _timestamp(session["signal_at"])
    bar_day = date.fromisoformat(session["bar_date"])
    if bar_day >= cutoff.date():
        return None, "bar_not_complete_before_signal"
    if (cutoff.date() - bar_day).days > 4:
        return None, "stale_signal_session"
    try:
        selected = [row for row in bars if row["symbol"] == symbol
                    and date.fromisoformat(row["date"]) <= bar_day
                    and _timestamp(row["available_at"]) <= cutoff]
    except (ValueError, TypeError, KeyError):
        return None, "invalid_bar_date_or_availability"
    if not selected:
        return None, "missing_ohlcv"
    if any(row.get("error") for row in selected):
        return None, "ohlcv_api_error"
    if any(_timestamp(row["available_at"]) < pd.Timestamp(
            row["date"] + "T16:00:00", tz="America/New_York").tz_convert("UTC") for row in selected):
        return None, "observation_before_bar_close"
    frame = pd.DataFrame(selected).sort_values("date")
    if frame["date"].duplicated().any():
        return None, "duplicate_bar"
    if frame.iloc[-1]["date"] != session["bar_date"]:
        return None, "stale_ohlcv"
    # Match live's trailing one-calendar-year input. The 252-bar admission
    # hypothesis belongs to Stage C, not the daily template.
    frame = frame.loc[frame["date"] > (bar_day - timedelta(days=365)).isoformat()]
    columns = ["open", "high", "low", "close", "volume"]
    if any(name not in frame for name in columns):
        return None, "invalid_ohlcv"
    if any(isinstance(value, (bool, np.bool_)) for value in frame[columns].to_numpy(dtype=object).flat):
        return None, "invalid_ohlcv"
    numeric = frame[columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy()).all() or (numeric <= 0).any().any():
        return None, "invalid_ohlcv"
    if ((numeric["high"] < numeric[["open", "close", "low"]].max(axis=1))
            | (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1))).any():
        return None, "invalid_ohlc_range"
    if len(frame) < StrategyConfig.MA_200_DAYS + StrategyConfig.MA_INCREASE_CHECK_DAYS - 1:
        return None, "insufficient_history"
    if pd.to_datetime(frame["date"]).diff().dt.days.gt(4).any():
        return None, "history_gap_or_suspension"
    numeric.index = pd.to_datetime(frame["date"])
    numeric.columns = [name.title() for name in columns]
    finder = UsaStockFinder.__new__(UsaStockFinder)  # deliberately bypass the downloading constructor
    finder.symbols = [symbol]
    finder.stock_data = pd.concat({name: numeric[[name]].rename(columns={name: symbol})
                                   for name in numeric.columns}, axis=1)
    finder.current_price = {symbol: float(numeric["Close"].iloc[-1])}
    finder.last_high = {symbol: float(numeric["High"].max())}
    finder.last_low = {symbol: float(numeric["Low"].min())}
    return finder, ""


def evaluate_daily_symbol(bundle: dict, symbol: str, session: dict) -> dict:  # pylint: disable=too-many-return-statements
    """The same live daily rules for either source; no source-specific weakening."""
    result = {'symbol': symbol, 'trend_ok': False, 'correlation_ok': False, 'safety_survivor': False,
                  'new_buy_signal': False, 'price': None, 'reason': ""}
    cutoff = _timestamp(session["signal_at"])
    metadata = [row for row in bundle["metadata"] if row["symbol"] == symbol
                and _timestamp(row["available_at"]) <= cutoff
                and _timestamp(row["asof_at"]) <= cutoff]
    if not metadata:
        return {**result, "reason": "missing_asof_metadata"}
    latest = max(metadata, key=lambda row: _timestamp(row["asof_at"]))
    if latest.get("error"):
        return {**result, "reason": "metadata_api_error"}
    if (cutoff - _timestamp(latest["asof_at"])).days > 7:
        return {**result, "reason": "stale_metadata"}
    allowed, reason = is_tradable_common_stock(latest["values"])
    if not allowed:
        return {**result, "reason": reason}
    finder, reason = _offline_finder(bundle["bars"], symbol, session)
    if finder is None:
        return {**result, "reason": reason}
    trend = finder.has_valid_trend_template(StrategyConfig.MARGIN)[symbol]
    correlation = calculate_correlations(finder)
    buys, _ = select_stocks(finder, correlation)
    result.update(trend_ok=bool(trend), correlation_ok=symbol in buys,
                  price=finder.current_price[symbol])
    if not trend:
        return {**result, "reason": "trend_failed"}
    if not buys:
        return {**result, "reason": "correlation_failed"}
    state = session["state"]
    if state.get("cooldown_complete") is not True:
        return {**result, "reason": "missing_cooldown_state"}
    losses = [row for row in state["stop_losses"] if row["symbol"] == symbol
              and date.fromisoformat(row["date"]) <= cutoff.date()]
    if losses:
        last = max(losses, key=lambda row: row["date"])
        elapsed = (cutoff.date() - date.fromisoformat(last["date"])).days
        if elapsed < calculate_cooldown_days(last["loss_pct"]):
            return {**result, "reason": "stop_loss_cooldown"}
    buys, _ = _filter_buy_candidates_by_event_quarantine(buys, finder, set(state["held_symbols"]))
    if not buys:
        return {**result, "reason": "event_quarantine"}
    buys, _ = _filter_buy_candidates_by_special_situation(buys, finder)
    if not buys:
        return {**result, "reason": "special_situation"}
    result["safety_survivor"] = True
    if symbol in state["held_symbols"]:
        return {**result, "reason": "existing_holding"}
    result["new_buy_signal"] = True
    quotes = [row for row in session["execution_quotes"] if row["symbol"] == symbol
              and _timestamp(row["available_at"]) <= cutoff and _timestamp(row["asof_at"]) <= cutoff]
    if not quotes:
        return {**result, "price": None, "reason": "missing_execution_quote"}
    quote = max(quotes, key=lambda row: _timestamp(row["asof_at"]))
    if (cutoff - _timestamp(quote["asof_at"])).total_seconds() > 86400:
        return {**result, "price": None, "reason": "stale_execution_quote"}
    try:
        result["price"] = _number(quote["price"], positive=True)
    except (ValueError, TypeError):
        return {**result, "price": None, "reason": "invalid_execution_quote"}
    return result


def _quarter_inputs(bundle: dict, quarter: dict) -> tuple[dict | None, str]:  # pylint: disable=too-many-return-statements
    cutoff = _timestamp(quarter["rebalance_at"])
    period = _quarter(cutoff)
    eligible = [row for row in bundle["quantus_snapshots"]
                if pd.Timestamp(row["asof_date"]).to_period("Q") == period
                and pd.Timestamp(row["asof_date"]).date() <= cutoff.date()
                and _timestamp(row["available_at"]) <= cutoff]
    if not eligible:
        return None, "missing_current_quarter_quantus"
    latest_day = max(row["asof_date"] for row in eligible)
    latest = [row for row in eligible if row["asof_date"] == latest_day]
    if len(latest) != 1:
        return None, "ambiguous_quantus_snapshot"
    if latest[0].get("input_error"):
        return None, latest[0]["input_error"]
    stage_c = quarter.get("stage_c")
    if not stage_c:
        return None, quarter.get("stage_c_error", "missing_stage_c")
    if stage_c.get("reviewed") is not True:
        return None, "stage_c_not_reviewed"
    if stage_c.get("core_snapshot_sha256") != latest[0]["sha256"]:
        return None, "stage_c_core_lineage_mismatch"
    if stage_c.get("core_asof_date", latest_day) != latest_day:
        return None, "stage_c_core_date_mismatch"
    if stage_c.get("core_symbols", _symbols(latest[0]["symbols"])) != _symbols(latest[0]["symbols"]):
        return None, "stage_c_core_symbols_mismatch"
    if not 0 <= (cutoff.date() - date.fromisoformat(stage_c.get("asof_date", latest_day))).days <= 7:
        return None, "stale_stage_c"
    for field in ("available_at", "data_cutoff_at", "listing_asof_at"):
        if _timestamp(stage_c[field]) > cutoff:
            return None, "future_stage_c_" + field
    if stage_c.get("ranked_coverage_complete") is not True:
        return None, "truncated_expansion_ranking"
    if stage_c.get("parameters") != {
        "target_watch": 100, "price_min": 5, "price_max": 90,
        "liquidity_sessions": 20, "min_dollar_volume": 2000000,
        "rank_weights": [0.4, 0.6],
    }:
        return None, "incompatible_stage_c_hypotheses"
    return {"core": latest[0]["symbols"], "expansion": stage_c["ranked_finalists"],
            "core_sha256": latest[0]["sha256"], "stage_c_sha256": stage_c["sha256"]}, ""


def validate_bundle(bundle: dict) -> None:
    """Reject ambiguous structural inputs rather than silently filling history."""
    if bundle["schema_version"] != 1:
        raise ValueError("Unsupported replay schema.")
    if bundle["price_convention"] not in {"asof_auto_adjusted", "unadjusted"}:
        raise ValueError("Declare the price convention.")
    if not bundle["corporate_action_policy"]:
        raise ValueError("Declare corporate-action and delisting limitations.")
    _number(bundle["assumptions"]["fee_per_order"])
    _number(bundle["assumptions"]["slippage_bps"])
    reserve = _number(bundle["assumptions"]["reserve_ratio"])
    if reserve > 1:
        raise ValueError("Invalid reserve_ratio.")
    sessions = [_timestamp(row["signal_at"]).date() for row in bundle["sessions"]]
    if len(sessions) != len(set(sessions)):
        raise ValueError("Duplicate daily session.")
    periods = [_quarter(_timestamp(row["rebalance_at"])) for row in bundle["quarters"]]
    if len(periods) != len(set(periods)):
        raise ValueError("One frozen rebalance per quarter is required.")
    for session in bundle["sessions"]:
        signal_at = _timestamp(session["signal_at"])
        state = session["state"]
        if _timestamp(state["available_at"]) > signal_at:
            raise ValueError("Future account state.")
        state_asof = _timestamp(state["asof_at"])
        if state_asof > _timestamp(state["available_at"]):
            raise ValueError("Account state asof exceeds availability.")
        if (signal_at - state_asof).total_seconds() > 86400:
            raise ValueError("Stale account state.")
        _number(state["cash"])
        _number(state["holdings_value"])
        state["held_symbols"] = _symbols(state["held_symbols"])
        for loss in state["stop_losses"]:
            if not math.isfinite(float(loss["loss_pct"])):
                raise ValueError("Invalid loss percentage.")


def replay(bundle: dict) -> dict:
    """Return stable, source-aware comparisons; unavailable measurements stay null."""
    # Avoid modifying the caller's state during normalization.
    bundle = json.loads(json.dumps(bundle, allow_nan=False))
    validate_bundle(bundle)
    coverage, cohorts, symbol_rows, daily, source_daily, quarter_evidence = [], [], [], [], [], []
    assigned_sessions = set()
    evaluated = {}
    symbol_inputs = {}
    for name in ("bars", "metadata"):
        for row in bundle[name]:
            symbol_inputs.setdefault(row["symbol"], {"bars": [], "metadata": []})[name].append(row)
    for quarter in sorted(bundle["quarters"], key=lambda row: row["rebalance_at"]):
        cutoff = _timestamp(quarter["rebalance_at"])
        label = str(_quarter(cutoff))
        inputs, reason = _quarter_inputs(bundle, quarter)
        if quarter.get("stage_c"):
            quarter_evidence.append({"quarter": label, **quarter["stage_c"]})
        sessions = [row for row in bundle["sessions"] if _timestamp(row["signal_at"]) >= cutoff
                    and str(_quarter(_timestamp(row["signal_at"]))) == label]
        coverage.append({'quarter': label, 'comparable_inputs': inputs is not None, 'reason': reason,
                             'requested_sessions': len(sessions)})
        assigned_sessions.update(row["signal_at"] for row in sessions)
        if inputs is None:
            continue  # all four arms use precisely the same supported dates
        for cap in CAPS:
            cohort = build_cohort(inputs["core"], inputs["expansion"], cap)
            cohort["overlap"] += quarter.get("stage_c", {}).get("stage_c_counts", {}).get(
                "reasons", {}).get("core_overlap", 0)
            cohorts.append({'quarter': label, 'cap': cap, **cohort,
                                'core_sha256': inputs["core_sha256"], 'stage_c_sha256': inputs["stage_c_sha256"]})
            for session in sorted(sessions, key=lambda row: row["signal_at"]):
                observations = []
                for symbol in cohort["watch_names"]:
                    evaluation_key = (session["signal_at"], symbol)
                    if evaluation_key not in evaluated:
                        evaluated[evaluation_key] = evaluate_daily_symbol(
                            symbol_inputs.get(symbol, {"bars": [], "metadata": []}), symbol, session)
                    observations.append({**evaluated[evaluation_key],
                                         "source_pool": cohort["source_by_symbol"][symbol]})
                signals = [row for row in observations if row["new_buy_signal"]]
                allocation = fixed_dollar_capacity(signals, session["state"], bundle["assumptions"])
                data_failures = [row for row in observations if _data_failure(row["reason"])]
                allocation["signal_scarcity"] = not signals and not data_failures
                if data_failures:
                    allocation["signal_capacity_gap_dollars"] = None
                key = {'quarter': label, 'cap': cap, 'signal_at': session["signal_at"]}
                allocated = {row["symbol"]: row for row in allocation.pop("allocations")}
                for row in observations:
                    symbol_rows.append({**key, **row, **{field: allocated.get(row["symbol"], {}).get(field)
                                                       for field in ("quantity", "dollars", "capacity_reason")}})
                daily.append({**key, **allocation,
                              "data_complete": not data_failures,
                              "data_failure_count": len(data_failures),
                              "cash_cause": "data_unavailable" if data_failures else
                              "no_qualified_signals" if not signals else "target_rounding_or_cash_constraints",
                              "core_count": cohort["core_count"], "expansion_count": cohort["expansion_count"],
                              "overlap": cohort["overlap"], "watch_count": len(observations),
                              "trend_ok": sum(row["trend_ok"] for row in observations),
                              "safety_survivors": sum(row["safety_survivor"] for row in observations),
                              "new_buy_signals": len(signals),
                              "exclusions": dict(sorted(Counter(row["reason"] for row in observations
                                                                if row["reason"]).items()))})
                for source in SOURCES:
                    rows = [row for row in observations if row["source_pool"] == source]
                    buys = [row for row in allocated.values() if row["source_pool"] == source]
                    source_daily.append({**key, "source_pool": source, "watch_count": len(rows),
                                         "trend_ok": sum(row["trend_ok"] for row in rows),
                                         "safety_survivors": sum(row["safety_survivor"] for row in rows),
                                         "new_buy_signals": sum(row["new_buy_signal"] for row in rows),
                                         "exclusions": dict(sorted(Counter(row["reason"] for row in rows
                                                                           if row["reason"]).items())),
                                         "target_affordable_entries": sum(row["capacity_reason"] not in {
                                             "whole_share_exceeds_target", "invalid_execution_price",
                                             "existing_holding_or_duplicate"} for row in buys),
                                         "affordable_new_entries": sum(row["quantity"] > 0 for row in buys),
                                         "capacity_entries": sum(row["quantity"] > 0 for row in buys),
                                         "hypothetical_dollars_invested": sum(row["dollars"] for row in buys),
                                         "new_positions": None, "actual_dollars_invested": None})
    for session in bundle["sessions"]:
        if session["signal_at"] not in assigned_sessions:
            coverage.append({'quarter': str(_quarter(_timestamp(session["signal_at"]))),
                                 'comparable_inputs': False, 'reason': "session_without_quarter_inputs",
                                 'requested_sessions': 1})
    # A missing expansion observation must not leave a more favorable denominator
    # in one arm. Cash-day comparisons use the intersection of complete days.
    incomplete_days = {row["signal_at"] for row in daily
                       if not row["data_complete"] or row["capacity_cash_ratio"] is None}
    complete_days = {row["signal_at"] for row in daily} - incomplete_days
    for row in daily:
        row["paired_complete_day"] = row["signal_at"] in complete_days
    summary, source_quarterly = [], []
    for cohort in cohorts:
        rows = [row for row in daily if (row["quarter"], row["cap"]) == (cohort["quarter"], cohort["cap"])]
        ratios = [row["capacity_cash_ratio"] for row in rows
                  if row["paired_complete_day"]]
        summary.append({"quarter": cohort["quarter"], "cap": cohort["cap"], "days": len(rows),
                        "cash_ratio_days": len(ratios),
                        "capacity_fraction_days_cash_gt_50": sum(ratio > .5 for ratio in ratios) / len(ratios)
                        if ratios else None,
                        "actual_fraction_days_cash_gt_50": None,
                        "mean_capacity_entries": sum(row["capacity_entries"] for row in rows) / len(rows)
                        if rows else None})
        for source in SOURCES:
            selected = [row for row in source_daily if (row["quarter"], row["cap"], row["source_pool"])
                        == (cohort["quarter"], cohort["cap"], source)]
            source_quarterly.append({"quarter": cohort["quarter"], "cap": cohort["cap"],
                                     "source_pool": source, "days": len(selected),
                                     **{"mean_" + field: sum(row[field] for row in selected) / len(selected)
                                        if selected else None for field in (
                                            "watch_count", "trend_ok", "safety_survivors", "new_buy_signals",
                                            "affordable_new_entries", "capacity_entries",
                                            "hypothetical_dollars_invested")}})
    return {
        "schema_version": 1, "conclusion": "INCONCLUSIVE", "mode": "daily_signal_cash_capacity_only",
        "conclusion_reason": "No comparable counterfactual portfolio performance; Stage E requires reviewed evidence.",
        "performance_comparable": False, "performance": dict.fromkeys(PERFORMANCE_KEYS),
        "research_arms": [{"cap": cap, "experiment_only": cap == 100,
                           "comparable_quarters": sum(row["comparable_inputs"] for row in coverage)}
                          for cap in CAPS],
        "limitations": LIMITATIONS, "assumptions": bundle["assumptions"],
        "resolved_strategy_config": {name: getattr(StrategyConfig, name) for name in dir(StrategyConfig)
                                     if name.isupper()},
        "price_convention": bundle["price_convention"], "corporate_action_policy": bundle["corporate_action_policy"],
        "coverage": coverage, "cohorts": cohorts, "symbols": symbol_rows,
        "quarter_evidence": quarter_evidence,
        "daily": daily, "source_daily": source_daily, "quarterly": summary,
        "source_quarterly": source_quarterly,
    }


def empty_bundle() -> dict:
    """An honest empty coverage input, never synthetic historical constituents."""
    return {'schema_version': 1, 'price_convention': "asof_auto_adjusted",
                'corporate_action_policy': "Unknown historical adjustments/delistings; no performance calculated.",
                'assumptions': {'reserve_ratio': 0, 'fee_per_order': 0, 'slippage_bps': 0},
                'quantus_snapshots': [], 'quarters': [], 'sessions': [], 'metadata': [], 'bars': []}


def write_outputs(result: dict, destination: Path) -> None:
    """Publish immutable CSV/JSON/Markdown together; identical reruns are idempotent."""
    artifacts = {"comparison.json": (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()}
    schemas = {
        "daily": ["quarter", "cap", "signal_at", "capacity_entries", "capacity_cash_ratio", "new_positions"],
        "source_daily": ["quarter", "cap", "signal_at", "source_pool", "watch_count", "capacity_entries"],
        "source_quarterly": ["quarter", "cap", "source_pool", "days", "mean_capacity_entries"],
        "symbols": ["quarter", "cap", "signal_at", "symbol", "source_pool", "reason"],
        "quarterly": ["quarter", "cap", "days", "capacity_fraction_days_cash_gt_50"],
        "coverage": ["quarter", "comparable_inputs", "reason", "requested_sessions"],
        "cohorts": ["quarter", "cap", "core_count", "expansion_count", "overlap", "watch_names"],
    }
    for name, columns in schemas.items():
        rows = [{key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
                 for key, value in row.items()} for row in result[name]]
        artifacts[name + ".csv"] = pd.DataFrame(rows, columns=None if rows else columns).to_csv(index=False).encode()
    text = ["# Expansion Watch Pool comparison", "", result["conclusion"], "",
            "Performance: **NOT COMPARABLE**. This is an independent daily cash-capacity diagnostic.", "",
            f"Comparable quarter inputs: {sum(row['comparable_inputs'] for row in result['coverage'])}.",
            f"Daily arm observations: {len(result['daily'])}.", "",
            "Research caps: Core-only / +30 / +50 / +100 (100 experimental only; Stage C max remains 50).", "",
            "Assumptions: $100 per new symbol; "
            f"reserve={result['assumptions']['reserve_ratio']:.1%}, "
            f"fee/order=${result['assumptions']['fee_per_order']}, "
            f"slippage={result['assumptions']['slippage_bps']} bps. "
            "These are research inputs, not verified deployed settings.", "",
            "| Quarter | Cap | Days | Capacity days cash >50% |", "|---|---:|---:|---:|"]
    for row in result["quarterly"]:
        fraction = row["capacity_fraction_days_cash_gt_50"]
        text.append(f"| {row['quarter']} | {row['cap']} | {row['days']} | "
                    + (f"{fraction:.1%}" if fraction is not None else "unavailable") + " |")
    text += ["", "Coverage exclusions: " + (", ".join(sorted({row["reason"] for row in result["coverage"]
                                                                 if row["reason"]})) or "none"), "",
             *["- " + limitation for limitation in result["limitations"]], "",
             "Collect genuine quarterly inputs and forward daily shadow observations. "
             "Do not activate Stage E before evidence review.", ""]
    artifacts["comparison.md"] = "\n".join(text).encode()
    if destination.exists():
        if (set(path.name for path in destination.iterdir()) != set(artifacts)
                or any((destination / name).read_bytes() != payload for name, payload in artifacts.items())):
            raise ValueError("Immutable comparison output differs; choose a new output directory.")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".comparison-", dir=destination.parent))
    try:
        for name, payload in artifacts.items():
            (staging / name).write_bytes(payload)
        os.rename(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _data_failure(reason: str) -> bool:
    """Keep unknown data separate from genuine failed trading conditions."""
    return reason.startswith(("missing_", "stale_", "invalid_", "duplicate_", "insufficient_")) or reason in {
        "bar_not_complete_before_signal", "history_gap_or_suspension", "recent_volume_unavailable",
        "ohlcv_api_error", "metadata_api_error",
        "observation_before_bar_close",
    }
