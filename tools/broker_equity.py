"""Read the Stage 2 broker CSV without legacy fallbacks or inferred observations."""

from __future__ import annotations

import csv
import fcntl
import io
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

BROKER_EQUITY_PATH = Path("data/live/broker_equity_snapshots.csv")
KST = ZoneInfo("Asia/Seoul")
AMOUNT_FIELDS = [
    "total_asset_krw", "stock_evaluation_krw", "cash_krw", "foreign_cash_krw",
    "unsettled_buy_krw", "unsettled_sell_krw",
]
HEADERS = ["run_id", "run_date", "fetched_at_kst", *AMOUNT_FIELDS, "source", "valuation_currency"]
EXPECTED_SOURCE = {
    "provider": "KIS", "endpoint": "/uapi/overseas-stock/v1/trading/inquire-present-balance",
    "tr_id": "CTRP6504R",
}
STALE_AFTER_DAYS = 3
DISCONTINUITY_THRESHOLD = 0.10


class InvalidBrokerRecord(ValueError):
    """A contract violation with a safe diagnostic, excluding raw input values."""


@dataclass
class BrokerEquityData:
    """Selected observations plus the untouched input for diagnostic publication."""

    daily: pd.DataFrame
    original_csv: str
    warnings: list[str]
    original_csv_bytes: bytes = b""


def _validate_record(row: dict, as_of: datetime) -> None:
    if None in row or any(value in (None, "") for value in row.values()):
        raise InvalidBrokerRecord("inconsistent or incomplete record structure")
    if not row["run_id"].strip() or any(char in row["run_id"] for char in "\r\n"):
        raise InvalidBrokerRecord("invalid run ID")
    if json.loads(row["source"]) != EXPECTED_SOURCE:
        raise InvalidBrokerRecord("incorrect broker source")
    if row["valuation_currency"] != "KRW":
        raise InvalidBrokerRecord("currency must be KRW")
    observed_date = date.fromisoformat(row["run_date"])
    if observed_date.isoformat() != row["run_date"]:
        raise InvalidBrokerRecord("invalid observation date format")
    fetched = datetime.fromisoformat(row["fetched_at_kst"])
    if fetched.utcoffset() != timedelta(hours=9):
        raise InvalidBrokerRecord("invalid KST observation timestamp")
    if fetched.date() != observed_date:
        raise InvalidBrokerRecord("stale observation: timestamp does not match observation date")
    if fetched > as_of:
        raise InvalidBrokerRecord("future observation timestamp")
    for field in AMOUNT_FIELDS:
        if not math.isfinite(float(row[field])):
            raise InvalidBrokerRecord(f"non-finite amount: {field}")
    if float(row["total_asset_krw"]) <= 0:
        raise InvalidBrokerRecord("equity must be positive and finite")


def _diagnose_dates(daily: pd.DataFrame, start_date: str | None, end_date: str | None,
                    as_of: datetime) -> list[str]:
    warnings = []
    if daily.empty:
        return warnings
    first, last = daily["run_date"].iloc[0], daily["run_date"].iloc[-1]
    expected = pd.date_range(start_date or first, end_date or last, freq="D")
    missing = expected.difference(pd.DatetimeIndex(daily["run_date"]))
    if len(missing):
        warnings.append("Missing calendar observation dates (no interpolation): " +
                        ", ".join(missing.strftime("%Y-%m-%d")))
    age = (as_of.astimezone(KST).date() - last.date()).days
    if age > STALE_AFTER_DAYS:
        warnings.append(f"Stale observations: latest selected observation is {age} calendar days old "
                        f"(threshold > {STALE_AFTER_DAYS} days).")
    equities = daily["total_asset_krw"].tolist()
    for idx in range(1, len(equities)):
        previous, current = equities[idx - 1], equities[idx]
        difference = current - previous
        if abs(difference) >= previous * DISCONTINUITY_THRESHOLD:
            change = difference / previous
            warnings.append(f"{daily.loc[idx, 'run_date']:%Y-%m-%d}: raw equity discontinuity "
                            f"{change * 100:.2f}% (>= 10%); observation preserved; "
                            "this is not an investment return.")
    return warnings


