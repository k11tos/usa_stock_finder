"""Explicit external-flow verification and boundary-valued KRW TWR.

See docs/krw_time_weighted_return.md for the accounting and timing contracts.
This module never imports, writes or reinterprets the legacy cash-flow ledger.
"""

from __future__ import annotations

import csv
import fcntl
import math
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import pandas as pd

DEFAULT_KRW_FLOWS = "data/live/krw_external_flows.csv"
FLOW_HEADERS = [
    "record_id", "interval_start", "interval_end", "effective_at", "amount_krw",
    "currency", "classification", "timing", "source", "description", "verification_status",
]
INBOUND = {"deposit", "domestic_to_overseas"}
OUTBOUND = {"withdrawal", "overseas_to_domestic"}
ATTESTATIONS = {"complete", "incomplete"}
CURVE_COLUMNS = [
    "run_date", "interval_start", "interval_end", "flow_status", "start_flow_krw",
    "end_flow_krw", "daily_return", "return_valid", "reason", "twr_index", "drawdown_pct",
]
TIMING_CONVENTION = "Verified start-after-opening / end-before-closing flows; intraday or unknown timing is N/A."


@dataclass
class ExternalFlowLedger:
    """Intervals contain explicit events and a separate completeness attestation."""

    intervals: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _timestamp(value: str) -> pd.Timestamp:
    stamp = pd.to_datetime(value, format="ISO8601")
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return stamp.tz_convert("Asia/Seoul")


def _parse_row(raw: dict) -> dict:
    if None in raw or any(raw.get(key) is None for key in FLOW_HEADERS):
        raise ValueError("incomplete row")
    row = dict(raw)
    for key in ("record_id", "source", "description"):
        if not row[key].strip():
            raise ValueError("missing identity or evidence")
    if row["currency"] != "KRW" or row["verification_status"] not in {"verified", "pending"}:
        raise ValueError("invalid currency or verification")
    start, end = _timestamp(row["interval_start"]), _timestamp(row["interval_end"])
    if start >= end:
        raise ValueError("invalid interval")
    row["interval_start"], row["interval_end"] = start, end
    if not math.isfinite(float(row["amount_krw"])):
        raise ValueError("non-finite amount")
    amount = Fraction(row["amount_krw"])
    row["amount_krw"] = amount
    kind, timing = row["classification"], row["timing"]
    if kind in ATTESTATIONS:
        if amount != 0 or row["effective_at"] or timing != "none":
            raise ValueError("invalid completeness attestation")
        return row
    if kind not in INBOUND | OUTBOUND or (kind in INBOUND and amount <= 0) or (kind in OUTBOUND and amount >= 0):
        raise ValueError("invalid external classification or sign")
    if timing not in {"start", "end", "intraday", "unknown"}:
        raise ValueError("invalid timing")
    effective = row["effective_at"]
    if timing in {"start", "end", "intraday"}:
        effective = _timestamp(effective)
        if not start <= effective <= end:
            raise ValueError("effective time outside interval")
        if timing == "start" and effective != start or timing == "end" and effective != end:
            raise ValueError("flow does not match valuation boundary")
        if timing == "intraday" and not start < effective < end:
            raise ValueError("intraday flow must be inside interval")
    elif effective:
        if len(effective) == 10:
            effective_date = pd.Timestamp(effective)
            if (effective_date.strftime("%Y-%m-%d") != effective
                    or not start.date() <= effective_date.date() <= end.date()):
                raise ValueError("invalid effective date")
        elif not start <= _timestamp(effective) <= end:
            raise ValueError("effective time outside interval")
    return row


