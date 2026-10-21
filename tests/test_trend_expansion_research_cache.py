"""Bounded network/cache failure coverage; no real HTTP and no real sleeps."""

import json
import multiprocessing
from dataclasses import replace
from datetime import datetime, timezone
from http.client import (
    BadStatusLine, HTTPResponse, IncompleteRead, LineTooLong, RemoteDisconnected,
    ResponseNotReady, UnknownProtocol, UnknownTransferEncoding,
)
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

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


def seed_cached_payload(directory, url, payload):
    """Write the real frozen format; leave reading and accounting unmocked."""
    path = directory / f"{sha256(url.encode())}.json"
    path.write_bytes(canonical_bytes({"url": url, "body": payload.decode(), "sha256": sha256(payload),
                                     "observed_at_utc": "2026-09-30T21:00:00+00:00"}))
    return path


@pytest.mark.parametrize("budget", [5, 6])
def test_cache_only_aggregate_boundary(tmp_path, budget):
    urls = [f"https://example.org/{name}" for name in ("a", "b")]
    original = [seed_cached_payload(tmp_path, url, b"123").read_bytes() for url in urls]
    def forbidden(*_args, **_kwargs):
        pytest.fail("cache replay accessed network")
    cache = ResearchCache(tmp_path, limits=ResourceLimits(max_total_bytes=budget), opener=forbidden)
    assert cache.get(urls[0]) == b"123"
    if budget == 6:
        assert cache.get(urls[1]) == b"123"
        assert len(cache.used) == 2
    else:
        with pytest.raises(ResearchDataError, match="^resource_byte_budget_exhausted$") as error:
            cache.get(urls[1])
        assert error.value.reason == "resource_byte_budget_exhausted"
        assert len(cache.used) == 1
    assert cache.total_bytes == 6
    assert cache.downloaded_bytes == cache.requests == 0
    assert [path.read_bytes() for path in (tmp_path / f"{sha256(url.encode())}.json" for url in urls)] == original


def test_repeated_cache_reads_charge_again_and_do_not_reset_with_lineage(tmp_path):
    url = "https://example.org/repeated"
    seed_cached_payload(tmp_path, url, b"123")
    cache = ResearchCache(tmp_path, limits=ResourceLimits(max_total_bytes=6))
    assert cache.get(url) == cache.get(url) == b"123"
    cache.used.clear()
    with patch.object(Path, "open", side_effect=AssertionError("exhausted cache opened")) as opened:
        for _ in range(2):
            with pytest.raises(ResearchDataError, match="^resource_byte_budget_exhausted$"):
                cache.get(url)
        opened.assert_not_called()
    assert cache.total_bytes == 6
    assert not cache.used


@pytest.mark.parametrize("download_first", [False, True])
@pytest.mark.parametrize("budget", [5, 6])
def test_cache_hits_and_downloads_share_one_budget(tmp_path, download_first, budget):
    cached, downloaded = "https://example.org/cached", "https://example.org/downloaded"
    seed_cached_payload(tmp_path, cached, b"123")
    reads = []
    class MeasuredResponse(Response):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)
    cache = ResearchCache(tmp_path, fetch=True, limits=ResourceLimits(max_total_bytes=budget),
                          opener=lambda *_a, **_k: MeasuredResponse(b"456"), sleeper=lambda _: None)
    first, second = (downloaded, cached) if download_first else (cached, downloaded)
    assert cache.get(first) in (b"123", b"456")
    if budget == 6:
        assert cache.get(second) in (b"123", b"456")
        assert len(cache.used) == 2
    else:
        with pytest.raises(ResearchDataError, match="^resource_byte_budget_exhausted$"):
            cache.get(second)
        assert len(cache.used) == 1
    assert cache.total_bytes == 6
    assert cache.downloaded_bytes == 3
    assert cache.requests == 1
    assert reads == ([budget + 1] if download_first else [budget - 3 + 1])


