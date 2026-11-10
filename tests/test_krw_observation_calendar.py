"""Synthetic observation schedule regressions; no broker or network access."""

import pandas as pd
import pytest
from test_krw_twr import (attestation, compute, inputs, snapshot, stamp, write_csv,
                          write_test_calendar)

from tools.broker_equity import HEADERS, load_broker_equity
from tools.krw_twr import (CALENDAR_HEADERS, calculate_twr, load_external_flow_ledger,
                           load_observation_calendar)


def recalculate(inputs):
    return calculate_twr(load_broker_equity().daily, load_external_flow_ledger(inputs[1]),
                         rejected_records=load_broker_equity().rejected_records)


@pytest.mark.parametrize("start,end,holiday", [(9, 12, "weekend"),
                                               (16, 20, "US MLK"), (1, 5, "reviewed extended closure")])
def test_confirmed_collection_closures_allow_full_interval(inputs, start, end, holiday):
    curve, summary = compute(inputs, [snapshot(start, 100), snapshot(end, 90)],
                             [attestation(end, interval_start=stamp(start))])
    assert summary["returns_validated"], holiday
    assert summary["cumulative_return_pct"] == summary["max_drawdown_pct"] == -10
    assert curve.iloc[-1]["interval_start"] == stamp(start)
    assert curve.iloc[-1]["interval_end"] == stamp(end)


@pytest.mark.parametrize("missing", [10, 12, 19])
def test_scheduled_weekend_or_holiday_is_still_a_collection_failure(inputs, missing):
    compute(inputs, [snapshot(9, 100), snapshot(20, 110), snapshot(21, 99)],
            [attestation(20, interval_start=stamp(9)), attestation(21)])
    write_test_calendar(inputs[0].with_name("krw_observation_calendar.csv"), {9, missing, 20, 21})
    curve, summary = recalculate(inputs)
    assert not summary["returns_validated"]
    assert summary["cumulative_return_pct"] is summary["max_drawdown_pct"] is None
    assert f"Missing scheduled observation on 2026-01-{missing:02d}" in curve.iloc[1]["reason"]
    assert curve.iloc[2]["return_valid"]
    assert curve["twr_index"].iloc[1:].isna().all()
    assert curve["drawdown_pct"].iloc[1:].isna().all()


@pytest.mark.parametrize("failure", ["absent", "coverage", "pending", "duplicate", "empty", "unexpected"])
def test_uncertain_collection_policy_fails_closed(inputs, failure):
    compute(inputs, [snapshot(9, 100), snapshot(12, 110)], [attestation(12, interval_start=stamp(9))])
    path = inputs[0].with_name("krw_observation_calendar.csv")
    rows = pd.read_csv(path, dtype=str).to_dict("records")
    if failure == "absent":
        path.unlink()
    else:
        if failure == "coverage":
            rows = [row for row in rows if row["date"] != "2026-01-10"]
        elif failure == "pending":
            rows[9]["verification_status"] = "pending"
        elif failure == "duplicate":
            rows.append(rows[9])
        elif failure == "unexpected":
            rows[11]["collection"] = "closed"
        else:
            rows = []
        write_csv(path, CALENDAR_HEADERS, rows)
    curve, summary = recalculate(inputs)
    assert not summary["returns_validated"]
    assert not curve.iloc[1]["return_valid"]
    assert summary["external_cash_flow_completeness"] == "verified_zero"
    assert summary["cumulative_return_pct"] is summary["max_drawdown_pct"] is None


def test_duplicate_snapshot_selection_keeps_exact_flow_boundaries(inputs):
    snaps = [snapshot(9, 100), snapshot(12, 110), snapshot(12, 110)]
    _, summary = compute(inputs, snaps, [attestation(12, interval_start=stamp(9))])
    assert summary["returns_validated"]  # Identical source retry is idempotent.
    later = snapshot(12, 111, run_id="later", fetched_at_kst=stamp(12).replace("16:", "17:"))
    write_csv(inputs[0], HEADERS, [*snaps, later])
    _, summary = recalculate(inputs)
    assert not summary["returns_validated"]  # Old ledger cannot cover the selected later instant.
    assert summary["external_cash_flow_completeness"] == "unknown"
    write_csv(inputs[0], HEADERS, [snapshot(9, 100), snapshot(12, 110), snapshot(12, 111)])
    _, summary = recalculate(inputs)
    assert not summary["returns_validated"]  # Conflicting duplicate run ID needs reconciliation.


def test_calendar_loader_never_infers_missing_dates(tmp_path):
    policy = load_observation_calendar(tmp_path / "missing.csv")
    assert not policy.days and policy.warnings


def test_reviewed_korean_seollal_collection_holiday(inputs):
    start, end = "2026-02-13T16:00:00+09:00", "2026-02-19T17:00:00+09:00"
    snapshots = [snapshot(13, 100, run_date="2026-02-13", fetched_at_kst=start),
                 snapshot(19, 105, run_date="2026-02-19", fetched_at_kst=end)]
    write_csv(inputs[0], HEADERS, snapshots)
    write_csv(inputs[1], list(attestation()), [attestation(interval_start=start, interval_end=end)])
    write_csv(inputs[0].with_name("krw_observation_calendar.csv"), CALENDAR_HEADERS, [
        {"date": day.strftime("%Y-%m-%d"), "collection": "scheduled" if day.day in {13, 19} else "closed",
         "verification_status": "verified", "source": "synthetic collector holiday exceptions",
         "description": "Reviewed weekend and Seollal Feb 16-18 collection closure"}
        for day in pd.date_range("2026-02-13", "2026-02-19")
    ])
    curve, summary = recalculate(inputs)
    assert summary["returns_validated"]
    assert summary["cumulative_return_pct"] == 5
    assert curve.iloc[1]["interval_end"] == end  # Actual fetch hour, never a calendar-derived boundary.


@pytest.mark.parametrize("contents", ["date,collection,verification_status,source,description\n2026-01-09,scheduled\n",
                                      "bad,header\n", "date,collection,verification_status,source,description\n,,,,\n"])
def test_malformed_calendar_is_unknown(tmp_path, contents):
    path = tmp_path / "calendar.csv"
    path.write_text(contents)
    policy = load_observation_calendar(path)
    assert policy.warnings and not policy.days
