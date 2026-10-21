"""Offline Stage C fixtures; never read/write real portfolios or runtime state."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from http.client import IncompleteRead
from io import BytesIO
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from tools import build_trend_expansion_watch_pool as cli
from trend_expansion import research_cache, universe_source, watch_pool
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
SHELL_CASES = json.loads((Path(__file__).parent / "fixtures/sec_shell_cover_cases.json").read_text())["cases"]


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
            f'<ix:nonNumeric name="dei:EntityShellCompany" contextRef="entity">{shell}</ix:nonNumeric>'
            '</html>').encode()


def fixture_cover(case, symbol="ABC"):
    """Keep class evidence synthetic; shell structures have documented filing sources."""
    page = cover(symbol)
    page = page[:page.index(b'<ix:nonNumeric name="dei:EntityShellCompany"')]
    namespaces = (f'<html xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/{case["registry_version"]}" '
                  'xmlns:ixt-sec="http://www.sec.gov/inlineXBRL/transformation/2015-08-31" '
                  'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">').encode()
    return page.replace(b"<html>", namespaces) + case["shell_markup"].encode() + b"</html>"


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
                          "form": [case.get("form", "10-K")], "filingDate": [case.get("filed", "2026-03-01")],
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


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("value", [True, False])
def test_boolean_ohlcv_never_ranks_or_enters_watch_pool(tmp_path, field, value):
    args, cache = scenario(tmp_path, ["A", "B"])
    bars = daily_bars()
    bars[0][field] = value  # Outside liquidity/momentum windows; still invalid evidence.
    payload = seed_prices(cache, "A", bars)
    decoded = decode_chart(payload, "A")
    assert decoded[0][field] is value  # Real JSON booleans, before numeric conversion.
    assert screen_bars(decoded, DAY, PARAMS)["reason"] == "missing_or_invalid_bar"
    original = {p.name: p.read_bytes() for p in cache.directory.iterdir()}
    result = build_watch_pool(**args, cache=cache)
    bad, good = result["audit"][0], result["audit"][1]
    assert bad["reason"] == "missing_or_invalid_bar"
    assert bad["ohlcv_validity"] == "invalid"
    assert bad["verification"]["status"] == "not_evaluated"
    assert "rank" not in bad and "score" not in bad
    assert good["reason"] == "selected" and good["rank"] == 1
    expected = screen_bars(daily_bars(), DAY, PARAMS)
    assert all(good[key] == value for key, value in expected.items() if key != "reason")
    assert [row["symbol"] for row in result["watch"]] == ["B"]
    counts = result["metadata"]["counts"]
    assert counts["numeric_eligible"] == counts["verification_attempted"] == counts["expansion"] == 1
    assert counts["reasons"] == {"missing_or_invalid_bar": 1, "selected": 1}
    assert bad["ohlcv_source"]["sha256"] == sha256(payload)
    replay = build_watch_pool(**args, cache=ResearchCache(cache.directory))
    assert canonical_bytes(result) == canonical_bytes(replay)
    one = publish_watch_pool(tmp_path / "one", result)
    two = publish_watch_pool(tmp_path / "two", replay)
    for name in ("watch.csv", "audit.json", "metadata.json"):
        assert (one / name).read_bytes() == (two / name).read_bytes()
    assert original == {p.name: p.read_bytes() for p in cache.directory.iterdir()}


def test_numeric_ohlcv_strings_and_numbers_keep_identical_screen_results():
    bars = daily_bars()
    strings = [{key: str(value) for key, value in row.items()} for row in bars]
    assert screen_bars(strings, DAY, PARAMS) == screen_bars(bars, DAY, PARAMS)


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


def test_cover_ignores_missing_and_valueless_ordinary_html_names():
    valid_cover = cover("ABC")
    for element in (b"<div></div>", b"<a name></a>"):
        payload = valid_cover.replace(b"<html>", b"<html>" + element, 1)
        status, evidence = classify_cover(payload, "ABC")
        assert status == "verified"
        assert evidence["classification"] == "operating_common_equity"


def test_valueless_inline_fact_name_cannot_supply_shell_evidence():
    payload = (b'<html><ix:nonNumeric name="dei:TradingSymbol" contextRef="class-a">ABC</ix:nonNumeric>'
               b'<ix:nonNumeric name="dei:Security12bTitle" contextRef="class-a">Common Stock</ix:nonNumeric>'
               b'<ix:nonNumeric name contextRef="entity">false</ix:nonNumeric></html>')
    status, evidence = classify_cover(payload, "ABC")
    assert status == "unknown"
    assert evidence["shell_status"] == "missing"
    assert evidence["classification"] == "shell_status_unknown"


def test_malformed_sec_finalist_does_not_abort_ranked_fallback(tmp_path):
    args, cache = scenario(tmp_path, ["A", "B"])
    seed_evidence(cache, ["A", "B"])
    malformed_top_cover = (
        b'<html><ix:nonNumeric name="dei:TradingSymbol" contextRef="class-a">A</ix:nonNumeric>'
        b'<ix:nonNumeric name="dei:Security12bTitle" contextRef="class-a">Common Stock</ix:nonNumeric>'
        b'<ix:nonNumeric name contextRef="entity">false</ix:nonNumeric></html>')
    url = "https://www.sec.gov/Archives/edgar/data/2000/000000200026000001/annual.htm"
    cache_entry(cache, url, malformed_top_cover)

    result = build_watch_pool(**args, cache=cache, params=replace(PARAMS, target_total=1))

    bad, good = result["audit"][0], result["audit"][1]
    assert bad["symbol"] == "A"
    assert bad["verification"]["status"] == "unknown"
    assert bad["verification"]["reason"] == "shell_status_unknown"
    assert bad["reason"] == "security_unknown"
    assert good["symbol"] == "B"
    assert good["verification"]["status"] == "verified"
    assert good["verification"]["classification"] == "operating_common_equity"
    assert good["reason"] == "selected"
    assert [row["symbol"] for row in result["watch"]] == ["B"]
    assert result["metadata"]["counts"]["verification_attempted"] == 2


@pytest.mark.parametrize("case", SHELL_CASES, ids=lambda case: case["id"])
def test_filing_derived_shell_evidence_and_cache_only_admission(tmp_path, case):
    args, cache = scenario(tmp_path, ["ABC", "ZZZ"])
    seed_evidence(cache, ["ABC", "ZZZ"],
                  {"ABC": {"form": "20-F" if case["source"].endswith("_20f") else "10-K"}})
    raw = fixture_cover(case)
    status, evidence = classify_cover(raw, "ABC")
    assert status == case["status"]
    assert evidence["shell_status"] == case["shell_status"]
    url = "https://www.sec.gov/Archives/edgar/data/2000/000000200026000001/annual.htm"
    cache_entry(cache, url, raw)
    original = {p.name: p.read_bytes() for p in cache.directory.iterdir()}
    def forbidden(*_args, **_kwargs):
        raise AssertionError("regressions must use frozen cache only")
    result = build_watch_pool(**args, cache=ResearchCache(cache.directory, opener=forbidden),
                              params=replace(PARAMS, target_total=1))
    first = result["audit"][0]
    assert first["verification"]["shell_status"] == case["shell_status"]
    assert first["verification"]["sources"][-1] == {"url": url, "sha256": sha256(raw)}
    assert first["verification"]["shell_facts"] == evidence["shell_facts"]
    assert result["metadata"]["raw_sources"][sha256(url.encode())]["sha256"] == sha256(raw)
    assert first["reason"] == ("selected" if status == "verified" else "security_" + status)
    assert [row["symbol"] for row in result["watch"]] == (["ABC"] if status == "verified" else ["ZZZ"])
    replay = build_watch_pool(**args, cache=ResearchCache(cache.directory, opener=forbidden),
                              params=replace(PARAMS, target_total=1))
    assert canonical_bytes(result) == canonical_bytes(replay)
    directories = [publish_watch_pool(tmp_path / name, build) for name, build in (("one", result), ("two", replay))]
    assert directories[0].name == directories[1].name
    for name in ("watch.csv", "audit.json", "metadata.json"):
        assert (directories[0] / name).read_bytes() == (directories[1] / name).read_bytes()
    assert inspect_watch_pool(directories[0])["counts"]["expansion"] == 1
    assert original == {p.name: p.read_bytes() for p in cache.directory.iterdir()}


@pytest.mark.parametrize("registry", ["2015-02-26", "2020-02-12", "2022-02-16"])
@pytest.mark.parametrize("value", [True, False])
def test_only_namespace_qualified_registered_boolean_transforms(registry, value):
    suffix = "true" if value else "false"
    transform = "boolean" + suffix if registry == "2015-02-26" else "fixed-" + suffix
    case = {"registry_version": registry, "shell_markup":
            f'<ix:nonNumeric name="dei:EntityShellCompany" contextRef="entity" '
            f'format="ixt:{transform}"><span>&#9746;</span></ix:nonNumeric>'}
    raw = fixture_cover(case)
    expected = "not_common" if value else "verified"
    assert classify_cover(raw, "ABC")[0] == expected
    assert classify_cover(raw.replace(b"ixt", b"alias"), "ABC")[0] == expected
    spoofed = raw.replace(b"http://www.xbrl.org/inlineXBRL/transformation/", b"https://example.com/")
    assert classify_cover(spoofed, "ABC")[1]["shell_status"] == "unsupported"
    # A local namespace override is scoped; a later false cannot hide unsupported evidence.
    bad = b'<div xmlns:ixt="https://example.com/unknown">' + case["shell_markup"].encode() + b'</div>'
    mixed = raw.replace(b"</html>", bad + case["shell_markup"].encode() + b"</html>")
    status, evidence = classify_cover(mixed, "ABC")
    assert status != "verified"
    assert evidence["shell_facts"][1]["status"] == "unsupported"
    assert evidence["shell_facts"][0]["value"] is value
    assert evidence["shell_facts"][2]["value"] is value  # Restore the outer namespace after the div.


@pytest.mark.parametrize("title,title_context,expected", [
    ("Common Stock", "other-class", "unknown"), ("Preferred Stock", "class-a", "not_common"),
    ("Depositary Receipts", "class-a", "unknown"), ("Ordinary Shares", "class-a", "verified"),
])
def test_transformed_nonshell_preserves_class_context_and_title_checks(title, title_context, expected):
    raw = fixture_cover(SHELL_CASES[0])
    raw = raw.replace(b"<b>Common Stock</b>", f"<b>{title}</b>".encode())
    raw = raw.replace(b'name="dei:Security12bTitle" contextRef="class-a"',
                      f'name="dei:Security12bTitle" contextRef="{title_context}"'.encode())
    assert classify_cover(raw, "ABC")[0] == expected


@pytest.mark.parametrize("entity_type,sic,reason", [
    ("investment", "6726", "investment_company_or_shell"),
    ("operating", "6770", "investment_company_or_shell"),
    ("other", "3571", "operating_status_unknown"), ("operating", "", "operating_status_unknown"),
])
def test_transformed_nonshell_does_not_bypass_operating_verification(tmp_path, entity_type, sic, reason):
    args, cache = scenario(tmp_path, ["ABC", "ZZZ"])
    seed_evidence(cache, ["ABC", "ZZZ"], {"ABC": {"entityType": entity_type, "sic": sic}})
    url = "https://www.sec.gov/Archives/edgar/data/2000/000000200026000001/annual.htm"
    cache_entry(cache, url, fixture_cover(SHELL_CASES[0]))
    result = build_watch_pool(**args, cache=cache, params=replace(PARAMS, target_total=1))
    assert result["audit"][0]["verification"]["reason"] == reason
    assert [row["symbol"] for row in result["watch"]] == ["ZZZ"]


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


@pytest.mark.parametrize("market_caps", [
    [], ["A"], False, True, 0, 1, "", "invalid", None,
])
def test_build_rejects_non_object_market_cap_documents(tmp_path, market_caps):
    args, cache = scenario(tmp_path, ["A"])
    if market_caps is None:
        # None is the API's explicit representation of omitted optional evidence.
        result = build_watch_pool(**args, cache=cache, market_caps=market_caps)
        assert result["metadata"]["market_cap_input_sha256"] == sha256(canonical_bytes({}))
        return

    with pytest.raises(ValueError, match="market_caps must be a mapping"):
        build_watch_pool(**args, cache=cache, market_caps=market_caps)


def test_market_cap_empty_and_populated_mappings_have_stable_canonical_checksums(tmp_path):
    args, cache = scenario(tmp_path, ["A"])
    empty = build_watch_pool(**args, cache=cache, market_caps={})
    omitted = build_watch_pool(**args, cache=cache)
    assert empty["metadata"]["market_cap_input_sha256"] == sha256(canonical_bytes({}))
    assert empty["metadata"]["market_cap_input_sha256"] == omitted["metadata"]["market_cap_input_sha256"]

    first = {"A": {"value": 350_000_000, "currency": "USD", "asof_date": DAY,
                   "source_url": "https://example.com/a", "coverage_verified": True},
             "B": {"value": 400_000_000, "currency": "USD", "asof_date": DAY,
                   "source_url": "https://example.com/b", "coverage_verified": True}}
    second = {"B": first["B"], "A": first["A"]}
    result_one = build_watch_pool(**args, cache=cache, market_caps=first)
    result_two = build_watch_pool(**args, cache=cache, market_caps=second)
    expected = sha256(canonical_bytes(first))
    assert result_one["metadata"]["market_cap_input_sha256"] == expected
    assert result_two["metadata"]["market_cap_input_sha256"] == expected
    assert result_one["metadata"]["market_cap_input_sha256"] == result_two["metadata"]["market_cap_input_sha256"]


@pytest.mark.parametrize("document", ["null", "[]", "false", "0", '""'])
def test_cli_rejects_non_object_market_cap_json_before_build_or_publication(
        tmp_path, monkeypatch, document):
    market_cap_file = tmp_path / "market_caps.json"
    market_cap_file.write_text(document)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(cli, "build_watch_pool", lambda *args, **kwargs: pytest.fail("pool build started"))
    monkeypatch.setattr(cli, "publish_watch_pool", lambda *args, **kwargs: pytest.fail("pool published"))

    with pytest.raises(ValueError, match="--market-caps must contain a JSON object"):
        cli.main([
            "build", "--asof-date", DAY, "--session-date", DAY, "--core-asof-date", DAY,
            "--market-caps", str(market_cap_file), "--output-dir", str(output_dir),
        ])
    assert not output_dir.exists()


@pytest.mark.parametrize("field", [
    "min_bars", "liquidity_sessions", "short_sessions", "long_sessions",
    "target_total", "max_expansion", "max_verifications",
])
@pytest.mark.parametrize("value", [True, False])
def test_cli_rejects_boolean_integer_parameter_overrides_before_build(
        tmp_path, monkeypatch, field, value):
    """JSON bools must not silently act as integer lookback or pool settings."""
    parameter_file = tmp_path / "parameters.json"
    parameter_file.write_text(json.dumps({field: value}))
    monkeypatch.setattr(cli, "ResearchCache", lambda *args, **kwargs: pytest.fail("cache initialized"))
    monkeypatch.setattr(cli, "build_watch_pool", lambda *args, **kwargs: pytest.fail("pool build started"))

    with pytest.raises(ValueError, match="invalid session or size parameter"):
        cli.main([
            "build", "--asof-date", DAY, "--session-date", DAY, "--core-asof-date", DAY,
            "--parameters", str(parameter_file),
        ])


@pytest.mark.parametrize("field", [
    "min_price", "max_price", "min_dollar_volume", "min_market_cap",
    "short_weight", "long_weight",
])
@pytest.mark.parametrize("value", [True, False])
def test_cli_rejects_boolean_numeric_parameter_overrides_before_build(
        tmp_path, monkeypatch, field, value):
    """JSON bools are not valid numeric threshold or weight overrides either."""
    parameter_file = tmp_path / "parameters.json"
    parameter_file.write_text(json.dumps({field: value}))
    monkeypatch.setattr(cli, "ResearchCache", lambda *args, **kwargs: pytest.fail("cache initialized"))
    monkeypatch.setattr(cli, "build_watch_pool", lambda *args, **kwargs: pytest.fail("pool build started"))

    with pytest.raises(ValueError, match="parameters must be finite and nonnegative"):
        cli.main([
            "build", "--asof-date", DAY, "--session-date", DAY, "--core-asof-date", DAY,
            "--parameters", str(parameter_file),
        ])


def test_overflowing_market_caps_are_unknown_without_aborting_build(tmp_path):
    args, cache = scenario(tmp_path, ["A", "B", "C"])
    # Parse JSON integers to exercise the same input type used by supplied JSON evidence.
    huge_positive, huge_negative = json.loads(f"[{10 ** 400}, {-10 ** 400}]")
    caps = {
        "A": {"value": huge_positive, "asof_date": DAY, "currency": "USD",
              "source_url": "https://example.com/a", "coverage_verified": True},
        "B": {"value": huge_negative, "asof_date": DAY, "currency": "USD",
              "source_url": "https://example.com/b", "coverage_verified": True},
        "C": {"value": 300_000_000, "asof_date": DAY, "currency": "USD",
              "source_url": "https://example.com/c", "coverage_verified": True},
    }

    # Diagnostic policy continues to admit unknown coverage as before.
    permissive = build_watch_pool(**args, cache=cache, market_caps=caps)
    by_symbol = {row["symbol"]: row for row in permissive["audit"]}
    for symbol in ("A", "B"):
        assert by_symbol[symbol]["market_cap_status"] == "unknown"
        assert by_symbol[symbol]["market_cap"] is None
        assert by_symbol[symbol]["reason"] == "selected"
    assert by_symbol["C"]["market_cap_status"] == "above_minimum"

    # Strict policy excludes only the two affected symbols; valid coverage proceeds.
    strict = build_watch_pool(**args, cache=cache, market_caps=caps,
                              params=replace(PARAMS, market_cap_policy="require_known"))
    by_symbol = {row["symbol"]: row for row in strict["audit"]}
    for symbol in ("A", "B"):
        assert by_symbol[symbol]["market_cap_status"] == "unknown"
        assert by_symbol[symbol]["market_cap"] is None
        assert by_symbol[symbol]["reason"] == "market_cap_unknown"
    assert by_symbol["C"]["market_cap_status"] == "above_minimum"
    assert by_symbol["C"]["reason"] == "selected"


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


def test_cache_only_byte_exhaustion_stays_in_audit_and_lineage_clear_does_not_reset(tmp_path):
    args, seeded = scenario(tmp_path, ["A", "B"])
    # A's entire price payload fits exactly; B and all verification evidence
    # must fail closed without reading more bodies. No accounting path is mocked.
    payload = seed_prices(seeded, "A")
    cache = ResearchCache(seeded.directory, limits=ResourceLimits(max_total_bytes=len(payload)))
    result = build_watch_pool(**args, cache=cache)
    first, second = result["audit"][0], result["audit"][1]
    assert first["ohlcv_validity"] == "valid"
    assert first["reason"] == "security_unknown"
    assert first["verification"]["reason"] == "resource_byte_budget_exhausted"
    assert second["ohlcv_validity"] == "unavailable"
    assert second["reason"] == "resource_byte_budget_exhausted"
    assert result["watch"] == []
    assert cache.total_bytes == len(payload)
    assert cache.requests == cache.downloaded_bytes == 0
    assert set(result["metadata"]["raw_sources"]) == {sha256(chart_url("A", DAY).encode())}
    replay = build_watch_pool(**args, cache=cache)  # build_watch_pool clears used.
    assert all(row["reason"] == "resource_byte_budget_exhausted" for row in replay["audit"])
    assert not replay["metadata"]["raw_sources"]
    assert cache.total_bytes == len(payload)


def test_cli_valid_json_parameters_preserve_deterministic_pool(tmp_path, capsys):
    """Explicit valid integer defaults preserve the same momentum and pool bytes."""
    args, cache = scenario(tmp_path, ["A", "B", "FBRT"])
    params_file = tmp_path / "parameters.json"
    params_file.write_text(json.dumps(PARAMS.__dict__))
    common = [
        "build", "--asof-date", DAY, "--session-date", DAY, "--core-asof-date", DAY,
        "--listing-dir", str(args["listing_dir"]), "--core-csv", str(args["core_csv"]),
        "--cache-dir", str(cache.directory),
    ]
    cli.main([*common, "--output-dir", str(tmp_path / "default")])
    default_snapshot = next((tmp_path / "default").iterdir())
    cli.main([*common, "--parameters", str(params_file), "--output-dir", str(tmp_path / "configured")])
    configured_snapshot = next((tmp_path / "configured").iterdir())
    capsys.readouterr()

    assert default_snapshot.name == configured_snapshot.name
    for name in ("watch.csv", "audit.json", "metadata.json"):
        assert (default_snapshot / name).read_bytes() == (configured_snapshot / name).read_bytes()


@pytest.mark.parametrize("source", ["price", "mapping", "submission", "filing"])
def test_truncated_sources_have_explicit_audit_reasons_and_build_continues(tmp_path, source):
    args, cache = scenario(tmp_path, ["A", "B"])
    url = {"price": chart_url("A", DAY), "mapping": TICKERS_URL,
           "submission": "https://data.sec.gov/submissions/CIK0000002000.json",
           "filing": "https://www.sec.gov/Archives/edgar/data/2000/000000200026000001/annual.htm"}[source]
    key = sha256(url.encode())
    (cache.directory / f"{key}.json").unlink()
    calls = []
    class Truncated(BytesIO):
        def read(self, size=-1):
            raise IncompleteRead(super().read(size), 10)
    def open_mock(request, timeout):
        assert request.full_url == url
        calls.append(timeout)
        return Truncated(b"partial")
    def build():
        fetching = ResearchCache(cache.directory, fetch=True, opener=open_mock, sleeper=lambda _: None)
        result = build_watch_pool(**args, cache=fetching)
        assert fetching.requests == 3
        assert key not in fetching.used
        return result
    result = build()
    first = result["audit"][0]
    if source == "price":
        assert first["reason"] == "network_failed"
        assert first["ohlcv_validity"] == "unavailable"
    else:
        assert first["reason"] == "security_unknown"
        assert first["verification"]["reason"] == "network_failed"
    assert [row["symbol"] for row in result["watch"]] == ([] if source == "mapping" else ["B"])
    assert not (cache.directory / f"{key}.json").exists()
    assert len(calls) == 3
    again = build()
    assert canonical_bytes(result) == canonical_bytes(again)
    one = publish_watch_pool(tmp_path / "one", result)
    two = publish_watch_pool(tmp_path / "two", again)
    assert one.name == two.name
    for name in ("watch.csv", "audit.json", "metadata.json"):
        assert (one / name).read_bytes() == (two / name).read_bytes()
    assert inspect_watch_pool(one)["counts"]["expansion"] == (0 if source == "mapping" else 1)


def test_concurrent_builds_publish_identical_artifacts_from_winning_cache(tmp_path, monkeypatch):
    args, seeded = scenario(tmp_path, ["A"])
    url = chart_url("A", DAY)
    path = seeded.directory / f"{sha256(url.encode())}.json"
    winner = seed_prices(seeded, "A", daily_bars(end_price=30))
    loser = seed_prices(seeded, "A", daily_bars(end_price=15))
    path.unlink()
    original = {entry.name: entry.read_bytes() for entry in seeded.directory.iterdir()}
    real_write = research_cache._atomic_write  # pylint: disable=protected-access
    ready, published = Barrier(2), Event()
    candidates = []
    def synchronized_write(destination, content):
        entry = json.loads(content)
        candidates.append(entry)
        ready.wait(timeout=10)
        if entry["body"].encode() == winner:
            try:
                real_write(destination, content)
            finally:
                published.set()
        else:
            assert published.wait(timeout=10)
            real_write(destination, content)
    monkeypatch.setattr(research_cache, "_atomic_write", synchronized_write)
    caches = [ResearchCache(seeded.directory, fetch=True,
                            opener=lambda *_a, body=body, **_k: BytesIO(body), sleeper=lambda _: None)
              for body in (winner, loser)]
    with patch.object(research_cache, "datetime", wraps=datetime) as dates:
        dates.now.side_effect = [datetime(2026, 9, 30, hour, tzinfo=timezone.utc) for hour in (21, 22)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(build_watch_pool, **args, cache=cache) for cache in caches]
            results = [future.result(timeout=15) for future in futures]
    assert len({entry["observed_at_utc"] for entry in candidates}) == 2
    winning_entry = json.loads(path.read_bytes())
    assert winning_entry["body"].encode() == winner
    assert winning_entry["sha256"] == sha256(winner)
    assert caches[0].used == caches[1].used
    assert all(cache.requests == 1 for cache in caches)
    assert original == {entry.name: entry.read_bytes() for entry in seeded.directory.iterdir() if entry != path}
    assert len(list(seeded.directory.iterdir())) == len(original) + 1  # No temporary files.
    replay = build_watch_pool(**args, cache=ResearchCache(seeded.directory))
    assert canonical_bytes(results[0]) == canonical_bytes(results[1]) == canonical_bytes(replay)
    assert replay["audit"][0]["ohlcv_source"]["sha256"] == sha256(winner)
    assert replay["metadata"]["raw_sources"][sha256(url.encode())] == {
        key: value for key, value in winning_entry.items() if key != "body"}
    assert replay["audit"][0]["reason"] == "selected"
    directories = [publish_watch_pool(tmp_path / name, result)
                   for name, result in zip(("one", "two", "replay"), [*results, replay])]
    assert len({directory.name for directory in directories}) == 1
    for name in ("watch.csv", "audit.json", "metadata.json"):
        assert len({(directory / name).read_bytes() for directory in directories}) == 1
    assert inspect_watch_pool(directories[0])["counts"]["expansion"] == 1


def test_corrupt_cache_retains_explicit_audit_reason_without_refetch(tmp_path):
    args, cache = scenario(tmp_path, ["A", "B"])
    url = chart_url("A", DAY)
    path = cache.directory / f"{sha256(url.encode())}.json"
    path.write_bytes(b"corrupt")
    def forbidden(*_args, **_kwargs):
        raise AssertionError("must not repair corrupted inputs")
    result = build_watch_pool(**args, cache=ResearchCache(cache.directory, fetch=True, opener=forbidden))
    assert result["audit"][0]["reason"] == "cache_invalid"
    assert [row["symbol"] for row in result["watch"]] == ["B"]
    published = publish_watch_pool(tmp_path / "output", result)
    assert json.loads((published / "audit.json").read_bytes())[0]["reason"] == "cache_invalid"
    assert inspect_watch_pool(published)["counts"]["expansion"] == 1
    assert path.read_bytes() == b"corrupt"


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


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("sign", [1, -1])
def test_json_integer_ohlcv_overflow_excludes_only_bad_symbol(tmp_path, field, sign):
    args, cache = scenario(tmp_path, ["A", "B"])
    bars = daily_bars()
    bars[-1][field] = sign * 10**400
    payload = seed_prices(cache, "A", bars)
    decoded = decode_chart(payload, "A")
    assert decoded[-1][field] == sign * 10**400  # No coercion or clamping.
    assert screen_bars(decoded, DAY, PARAMS)["reason"] == "missing_or_invalid_bar"
    result = build_watch_pool(**args, cache=cache)
    bad, good = result["audit"][0], result["audit"][1]
    assert bad["reason"] == "missing_or_invalid_bar"
    assert bad["ohlcv_validity"] == "invalid"
    assert bad["verification"]["status"] == "not_evaluated"
    assert "rank" not in bad
    expected = screen_bars(daily_bars(), DAY, PARAMS)
    assert good["reason"] == "selected"
    assert all(good[key] == value for key, value in expected.items() if key != "reason")
    assert [row["symbol"] for row in result["watch"]] == ["B"]
    counts = result["metadata"]["counts"]
    assert counts["numeric_eligible"] == counts["verification_attempted"] == counts["expansion"] == 1
    assert counts["excluded"] == 1
    assert counts["reasons"] == {"missing_or_invalid_bar": 1, "selected": 1}
    assert counts["ohlcv_validity"] == {"invalid": 1, "valid": 1}


@pytest.mark.parametrize("provider_symbol,reason", [
    (None, "ohlcv_malformed"), (123, "ohlcv_malformed"), ({"symbol": "A"}, "ohlcv_malformed"),
    ("OTHER", "provider_symbol_mismatch"), ("a", None),
])
def test_yahoo_symbol_types_and_mismatch_do_not_abort_build(tmp_path, provider_symbol, reason):
    args, cache = scenario(tmp_path, ["A", "B"])
    original = seed_prices(cache, "A")
    payload = json.loads(original)
    payload["chart"]["result"][0]["meta"]["symbol"] = provider_symbol
    encoded = json.dumps(payload).encode()
    cache_entry(cache, chart_url("A", DAY), encoded)
    if reason:
        with pytest.raises(ResearchDataError, match=f"^{reason}$"):
            decode_chart(encoded, "A")
    else:
        assert decode_chart(encoded, "A") == decode_chart(original, "A")
    result = build_watch_pool(**args, cache=cache)
    first = result["audit"][0]
    assert first["reason"] == (reason or "selected")
    assert first["ohlcv_validity"] == ("unavailable" if reason else "valid")
    assert [row["symbol"] for row in result["watch"]] == (["B"] if reason else ["A", "B"])
    counts = result["metadata"]["counts"]
    admitted = 1 if reason else 2
    assert counts["numeric_eligible"] == counts["verification_attempted"] == counts["expansion"] == admitted
    assert counts["excluded"] + counts["expansion"] == counts["preliminary"] == 2
    assert counts["reasons"] == ({reason: 1, "selected": 1} if reason else {"selected": 2})


@pytest.mark.parametrize("ticker", [None, 123, {"ticker": "A"}, "a"])
def test_sec_ticker_types_fail_closed_without_aborting_finalists(tmp_path, ticker):
    args, cache = scenario(tmp_path, ["A", "B"])
    mapping = {"0": {"ticker": ticker, "cik_str": 2000}, "1": {"ticker": "B", "cik_str": 2001}}
    cache_entry(cache, TICKERS_URL, canonical_bytes(mapping))
    verifier = SecVerifier(cache, DAY)
    valid = isinstance(ticker, str)
    for symbol in ("A", "B"):
        evidence = verifier.verify(symbol)
        assert evidence["status"] == ("verified" if valid else "unknown")
        assert evidence["reason"] == ("operating_common_equity" if valid else "sec_mapping_invalid")
        assert len(evidence["sources"]) == (3 if valid else 1)
    result = build_watch_pool(**args, cache=cache)
    assert [row["symbol"] for row in result["watch"]] == (["A", "B"] if valid else [])
    counts = result["metadata"]["counts"]
    assert counts["numeric_eligible"] == counts["verification_attempted"] == 2
    assert counts["expansion"] == (2 if valid else 0)
    assert counts["excluded"] + counts["expansion"] == counts["preliminary"] == 2
    assert counts["reasons"] == ({"selected": 2} if valid else {"security_unknown": 2})
    if not valid:
        assert all(row["verification"]["reason"] == "sec_mapping_invalid" for row in result["audit"])


def test_malformed_sec_cik_allows_next_ranked_valid_class_share(tmp_path):
    args, cache = scenario(tmp_path, ["A", "BRK.B"])
    mapping = {"0": {"ticker": "A", "cik_str": {}},
               "1": {"ticker": "BRK-B", "cik_str": 2001}}
    cache_entry(cache, TICKERS_URL, canonical_bytes(mapping))
    result = build_watch_pool(**args, cache=cache, params=replace(PARAMS, target_total=1))
    bad, good = result["audit"][0], result["audit"][1]
    assert bad["reason"] == "security_unknown"
    assert bad["verification"]["reason"] == "sec_evidence_malformed"
    assert good["verification"]["cik"] == 2001
    assert good["verification"]["status"] == "verified"
    assert [row["symbol"] for row in result["watch"]] == ["BRK.B"]
    counts = result["metadata"]["counts"]
    assert counts["verification_attempted"] == 2
    assert counts["expansion"] == counts["excluded"] == 1
    assert counts["reasons"] == {"security_unknown": 1, "selected": 1}


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("minimum", [0, 0.5, 1])
def test_boolean_market_caps_are_unknown_and_cannot_pass_strict_gate(tmp_path, value, minimum):
    args, cache = scenario(tmp_path, ["A", "B"])
    caps = {symbol: {"value": cap, "asof_date": DAY, "currency": "USD",
                     "source_url": "https://example.com/cap", "coverage_verified": True}
            for symbol, cap in (("A", value), ("B", 1))}
    for policy in ("diagnostic", "require_known"):
        result = build_watch_pool(**args, cache=cache, market_caps=caps,
                                  params=replace(PARAMS, market_cap_policy=policy, min_market_cap=minimum))
        bad, good = result["audit"][0], result["audit"][1]
        assert bad["market_cap_status"] == "unknown"
        assert bad["market_cap"] is None
        assert bad["market_cap_evidence"] == caps["A"]
        assert good["market_cap_status"] == "above_minimum"
        assert good["reason"] == "selected"
        if policy == "require_known":
            assert bad["reason"] == "market_cap_unknown"
            assert bad["verification"]["status"] == "not_evaluated"
            assert "rank" not in bad
            assert [row["symbol"] for row in result["watch"]] == ["B"]
            assert result["metadata"]["counts"]["numeric_eligible"] == 1
        else:
            assert bad["reason"] == "selected"
            assert [row["symbol"] for row in result["watch"]] == ["A", "B"]


@pytest.mark.parametrize("value", [300_000_000, 300_000_000.0, "300000000", "300000000.0", "3e8"])
def test_market_cap_numeric_representations_keep_strict_admission(tmp_path, value):
    args, cache = scenario(tmp_path, ["A"])
    caps = {"A": {"value": value, "asof_date": DAY, "currency": "USD",
                  "source_url": "https://example.com/cap", "coverage_verified": True}}
    result = build_watch_pool(**args, cache=cache, market_caps=caps,
                              params=replace(PARAMS, market_cap_policy="require_known"))
    assert result["audit"][0]["market_cap"] == 300_000_000
    assert result["audit"][0]["market_cap_status"] == "above_minimum"
    assert [row["symbol"] for row in result["watch"]] == ["A"]


@pytest.mark.parametrize("source", ["mapping", "submission"])
@pytest.mark.parametrize("value", [2000.9, 2000.0, True, False, "+2000", "-2000", "2000.9", "2000.0",
                                   " 2000", "2000 ", "2e3", "２０００", "", None, {}, []])
def test_malformed_cik_never_certifies_or_looks_up_coerced_issuer(tmp_path, source, value):
    args, cache = scenario(tmp_path, ["A", "B"])
    # Seed the issuer int(value) would select, including CIK 1 for true.
    cik = 1 if value is True else 2000
    seed_evidence(cache, ["A", "B"], {"A": {"cik": cik}})
    url = TICKERS_URL if source == "mapping" else f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    raw = json.loads(cache.get(url))
    if source == "mapping":
        raw["0"]["cik_str"] = value
    else:
        raw["cik"] = value
    cache_entry(cache, url, canonical_bytes(raw))
    result = build_watch_pool(**args, cache=cache, params=replace(PARAMS, target_total=1))
    bad, good = result["audit"][0], result["audit"][1]
    evidence = bad["verification"]
    assert bad["reason"] == "security_unknown"
    assert evidence["status"] == "unknown"
    assert evidence["reason"] == "sec_evidence_malformed"
    assert "classification" not in evidence and "cik" not in evidence
    assert len(evidence["sources"]) == (1 if source == "mapping" else 2)
    assert good["verification"]["classification"] == "operating_common_equity"
    assert [row["symbol"] for row in result["watch"]] == ["B"]
    if source == "mapping":
        issuer_url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        assert sha256(issuer_url.encode()) not in result["metadata"]["raw_sources"]


@pytest.mark.parametrize("source", ["mapping", "submission"])
@pytest.mark.parametrize("cik", [1, 2000, 9_999_999_999])
@pytest.mark.parametrize("representation", ["integer", "digits", "padded_digits"])
def test_legitimate_cik_representations_and_boundaries_verify(tmp_path, source, cik, representation):
    cache = ResearchCache(tmp_path / "cache")
    seed_evidence(cache, ["A"], {"A": {"cik": cik}})
    url = TICKERS_URL if source == "mapping" else f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    raw = json.loads(cache.get(url))
    value = cik if representation == "integer" else str(cik) if representation == "digits" else f"{cik:010d}"
    if source == "mapping":
        raw["0"]["cik_str"] = value
    else:
        raw["cik"] = value
    payload = canonical_bytes(raw)
    cache_entry(cache, url, payload)
    evidence = SecVerifier(cache, DAY).verify("A")
    assert evidence["status"] == "verified"
    assert evidence["classification"] == "operating_common_equity"
    assert evidence["cik"] == cik
    assert len(evidence["sources"]) == 3
    assert {"url": url, "sha256": sha256(payload)} in evidence["sources"]
    assert cache.requests == 0


@pytest.mark.parametrize("source", ["mapping", "submission"])
@pytest.mark.parametrize("value", [0, "0", "0000000000", -1, 10_000_000_000, "10000000000"])
def test_cik_out_of_range_fails_closed(tmp_path, source, value):
    cache = ResearchCache(tmp_path / "cache")
    seed_evidence(cache, ["A"])
    url = TICKERS_URL if source == "mapping" else "https://data.sec.gov/submissions/CIK0000002000.json"
    raw = json.loads(cache.get(url))
    if source == "mapping":
        raw["0"]["cik_str"] = value
    else:
        raw["cik"] = value
    cache_entry(cache, url, canonical_bytes(raw))
    evidence = SecVerifier(cache, DAY).verify("A")
    assert evidence["status"] == "unknown"
    assert "classification" not in evidence
    assert len(evidence["sources"]) == (1 if source == "mapping" else 2)


@pytest.mark.parametrize("value", [2001, "2001", "0000002001"])
def test_submission_cik_mismatch_still_fails_closed(tmp_path, value):
    cache = ResearchCache(tmp_path / "cache")
    seed_evidence(cache, ["A"])
    url = "https://data.sec.gov/submissions/CIK0000002000.json"
    raw = json.loads(cache.get(url))
    raw["cik"] = value
    cache_entry(cache, url, canonical_bytes(raw))
    evidence = SecVerifier(cache, DAY).verify("A")
    assert evidence["status"] == "unknown"
    assert evidence["reason"] == "sec_cik_mismatch"
    assert len(evidence["sources"]) == 2


def test_conflicting_valid_cik_matches_do_not_choose_an_issuer(tmp_path):
    cache = ResearchCache(tmp_path / "cache")
    mapping = {"0": {"ticker": "A", "cik_str": 2000}, "1": {"ticker": "A", "cik_str": "2001"}}
    cache_entry(cache, TICKERS_URL, canonical_bytes(mapping))
    evidence = SecVerifier(cache, DAY).verify("A")
    assert evidence["status"] == "unknown"
    assert evidence["reason"] == "sec_cik_unknown"
    assert len(evidence["sources"]) == 1