def load_external_flow_ledger(path: str | Path = DEFAULT_KRW_FLOWS) -> ExternalFlowLedger:
    """Fail closed on malformed evidence; an absent event is never a zero assertion."""
    result = ExternalFlowLedger()
    try:
        with Path(path).open(encoding="utf-8", newline="") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames != FLOW_HEADERS:
                raise ValueError("invalid ledger header")
            rows = list(reader)
        ids = set()
        for raw in rows:
            row = _parse_row(raw)
            if row["record_id"] in ids:
                raise ValueError("duplicate event or attestation ID")
            ids.add(row["record_id"])
            key = (row["interval_start"], row["interval_end"])
            result.intervals.setdefault(key, []).append(row)
        previous_end = None
        for (start, end), interval in sorted(result.intervals.items()):
            if previous_end is not None and start < previous_end:
                raise ValueError("overlapping declared intervals")
            previous_end = end
            if sum(row["classification"] in ATTESTATIONS for row in interval) > 1:
                raise ValueError("conflicting completeness attestations")
    except (OSError, UnicodeError, csv.Error, ValueError, TypeError, OverflowError, ZeroDivisionError):
        return ExternalFlowLedger(warnings=[
            "KRW external-flow ledger missing, unreadable or invalid; flow history is unknown. "
            "Verify schema, unique IDs, nonoverlapping intervals, KRW amounts, evidence and timing.",
        ])
    if not result.intervals:
        result.warnings.append("KRW external-flow ledger is empty; flow history is unknown.")
    return result


def _interval_flows(ledger: ExternalFlowLedger, start: pd.Timestamp, end: pd.Timestamp) -> tuple:
    rows = ledger.intervals.get((start, end), [])
    coverage = [row for row in rows if row["classification"] in ATTESTATIONS]
    if (len(coverage) != 1 or coverage[0]["classification"] != "complete"
            or any(row["verification_status"] != "verified" for row in rows)):
        return "unknown", None, None, "External cash-flow completeness is unknown or incomplete."
    flows = [row for row in rows if row["classification"] not in ATTESTATIONS]
    status = "verified_nonzero" if flows else "verified_zero"
    if any(row["timing"] not in {"start", "end"} for row in flows):
        return status, None, None, "Intraday or unknown flow timing lacks boundary valuations; exact daily TWR is N/A."
    start_flow = sum((row["amount_krw"] for row in flows if row["timing"] == "start"), Fraction(0))
    end_flow = sum((row["amount_krw"] for row in flows if row["timing"] == "end"), Fraction(0))
    return status, start_flow, end_flow, ""


def _daily_result(previous: dict, current: dict, ledger: ExternalFlowLedger) -> dict:
    start, end = _timestamp(previous["fetched_at_kst"]), _timestamp(current["fetched_at_kst"])
    status, start_flow, end_flow, reason = _interval_flows(ledger, start, end)
    result = {
        "run_date": current["run_date"], "interval_start": start.isoformat(), "interval_end": end.isoformat(),
        "flow_status": status, "start_flow_krw": None if start_flow is None else float(start_flow),
        "end_flow_krw": None if end_flow is None else float(end_flow), "daily_return": None,
        "return_valid": False, "reason": reason, "twr_index": None, "drawdown_pct": None,
    }
    if (end.date() - start.date()).days != 1:
        result["reason"] = "Missing consecutive calendar observations; no daily return across a gap."
        return result
    if reason:
        return result
    opening, closing = Fraction(str(previous["total_asset_krw"])), Fraction(str(current["total_asset_krw"]))
    if (previous["valuation_currency"] != "KRW" or current["valuation_currency"] != "KRW"
            or opening <= 0 or closing <= 0):
        result["reason"] = "Invalid positive KRW equity."
        return result
    capital, terminal = opening + start_flow, closing - end_flow
    if capital <= 0 or terminal <= 0:
        result["reason"] = "Nonpositive flow-adjusted equity; return denominator/subperiod is invalid."
        return result
    daily_return = float(terminal / capital - 1)
    if not math.isfinite(daily_return):
        result["reason"] = "Non-finite return."
        return result
    result.update(daily_return=daily_return, return_valid=True, _growth=terminal / capital)
    return result