def test_download_validation_readback_has_only_a_local_credit(tmp_path):
    url = "https://example.org/download"
    cache = ResearchCache(tmp_path, fetch=True, limits=ResourceLimits(max_total_bytes=3),
                          opener=lambda *_a, **_k: Response(b"123"), sleeper=lambda _: None)
    # The actual readback validates and populates provenance even at the limit.
    assert cache.get(url) == b"123"
    assert cache.used[sha256(url.encode())]["sha256"] == sha256(b"123")
    assert cache.total_bytes == cache.downloaded_bytes == 3
    with pytest.raises(ResearchDataError, match="^resource_byte_budget_exhausted$"):
        cache.get(url)
    with pytest.raises(ResearchDataError, match="^resource_byte_budget_exhausted$"):
        cache.get("https://example.org/another")
    assert cache.downloaded_bytes == 3


def test_download_credit_does_not_survive_to_next_cached_read(tmp_path):
    url = "https://example.org/download"
    cache = ResearchCache(tmp_path, fetch=True, limits=ResourceLimits(max_total_bytes=6),
                          opener=lambda *_a, **_k: Response(b"123"), sleeper=lambda _: None)
    assert cache.get(url) == cache.get(url) == b"123"
    assert cache.total_bytes == 6
    assert cache.downloaded_bytes == 3
    assert cache.requests == 1


@pytest.mark.parametrize("budget", [1, 5000])
def test_cache_budget_preflight_rejects_large_envelope_before_open(tmp_path, budget):
    url = "https://example.org/large-cache"
    seed_cached_payload(tmp_path, url, b"x" * (budget * 6 + 4096))
    cache = ResearchCache(tmp_path, limits=ResourceLimits(max_total_bytes=budget))
    with patch.object(Path, "open", side_effect=AssertionError("oversized cache opened")) as opened:
        with pytest.raises(ResearchDataError, match="^resource_byte_budget_exhausted$"):
            cache.get(url)
        opened.assert_not_called()
    assert cache.total_bytes == cache.requests == 0
    assert not cache.used


@pytest.mark.parametrize("budget,reason", [(2, "resource_byte_budget_exhausted"), (10, "cache_invalid")])
def test_cache_read_remains_bounded_if_file_grows_after_stat(tmp_path, monkeypatch, budget, reason):
    url = "https://example.org/growing"
    path = seed_cached_payload(tmp_path, url, b"a")
    real_open = Path.open
    reads = []
    class GrowingReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def read(self, size):
            result = self.stream.read(size)
            reads.append((size, len(result)))
            return result

        def __exit__(self, *_args):
            self.stream.close()
    def grow_before_open(file_path, mode, *args, **kwargs):
        assert file_path == path and mode == "rb"
        # Controlled local mutation only; accounting and the actual file read
        # still run. This verifies stat is not the only read-size guard.
        with real_open(file_path, "ab") as stream:
            stream.write(b" " * 10_000)
        return GrowingReader(real_open(file_path, mode, *args, **kwargs))
    monkeypatch.setattr(Path, "open", grow_before_open)
    cache = ResearchCache(tmp_path, limits=ResourceLimits(max_total_bytes=budget, max_response_bytes=10))
    with pytest.raises(ResearchDataError, match=f"^{reason}$"):
        cache.get(url)
    bound = budget * 6 + 4096 + 1
    assert reads == [(bound, bound)]
    assert not cache.used


def test_cached_utf8_payload_bytes_exclude_json_escaping_and_envelope(tmp_path):
    url = "https://example.org/unicode"
    payload = '\x00"\\\n한😀'.encode()
    path = seed_cached_payload(tmp_path, url, payload)
    assert path.stat().st_size > len(payload)
    cache = ResearchCache(tmp_path, limits=ResourceLimits(max_total_bytes=len(payload)))
    assert cache.get(url) == payload
    assert cache.total_bytes == len(payload)


