"""Offline persistence regressions using complete Stage 1 broker results."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from csv import DictReader
from unittest.mock import MagicMock

import pytest

import broker_equity_snapshot_runner as runner
from live_performance_logger import (
    BROKER_EQUITY_AMOUNT_FIELDS,
    BROKER_EQUITY_SNAPSHOT_HEADERS,
    append_broker_equity_snapshot,
)
from stock_operations import APIError

EQUITY = {
    "total_asset_krw": 6139950.0,
    "stock_evaluation_krw": 4537263.0,
    "cash_krw": 358864.0,
    "foreign_cash_krw": 1508022.0,
    "unsettled_buy_krw": 264199.0,
    "unsettled_sell_krw": 0.0,
    "fetched_at_kst": "2026-10-14T20:00:01+09:00",
    "source": {
        "provider": "KIS", "endpoint": "/uapi/overseas-stock/v1/trading/inquire-present-balance",
        "tr_id": "CTRP6504R",
    },
    "query_parameters": {
        "WCRC_FRCR_DVSN_CD": "01", "NATN_CD": "840", "TR_MKET_CD": "00", "INQR_DVSN_CD": "00",
    },
}


def test_single_row_and_append_preserve_history(tmp_path):
    historical = tmp_path / "account_snapshots.csv"
    historical.write_bytes(b"legacy,cash\nold,1\n")
    assert append_broker_equity_snapshot("run1", "2026-10-14", EQUITY, str(tmp_path))
    path = tmp_path / "broker_equity_snapshots.csv"
    original = path.read_bytes()
    with path.open(encoding="utf-8", newline="") as file_obj:
        reader = DictReader(file_obj)
        rows = list(reader)
        assert reader.fieldnames == BROKER_EQUITY_SNAPSHOT_HEADERS
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run1"
    assert rows[0]["valuation_currency"] == "KRW"
    for field in BROKER_EQUITY_AMOUNT_FIELDS:
        assert float(rows[0][field]) == EQUITY[field]
    assert rows[0]["fetched_at_kst"] == EQUITY["fetched_at_kst"]
    assert append_broker_equity_snapshot("run2", "2026-10-14", EQUITY, str(tmp_path))
    assert path.read_bytes().startswith(original)
    assert historical.read_bytes() == b"legacy,cash\nold,1\n"


def test_duplicate_run_and_concurrent_writers(tmp_path):
    def append(_index):
        return append_broker_equity_snapshot("same-run", "2026-10-14", EQUITY, str(tmp_path))

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(append, range(8))) == 1
    path = tmp_path / "broker_equity_snapshots.csv"
    original = path.read_bytes()
    assert not append(9)
    assert path.read_bytes() == original


@pytest.mark.parametrize("field", list(EQUITY))
def test_missing_fields_never_write(tmp_path, field):
    equity = deepcopy(EQUITY)
    del equity[field]
    with pytest.raises(ValueError):
        append_broker_equity_snapshot("run", "2026-10-14", equity, str(tmp_path))
    assert not (tmp_path / "broker_equity_snapshots.csv").exists()


@pytest.mark.parametrize("value", [None, "", "0", True, float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", BROKER_EQUITY_AMOUNT_FIELDS)
def test_invalid_amounts_never_write(tmp_path, field, value):
    equity = {**EQUITY, field: value}
    with pytest.raises(ValueError):
        append_broker_equity_snapshot("run", "2026-10-14", equity, str(tmp_path))
    assert not (tmp_path / "broker_equity_snapshots.csv").exists()


def test_explicit_broker_zero_is_valid(tmp_path):
    equity = {**EQUITY, **dict.fromkeys(BROKER_EQUITY_AMOUNT_FIELDS, 0.0)}
    assert append_broker_equity_snapshot("zero", "2026-10-14", equity, str(tmp_path))


@pytest.mark.parametrize("replacement", [
    {"total_asset_krw": -1.0}, {"fetched_at_kst": "2026-10-14T20:00:01"},
    {"fetched_at_kst": "invalid"}, {"source": {}}, {"query_parameters": {}},
])
def test_invalid_metadata_or_total(tmp_path, replacement):
    with pytest.raises(ValueError):
        append_broker_equity_snapshot("run", "2026-10-14", {**EQUITY, **replacement}, str(tmp_path))
    assert not (tmp_path / "broker_equity_snapshots.csv").exists()


def test_successful_collection_retries_skip_api(monkeypatch, tmp_path):
    monkeypatch.setenv("PERFORMANCE_KRW_SNAPSHOT_ENABLED", "true")
    fetch = MagicMock(return_value=EQUITY)
    monkeypatch.setattr(runner, "fetch_overseas_portfolio_equity", fetch)
    assert runner.collect_broker_equity_snapshot_safely("run", "2026-10-14", str(tmp_path))
    for _attempt in range(3):
        assert not runner.collect_broker_equity_snapshot_safely("run", "2026-10-14", str(tmp_path))
    fetch.assert_called_once_with()


@pytest.mark.parametrize("error", [APIError("private payload"), RuntimeError("private payload"), OSError("disk")])
def test_api_failure_isolated_and_sanitized(monkeypatch, tmp_path, caplog, error):
    monkeypatch.setenv("PERFORMANCE_KRW_SNAPSHOT_ENABLED", "true")
    monkeypatch.setattr(runner, "fetch_overseas_portfolio_equity", MagicMock(side_effect=error))
    assert not runner.collect_broker_equity_snapshot_safely("run", "2026-10-14", str(tmp_path))
    assert not (tmp_path / "broker_equity_snapshots.csv").exists()
    assert "private payload" not in caplog.text


@pytest.mark.parametrize("enabled", [None, "false", "0", "invalid"])
def test_disabled_by_default_no_api_or_files(monkeypatch, tmp_path, enabled):
    monkeypatch.delenv("PERFORMANCE_KRW_SNAPSHOT_ENABLED", raising=False)
    if enabled is not None:
        monkeypatch.setenv("PERFORMANCE_KRW_SNAPSHOT_ENABLED", enabled)
    fetch = MagicMock(side_effect=AssertionError("Disabled collection called broker"))
    monkeypatch.setattr(runner, "fetch_overseas_portfolio_equity", fetch)
    assert not runner.collect_broker_equity_snapshot_safely("run", "2026-10-14", str(tmp_path))
    fetch.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("contents", ["old,header\n", ",".join(BROKER_EQUITY_SNAPSHOT_HEADERS) + "\npartial\n"])
def test_bad_existing_csv_fails_closed(monkeypatch, tmp_path, contents):
    monkeypatch.setenv("PERFORMANCE_KRW_SNAPSHOT_ENABLED", "true")
    path = tmp_path / "broker_equity_snapshots.csv"
    path.write_text(contents, encoding="utf-8")
    fetch = MagicMock()
    monkeypatch.setattr(runner, "fetch_overseas_portfolio_equity", fetch)
    assert not runner.collect_broker_equity_snapshot_safely("run", "2026-10-14", str(tmp_path))
    fetch.assert_not_called()
    assert path.read_text(encoding="utf-8") == contents