def load_broker_equity(start_date: str | None = None, end_date: str | None = None,
                       *, as_of: datetime | None = None) -> BrokerEquityData:
    """Read only the fixed KRW path; latest means greatest KST fetch timestamp.

    Exact duplicate run records are selected once. Conflicting records for a run
    ID are all quarantined, including conflicts with invalid rows. Distinct runs
    tied on fetch time use run ID as a deterministic tie-break, with a warning.
    The original CSV is retained even when validation fails.
    """
    result = BrokerEquityData(pd.DataFrame(columns=HEADERS), "", [])
    if not BROKER_EQUITY_PATH.exists() or BROKER_EQUITY_PATH.stat().st_size == 0:
        result.warnings.append("Broker KRW snapshot CSV is missing or empty; no fallback source used.")
        return result
    with BROKER_EQUITY_PATH.open("rb") as file_obj:
        fcntl.flock(file_obj, fcntl.LOCK_SH)
        result.original_csv_bytes = file_obj.read()
    try:
        result.original_csv = result.original_csv_bytes.decode("utf-8")
    except UnicodeDecodeError:
        result.warnings.append("Invalid UTF-8 in broker KRW snapshot CSV; no observations selected.")
        return result
    try:
        reader = csv.DictReader(io.StringIO(result.original_csv), strict=True)
        if reader.fieldnames != HEADERS:
            result.warnings.append("Invalid broker KRW CSV header; expected the complete Stage 2 structure.")
            return result
        rows = list(reader)
    except csv.Error:
        result.warnings.append("Malformed broker KRW CSV; no observations selected.")
        return result

    current = as_of or datetime.now(KST)
    valid_rows = []
    seen = {}
    conflicting_ids = set()
    for number, row in enumerate(rows, start=2):
        run_id = row.get("run_id")
        if run_id in seen:
            result.warnings.append(f"Row {number}: duplicate run ID detected.")
            if row != seen[run_id]:
                conflicting_ids.add(run_id)
                result.warnings.append(f"Row {number}: conflicting duplicate run ID; all its records quarantined.")
            continue
        seen[run_id] = row
        try:
            _validate_record(row, current)
        except InvalidBrokerRecord as exc:
            result.warnings.append(f"Row {number}: invalid broker KRW record: {exc}.")
            continue
        except (ValueError, TypeError, OverflowError):
            # Describe the failed contract without echoing private/raw CSV values.
            result.warnings.append(f"Row {number}: invalid broker KRW record; verify source, KRW currency, "
                                   "finite amounts, positive equity, date/timestamp and record structure.")
            continue
        valid_rows.append(row)

    valid_rows = [row for row in valid_rows if row["run_id"] not in conflicting_ids]
    if not valid_rows:
        return result
    frame = pd.DataFrame(valid_rows)
    frame["run_date"] = pd.to_datetime(frame["run_date"])
    frame["_fetched"] = pd.to_datetime(frame["fetched_at_kst"], format="ISO8601", utc=True)
    for field in AMOUNT_FIELDS:
        frame[field] = frame[field].map(float)
    if start_date:
        frame = frame[frame["run_date"] >= pd.Timestamp(start_date)]
    if end_date:
        frame = frame[frame["run_date"] <= pd.Timestamp(end_date)]
    duplicate_dates = frame.loc[frame.duplicated("run_date", keep=False), "run_date"].unique()
    for observed_date in duplicate_dates:
        result.warnings.append(f"{pd.Timestamp(observed_date):%Y-%m-%d}: duplicate observation date; "
                               "selected latest valid run by KST fetch timestamp.")
    if frame.duplicated(["run_date", "_fetched"]).any():
        result.warnings.append("Duplicate fetch timestamps; run ID used as deterministic tie-break.")
    result.daily = (frame.sort_values(["run_date", "_fetched", "run_id"])
                    .drop_duplicates("run_date", keep="last").drop(columns="_fetched").reset_index(drop=True))
    result.warnings.extend(_diagnose_dates(result.daily, start_date, end_date, current))
    return result