@pytest.mark.parametrize("rejection", ["checksum", "observation"])
def test_cache_validation_failure_does_not_refund_payload(tmp_path, rejection):
    url = "https://example.org/rejected"
    path = seed_cached_payload(tmp_path, url, b"123")
    if rejection == "checksum":
        entry = json.loads(path.read_bytes())
        entry["sha256"] = "wrong"
        path.write_bytes(canonical_bytes(entry))
    cache = ResearchCache(tmp_path, limits=ResourceLimits(max_total_bytes=3))
    reason = "cache_invalid" if rejection == "checksum" else "source_observed_after_asof"
    with pytest.raises(ResearchDataError, match=f"^{reason}$"):
        cache.get_asof(url, "2026-09-29")
    assert cache.total_bytes == 3
    with pytest.raises(ResearchDataError, match="^resource_byte_budget_exhausted$"):
        cache.get(url)


@pytest.mark.parametrize("winner", [b"win", b"123"])
@pytest.mark.parametrize("budget", [5, 6])
def test_publication_race_charges_download_and_winner_even_if_identical(tmp_path, monkeypatch, winner, budget):
    from trend_expansion import research_cache
    real_link = research_cache.os.link
    url = "https://example.org/race"
    def publish_winner(source, destination):
        seed_cached_payload(tmp_path, url, winner)
        real_link(source, destination)  # Real FileExistsError and temporary-file cleanup.
    monkeypatch.setattr(research_cache.os, "link", publish_winner)
    cache = ResearchCache(tmp_path, fetch=True, limits=ResourceLimits(max_total_bytes=budget),
                          opener=lambda *_a, **_k: Response(b"123"), sleeper=lambda _: None)
    if budget == 6:
        assert cache.get(url) == winner
        assert cache.used[sha256(url.encode())]["observed_at_utc"] == "2026-09-30T21:00:00+00:00"
        assert cache.used[sha256(url.encode())]["sha256"] == sha256(winner)
    else:
        with pytest.raises(ResearchDataError, match="^resource_byte_budget_exhausted$"):
            cache.get(url)
        assert not cache.used
    assert cache.total_bytes == 6
    assert cache.downloaded_bytes == 3
    assert cache.requests == 1
    assert [path.name for path in tmp_path.iterdir()] == [f"{sha256(url.encode())}.json"]


class TruncatedResponse(Response):
    def read(self, size=-1):
        partial = super().read(size)
        raise IncompleteRead(partial, 10)


@pytest.mark.parametrize("budget,reason,total,requests,read_sizes", [
    (8, None, 8, 2, [7, 5]),
    (7, "resource_byte_budget_exhausted", 8, 2, [6, 4]),
    (4, "resource_byte_budget_exhausted", 4, 1, [3]),
])
@pytest.mark.parametrize("short_body", [False, True])
def test_cached_bytes_and_partial_retry_attempts_share_budget(
        tmp_path, budget, reason, total, requests, read_sizes, short_body):
    cached, fetched = "https://example.org/cached", "https://example.org/partial"
    seed_cached_payload(tmp_path, cached, b"12")
    responses, reads, pauses = [], [], []
    class PartialResponse(Response):
        length = 10 if short_body else None

        def read(self, size=-1):
            reads.append(size)
            partial = super().read(size)
            if short_body:
                return partial
            raise IncompleteRead(partial, 10)
    class CompleteResponse(Response):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)
    def open_mock(*_args, **_kwargs):
        response = PartialResponse(b"ab") if not responses else CompleteResponse(b"cdef")
        responses.append(response)
        return response
    cache = ResearchCache(tmp_path, fetch=True, limits=ResourceLimits(max_total_bytes=budget),
                          opener=open_mock, sleeper=pauses.append, clock=lambda: 0)
    assert cache.get(cached) == b"12"
    if reason:
        with pytest.raises(ResearchDataError, match=f"^{reason}$"):
            cache.get(fetched)
        assert sha256(fetched.encode()) not in cache.used
        assert not (tmp_path / f"{sha256(fetched.encode())}.json").exists()
    else:
        assert cache.get(fetched) == b"cdef"
    assert cache.total_bytes == total
    assert cache.downloaded_bytes == total - 2
    assert len(responses) == requests
    assert reads == read_sizes
    assert pauses == ([1, 0.25] if reason is None else [1])
    assert all(response.closed for response in responses)
    with pytest.raises(ResearchDataError, match="^resource_byte_budget_exhausted$"):
        cache.get(cached)


