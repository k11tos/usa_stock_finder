"""Offline Stage C fixtures; never read/write real portfolios or runtime state."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from tools import build_trend_expansion_watch_pool as cli
from trend_expansion import universe_source, watch_pool
from trend_expansion.base_universe import write_filter_outputs
from trend_expansion.research_cache import (
    ResearchCache, ResearchDataError, ResourceLimits, canonical_bytes, sha256,
)
from trend_expansion.security_evidence import TICKERS_URL, SecVerifier, classify_cover
from trend_expansion.watch_pool import build_watch_pool, inspect_watch_pool, publish_watch_pool
from trend_expansion.watch_prices import (
    WatchParameters, asof_cutoff, chart_url, decode_chart, rank_momentum, screen_bars,
)

DAY = "2026-09-30"
PARAMS = WatchParameters()
CASES = json.loads((Path(__file__).parent / "fixtures/watch_security_cases.json").read_text())["cases"]


def daily_bars(*, count=270, start_price=10, end_price=20, volume=300_000, end=DAY):
    dates = pd.bdate_range(end=end, periods=count)
    closes = [start_price + (end_price - start_price) * i / max(count - 1, 1) for i in range(count)]
    return [{"date": day.date().isoformat(), "open": close, "high": close + 1,
             "low": close - 1, "close": close, "volume": volume} for day, close in zip(dates, closes)]


def cache_entry(cache, url, payload, observed="2026-09-30T21:00:00+00:00"):
    cache.directory.mkdir(parents=True, exist_ok=True)
    (cache.directory / f"{sha256(url.encode())}.json").write_bytes(canonical_bytes(
        {"url": url, "sha256": sha256(payload), "body": payload.decode(), "observed_at_utc": observed}))


def seed_prices(cache, symbol, bars=None):
    bars = daily_bars() if bars is None else bars
    zone = ZoneInfo("America/New_York")
    values = {key: [row[key] for row in bars] for key in ("open", "high", "low", "close", "volume")}
    payload = json.dumps({"chart": {"error": None, "result": [{"meta": {"symbol": symbol.replace('.', '-')},
        "timestamp": [int(datetime.fromisoformat(row["date"]).replace(hour=9, minute=30, tzinfo=zone).timestamp())
                      for row in bars], "indicators": {"quote": [values]}}]}}).encode()
    cache_entry(cache, chart_url(symbol, DAY), payload)
    return payload


def cover(symbol, *, title="Common Stock", shell="false", context="class-a", title_context=None):
    return (f'<html><ix:nonNumeric name="dei:TradingSymbol" contextRef="{context}">{symbol}</ix:nonNumeric>'
            f'<ix:nonNumeric name="dei:Security12bTitle" contextRef="{title_context or context}">'
            f'<b>{title}</b></ix:nonNumeric>'
            f'<ix:nonNumeric name="dei:EntityShellCompanyBoolean" contextRef="entity">{shell}</ix:nonNumeric>'
            '</html>').encode()


def seed_evidence(cache, symbols, overrides=None):
    overrides = overrides or {}
    mapping = {}
    for index, symbol in enumerate(symbols):
        case = overrides.get(symbol, CASES.get(symbol, {}))
        cik = case.get("cik", 2000 + index)
        mapping[str(index)] = {"cik_str": cik, "ticker": symbol, "title": "Synthetic"}
        accession = f"{cik:010d}-26-000001"
        submission = {"cik": str(cik), "entityType": case.get("entityType", "operating"),
                      "sic": case.get("sic", "3571"), "filings": {"recent": {
                          "form": ["10-K"], "filingDate": [case.get("filed", "2026-03-01")],
                          "accessionNumber": [accession], "primaryDocument": ["annual.htm"]}}}
        cache_entry(cache, f"https://data.sec.gov/submissions/CIK{cik:010d}.json", canonical_bytes(submission))
        cache_entry(cache, f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/annual.htm",
                    cover(symbol, title=case.get("title", "Common Stock"), shell=case.get("shell", "false")))
    cache_entry(cache, TICKERS_URL, canonical_bytes(mapping))


def inputs(tmp_path, symbols, core_count=0, core_symbols=None):
    listing_dir = tmp_path / "listing"
    text = ("Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
            + "".join(f"{s}|{s} Trust Inc. Common Stock|Q|N|N|100|N|N\n" for s in symbols))
    # Ensure both Stage A directories have a usable row, even when only one symbol.
    other = ("ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
             f"{symbols[0]}|{symbols[0]} Common Stock|N|{symbols[0]}|N|100|N|{symbols[0]}\n")
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 30, 20, 30, tzinfo=timezone.utc).astimezone(tz)
    with patch.object(universe_source, "datetime", FrozenDateTime):
        universe_source.build_snapshot(listing_dir, snapshot_date=DAY,
                                       downloader=lambda url: (text if "nasdaqlisted" in url else other).encode())
    records, _ = universe_source.load_snapshot(listing_dir)
    write_filter_outputs(records, listing_dir / "base_universe.csv", listing_dir / "exclusions.json")
    core = tmp_path / "current_core.csv"
    core.write_text("symbol\n" + "\n".join(core_symbols or [f"C{i:03d}" for i in range(core_count)]) + "\n")
    return {"listing_dir": listing_dir, "core_csv": core, "core_asof_date": DAY,
            "asof_date": DAY, "session_date": DAY}


def scenario(tmp_path, symbols, **kwargs):
    args = inputs(tmp_path, symbols, **kwargs)
    cache = ResearchCache(tmp_path / "cache")
    for symbol in symbols:
        seed_prices(cache, symbol)
    seed_evidence(cache, symbols)
    return args, cache


@pytest.mark.parametrize("price,reason", [(5, None), (90, None), (4.999, "price_out_of_band"),
                                         (90.001, "price_out_of_band")])
def test_inclusive_price_boundaries(price, reason):
    result = screen_bars(daily_bars(start_price=price, end_price=price, volume=1_000_000), DAY, PARAMS)
    assert result["reason"] == reason
    assert result["ohlcv_validity"] == "valid"


@pytest.mark.parametrize("count,reason", [(251, "insufficient_history"), (252, None)])
def test_adequate_history(count, reason):
    assert screen_bars(daily_bars(count=count), DAY, PARAMS)["reason"] == reason


@pytest.mark.parametrize("field,value,reason", [
    ("close", 0, "zero_or_negative_price"), ("open", -1, "zero_or_negative_price"),
    ("volume", 0, "zero_or_negative_volume"), ("volume", -1, "zero_or_negative_volume"),
    ("high", float("inf"), "nonfinite_bar"), ("low", float("nan"), "nonfinite_bar"),
    ("open", None, "missing_or_invalid_bar"), ("close", "bad", "missing_or_invalid_bar"),
    ("high", 1, "inconsistent_ohlc"), ("date", "2026-10-01", "future_bar"),
    ("date", "2026-09-27", "invalid_bar_date"), ("date", "bad", "missing_or_invalid_bar"),
])
def test_bad_bar_diagnoses(field, value, reason):
    bars = daily_bars()
    bars[-1][field] = value
    result = screen_bars(bars, DAY, PARAMS)
    assert result["reason"] == reason
    assert result["ohlcv_validity"] == "invalid"


def test_missing_stale_duplicate_and_suspension_gap():
    assert screen_bars([], DAY, PARAMS)["reason"] == "missing_bars"
    bars = daily_bars()
    assert screen_bars(bars[:-1], DAY, PARAMS)["reason"] == "stale_bars"
    assert screen_bars(bars + bars[-1:], DAY, PARAMS)["reason"] == "duplicate_bar_date"
    assert screen_bars(bars[:100] + bars[110:], DAY, PARAMS)["reason"] == "history_gap_or_suspension"
    del bars[0]["volume"]
    assert screen_bars(bars, DAY, PARAMS)["reason"] == "missing_or_invalid_bar"


def test_dollar_volume_product_mean_and_threshold():
    bars = daily_bars(start_price=20, end_price=20, volume=100_000)
    assert screen_bars(bars, DAY, PARAMS)["avg_dollar_volume_20"] == 2_000_000
    assert screen_bars(bars, DAY, PARAMS)["reason"] is None
    bars[-21]["volume"] = 999999999  # strictly trailing 20
    bars[-1]["volume"] = 99_999
    result = screen_bars(bars, DAY, PARAMS)
    assert result["reason"] == "low_dollar_volume"
    assert result["avg_dollar_volume_20"] == 1_999_999
    # Product of means would be incorrect when prices/volume covary.
    for i, row in enumerate(bars[-20:]):
        row.update(open=10 + i, close=10 + i, high=11 + i, low=9 + i, volume=100_000 * (i + 1))
    expected = sum(row["close"] * row["volume"] for row in bars[-20:]) / 20
    assert screen_bars(bars, DAY, PARAMS)["avg_dollar_volume_20"] == expected


def test_return_arithmetic_and_future_bar_never_used():
    bars = daily_bars()
    result = screen_bars(bars, DAY, PARAMS)
    assert result["return_3m"] == bars[-1]["close"] / bars[-64]["close"] - 1
    assert result["return_6m"] == bars[-1]["close"] / bars[-127]["close"] - 1
    future = daily_bars(count=1, end="2026-10-01", end_price=1000)
    assert screen_bars(bars + future, DAY, PARAMS)["reason"] == "future_bar"
    assert "return_3m" not in screen_bars(bars + future, DAY, PARAMS)


def test_session_and_asof_dates_are_explicit():
    assert asof_cutoff(DAY, DAY) == "2026-09-30T16:00:00-04:00"
    assert asof_cutoff("2026-10-04", "2026-10-02") == "2026-10-02T16:00:00-04:00"
    assert asof_cutoff("2026-01-30", "2026-01-30").endswith("-05:00")
    for asof, session in [("2099-01-01", "2099-01-01"), (DAY, "2026-10-01"),
                          ("2026-10-04", "2026-10-04"), (DAY, "2026-09-23")]:
        with pytest.raises(ValueError):
            asof_cutoff(asof, session)


def test_stable_average_percentiles_and_symbol_ties():
    rows = [{"symbol": "B", "return_3m": 0.1, "return_6m": 0.2},
            {"symbol": "A", "return_3m": 0.1, "return_6m": 0.2},
            {"symbol": "C", "return_3m": 0, "return_6m": -0.1}]
    ranked = rank_momentum(rows, PARAMS)
    assert ranked == rank_momentum(list(reversed(rows)), PARAMS)
    assert [row["symbol"] for row in ranked] == ["A", "B", "C"]
    assert ranked[0]["percentile_3m"] == ranked[0]["percentile_6m"] == 2.5 / 3
    assert ranked[-1]["score"] == pytest.approx(1 / 3)
    assert rank_momentum([], PARAMS) == []
    assert rank_momentum(rows[:1], PARAMS)[0]["score"] == 1


@pytest.mark.parametrize("core_count,needed,total", [(40, 50, 90), (60, 40, 100), (100, 0, 100)])
def test_watch_bounds_and_core_count_before_live_filter(tmp_path, core_count, needed, total):
    symbols = [f"S{i:03d}" for i in range(55)]
    args, cache = scenario(tmp_path, symbols, core_count=core_count)
    result = build_watch_pool(**args, cache=cache)
    assert result["metadata"]["counts"]["needed"] == needed
    assert result["metadata"]["counts"]["expansion"] == needed
    assert len(result["watch"]) == total
    assert result["metadata"]["lineage"]["core"]["eligibility_filter_applied"] is False
    assert sum(result["metadata"]["counts"]["reasons"].values()) == 55
    assert len(result["metadata"]["raw_sources"]) == (0 if needed == 0 else 55 + 1 + needed * 2)


def test_insufficient_qualified_and_core_priority_dedupe(tmp_path):
    args, cache = scenario(tmp_path, ["A", "FBRT", "BAD"], core_symbols=["A-US", "A-US", " c/a "])
    # Production normalization: suffix removal and slash -> hyphen; count before live filter.
    seed_prices(cache, "BAD", daily_bars(end_price=100))
    result = build_watch_pool(**args, cache=cache)
    assert [(r["symbol"], r["source_pool"]) for r in result["watch"]] == [
        ("A", "core_quant"), ("C-A", "core_quant"), ("FBRT", "trend_expansion")]
    assert result["metadata"]["counts"]["needed"] == 50
    assert result["metadata"]["counts"]["expansion"] == 1
    assert result["audit"][0]["reason"] == "core_overlap"
    assert result["audit"][0]["ohlcv_validity"] == "not_evaluated"


def test_security_positive_fund_denial_unknown_and_next_ranked(tmp_path):
    args, cache = scenario(tmp_path, ["RMT", "RVT", "UNKNOWN", "FBRT", "ZZZ"])
    for index, symbol in enumerate(["RMT", "RVT", "UNKNOWN", "FBRT", "ZZZ"]):
        seed_prices(cache, symbol, daily_bars(end_price=40 - index * 2))
    result = build_watch_pool(**args, cache=cache, params=replace(PARAMS, target_total=1))
    assert [row["symbol"] for row in result["watch"]] == ["FBRT"]
    reasons = {row["symbol"]: row["reason"] for row in result["audit"]}
    assert reasons == {"RMT": "security_not_common", "RVT": "security_not_common",
                       "UNKNOWN": "security_unknown", "FBRT": "selected", "ZZZ": "outside_watch_capacity"}
    fbrt = next(row for row in result["audit"] if row["symbol"] == "FBRT")
    assert fbrt["verification"]["sic"] == "6798"
    assert fbrt["verification"]["classification"] == "operating_common_equity"
    assert len(fbrt["verification"]["sources"]) == 3
    assert result["metadata"]["lineage"]["stage_b"]["counts"]["final_common_equity_count"] == 5


def test_stage_b_alone_never_certifies_and_fallback_after_network_failure(tmp_path):
    args, cache = scenario(tmp_path, ["A", "B"])
    # Missing authoritative evidence for the top finalist, but next one is verified.
    seed_evidence(cache, ["A", "B"])
    url = "https://data.sec.gov/submissions/CIK0000002000.json"
    (cache.directory / f"{sha256(url.encode())}.json").unlink()
    result = build_watch_pool(**args, cache=cache, params=replace(PARAMS, target_total=1))
    assert [r["symbol"] for r in result["watch"]] == ["B"]
    assert result["audit"][0]["verification"]["reason"] == "cache_missing"
    assert result["audit"][0]["reason"] == "security_unknown"


@pytest.mark.parametrize("title,shell,status", [("Common Stock", "false", "verified"),
    ("Common Shares of Beneficial Interest", "false", "verified"),
    ("Ordinary Shares", "false", "verified"), ("Preferred Stock", "false", "not_common"),
    ("Common Stock", "true", "not_common"), ("Common Stock", "", "unknown"),
    ("Depositary Receipts", "false", "unknown")])
def test_cover_requires_class_level_common_and_nonshell_evidence(title, shell, status):
    assert classify_cover(cover("ABC", title=title, shell=shell), "ABC")[0] == status
    assert classify_cover(cover("ABC", title_context="different"), "ABC")[0] == "unknown"
    assert classify_cover(cover("OTHER"), "ABC")[0] == "unknown"


def test_future_filing_and_future_observation_fail_closed(tmp_path):
    cache = ResearchCache(tmp_path)
    seed_evidence(cache, ["A"], {"A": {"filed": "2026-10-01"}})
    assert SecVerifier(cache, DAY).verify("A")["reason"] == "annual_filing_unavailable_asof"
    cache_entry(cache, TICKERS_URL, canonical_bytes({}), observed="2026-10-02T12:00:00+00:00")
    assert SecVerifier(cache, DAY).verify("A")["reason"] == "source_observed_after_asof"


def test_verification_resource_cap_and_expansion_shortfall(tmp_path):
    args, cache = scenario(tmp_path, ["UNKNOWN", "ZZZ"])
    result = build_watch_pool(**args, cache=cache, params=replace(PARAMS, max_verifications=1))
    assert result["metadata"]["counts"]["expansion"] == 0
    assert result["metadata"]["counts"]["verification_attempted"] == 1
    assert result["audit"][1]["reason"] == "verification_budget_exhausted"


def test_market_cap_policy_missing_unknown_not_verified(tmp_path):
    args, cache = scenario(tmp_path, ["A"])
    result = build_watch_pool(**args, cache=cache)
    assert result["audit"][0]["market_cap_status"] == "unknown"
    assert result["audit"][0]["market_cap"] is None
    assert result["metadata"]["counts"]["expansion"] == 1
    strict = build_watch_pool(**args, cache=cache, params=replace(PARAMS, market_cap_policy="require_known"))
    assert strict["audit"][0]["reason"] == "market_cap_unknown"
    cap = {"A": {"value": 300_000_000, "asof_date": DAY, "currency": "USD",
                 "source_url": "https://example.com/sourced-cap", "coverage_verified": True}}
    strict = build_watch_pool(**args, cache=cache, market_caps=cap,
                              params=replace(PARAMS, market_cap_policy="require_known"))
    assert strict["audit"][0]["market_cap_status"] == "above_minimum"
    cap["A"]["value"] -= 1
    strict = build_watch_pool(**args, cache=cache, market_caps=cap,
                              params=replace(PARAMS, market_cap_policy="require_known"))
    assert strict["audit"][0]["reason"] == "market_cap_below_minimum"
    cap["A"]["asof_date"] = "2026-10-01"
    strict = build_watch_pool(**args, cache=cache, market_caps=cap,
                              params=replace(PARAMS, market_cap_policy="require_known"))
    assert strict["audit"][0]["reason"] == "market_cap_unknown"


def test_candidate_failing_actual_minervini_today_still_admitted(tmp_path):
    from stock_analysis import UsaStockFinder
    args, cache = scenario(tmp_path, ["FBRT"])
    bars = daily_bars(start_price=40, end_price=20)
    seed_prices(cache, "FBRT", bars)
    finder = UsaStockFinder.__new__(UsaStockFinder)
    finder.symbols = ["FBRT"]
    finder.stock_data = pd.DataFrame({(field, "FBRT"): [r[key] for r in bars]
                                     for field, key in [("Open", "open"), ("High", "high"),
                                                        ("Low", "low"), ("Close", "close"), ("Volume", "volume")]},
                                    index=pd.to_datetime([r["date"] for r in bars]))
    finder.current_price = {"FBRT": 20}
    finder.last_high = {"FBRT": 41}
    finder.last_low = {"FBRT": 19}
    assert finder.has_valid_trend_template(0)["FBRT"] is False
    before = finder.has_valid_trend_template(0)
    result = build_watch_pool(**args, cache=cache)
    assert [r["symbol"] for r in result["watch"]] == ["FBRT"]
    assert finder.has_valid_trend_template(0) == before


def test_identical_fixed_inputs_produce_identical_bytes_and_generation(tmp_path):
    args, cache = scenario(tmp_path, ["B", "A", "FBRT"], core_count=2)
    first = build_watch_pool(**args, cache=cache)
    # Reusing a cache instance or fresh instance is identical.
    second = build_watch_pool(**args, cache=cache)
    third = build_watch_pool(**args, cache=ResearchCache(cache.directory))
    assert canonical_bytes(first) == canonical_bytes(second) == canonical_bytes(third)
    one = publish_watch_pool(tmp_path / "one", first)
    two = publish_watch_pool(tmp_path / "two", second)
    assert one.name == two.name
    for name in ("watch.csv", "audit.json", "metadata.json"):
        assert (one / name).read_bytes() == (two / name).read_bytes()
    assert publish_watch_pool(tmp_path / "one", second) == one
    assert inspect_watch_pool(one)["counts"]["watch"] == 5


def test_atomic_failure_and_integrity_detection(tmp_path, monkeypatch):
    args, cache = scenario(tmp_path, ["A"])
    result = build_watch_pool(**args, cache=cache)
    output = tmp_path / "out"
    old = publish_watch_pool(output, result)
    old_bytes = (old / "watch.csv").read_bytes()
    real_write = watch_pool._atomic_write  # pylint: disable=protected-access
    def fail_metadata(path, content):
        if path.name == "metadata.json":
            raise OSError("injected failure")
        real_write(path, content)
    monkeypatch.setattr(watch_pool, "_atomic_write", fail_metadata)
    result["metadata"]["parameters"]["target_total"] = 99
    with pytest.raises(OSError, match="injected"):
        publish_watch_pool(output, result)
    assert list(output.iterdir()) == [old]
    assert (old / "watch.csv").read_bytes() == old_bytes
    inspect_watch_pool(old)
    (old / "watch.csv").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        inspect_watch_pool(old)


def test_stage_b_tampering_and_future_listing_rejected(tmp_path):
    args, cache = scenario(tmp_path, ["A"])
    listing = args["listing_dir"]
    generation = (listing / "FILTER_CURRENT").read_text().strip()
    base = listing / "filter_generations" / generation / "base_universe.csv"
    old = base.read_bytes()
    base.write_bytes(old.replace(b"A Trust", b"Other Trust"))
    with pytest.raises(ValueError, match="Stage B"):
        build_watch_pool(**args, cache=cache)
    base.write_bytes(old)
    generation = (listing / "CURRENT").read_text().strip()
    metadata_file = listing / "generations" / generation / "metadata.json"
    metadata = json.loads(metadata_file.read_bytes())
    metadata["created_at_utc"] = "2026-10-01T22:00:00+00:00"
    metadata_file.write_bytes(canonical_bytes(metadata))
    with pytest.raises(ValueError, match="observed after"):
        build_watch_pool(**args, cache=cache)


def test_core_asof_and_universe_resource_bound(tmp_path):
    args, cache = scenario(tmp_path, ["A", "B"])
    with pytest.raises(ValueError, match="resource bound"):
        build_watch_pool(**args, cache=ResearchCache(cache.directory, limits=ResourceLimits(max_symbols=1)))
    assert not cache.used
    for core_day in ("2025-01-01", "2026-10-01"):
        with pytest.raises(ValueError, match="Core snapshot"):
            build_watch_pool(**{**args, "core_asof_date": core_day}, cache=cache)


def test_cli_build_inspect_offline_and_no_production_writes(tmp_path, capsys, monkeypatch):
    args, cache = scenario(tmp_path, ["FBRT"])
    # Work from an isolated fake runtime and prove every existing state byte survives.
    live = tmp_path / "live"
    for relative in ("portfolio/portfolio.csv", "data/data.json", "data/live/state.json"):
        path = live / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("production-state-sentinel")
    before = {p.relative_to(live): p.read_bytes() for p in live.rglob("*") if p.is_file()}
    monkeypatch.chdir(live)
    cli.main(["build", "--asof-date", DAY, "--session-date", DAY, "--core-asof-date", DAY,
              "--listing-dir", str(args["listing_dir"]), "--core-csv", str(args["core_csv"]),
              "--cache-dir", str(cache.directory), "--output-dir", str(tmp_path / "output")])
    output = next((tmp_path / "output").iterdir())
    cli.main(["inspect", str(output)])
    assert '"expansion": 1' in capsys.readouterr().out
    assert before == {p.relative_to(live): p.read_bytes() for p in live.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="SEC organization"):
        cli.main(["build", "--asof-date", DAY, "--session-date", DAY, "--core-asof-date", DAY, "--fetch"])


def test_class_share_alias_overlap_and_ambiguous_provider_collision(tmp_path):
    args, cache = scenario(tmp_path, ["BRK.B", "XYZ.A", "XYZ-A"], core_symbols=["BRK/B-US", "BRK.B-US"])
    result = build_watch_pool(**args, cache=cache)
    assert [(r["symbol"], r["source_pool"]) for r in result["watch"]] == [("BRK-B", "core_quant")]
    assert result["metadata"]["counts"]["reasons"] == {"core_overlap": 1, "provider_symbol_collision": 2}
    assert result["metadata"]["counts"]["excluded"] == 3
    assert not result["metadata"]["raw_sources"]


def test_source_observation_staleness_before_session_and_future_prices(tmp_path):
    args, cache = scenario(tmp_path, ["A"])
    url = chart_url("A", DAY)
    payload = seed_prices(cache, "A")
    for observed, reason in [("2026-09-01T22:00:00+00:00", "source_cache_stale"),
                             ("2026-09-29T22:00:00+00:00", "source_observed_before_data"),
                             ("2026-10-01T22:00:00+00:00", "source_observed_after_asof")]:
        cache_entry(cache, url, payload, observed=observed)
        result = build_watch_pool(**args, cache=cache)
        assert result["audit"][0]["reason"] == reason
        assert result["metadata"]["counts"]["expansion"] == 0


@pytest.mark.parametrize("session,utc_hour", [("2026-01-30", 21), ("2026-07-31", 20)])
@pytest.mark.parametrize("offset,accepted", [(-21600, False), (-0.000001, False), (0, True), (1, True)])
def test_price_observation_full_timestamp_cutoff(tmp_path, session, utc_hour, offset, accepted):
    from datetime import timedelta
    cutoff = datetime.fromisoformat(asof_cutoff(session, session))
    assert cutoff.astimezone(timezone.utc).hour == utc_hour
    observed = (cutoff.astimezone(timezone.utc) + timedelta(seconds=offset)).isoformat()
    cache = ResearchCache(tmp_path)
    url = chart_url("A", session)
    cache_entry(cache, url, b"synthetic", observed=observed)
    if accepted:
        assert cache.get_asof(url, session, not_before=session,
                              observed_not_before=cutoff) == b"synthetic"
    else:
        with pytest.raises(ResearchDataError, match="^source_observed_before_cutoff$"):
            cache.get_asof(url, session, not_before=session, observed_not_before=cutoff)


@pytest.mark.parametrize("asof", ["2026-08-01", "2026-08-02"])
def test_friday_close_observation_valid_for_weekend(tmp_path, asof):
    session = "2026-07-31"
    cache = ResearchCache(tmp_path)
    url = chart_url("A", session)
    cache_entry(cache, url, b"synthetic", observed="2026-07-31T20:00:01+00:00")
    assert cache.get_asof(url, asof, not_before=session,
                          observed_not_before=datetime.fromisoformat(asof_cutoff(asof, session))) == b"synthetic"


def test_intraday_sec_observations_remain_valid(tmp_path):
    cache = ResearchCache(tmp_path)
    seed_evidence(cache, ["A"], {"A": {"filed": DAY}})
    for path in cache.directory.glob("*.json"):
        entry = json.loads(path.read_bytes())
        entry["observed_at_utc"] = "2026-09-30T14:00:00+00:00"  # 10:00 EDT, including filing day
        path.write_bytes(canonical_bytes(entry))
    result = SecVerifier(cache, DAY).verify("A")
    assert result["status"] == "verified"
    assert len(result["sources"]) == 3


def test_intraday_chart_cannot_rank_or_enter_watch_pool(tmp_path):
    args, cache = scenario(tmp_path, ["A"])
    url = chart_url("A", DAY)
    payload = seed_prices(cache, "A")
    numeric = screen_bars(decode_chart(payload, "A"), DAY, PARAMS)
    assert numeric["last_bar_date"] == DAY
    assert numeric["reason"] is None
    cache_entry(cache, url, payload, observed="2026-09-30T14:00:00+00:00")
    original = {path.name: path.read_bytes() for path in cache.directory.iterdir()}
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unsafe cache must never refresh")
    fetching = ResearchCache(cache.directory, fetch=True, opener=forbidden)
    rejected = build_watch_pool(**args, cache=fetching)
    row = rejected["audit"][0]
    assert row["reason"] == "source_observed_before_cutoff"
    assert row["ohlcv_validity"] == "unavailable"
    assert row["verification"]["status"] == "not_evaluated"
    assert "rank" not in row and "score" not in row
    assert rejected["watch"] == []
    counts = rejected["metadata"]["counts"]
    assert counts["numeric_eligible"] == counts["verification_attempted"] == counts["expansion"] == 0
    assert counts["excluded"] == 1
    assert counts["reasons"] == {"source_observed_before_cutoff": 1}
    assert rejected["metadata"]["raw_sources"][sha256(url.encode())]["sha256"] == sha256(payload)
    assert fetching.requests == 0
    assert original == {path.name: path.read_bytes() for path in cache.directory.iterdir()}
    assert canonical_bytes(rejected) == canonical_bytes(build_watch_pool(**args, cache=fetching))
    published = publish_watch_pool(tmp_path / "output", rejected)
    assert inspect_watch_pool(published)["counts"]["excluded"] == 1
    assert json.loads((published / "audit.json").read_bytes())[0]["reason"] == row["reason"]

    # A separately supplied corrected observation uses exactly the same chart bytes.
    corrected = ResearchCache(tmp_path / "corrected")
    for path in cache.directory.iterdir():
        entry = json.loads(path.read_bytes())
        cache_entry(corrected, entry["url"], entry["body"].encode(), observed=entry["observed_at_utc"])
    cache_entry(corrected, url, payload, observed="2026-09-30T20:00:00+00:00")
    accepted = build_watch_pool(**args, cache=corrected)
    admitted = accepted["audit"][0]
    assert admitted["reason"] == "selected"
    assert admitted["rank"] == 1
    assert [r["symbol"] for r in accepted["watch"]] == ["A"]
    assert all(admitted[key] == value for key, value in numeric.items() if key != "reason")
    assert inspect_watch_pool(published)["counts"]["expansion"] == 0


def test_immutable_repeat_refuses_corruption_and_metadata_tampering(tmp_path):
    args, cache = scenario(tmp_path, ["A"])
    result = build_watch_pool(**args, cache=cache)
    path = publish_watch_pool(tmp_path / "out", result)
    metadata = path / "metadata.json"
    data = json.loads(metadata.read_bytes())
    data["counts"]["expansion"] = 99
    metadata.write_bytes(canonical_bytes(data))
    with pytest.raises(ValueError, match="metadata checksum"):
        inspect_watch_pool(path)
    with pytest.raises(ValueError, match="immutable snapshot integrity"):
        publish_watch_pool(tmp_path / "out", result)


def test_future_bar_and_numeric_vs_provider_exclusions_reconcile(tmp_path):
    args, cache = scenario(tmp_path, ["A", "B", "C", "D"])
    seed_prices(cache, "A", daily_bars() + daily_bars(count=1, end="2026-10-01"))
    seed_prices(cache, "B", daily_bars(end_price=100))
    cache_entry(cache, chart_url("C", DAY), b'{"chart":{"error":{"code":"Not Found"}}}')
    result = build_watch_pool(**args, cache=cache)
    assert result["metadata"]["counts"]["reasons"] == {
        "future_bar": 1, "price_out_of_band": 1, "provider_error": 1, "selected": 1}
    assert result["metadata"]["counts"]["ohlcv_validity"] == {"invalid": 1, "unavailable": 1, "valid": 2}
    assert result["metadata"]["counts"]["excluded"] + result["metadata"]["counts"]["expansion"] == 4


def test_annual_filing_staleness_and_no_ticker_specific_exclusions(tmp_path):
    cache = ResearchCache(tmp_path)
    seed_evidence(cache, ["RMT", "FBRT"], {"RMT": {"entityType": "operating", "sic": "3571"},
                                          "FBRT": {"filed": "2020-01-01"}})
    # The symbol itself is never an exclusion: changing evidence changes the result.
    assert SecVerifier(cache, DAY).verify("RMT")["status"] == "verified"
    assert SecVerifier(cache, DAY).verify("FBRT")["reason"] == "annual_filing_stale_or_invalid"


def test_finite_raw_values_with_overflowed_aggregate_fail_closed():
    bars = daily_bars()
    for row in bars[-20:]:
        row["volume"] = 5e306
    # Each close*volume is finite, but their sum overflows IEEE double.
    result = screen_bars(bars, DAY, PARAMS)
    assert result["reason"] == "nonfinite_metric"
    assert result["ohlcv_validity"] == "invalid"


def test_watch_affordability_proxy_does_not_change_daily_whole_share_sizing():
    from types import SimpleNamespace
    from main import calculate_share_quantities
    finder = SimpleNamespace(current_price={"LOW": 5, "CEILING": 90, "LATER": 101})
    result = calculate_share_quantities({"LOW": 100, "CEILING": 100, "LATER": 100}, finder, current_holdings=[])
    assert result["LOW"]["shares_to_buy"] == 20
    assert result["CEILING"]["shares_to_buy"] == 1
    assert result["CEILING"]["actual_investment"] == 90
    assert "LATER" not in result
