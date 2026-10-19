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
    "interval_return", "interval_days", "calendar_days", "gap_warning",
]
TIMING_CONVENTION = "Verified start-after-opening / end-before-closing flows; intraday or unknown timing is N/A."
VOLATILITY_CONVENTION = (
    "Sample standard deviation of verified interval returns × sqrt(365.25 / elapsed interval days). "
    "Requires at least two valid returns and identical positive elapsed durations for all observed intervals; "
    "mixed or unknown durations are N/A. No daily interpolation or partial-duration filtering."
)
LONG_GAP_DAYS = 4


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
        return status, None, None, (
            "Intraday or unknown flow timing lacks boundary valuations; exact interval TWR is N/A."
        )
    start_flow = sum((row["amount_krw"] for row in flows if row["timing"] == "start"), Fraction(0))
    end_flow = sum((row["amount_krw"] for row in flows if row["timing"] == "end"), Fraction(0))
    return status, start_flow, end_flow, ""


def _interval_result(previous: dict, current: dict, ledger: ExternalFlowLedger) -> dict:
    start, end = _timestamp(previous["fetched_at_kst"]), _timestamp(current["fetched_at_kst"])
    status, start_flow, end_flow, reason = _interval_flows(ledger, start, end)
    result = {
        "run_date": current["run_date"], "interval_start": start.isoformat(), "interval_end": end.isoformat(),
        "flow_status": status, "start_flow_krw": None if start_flow is None else float(start_flow),
        "end_flow_krw": None if end_flow is None else float(end_flow), "daily_return": None,
        "return_valid": False, "reason": reason, "twr_index": None, "drawdown_pct": None,
        "interval_return": None, "interval_days": (end - start) / pd.Timedelta(days=1),
        "calendar_days": (end.date() - start.date()).days, "gap_warning": "",
    }
    if end <= start:
        result["reason"] = "Non-increasing observation timestamps; interval TWR is N/A."
        return result
    missing = pd.bdate_range(start.normalize() + pd.Timedelta(days=1), end.normalize() - pd.Timedelta(days=1))
    warnings = []
    if len(missing):
        warnings.append("Missing weekday observations (may include market holidays): " +
                        ", ".join(missing.strftime("%Y-%m-%d")) + ".")
    if result["calendar_days"] > LONG_GAP_DAYS:
        warnings.append(f"Unusually long observation gap: {result['calendar_days']} calendar days "
                        f"(threshold > {LONG_GAP_DAYS}).")
    if warnings:
        result["gap_warning"] = " ".join(warnings) + " No snapshots or flows inferred; verify the entire interval."
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
    interval_return = float(terminal / capital - 1)
    if not math.isfinite(interval_return):
        result["reason"] = "Non-finite return."
        return result
    result.update(interval_return=interval_return, return_valid=True, _growth=terminal / capital)
    if result["calendar_days"] == 1:
        result["daily_return"] = interval_return  # Compatibility: strictly one KST calendar day only.
    return result


def interval_volatility(curve: pd.DataFrame) -> tuple[pd.Series, dict]:
    """Use one elapsed sampling duration, or decline annualization for the whole sample.

    This is the usual equal-period arithmetic-return estimator (independent,
    stationary increments assumed), not a model for unobserved daily paths.
    Invalid returns may be excluded, but their interval durations may not be.
    """
    returns = pd.to_numeric(curve["interval_return"], errors="coerce").where(curve["return_valid"])
    durations = pd.to_numeric(curve["interval_days"].iloc[1:], errors="coerce")
    interval_days = None
    reason = ""
    if durations.isna().any() or (durations <= 0).any():
        reason = "Unknown or nonpositive interval durations; annualized volatility is N/A."
    elif durations.nunique() > 1:
        reason = "Mixed elapsed interval durations; reliable annualized volatility is N/A."
    elif not durations.empty:
        interval_days = float(durations.iloc[0])
    if not reason and returns.count() < 2:
        reason = "At least two valid interval returns are required for annualized volatility."
    values = pd.Series(float("nan"), index=curve.index, dtype=float)
    if not reason:
        values = returns.expanding(min_periods=2).std(ddof=1) * math.sqrt(365.25 / interval_days) * 100
        values = values.where(returns.notna() & values.map(math.isfinite))
        if pd.isna(values.loc[returns.notna()].iloc[-1]):
            reason = "Non-finite sample volatility; annualized volatility is N/A."
            values[:] = float("nan")
    available = values.dropna()
    return values, {
        "annualized_volatility_pct": None if available.empty else float(available.iloc[-1]),
        "volatility_valid_return_count": int(returns.count()),
        "volatility_annualization_days": 365.25,
        "volatility_interval_days": interval_days,
        "volatility_convention": VOLATILITY_CONVENTION,
        "volatility_unavailable_reason": reason or None,
    }


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
            "interval_return": None, "interval_days": None, "calendar_days": None, "gap_warning": "",
        })
    index, peak = Fraction(100), Fraction(100)
    chain_valid = endpoints_valid and not rejected_records
    if not chain_valid and rows:
        rows[0].update(twr_index=None, drawdown_pct=None)
    for previous, current in zip(observations, observations[1:]):
        try:
            row = _interval_result(previous, current, ledger)
        except (ValueError, TypeError, OverflowError, ZeroDivisionError):
            row = dict.fromkeys(CURVE_COLUMNS)
            row.update(run_date=current["run_date"], flow_status="unknown", return_valid=False,
                       reason="Invalid equity or timestamp; interval TWR is N/A.")
        growth = row.pop("_growth", None)
        if rejected_records:
            row.update(daily_return=None, interval_return=None, return_valid=False,
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
    returns = pd.to_numeric(curve["interval_return"], errors="coerce").dropna()
    complete = bool(chain_valid and len(observations) >= 2)
    statuses = curve["flow_status"].iloc[1:].tolist()
    flow_status = "unknown"
    if statuses and "unknown" not in statuses and endpoints_valid and not rejected_records:
        flow_status = "verified_nonzero" if "verified_nonzero" in statuses else "verified_zero"
    _, volatility_metrics = interval_volatility(curve)
    summary = {
        "report_kind": "krw_time_weighted_return", "returns_validated": complete,
        "external_cash_flow_completeness": flow_status, "timing_convention": TIMING_CONVENTION,
        "cumulative_return_pct": float((index / 100 - 1) * 100) if complete else None,
        "max_drawdown_pct": float(curve["drawdown_pct"].min()) if complete else None,
        **volatility_metrics,
        "volatility_scope": "full_period" if complete else "valid_returns_only_incomplete_period",
        "valid_interval_return_count": len(returns),
        "expected_interval_return_count": max(len(observations) - 1, 0),
        "valid_daily_return_count": int(curve["daily_return"].notna().sum()),
        "expected_daily_return_count": int((curve["calendar_days"] == 1).sum()),
        "observation_gap_warnings": curve["gap_warning"].dropna().loc[lambda values: values != ""].tolist(),
        "twr_unavailable_reasons": list(dict.fromkeys(reasons)),
    }
    summary["cash_flow_adjusted_return_pct"] = summary["cumulative_return_pct"]
    return curve, summary