@pytest.mark.parametrize("failure", ["network", "close", "encoding", "publication", "pause"])
def test_failed_downloads_keep_charges_for_subsequent_cache_reads(tmp_path, monkeypatch, failure):
    from trend_expansion import research_cache
    cached = "https://example.org/cached"
    seed_cached_payload(tmp_path, cached, b"12")
    def write_failure(*_args):
        raise OSError("disk full")
    if failure == "publication":
        monkeypatch.setattr(research_cache, "_atomic_write", write_failure)
    payload = b"\xff\xff" if failure == "encoding" else b"ab"
    limits = ResourceLimits(max_total_bytes=4, attempts=1, max_seconds=0.1 if failure == "pause" else 10)
    reasons = {"network": "network_failed", "close": "network_failed", "encoding": "response_encoding",
               "publication": "cache_write_failed", "pause": "resource_budget_exhausted"}
    class CloseFailureResponse(Response):
        def __exit__(self, *_args):
            self.close()
            raise OSError("close failed after reading")
    def open_mock(*_args, **_kwargs):
        if failure == "network":
            return TruncatedResponse(payload)
        if failure == "close":
            return CloseFailureResponse(payload)
        return Response(payload)
    cache = ResearchCache(tmp_path, fetch=True, limits=limits,
                          opener=open_mock,
                          sleeper=lambda _: None, clock=lambda: 0)
    with pytest.raises(ResearchDataError, match=f"^{reasons[failure]}$"):
        cache.get("https://example.org/failed")
    assert cache.total_bytes == cache.downloaded_bytes == 2
    assert cache.get(cached) == b"12"
    assert cache.total_bytes == 4
    assert not (tmp_path / f"{sha256(b'https://example.org/failed')}.json").exists()


def test_incomplete_read_retries_without_publishing_partial_bytes(tmp_path):
    calls, pauses, responses = [], [], []
    def open_mock(request, timeout):
        assert not list(tmp_path.iterdir())
        calls.append((request.full_url, timeout))
        response = TruncatedResponse(b"partial") if len(calls) == 1 else Response(b"complete")
        responses.append(response)
        return response
    cache = ResearchCache(tmp_path, fetch=True, opener=open_mock, sleeper=pauses.append, clock=lambda: 0)
    url = "https://example.org/truncated"
    assert cache.get(url) == b"complete"
    assert cache.requests == 2
    assert cache.downloaded_bytes == len(b"partialcomplete")
    assert calls == [(url, 15)] * 2
    assert pauses == [1, 0.25]
    assert all(response.closed for response in responses)
    entry = json.loads(next(tmp_path.iterdir()).read_bytes())
    assert entry["body"] == "complete"
    assert entry["sha256"] == cache.used[sha256(url.encode())]["sha256"] == sha256(b"complete")
    assert ResearchCache(tmp_path).get(url) == b"complete"


