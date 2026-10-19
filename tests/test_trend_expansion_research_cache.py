"""Bounded network/cache failure coverage; no real HTTP and no real sleeps."""

import json
from dataclasses import replace
from io import BytesIO
from urllib.error import HTTPError

import pytest

from trend_expansion.research_cache import (
    ResearchCache, ResearchDataError, ResourceLimits, canonical_bytes, sha256,
)
from trend_expansion.watch_prices import WatchParameters, decode_chart


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_retry_backoff_cache_reuse_and_fixed_timeout(tmp_path):
    calls, pauses = [], []
    def open_mock(request, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) < 3:
            raise HTTPError(request.full_url, 429, "rate limited", {}, None)
        return Response(b'{"data": "ok"}')
    cache = ResearchCache(tmp_path, fetch=True, opener=open_mock, sleeper=pauses.append,
                          user_agent="Research team research@example.org")
    assert cache.get("https://example.org/source") == b'{"data": "ok"}'
    assert cache.requests == 3
    assert calls == [("https://example.org/source", 15)] * 3
    assert pauses == [1, 2, 0.25]
    def forbidden(*_args, **_kwargs):
        raise AssertionError("network accessed in offline mode")
    offline = ResearchCache(tmp_path, opener=forbidden)
    assert offline.get("https://example.org/source") == b'{"data": "ok"}'
    assert offline.used == cache.used
    assert offline.requests == 0


def test_retry_failure_is_explicit_and_never_cached_as_success(tmp_path):
    attempts = []
    def fail(*_args, **_kwargs):
        attempts.append(1)
        raise OSError("offline")
    cache = ResearchCache(tmp_path, fetch=True, opener=fail, sleeper=lambda _: None)
    with pytest.raises(ResearchDataError, match="network_failed"):
        cache.get("https://example.org/missing")
    assert len(attempts) == 3
    assert not list(tmp_path.iterdir())
    with pytest.raises(ResearchDataError, match="cache_missing"):
        ResearchCache(tmp_path).get("https://example.org/missing")


def test_request_count_limit_includes_retries(tmp_path):
    calls = []
    def fail(*_args, **_kwargs):
        calls.append(1)
        raise OSError("offline")
    cache = ResearchCache(tmp_path, fetch=True, limits=ResourceLimits(max_requests=2),
                          opener=fail, sleeper=lambda _: None)
    with pytest.raises(ResearchDataError, match="resource_budget_exhausted"):
        cache.get("https://example.org/a")
    assert len(calls) == cache.requests == 2
    with pytest.raises(ResearchDataError, match="resource_budget_exhausted"):
        cache.get("https://example.org/b")
    assert len(calls) == 2


def test_response_byte_and_wall_time_bounds(tmp_path):
    reads = []
    class LargeResponse(Response):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)
    cache = ResearchCache(tmp_path, fetch=True, limits=ResourceLimits(max_response_bytes=10),
                          opener=lambda *_a, **_k: LargeResponse(b"x" * 100), sleeper=lambda _: None)
    with pytest.raises(ResearchDataError, match="response_too_large"):
        cache.get("https://example.org/large")
    assert reads == [11]
    clock = iter([0, 100])
    cache = ResearchCache(tmp_path, fetch=True, limits=ResourceLimits(max_seconds=10), clock=lambda: next(clock))
    with pytest.raises(ResearchDataError, match="resource_budget_exhausted"):
        cache.get("https://example.org/deadline")
    assert cache.requests == 0


def test_corrupt_cache_does_not_refetch_and_write_failure_is_explicit(tmp_path, monkeypatch):
    from trend_expansion import research_cache
    url = "https://example.org/data"
    key = sha256(url.encode())
    path = tmp_path / f"{key}.json"
    path.write_bytes(b"not-json")
    def forbidden(*_args, **_kwargs):
        raise AssertionError("must not repair silently")
    with pytest.raises(ResearchDataError, match="cache_invalid"):
        ResearchCache(tmp_path, fetch=True, opener=forbidden).get(url)
    path.write_bytes(canonical_bytes({"url": url, "body": "body", "sha256": "wrong",
                                     "observed_at_utc": "2026-09-30T21:00:00+00:00"}))
    with pytest.raises(ResearchDataError, match="cache_invalid"):
        ResearchCache(tmp_path).get(url)
    path.unlink()
    def write_failure(*_args):
        raise OSError("disk full")
    monkeypatch.setattr(research_cache, "_atomic_write", write_failure)
    with pytest.raises(ResearchDataError, match="cache_write_failed"):
        ResearchCache(tmp_path, fetch=True, opener=lambda *_a, **_k: Response(b"body"),
                      sleeper=lambda _: None).get(url)
    assert not path.exists()


@pytest.mark.parametrize("payload,reason", [(b'{}', "ohlcv_malformed"),
    (b'{"chart":{"error":{"code":"Not Found"}}}', "provider_error"),
    (b'{"chart":{"error":null,"result":[]}}', "ohlcv_malformed"),
    (b'{"chart":{"error":null,"result":[{"meta":{"symbol":"OTHER"}}]}}', "provider_symbol_mismatch")])
def test_provider_failure_never_becomes_threshold_failure(payload, reason):
    with pytest.raises(ResearchDataError, match=reason):
        decode_chart(payload, "ABC")


@pytest.mark.parametrize("changes", [{"max_symbols": 0}, {"batch_size": 26}, {"attempts": 5},
    {"max_requests": 40001}, {"max_seconds": float("inf")}, {"timeout_seconds": -1},
    {"pause_seconds": 0}, {"max_response_bytes": 100_000_000}])
def test_resource_limits_are_finite_and_bounded(changes):
    with pytest.raises(ValueError):
        ResourceLimits(**changes)


@pytest.mark.parametrize("changes", [{"max_expansion": 51}, {"min_bars": 251},
    {"market_cap_policy": "silent_pass"}, {"short_weight": 0.5}, {"max_price": 4},
    {"min_price": float("nan")}, {"max_verifications": 201}])
def test_invalid_research_parameters_are_rejected(changes):
    with pytest.raises(ValueError):
        WatchParameters(**changes)


def test_total_download_byte_budget_is_finite(tmp_path):
    cache = ResearchCache(tmp_path, fetch=True, limits=ResourceLimits(max_total_bytes=5),
                          opener=lambda *_a, **_k: Response(b"123"), sleeper=lambda _: None)
    assert cache.get("https://example.org/a") == b"123"
    with pytest.raises(ResearchDataError, match="resource_byte_budget_exhausted"):
        cache.get("https://example.org/b")
    assert cache.downloaded_bytes == 6
    # The crossing response was not published as a valid cache entry.
    assert len(list(tmp_path.iterdir())) == 1
