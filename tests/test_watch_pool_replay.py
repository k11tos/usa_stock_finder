"""Synthetic offline research regressions; no fixture represents investment evidence."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pandas as pd
import pytest

from backtests import watch_pool_replay as replay_module
from backtests.watch_pool_inputs import load_bundle, load_stage_c
from backtests.watch_pool_replay import (
    build_cohort, empty_bundle, evaluate_daily_symbol, fixed_dollar_capacity, replay, write_outputs,
)
from tools.compare_expansion_watch_pool import main
from trend_expansion.watch_pool import publish_watch_pool
from trend_expansion.watch_prices import WatchParameters


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """Any accidental data download fails, including supplemental SEC verification."""
    def fail(*_args, **_kwargs):
        pytest.fail("Replay must remain fully offline")
    monkeypatch.setattr("yfinance.download", fail)
    monkeypatch.setattr("requests.sessions.Session.request", fail)
    monkeypatch.setattr("trend_expansion.research_cache.urlopen", fail)


def sample_bundle():
    bundle = empty_bundle()
    bundle["quantus_snapshots"] = [{'asof_date': "2025-01-02", 'available_at': "2025-01-02T21:00:00Z",
                                        'symbols': ["AAA"], 'sha256': "core-fixture"}]
    stage_c = {'reviewed': True, 'sha256': "stage-c-fixture", 'core_snapshot_sha256': "core-fixture",
                   'available_at': "2025-01-02T21:30:00Z", 'data_cutoff_at': "2025-01-02T21:00:00Z",
                   'listing_asof_at': "2025-01-02T15:00:00Z", 'ranked_coverage_complete': True,
                   'ranked_finalists': [{'symbol': "BBB", 'rank': 1, 'verification': "verified_common_equity"}],
                   'parameters': vars_from_parameters()}
    bundle["quarters"] = [{'rebalance_at': "2025-01-02T22:00:00Z", 'stage_c': stage_c}]
    state = {'available_at': "2025-01-03T13:00:00Z", 'asof_at': "2025-01-03T13:00:00Z",
                 'cash': 1000, 'holdings_value': 0, 'held_symbols': [], 'cooldown_complete': True, 'stop_losses': []}
    bundle["sessions"] = [{'signal_at': "2025-01-03T14:00:00Z", 'bar_date': "2025-01-02", 'state': state,
                               'execution_quotes': [{'symbol': symbol, 'price': 30, 'asof_at': "2025-01-03T13:00:00Z",
                                                      'available_at': "2025-01-03T13:00:00Z"}
                                                 for symbol in ("AAA", "BBB")]}]
    for symbol in ("AAA", "BBB"):
        bundle["metadata"].append({'symbol': symbol, 'asof_at': "2025-01-03T13:00:00Z",
                                       'available_at': "2025-01-03T13:00:00Z",
                                  'values': {'exchange': "NASDAQ", 'quoteType': "EQUITY", 'longName': "Plain Inc"}})
        for index, day in enumerate(pd.bdate_range(end="2025-01-02", periods=252)):
            close = 10 + index * 20 / 251
            bundle["bars"].append({'symbol': symbol, 'date': day.date().isoformat(), 'open': close,
                                      'high': close + .05, 'low': close - .05, 'close': close,
                                      'volume': 200000 + index * 100,
                                       'available_at': day.date().isoformat() + "T22:00:00Z"})
    return bundle


@pytest.mark.parametrize(("core_count", "expected"), [(0, (30, 50, 100)), (40, (30, 50, 60)),
                                                         (60, (30, 40, 40)), (100, (0, 0, 0))])
def test_caps_core_priority_aliases_and_no_forced_fill(core_count, expected):
    core = [f"C{i}" for i in range(core_count)]
    expansion = [{'symbol': f"E{i:03d}", 'rank': i + 1, 'verification': "verified_common_equity"} for i in range(110)]
    if core:
        expansion.insert(0, {'symbol': core[0], 'rank': .5, 'verification': "unknown"})
    for cap, count in zip((30, 50, 100), expected):
        cohort = build_cohort(core + core, expansion, cap)
        assert cohort["core_count"] == core_count
        assert cohort["expansion_count"] == count
        assert cohort["overlap"] == bool(core)
        assert all(cohort["source_by_symbol"][symbol] == "core_quant" for symbol in core)
    assert build_cohort(["BRK.B", "BRK-B"], [], 50)["core_count"] == 1
    verified = [row for row in expansion if row["verification"] == "verified_common_equity"]
    assert build_cohort([], verified[:2], 100)["expansion_count"] <= 2
    assert WatchParameters().max_expansion == 50
    with pytest.raises(ValueError, match="resource bound"):
        WatchParameters(max_expansion=100)


def test_core_only_reproducible_and_daily_live_conditions_equal_across_sources(monkeypatch):
    bundle = sample_bundle()
    original = deepcopy(bundle)
    evaluator = Mock(wraps=evaluate_daily_symbol)
    monkeypatch.setattr(replay_module, "evaluate_daily_symbol", evaluator)
    result = replay(bundle)
    assert bundle == original
    assert result == replay(bundle)
    assert evaluator.call_count == 4  # two symbols, once per daily run, across two replays
    rows = [row for row in result["symbols"] if row["cap"] == 30]
    assert len(rows) == 2
    for field in ("trend_ok", "correlation_ok", "safety_survivor", "new_buy_signal"):
        assert all(row[field] is True for row in rows)
    assert [row["capacity_entries"] for row in result["daily"]] == [1, 2, 2, 2]
    assert [row["capacity_cash_dollars"] for row in result["daily"]] == [910, 820, 820, 820]
    assert result["daily"][0]["capacity_cash_ratio"] == .91
    assert result["daily"][0]["new_positions"] is None
    assert all(value is None for value in result["performance"].values())
    assert result["conclusion"] == "INCONCLUSIVE"
    for cap in (0, 30, 50, 100):
        source_rows = [row for row in result["source_daily"] if row["cap"] == cap]
        daily = next(row for row in result["daily"] if row["cap"] == cap)
        assert sum(row["watch_count"] for row in source_rows) == daily["watch_count"]
        assert sum(row["capacity_entries"] for row in source_rows) == daily["capacity_entries"]


def capacity(signals, cash=1000, reserve=0, held=None, fee=0, slip=0):
    return fixed_dollar_capacity([{'symbol': symbol, 'price': price} for symbol, price in signals],
                                 {'cash': cash, 'holdings_value': 0, 'held_symbols': held or []},
                                 {'reserve_ratio': reserve, 'fee_per_order': fee, 'slippage_bps': slip})


def test_fixed_dollars_whole_shares_residual_cash_no_phantom_buys():
    result = capacity([("A", 30), ("B", 101), ("C", 0), ("D", float("nan")), ("A", 30)])
    assert [row["quantity"] for row in result["allocations"]] == [3, 0, 0, 0, 0]
    assert result["affordable_new_entries"] == 1
    assert result["capacity_cash_dollars"] == 910
    assert result["signal_capacity_gap_dollars"] == 900
    assert result["rounding_or_price_constraint_dollars"] == 10
    assert capacity([("A", .1)], cash=100)["allocations"][0]["quantity"] == 1000
    assert capacity([("A", 100)], cash=100)["capacity_cash_dollars"] == 0
    assert capacity([("A", 30)], held=["A"])["capacity_entries"] == 0


def test_available_cash_reserves_fees_and_slippage():
    result = capacity([("A", 30), ("B", 30)], cash=100, reserve=.2)
    assert result["intended_reserve_dollars"] == 20
    assert result["capacity_entries"] == 1
    assert result["cash_constrained_signals"] == 1
    assert result["capacity_cash_dollars"] == 40
    assert result["unallocated_nonreserve_cash"] == 20
    result = capacity([("A", 30)], cash=100, fee=1, slip=100)
    assert result["allocations"][0]["quantity"] == 3
    assert result["hypothetical_dollars_invested"] == 91.9
    assert result["capacity_cash_dollars"] == 8.1
    assert capacity([], reserve=.2)["signal_scarcity"] is True
    assert capacity([("A", 100)], cash=99)["capacity_entries"] == 0
    assert capacity([], cash=0)["capacity_cash_ratio"] is None


@pytest.mark.parametrize("bad", [-1, float("inf"), True])
def test_invalid_cash_rejected(bad):
    with pytest.raises(ValueError):
        capacity([], cash=bad)


@pytest.mark.parametrize(("change", "reason"), [
    ("old_snapshot", "missing_current_quarter_quantus"), ("no_stage_c", "missing_stage_c"),
    ("future_stage_c", "future_stage_c_available_at"), ("truncated", "truncated_expansion_ranking"),
    ("lineage", "stage_c_core_lineage_mismatch"), ("stale", "stale_stage_c"),
])
def test_missing_quarter_inputs_and_asof_cutoffs(change, reason):
    bundle = sample_bundle()
    stage_c = bundle["quarters"][0]["stage_c"]
    if change == "old_snapshot":
        bundle["quantus_snapshots"][0]["asof_date"] = "2024-12-31"
    elif change == "no_stage_c":
        bundle["quarters"][0]["stage_c"] = None
    elif change == "future_stage_c":
        stage_c["available_at"] = "2025-01-03T21:00:00Z"
    elif change == "truncated":
        stage_c["ranked_coverage_complete"] = False
    elif change == "lineage":
        stage_c["core_snapshot_sha256"] = "wrong"
    else:
        stage_c["asof_date"] = "2024-12-01"
    result = replay(bundle)
    assert result["coverage"][0]["reason"] == reason
    assert not result["daily"]
    assert result["performance_comparable"] is False


def test_latest_available_quantus_per_quarter_only_and_never_future():
    bundle = sample_bundle()
    bundle["quantus_snapshots"] += [{'asof_date': "2025-01-01", 'available_at': "2025-01-01T22:00:00Z",
                                         'symbols': ["OLD"], 'sha256': "old"},
                                    {'asof_date': "2025-01-03", 'available_at': "2025-01-03T22:00:00Z",
                                         'symbols': ["FUTURE"], 'sha256': "future"}]
    assert replay(bundle)["cohorts"][0]["watch_names"] == ["AAA"]
    bundle["quantus_snapshots"].append(deepcopy(bundle["quantus_snapshots"][0]))
    assert replay(bundle)["coverage"][0]["reason"] == "ambiguous_quantus_snapshot"


@pytest.mark.parametrize(("change", "reason"), [("missing", "missing_ohlcv"), ("stale", "stale_ohlcv"),
    ("invalid", "invalid_ohlcv"), ("short", "insufficient_history"), ("duplicate", "duplicate_bar"),
    ("metadata", "missing_asof_metadata"), ("cooldown_missing", "missing_cooldown_state"),
    ("quote_missing", "missing_execution_quote")])
def test_data_failures_not_signal_scarcity_and_paired_denominators(change, reason):
    bundle = sample_bundle()
    if change == "missing":
        bundle["bars"] = [row for row in bundle["bars"] if row["symbol"] != "BBB"]
    elif change == "stale":
        bundle["bars"] = [row for row in bundle["bars"] if (row["symbol"], row["date"]) != ("BBB", "2025-01-02")]
    elif change == "invalid":
        bundle["bars"][-1]["close"] = 0
    elif change == "short":
        bundle["bars"] = bundle["bars"][:252] + bundle["bars"][-150:]
    elif change == "duplicate":
        bundle["bars"].append(deepcopy(bundle["bars"][-1]))
    elif change == "metadata":
        bundle["metadata"][-1]["available_at"] = "2025-01-04T00:00:00Z"
    elif change == "cooldown_missing":
        bundle["sessions"][0]["state"]["cooldown_complete"] = False
    else:
        bundle["sessions"][0]["execution_quotes"] = []
    result = replay(bundle)
    assert reason in result["daily"][1]["exclusions"]
    assert result["daily"][1]["signal_scarcity"] is False
    assert result["daily"][1]["cash_cause"] == "data_unavailable"
    assert all(row["cash_ratio_days"] == 0 for row in result["quarterly"])
    assert all(row["capacity_fraction_days_cash_gt_50"] is None for row in result["quarterly"])
    assert all(row["capacity_days"] == 0 and row["mean_capacity_entries"] is None
               for row in result["quarterly"])
    for row in result["source_quarterly"]:
        assert row["days"] == 1
        assert row["capacity_days"] == 0
        for field in ("affordable_new_entries", "capacity_entries", "hypothetical_dollars_invested"):
            assert row["mean_" + field] is None


@pytest.mark.parametrize("missing", [None, "bars", "metadata", "execution_quotes"])
@pytest.mark.parametrize("symbol", ["AAA", "BBB"])
@pytest.mark.parametrize("first_core_price", [30, 101])
def test_capacity_means_use_paired_days_under_asymmetric_missingness(missing, symbol, first_core_price):
    bundle = sample_bundle()
    first = bundle["sessions"][0]
    second = deepcopy(first)
    second["signal_at"] = "2025-01-06T14:00:00Z"
    second["state"].update(asof_at="2025-01-06T13:00:00Z", available_at="2025-01-06T13:00:00Z")
    for quote in second["execution_quotes"]:
        quote.update(asof_at="2025-01-06T13:00:00Z", available_at="2025-01-06T13:00:00Z")
    bundle["sessions"].append(second)
    first["execution_quotes"][0]["price"] = first_core_price
    if missing == "execution_quotes":
        first["execution_quotes"] = [row for row in first["execution_quotes"] if row["symbol"] != symbol]
    elif missing:
        # The same frozen observations are unavailable on day one, available
        # on day two. No future information repairs the earlier evaluation.
        for row in bundle[missing]:
            if row["symbol"] == symbol:
                row["available_at"] = "2025-01-04T13:00:00Z"
    result = replay(bundle)
    paired_days = 1 if missing else 2
    for row in result["quarterly"]:
        assert row["days"] == 2
        assert row["capacity_days"] == row["cash_ratio_days"] == paired_days
        expected = 1 if row["cap"] == 0 else 2
        if not missing and first_core_price == 101:
            expected -= .5
        assert row["mean_capacity_entries"] == expected
    for row in result["source_quarterly"]:
        assert row["days"] == 2
        assert row["capacity_days"] == paired_days
        expected = int(row["source_pool"] == "core_quant" or row["cap"] != 0)
        if not missing and row["source_pool"] == "core_quant" and first_core_price == 101:
            expected = .5
        assert row["mean_capacity_entries"] == expected
        assert row["mean_affordable_new_entries"] == expected
        assert row["mean_hypothetical_dollars_invested"] == expected * 90
        # Signal/coverage means retain their established all-observation denominator.
        selected = [daily for daily in result["source_daily"]
                    if (daily["cap"], daily["source_pool"]) == (row["cap"], row["source_pool"])]
        for field in ("watch_count", "trend_ok", "safety_survivors", "new_buy_signals"):
            assert row["mean_" + field] == sum(day[field] for day in selected) / 2
        assert sum(day["paired_complete_day"] for day in selected) == paired_days
    if missing:
        incomplete = [row for row in result["daily"] if row["signal_at"] == first["signal_at"]]
        assert all(not row["paired_complete_day"] for row in incomplete)
        affected = next(row for row in incomplete if row["cap"] == 30)
        assert affected["data_failure_count"] == 1
        assert affected["cash_cause"] == "data_unavailable"
        assert affected["signal_capacity_gap_dollars"] is None
        assert affected["signal_scarcity"] is False
        # Partial/zero counts stay visible as diagnostics, excluded from means.
        assert affected["capacity_entries"] == int(symbol == "AAA" or first_core_price == 30)


def test_future_bars_and_late_observations_cannot_leak():
    bundle = sample_bundle()
    expected = replay(bundle)
    for symbol in ("AAA", "BBB"):
        future = dict(bundle["bars"][-1], symbol=symbol, date="2025-01-03", close=99999)
        bundle["bars"].append(future)
        correction = dict(bundle["bars"][0], symbol=symbol, available_at="2025-02-01T00:00:00Z", close=9999)
        bundle["bars"].append(correction)
    assert replay(bundle) == expected


def test_cooldown_exact_boundary_and_no_duplicate_holdings():
    bundle = sample_bundle()
    bundle["sessions"][0]["state"]["stop_losses"] = [{'symbol': "AAA", 'date': "2025-01-01", 'loss_pct': -.08}]
    assert replay(bundle)["daily"][0]["exclusions"] == {"stop_loss_cooldown": 1}
    bundle["sessions"][0]["state"]["stop_losses"][0]["date"] = "2024-12-29"
    assert replay(bundle)["daily"][0]["capacity_entries"] == 1
    bundle["sessions"][0]["state"]["held_symbols"] = ["AAA"]
    assert replay(bundle)["daily"][0]["capacity_entries"] == 0


def test_source_agnostic_quarantine_and_pinned_rules(monkeypatch):
    bundle = sample_bundle()
    monkeypatch.setattr("stock_analysis.UsaStockFinder.get_event_quarantine_metrics",
                        lambda *_a, **_k: {"is_event_quarantine": True, "max_gap_up_pct": .2,
                                           "days_since_gap": 1, "current_vs_gap_close_pct": 0,
                                           "drawdown_from_post_gap_high_pct": 0})
    result = replay(bundle)
    assert result["daily"][1]["exclusions"] == {"event_quarantine": 2}
    assert result["daily"][1]["capacity_entries"] == 0
    monkeypatch.setattr("stock_analysis.UsaStockFinder.get_event_quarantine_metrics",
                        lambda *_a, **_k: {"is_event_quarantine": False})
    monkeypatch.setattr("stock_analysis.UsaStockFinder.get_special_situation_price_pinned_metrics",
                        lambda *_a, **_k: {'is_special_situation': True, 'max_gap_up_pct': .2, 'days_since_gap': 10,
                                               'post_gap_atr_pct': .001, 'atr_pct': .001, 'recent_range_pct': .001,
                                               'recent_abs_return_pct': .001})
    assert replay(bundle)["daily"][1]["exclusions"] == {"special_situation": 2}


def test_empty_inputs_stable_artifacts_cli_and_no_fake_metrics(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    assert main(["--output", str(first)]) == 0
    assert main(["--output", str(second)]) == 0
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {p.name: p.read_bytes() for p in second.iterdir()}
    result = json.loads((first / "comparison.json").read_bytes())
    root = Path(__file__).resolve().parents[1]
    for name, digest in result["implementation_sha256"].items():
        assert digest == hashlib.sha256((root / name).read_bytes()).hexdigest()
    assert result["resolved_data_quality_config"] == {
        "MIN_PRICE_THRESHOLD": replay_module.DataQualityConfig.MIN_PRICE_THRESHOLD}
    assert (first / "comparison.json").read_text() == json.dumps(
        result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    assert result["conclusion"] == "INCONCLUSIVE"
    assert not result["cohorts"]
    assert result["performance"]["total_return"] is None
    assert "NOT COMPARABLE" in (first / "comparison.md").read_text()
    with pytest.raises(ValueError, match="live"):
        main(["--output", str(Path(__file__).resolve().parents[1] / "data/replay-results")])


def test_deterministic_comparison_artifacts_and_zero_denominators(tmp_path):
    result = replay(sample_bundle())
    write_outputs(result, tmp_path / "one")
    write_outputs(replay(sample_bundle()), tmp_path / "two")
    assert {p.name: p.read_bytes() for p in (tmp_path / "one").iterdir()} == {
        p.name: p.read_bytes() for p in (tmp_path / "two").iterdir()}
    bundle = sample_bundle()
    bundle["sessions"] = []
    assert all(row["mean_capacity_entries"] is None for row in replay(bundle)["quarterly"])


def stage_c_fixture(tmp_path, *, outside=False, parameters=None):
    """A tiny genuine Stage C publisher format; contents are explicitly synthetic."""
    core = tmp_path / "core.csv"
    core.write_text("symbol\nAAA\n", encoding="utf-8")
    from trend_expansion.research_cache import sha256
    core_sha = sha256(core.read_bytes())
    status = "not_evaluated" if outside else "verified"
    audit = [{'symbol': "BBB", 'rank': 1, 'verification': {'status': status}, 'reason': "outside_watch_capacity"}]
    metadata = {'schema_version': 1, 'research_only': True, 'asof_date': "2025-01-02",
                    'asof_timestamp': "2025-01-02T21:00:00Z",
                    'parameters': vars_from_parameters() if parameters is None else parameters,
                    'lineage': {'core': {'unique_count': 1, 'sha256': core_sha, 'asof_date': "2025-01-02"},
                                 'stage_a': {'metadata': {'created_at_utc': "2025-01-02T15:00:00Z"}}},
                    'raw_sources': {"fixture": {'observed_at_utc': "2025-01-02T21:30:00Z"}},
                    'counts': {'numeric_eligible': 1}, 'point_in_time_limitations': ["synthetic regression only"],
                    'price_convention': "yahoo_close_split_adjusted_dividend_unadjusted"}
    result = {'watch': [{'symbol': "AAA", 'source_pool': "core_quant"}], 'audit': audit, 'metadata': metadata}
    return publish_watch_pool(tmp_path / "watch", result), core


def vars_from_parameters():
    from dataclasses import asdict
    return asdict(WatchParameters())


@pytest.mark.parametrize(("key", "value"), [
    ("min_price", 6), ("max_price", 89), ("min_bars", 253),
    ("liquidity_sessions", 21), ("min_dollar_volume", 3_000_000),
    ("short_sessions", 64), ("long_sessions", 127),
    ("short_weight", .5), ("long_weight", .5),
    ("market_cap_policy", "require_known"), ("min_market_cap", 400_000_000),
    ("target_total", 99), ("max_expansion", 49), ("max_verifications", 149),
])
def test_stage_c_rejects_every_changed_parameter(tmp_path, key, value):
    params = vars_from_parameters()
    params[key] = value
    # Publish valid nondefault weight pairs rather than testing invalid sums.
    if key in {"short_weight", "long_weight"}:
        params.update(short_weight=.5, long_weight=.5)
    WatchParameters(**params)
    directory, _ = stage_c_fixture(tmp_path, parameters=params)
    with pytest.raises(ValueError, match="Stage C hypotheses differ: " + key
                       if key != "long_weight" else "Stage C hypotheses differ: short_weight"):
        load_stage_c(directory)
    bundle = sample_bundle()
    bundle["quarters"][0]["stage_c"]["parameters"] = params
    result = replay(bundle)
    assert result["coverage"][0]["reason"] == "incompatible_stage_c_hypotheses"
    assert not result["daily"]
    assert not result["cohorts"]


@pytest.mark.parametrize("change", ["missing", "unknown", "boolean", "null"])
def test_stage_c_rejects_incomplete_or_invalid_parameter_schema(tmp_path, change):
    params = vars_from_parameters()
    if change == "missing":
        del params["market_cap_policy"]
    elif change == "unknown":
        params["unknown_gate"] = 1
    elif change == "boolean":
        params["min_price"] = True
    else:
        params["min_market_cap"] = None
    directory, _ = stage_c_fixture(tmp_path, parameters=params)
    with pytest.raises((ValueError, TypeError)):
        load_stage_c(directory)
    bundle = sample_bundle()
    bundle["quarters"][0]["stage_c"]["parameters"] = params
    assert replay(bundle)["coverage"][0]["reason"] == "incompatible_stage_c_hypotheses"


def test_incompatible_stage_c_bundle_fails_closed(tmp_path):
    params = vars_from_parameters()
    params["market_cap_policy"] = "require_known"
    directory, core = stage_c_fixture(tmp_path, parameters=params)
    bundle = sample_bundle()
    bundle["quantus_snapshots"][0]["path"] = core.name
    bundle["quarters"][0] = {
        "rebalance_at": "2025-01-02T22:00:00Z",
        "stage_c_path": str(directory.relative_to(tmp_path)),
        "stage_c_available_at": "2025-01-02T21:40:00Z",
    }
    manifest = tmp_path / "bundle.json"
    manifest.write_text(json.dumps(bundle))
    loaded, provenance = load_bundle(manifest)
    assert loaded["quarters"][0]["stage_c"] is None
    assert str(directory.relative_to(tmp_path)) not in provenance
    result = replay(loaded)
    assert result["coverage"][0]["reason"] == "invalid_or_missing_stage_c:ValueError"
    assert not result["daily"]


def test_data_quality_provenance_records_consumed_value(monkeypatch):
    monkeypatch.setattr(replay_module.DataQualityConfig, "MIN_PRICE_THRESHOLD", .02)
    # Config resolves at import time; a later env change must not mislabel it.
    monkeypatch.setenv("MIN_PRICE_THRESHOLD", "999")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "irrelevant-test-secret")
    result = replay(sample_bundle())
    assert result["resolved_data_quality_config"] == {"MIN_PRICE_THRESHOLD": .02}
    assert "irrelevant-test-secret" not in json.dumps(result)


def test_environment_data_quality_provenance_and_byte_stable_artifacts(tmp_path):
    # Fresh processes exercise config.py's real environment resolution without
    # reloading shared config classes in the pytest process.
    script = '''
import json
from pathlib import Path
import sys
from unittest.mock import patch
from backtests.watch_pool_replay import replay, write_outputs
with patch("yfinance.download", side_effect=AssertionError("network forbidden")), \\
     patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden")), \\
     patch("trend_expansion.research_cache.urlopen", side_effect=AssertionError("network forbidden")):
    write_outputs(replay(json.load(sys.stdin)), Path(sys.argv[1]))
'''
    artifacts = {}
    for threshold in ("0.01", "100"):
        env = dict(os.environ, MIN_PRICE_THRESHOLD=threshold)
        for repeat in range(2):
            destination = tmp_path / f"{threshold}-{repeat}"
            subprocess.run([sys.executable, "-c", script, str(destination)],
                           input=json.dumps(sample_bundle()), text=True, env=env,
                           check=True, capture_output=True, timeout=60)
            current = {path.name: path.read_bytes() for path in destination.iterdir()}
            if repeat == 0:
                artifacts[threshold] = current
            else:
                assert current == artifacts[threshold]
    low = json.loads(artifacts["0.01"]["comparison.json"])
    high = json.loads(artifacts["100"]["comparison.json"])
    assert low["resolved_data_quality_config"] == {"MIN_PRICE_THRESHOLD": .01}
    assert high["resolved_data_quality_config"] == {"MIN_PRICE_THRESHOLD": 100.0}
    assert low["resolved_strategy_config"] == high["resolved_strategy_config"]
    assert [row["capacity_entries"] for row in low["daily"]] == [1, 2, 2, 2]
    assert [row["capacity_entries"] for row in high["daily"]] == [0, 0, 0, 0]
    assert all(row["reason"] == "trend_failed" for row in high["symbols"])


def test_stage_c_artifact_adapter_and_lineage_cli(tmp_path):
    directory, core = stage_c_fixture(tmp_path)
    normalized = load_stage_c(directory)
    assert normalized["parameters"] == vars_from_parameters()
    assert normalized["ranked_finalists"] == [{'symbol': "BBB", 'rank': 1, 'verification': "verified_common_equity"}]
    bundle = sample_bundle()
    bundle["quantus_snapshots"][0] = {'asof_date': "2025-01-02", 'available_at': "2025-01-02T21:00:00Z",
                                         'path': core.name}
    bundle["quarters"][0] = {'rebalance_at': "2025-01-02T22:00:00Z",
                                 'stage_c_path': str(directory.relative_to(tmp_path)),
                                 'stage_c_available_at': "2025-01-02T21:40:00Z"}
    manifest = tmp_path / "replay.json"
    manifest.write_text(json.dumps(bundle))
    loaded, hashes = load_bundle(manifest)
    assert hashes[core.name] == normalized["core_snapshot_sha256"]
    assert replay(loaded)["daily"][1]["capacity_entries"] == 2
    assert main(["--bundle", str(manifest), "--output", str(tmp_path / "result")]) == 0
    (directory / "audit.json").write_text("[]")
    loaded, _ = load_bundle(manifest)
    assert replay(loaded)["coverage"][0]["reason"].startswith("invalid_or_missing_stage_c")


def test_100_cap_never_certifies_unverified_outside_capacity(tmp_path):
    directory, _ = stage_c_fixture(tmp_path, outside=True)
    result = load_stage_c(directory)
    assert result["ranked_coverage_complete"] is False
    assert not result["ranked_finalists"]
    # An empty cache may diagnose missing evidence but may never fetch it.
    result = load_stage_c(directory, tmp_path / "empty-cache")
    assert result["ranked_coverage_complete"] is False
    assert result["verification_exclusions"][0]["reason"] == "security_unknown"


def test_no_carry_forward_simulation_or_live_state_mutation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    sentinel = tmp_path / "data/stop_loss_log.json"
    sentinel.write_text('{"DO_NOT_READ_OR_CHANGE": true}')
    bundle = sample_bundle()
    second = deepcopy(bundle["sessions"][0])
    second["signal_at"] = "2025-01-06T14:00:00Z"
    second["bar_date"] = "2025-01-03"
    second["state"].update(asof_at="2025-01-06T13:00:00Z", available_at="2025-01-06T13:00:00Z")
    for quote in second["execution_quotes"]:
        quote.update(asof_at="2025-01-06T13:00:00Z", available_at="2025-01-06T13:00:00Z")
    for symbol in ("AAA", "BBB"):
        last = next(row for row in bundle["bars"] if row["symbol"] == symbol and row["date"] == "2025-01-02")
        bundle["bars"].append({**last, "date": "2025-01-03", "available_at": "2025-01-03T22:00:00Z"})
    bundle["sessions"].append(second)
    result = replay(bundle)
    baseline = [row for row in result["daily"] if row["cap"] == 0]
    assert [row["capacity_cash_dollars"] for row in baseline] == [910, 910]
    assert all(row["new_positions"] is None for row in baseline)
    assert sentinel.read_text() == '{"DO_NOT_READ_OR_CHANGE": true}'


@pytest.mark.parametrize("field", ["available_at", "asof_at"])
def test_future_account_state_rejected(field):
    bundle = sample_bundle()
    bundle["sessions"][0]["state"][field] = "2025-01-04T12:00:00Z"
    with pytest.raises(ValueError, match="account|Account"):
        replay(bundle)


def test_strict_cash_threshold_and_zero_equity_denominators():
    bundle = sample_bundle()
    bundle["sessions"][0]["state"]["cash"] = 180
    result = replay(bundle)
    assert result["daily"][0]["capacity_cash_ratio"] == .5
    assert result["quarterly"][0]["capacity_fraction_days_cash_gt_50"] == 0
    assert result["daily"][0]["target_affordable_entries"] == 1
    bundle["sessions"][0]["state"]["cash"] = 0
    result = replay(bundle)
    assert all(row["capacity_entries"] == 0 for row in result["daily"])
    assert all(row["cash_ratio_days"] == 0 for row in result["quarterly"])
    assert all(row["capacity_days"] == 0 and row["mean_capacity_entries"] is None
               for row in result["quarterly"] + result["source_quarterly"])


def test_unqualified_watch_name_remains_watch_name():
    bundle = sample_bundle()
    for index, row in enumerate(bundle["bars"][252:]):
        row.update(open=30 - index * .05, high=31 - index * .05,
                   low=29 - index * .05, close=30 - index * .05)
    result = replay(bundle)
    assert result["cohorts"][1]["watch_names"] == ["AAA", "BBB"]
    assert result["daily"][1]["exclusions"] == {"trend_failed": 1}
    assert result["daily"][1]["data_complete"] is True


def test_missing_latest_quantus_file_never_falls_back_to_old_list(tmp_path):
    bundle = sample_bundle()
    bundle["quantus_snapshots"] = [{'asof_date': "2025-01-02", 'available_at': "2025-01-02T21:00:00Z",
                                    'path': "absent.csv"}]
    bundle["quarters"][0].pop("stage_c")
    manifest = tmp_path / "replay.json"
    manifest.write_text(json.dumps(bundle))
    loaded, _ = load_bundle(manifest)
    assert replay(loaded)["coverage"][0]["reason"] == "missing_quantus_file"


def test_supplemental_cached_verification_without_changing_stage_c_bound(tmp_path, monkeypatch):
    directory, _ = stage_c_fixture(tmp_path, outside=True)
    from backtests import watch_pool_inputs
    verifier = Mock()
    verifier.verify.return_value = {"status": "verified", "sources": []}
    monkeypatch.setattr(watch_pool_inputs, "SecVerifier", lambda *_: verifier)
    result = load_stage_c(directory, tmp_path / "cache")
    assert result["ranked_coverage_complete"] is True
    assert result["ranked_finalists"][0]["symbol"] == "BBB"
    verifier.verify.assert_called_once_with("BBB")
    assert WatchParameters().max_expansion == 50


@pytest.mark.parametrize("kind", ["metadata", "bars"])
def test_api_error_is_unknown_data_not_numeric_failure(kind):
    bundle = sample_bundle()
    bundle[kind][-1]["error"] = "provider_request_failed"
    result = replay(bundle)
    assert result["daily"][1]["data_complete"] is False
    assert result["daily"][1]["cash_cause"] == "data_unavailable"
    assert result["daily"][1]["signal_capacity_gap_dollars"] is None


def test_duplicate_daily_observations_rejected():
    bundle = sample_bundle()
    duplicate = deepcopy(bundle["sessions"][0])
    duplicate["signal_at"] = "2025-01-03T15:00:00Z"
    bundle["sessions"].append(duplicate)
    with pytest.raises(ValueError, match="Duplicate daily"):
        replay(bundle)


def test_comparison_publication_idempotent_and_refuses_changed_inputs(tmp_path):
    result = replay(empty_bundle())
    destination = tmp_path / "result"
    write_outputs(result, destination)
    original = {path.name: path.read_bytes() for path in destination.iterdir()}
    write_outputs(result, destination)
    result["assumptions"]["fee_per_order"] = 1
    with pytest.raises(ValueError, match="Immutable"):
        write_outputs(result, destination)
    assert original == {path.name: path.read_bytes() for path in destination.iterdir()}


def test_no_partial_artifacts_on_publication_failure(tmp_path, monkeypatch):
    def fail(*_args):
        raise OSError("injected publication failure")
    monkeypatch.setattr(replay_module.os, "rename", fail)
    with pytest.raises(OSError, match="injected"):
        write_outputs(replay(empty_bundle()), tmp_path / "output")
    assert not list(tmp_path.iterdir())


def test_daily_bar_captured_before_close_is_not_a_completed_bar():
    bundle = sample_bundle()
    bundle["bars"][-1]["available_at"] = "2025-01-02T15:00:00Z"
    result = replay(bundle)
    assert result["daily"][1]["exclusions"] == {"observation_before_bar_close": 1}
    assert result["daily"][1]["data_complete"] is False


@pytest.mark.parametrize("symbol", ["AAA", "BBB"])
@pytest.mark.parametrize(("day", "available", "reason"), [
    ("2023-12-01", "2023-12-01T22:00:00Z", ""),
    ("2024-01-03", "2024-01-03T22:00:00Z", ""),  # exclusive 365-day lower bound
    ("2024-01-04", "2024-01-04T22:00:00Z", "ohlcv_api_error"),
    ("2025-01-02", "2025-01-02T22:00:00Z", "ohlcv_api_error"),
    ("2025-01-02", "2025-01-03T14:00:00Z", "ohlcv_api_error"),  # signal cutoff inclusive
    ("2025-01-02", "2025-01-03T14:00:01Z", ""),
    ("2025-01-03", "2025-01-03T13:00:00Z", ""),  # future session, even if available
])
def test_bar_errors_only_affect_required_asof_window(symbol, day, available, reason):
    bundle = sample_bundle()
    # Error rows deliberately have no OHLCV payload. Out-of-window provider
    # failures cannot poison a complete pair; required-window failures must.
    bundle["bars"].append({'symbol': symbol, 'date': day, 'available_at': available,
                           'error': "provider_request_failed"})
    result = replay(bundle)
    assert result["coverage"][0]["comparable_inputs"] is True
    assert all(row["paired_complete_day"] == (not reason) for row in result["daily"])
    for row in result["daily"]:
        affected = bool(reason) and (symbol == "AAA" or row["cap"] != 0)
        assert row["exclusions"] == ({reason: 1} if affected else {})
        assert row["data_complete"] == (not affected)
        assert row["data_failure_count"] == int(affected)
        if affected:
            assert row["cash_cause"] == "data_unavailable"
            assert row["signal_capacity_gap_dollars"] is None
            assert row["signal_scarcity"] is False
        else:
            assert row["capacity_entries"] == (1 if row["cap"] == 0 else 2)
    assert all(row["capacity_days"] == (0 if reason else 1) for row in result["quarterly"])
    assert all(row["paired_complete_day"] == (not reason) for row in result["source_daily"])
    assert all(row["capacity_days"] == (0 if reason else 1) for row in result["source_quarterly"])


@pytest.mark.parametrize("kind", ["duplicate", "before_close", "corrupt"])
def test_obsolete_integrity_failures_do_not_affect_current_window(kind):
    bundle = sample_bundle()
    old = dict(bundle["bars"][-1], date="2024-01-03", available_at="2024-01-03T22:00:00Z")
    if kind == "duplicate":
        bundle["bars"].append(dict(old))
    elif kind == "before_close":
        old["available_at"] = "2024-01-03T15:00:00Z"
    else:
        old["close"] = "corrupt"
    expected = replay(sample_bundle())
    bundle["bars"].append(old)
    assert replay(bundle) == expected


@pytest.mark.parametrize(("change", "reason"), [
    ("gap", "history_gap_or_suspension"), ("warmup", "insufficient_history"),
    ("missing_column", "invalid_ohlcv"), ("range", "invalid_ohlc_range"),
])
def test_old_history_cannot_repair_missing_or_corrupt_required_data(change, reason):
    bundle = sample_bundle()
    # Plenty of obsolete history cannot satisfy the daily MA warmup.
    old = [dict(bundle["bars"][-1], date=day.date().isoformat(),
                available_at=day.date().isoformat() + "T22:00:00Z")
           for day in pd.bdate_range(end="2024-01-03", periods=252)]
    if change == "gap":
        bundle["bars"] = [row for row in bundle["bars"] if row["symbol"] != "BBB"
                          or not "2024-06-03" <= row["date"] <= "2024-06-07"]
    elif change == "warmup":
        bundle["bars"] = bundle["bars"][:252] + bundle["bars"][-150:]
    elif change == "missing_column":
        for row in bundle["bars"]:
            if row["symbol"] == "BBB":
                del row["volume"]
    else:
        bundle["bars"][-1]["low"] = 100
    bundle["bars"] += old
    result = replay(bundle)
    assert result["daily"][1]["exclusions"] == {reason: 1}
    assert result["daily"][1]["data_complete"] is False
    assert all(not row["paired_complete_day"] for row in result["daily"])
    assert all(row["capacity_days"] == 0 for row in result["quarterly"])


@pytest.mark.parametrize(("asof", "reason"), [
    ("2024-12-27T14:00:00Z", ""),  # exactly seven elapsed days, inclusive
    ("2024-12-27T09:00:00-05:00", ""),  # same instant in exchange-local offset
    ("2024-12-27T13:59:59Z", "stale_metadata"),
    ("2024-12-27T08:00:00Z", "stale_metadata"),
    ("2024-12-27T14:00:01Z", ""),
    ("2025-01-03T14:00:00Z", ""),
    ("2025-01-03T14:00:01Z", "missing_asof_metadata"),
])
def test_metadata_full_elapsed_freshness_and_paired_diagnostics(asof, reason):
    bundle = sample_bundle()
    bundle["metadata"][-1].update(asof_at=asof, available_at=asof)
    result = replay(bundle)
    affected = result["daily"][1]
    assert affected["exclusions"] == ({reason: 1} if reason else {})
    assert affected["data_complete"] == (not reason)
    assert affected["data_failure_count"] == int(bool(reason))
    assert all(row["paired_complete_day"] == (not reason) for row in result["daily"])
    assert all(row["capacity_days"] == (0 if reason else 1) for row in result["quarterly"])
    if reason:
        assert affected["cash_cause"] == "data_unavailable"
        assert affected["signal_capacity_gap_dollars"] is None
    else:
        assert affected["capacity_entries"] == 2


@pytest.mark.parametrize("field", ["asof_at", "available_at"])
def test_future_metadata_never_overrides_available_fresh_observation(field):
    bundle = sample_bundle()
    expected = replay(bundle)
    future = dict(bundle["metadata"][-1], error="future_provider_failure")
    future[field] = "2025-01-03T14:00:01Z"
    bundle["metadata"].append(future)
    assert replay(bundle) == expected


@pytest.mark.parametrize("field", ["asof_at", "available_at"])
@pytest.mark.parametrize("invalid", [None, "NaT", "not-a-timestamp", "2025-01-03T13:00:00", "missing"])
def test_invalid_metadata_timestamps_keep_structural_rejection(field, invalid):
    bundle = sample_bundle()
    if invalid == "missing":
        del bundle["metadata"][-1][field]
    else:
        bundle["metadata"][-1][field] = invalid
    with pytest.raises((ValueError, TypeError, KeyError)):
        replay(bundle)