def test_incomplete_read_exhaustion_is_explicit_without_cache_or_lineage(tmp_path):
    pauses = []
    cache = ResearchCache(tmp_path, fetch=True, opener=lambda *_a, **_k: TruncatedResponse(b"part"),
                          sleeper=pauses.append, clock=lambda: 0)
    with pytest.raises(ResearchDataError, match="^network_failed$") as error:
        cache.get("https://example.org/truncated")
    assert isinstance(error.value.__cause__, IncompleteRead)
    assert cache.requests == 3
    assert cache.downloaded_bytes == 12
    assert pauses == [1, 2]
    assert not cache.used
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("limits,reason,requests,downloaded", [
    (ResourceLimits(max_requests=2), "resource_budget_exhausted", 2, 8),
    (ResourceLimits(max_total_bytes=5), "resource_byte_budget_exhausted", 2, 6),
    (ResourceLimits(max_response_bytes=3), "response_too_large", 1, 4),
    (ResourceLimits(max_seconds=1), "resource_budget_exhausted", 1, 4),
])
def test_incomplete_reads_obey_all_resource_budgets(tmp_path, limits, reason, requests, downloaded):
    elapsed, calls = [0], []
    def open_mock(_request, timeout):
        calls.append(timeout)
        return TruncatedResponse(b"part")
    def advance(seconds):
        elapsed[0] += seconds
    cache = ResearchCache(tmp_path, fetch=True, limits=limits, opener=open_mock,
                          sleeper=advance, clock=lambda: elapsed[0])
    with pytest.raises(ResearchDataError, match=f"^{reason}$"):
        cache.get("https://example.org/truncated")
    assert cache.requests == requests
    assert cache.downloaded_bytes == downloaded
    assert all(0 < timeout <= min(limits.timeout_seconds, limits.max_seconds) for timeout in calls)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("failure", [BadStatusLine("bad status"), LineTooLong("header"),
    UnknownProtocol("invalid protocol"), UnknownTransferEncoding("invalid transfer encoding"),
    RemoteDisconnected("closed"), URLError("offline"), TimeoutError("timed out"),
    OSError("offline"), ValueError("invalid URL")])
def test_response_protocol_and_existing_network_errors_remain_bounded(tmp_path, failure):
    def fail(*_args, **_kwargs):
        raise failure
    cache = ResearchCache(tmp_path, fetch=True, opener=fail, sleeper=lambda _: None, clock=lambda: 0)
    with pytest.raises(ResearchDataError, match="^network_failed$"):
        cache.get("https://example.org/failure")
    assert cache.requests == 3
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("failure", [TypeError("programming error"), RuntimeError("unrelated"),
                                     ResponseNotReady("invalid connection state")])
def test_unrelated_errors_are_not_converted_or_retried(tmp_path, failure):
    def fail(*_args, **_kwargs):
        raise failure
    cache = ResearchCache(tmp_path, fetch=True, opener=fail, sleeper=lambda _: None)
    with pytest.raises(type(failure), match=str(failure)):
        cache.get("https://example.org/failure")
    assert cache.requests == 1
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("headers,body", [
    (b"Content-Length: 20\r\n", b"partial"),
    (b"Transfer-Encoding: chunked\r\n", b"7\r\npartial\r\n5\r\ncut"),
])
def test_actual_http_response_truncation_is_not_a_success(tmp_path, headers, body):
    class Socket:
        def makefile(self, *_args):
            return BytesIO(b"HTTP/1.1 200 OK\r\n" + headers + b"\r\n" + body)
    def open_mock(*_args, **_kwargs):
        response = HTTPResponse(Socket())
        response.begin()
        return response
    cache = ResearchCache(tmp_path, fetch=True, opener=open_mock, sleeper=lambda _: None, clock=lambda: 0)
    with pytest.raises(ResearchDataError, match="^network_failed$"):
        cache.get("https://example.org/truncated")
    assert cache.requests == 3
    assert cache.downloaded_bytes > 0
    assert not list(tmp_path.iterdir())


def _race_cache_process(directory, body, observed, ready, published, output):
    """Spawned worker: independent cache and mocked HTTP, shared publication path."""
    from trend_expansion import research_cache
    real_write = research_cache._atomic_write  # pylint: disable=protected-access
    entries = []
    def synchronized_write(path, content):
        entry = json.loads(content)
        entries.append(entry)
        ready.wait(timeout=10)
        if entry["body"] == "winner":
            try:
                real_write(path, content)
            finally:
                published.set()
        else:
            assert published.wait(timeout=10)
            real_write(path, content)
    cache = ResearchCache(directory, fetch=True, opener=lambda *_a, **_k: Response(body), sleeper=lambda _: None)
    with patch.object(research_cache, "datetime", wraps=datetime) as dates:
        dates.now.return_value = datetime.fromisoformat(observed)
        with patch.object(research_cache, "_atomic_write", synchronized_write):
            payload = cache.get("https://example.org/race")
    output.put((body, payload, cache.used, cache.requests, entries[0]))


