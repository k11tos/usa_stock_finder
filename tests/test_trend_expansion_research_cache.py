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


class TruncatedResponse(Response):
    def read(self, size=-1):
        partial = super().read(size)
        raise IncompleteRead(partial, 10)


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