def calculate_twr(daily: pd.DataFrame, ledger: ExternalFlowLedger, *, start_date: str | None = None,
                  end_date: str | None = None, rejected_records: bool = False) -> tuple[pd.DataFrame, dict]:
    """Keep later valid returns, but never restart/link an index after an invalid interval."""
    rows = []
    reasons = list(ledger.warnings)
    observations = daily.to_dict("records")
    if len(observations) < 2:
        reasons.append("At least two validated broker observations are required.")
    endpoints_valid = bool(observations)
    if observations:
        for requested, actual in ((start_date, observations[0]["run_date"]),
                                  (end_date, observations[-1]["run_date"])):
            if requested and pd.Timestamp(requested).normalize() != pd.Timestamp(actual).normalize():
                endpoints_valid = False
                reasons.append("Requested period endpoint has no validated equity; full-period TWR is N/A.")
        rows.append({
            "run_date": observations[0]["run_date"], "interval_start": None,
            "interval_end": observations[0]["fetched_at_kst"], "flow_status": "baseline",
            "start_flow_krw": None, "end_flow_krw": None, "daily_return": None, "return_valid": False,
            "reason": "Opening valuation; no return interval.", "twr_index": 100.0, "drawdown_pct": 0.0,
        })
    index, peak = Fraction(100), Fraction(100)
    chain_valid = endpoints_valid and not rejected_records
    if not chain_valid and rows:
        rows[0].update(twr_index=None, drawdown_pct=None)
    for previous, current in zip(observations, observations[1:]):
        try:
            row = _daily_result(previous, current, ledger)
        except (ValueError, TypeError, OverflowError, ZeroDivisionError):
            row = dict.fromkeys(CURVE_COLUMNS)
            row.update(run_date=current["run_date"], flow_status="unknown", return_valid=False,
                       reason="Invalid equity or timestamp; daily TWR is N/A.")
        growth = row.pop("_growth", None)
        if rejected_records:
            row.update(daily_return=None, return_valid=False,
                       reason="Rejected broker records require reconciliation before TWR validation.")
        if not row["return_valid"]:
            chain_valid = False
            reasons.append(f"{pd.Timestamp(current['run_date']):%Y-%m-%d}: {row['reason']}")
        if chain_valid:
            # Fractions preserve decimal inputs and deterministic chaining order.
            index *= growth
            peak = max(peak, index)
            try:
                row["twr_index"] = float(index)
                if not math.isfinite(row["twr_index"]):
                    raise OverflowError
                row["drawdown_pct"] = float((index / peak - 1) * 100)
            except OverflowError:
                chain_valid = False
                row.update(twr_index=None, drawdown_pct=None)
                reasons.append("TWR index exceeds finite numeric range; full-period TWR is N/A.")
        rows.append(row)
    curve = pd.DataFrame(rows, columns=CURVE_COLUMNS)
    returns = pd.to_numeric(curve["daily_return"], errors="coerce").dropna()
    complete = bool(chain_valid and len(observations) >= 2)
    statuses = curve["flow_status"].iloc[1:].tolist()
    flow_status = "unknown"
    if statuses and "unknown" not in statuses and endpoints_valid and not rejected_records:
        flow_status = "verified_nonzero" if "verified_nonzero" in statuses else "verified_zero"
    volatility = float(returns.std(ddof=1) * math.sqrt(365.25) * 100) if len(returns) >= 2 else None
    if volatility is not None and not math.isfinite(volatility):
        volatility = None
    expected_count = 0
    if observations:
        expected_count = max((pd.Timestamp(end_date or observations[-1]["run_date"])
                              - pd.Timestamp(start_date or observations[0]["run_date"])).days, 0)
    summary = {
        "report_kind": "krw_time_weighted_return", "returns_validated": complete,
        "external_cash_flow_completeness": flow_status, "timing_convention": TIMING_CONVENTION,
        "cumulative_return_pct": float((index / 100 - 1) * 100) if complete else None,
        "max_drawdown_pct": float(curve["drawdown_pct"].min()) if complete else None,
        "annualized_volatility_pct": volatility, "volatility_valid_return_count": len(returns),
        "volatility_scope": "full_period" if complete else "valid_returns_only_incomplete_period",
        "volatility_annualization_days": 365.25, "valid_daily_return_count": len(returns),
        "expected_daily_return_count": expected_count,
        "twr_unavailable_reasons": list(dict.fromkeys(reasons)),
    }
    summary["cash_flow_adjusted_return_pct"] = summary["cumulative_return_pct"]
    return curve, summary