def test_two_processes_validate_and_reuse_the_publication_winner(tmp_path):
    context = multiprocessing.get_context("spawn")
    ready, published, output = context.Barrier(2), context.Event(), context.Queue()
    url = "https://example.org/race"
    observations = [datetime(2026, 9, 30, hour, tzinfo=timezone.utc) for hour in (21, 22)]
    processes = [context.Process(target=_race_cache_process,
        args=(tmp_path, body, observed.isoformat(), ready, published, output))
        for body, observed in zip((b"winner", b"loser"), observations)]
    try:
        for process in processes:
            process.start()
        results = [output.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
        output.close()
        output.join_thread()
    entries = [result[4] for result in results]
    assert {entry["observed_at_utc"] for entry in entries} == {value.isoformat() for value in observations}
    winner = next(entry for entry in entries if entry["body"] == "winner")
    assert [json.loads(path.read_bytes()) for path in tmp_path.iterdir()] == [winner]
    assert results[0][1] == results[1][1] == b"winner"
    assert results[0][2] == results[1][2] == {sha256(url.encode()): {
        key: value for key, value in winner.items() if key != "body"}}
    assert [result[3] for result in results] == [1, 1]


@pytest.mark.parametrize("damage", ["checksum", "url", "timestamp", "body_type", "not_json", "oversized"])
def test_invalid_concurrent_winner_fails_closed_and_cleans_temporary_files(tmp_path, monkeypatch, damage):
    from trend_expansion import research_cache
    real_link = research_cache.os.link
    url = "https://example.org/race"
    def publish_invalid_winner(source, destination):
        winner = {"url": url, "body": "winner", "sha256": sha256(b"winner"),
                  "observed_at_utc": "2026-09-30T21:00:00+00:00"}
        if damage == "checksum":
            winner["sha256"] = sha256(b"other response")
        elif damage == "url":
            winner["url"] = "https://example.org/other"
        elif damage == "timestamp":
            winner["observed_at_utc"] = "2026-09-30T21:00:00"
        elif damage == "body_type":
            winner["body"] = 123
        elif damage == "oversized":
            winner["body"] = "x" * 100
        destination.write_bytes(b"not-json" if damage == "not_json" else canonical_bytes(winner))
        real_link(source, destination)
    monkeypatch.setattr(research_cache.os, "link", publish_invalid_winner)
    cache = ResearchCache(tmp_path, fetch=True, limits=ResourceLimits(max_response_bytes=20),
                          opener=lambda *_a, **_k: Response(b"loser"), sleeper=lambda _: None)
    with pytest.raises(ResearchDataError, match="^cache_invalid$"):
        cache.get(url)
    assert not cache.used
    assert cache.requests == 1
    assert [path.name for path in tmp_path.iterdir()] == [f"{sha256(url.encode())}.json"]


@pytest.mark.parametrize("stage", ["write", "link"])
def test_publication_failure_cleans_temporary_file(tmp_path, monkeypatch, stage):
    from trend_expansion import research_cache
    real_fdopen = research_cache.os.fdopen
    class BrokenWriter:
        def __init__(self, descriptor, mode):
            self.file = real_fdopen(descriptor, mode)

        def __enter__(self):
            return self

        def write(self, _content):
            raise OSError("disk full")

        def __exit__(self, *_args):
            self.file.close()
    def fail_link(*_args):
        raise OSError("hard links unavailable")
    if stage == "write":
        monkeypatch.setattr(research_cache.os, "fdopen", BrokenWriter)
    else:
        monkeypatch.setattr(research_cache.os, "link", fail_link)
    cache = ResearchCache(tmp_path, fetch=True, opener=lambda *_a, **_k: Response(b"body"),
                          sleeper=lambda _: None)
    with pytest.raises(ResearchDataError, match="^cache_write_failed$"):
        cache.get("https://example.org/failure")
    assert not list(tmp_path.iterdir())
