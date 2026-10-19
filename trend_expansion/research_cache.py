"""Bounded HTTP and immutable raw-response cache for quarterly research only."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.request import Request, urlopen

from trend_expansion.universe_source import _atomic_write


def canonical_bytes(value: object) -> bytes:
    """Canonical JSON; timestamps come from inputs, never from a build clock."""
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class ResearchDataError(RuntimeError):
    """A diagnosed data failure, distinct from a numeric screen failure."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ResourceLimits:  # pylint: disable=too-many-instance-attributes
    """Hard upper bounds, including retries and all evidence requests."""

    max_symbols: int = 8000
    batch_size: int = 10
    max_requests: int = 25000
    attempts: int = 3
    timeout_seconds: float = 15
    max_response_bytes: int = 8_000_000
    max_total_bytes: int = 512_000_000
    max_seconds: float = 7200
    pause_seconds: float = 0.25

    def __post_init__(self):
        for value, ceiling in (
            (self.max_symbols, 12000), (self.batch_size, 25),
            (self.max_requests, 40000), (self.attempts, 4),
            (self.max_response_bytes, 16_000_000), (self.max_total_bytes, 1_024_000_000),
        ):
            if not isinstance(value, int) or not 1 <= value <= ceiling:
                raise ValueError("invalid integer resource bound")
        for value, ceiling in (
            (self.timeout_seconds, 30), (self.max_seconds, 14400), (self.pause_seconds, 10),
        ):
            if not math.isfinite(value) or not 0 < value <= ceiling:
                raise ValueError("invalid time resource bound")


class ResearchCache:  # pylint: disable=too-many-instance-attributes
    """Cache URL-addressed raw responses; never overwrite or refresh a frozen input.

    Cache-only is the default. One request at a time, finite attempts, byte and
    wall-clock budgets, and no external threads/processes. Exceptions are not
    cached as successful responses. A corrupt entry is never silently refetched.
    """

    def __init__(self, directory: Path, *, fetch=False, limits=None, user_agent=None,
                 opener=urlopen, sleeper=time.sleep, clock=time.monotonic):
        self.directory = Path(directory)
        self.fetch = fetch
        self.limits = limits or ResourceLimits()
        self.user_agent = user_agent or "QuarterlyExpansionResearch/1.0"
        self.opener = opener
        self.sleeper = sleeper
        self.clock = clock
        self.started = clock()
        self.requests = 0
        self.downloaded_bytes = 0
        self.used = {}

    def get(self, url: str) -> bytes:
        """Read a validated cache entry or explicitly fetch within resource bounds."""
        key = sha256(url.encode())
        path = self.directory / f"{key}.json"
        if path.exists():
            try:
                if path.stat().st_size > self.limits.max_response_bytes * 6 + 4096:
                    raise ValueError("oversized cache entry")
                entry = json.loads(path.read_bytes())
                payload = entry["body"].encode("utf-8")
                observed = datetime.fromisoformat(entry["observed_at_utc"])
                if (entry["url"] != url or entry["sha256"] != sha256(payload)
                        or len(payload) > self.limits.max_response_bytes or observed.tzinfo is None):
                    raise ValueError("invalid cache provenance")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ResearchDataError("cache_invalid") from exc
        else:
            if not self.fetch:
                raise ResearchDataError("cache_missing")
            payload = self._download(url)
            try:
                body = payload.decode("utf-8")
            except UnicodeError as exc:
                raise ResearchDataError("response_encoding") from exc
            entry = {"url": url, "sha256": sha256(payload), "body": body,
                     "observed_at_utc": datetime.now(timezone.utc).isoformat()}
            try:
                _atomic_write(path, canonical_bytes(entry))
            except OSError as exc:
                raise ResearchDataError("cache_write_failed") from exc
        self.used[key] = {k: v for k, v in entry.items() if k != "body"}
        return payload

    def get_asof(self, url: str, asof_date: str, *, not_before: str | None = None) -> bytes:
        """Reject source observations from later calendar days (no backfill)."""
        payload = self.get(url)
        observed = datetime.fromisoformat(self.used[sha256(url.encode())]["observed_at_utc"])
        observed_day = observed.astimezone(ZoneInfo("America/New_York")).date()
        asof_day = date.fromisoformat(asof_date)
        if observed_day > asof_day:
            raise ResearchDataError("source_observed_after_asof")
        if (asof_day - observed_day).days > 7:
            raise ResearchDataError("source_cache_stale")
        if not_before is not None and observed_day < date.fromisoformat(not_before):
            raise ResearchDataError("source_observed_before_data")
        return payload

    def _download(self, url):
        for attempt in range(self.limits.attempts):
            remaining = self.limits.max_seconds - (self.clock() - self.started)
            if self.requests >= self.limits.max_requests or remaining <= 0:
                raise ResearchDataError("resource_budget_exhausted")
            self.requests += 1
            try:
                request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json,text/html"})
                remaining_bytes = self.limits.max_total_bytes - self.downloaded_bytes
                if remaining_bytes <= 0:
                    raise ResearchDataError("resource_byte_budget_exhausted")
                read_limit = min(self.limits.max_response_bytes, remaining_bytes)
                with self.opener(request, timeout=min(self.limits.timeout_seconds, remaining)) as response:
                    payload = response.read(read_limit + 1)
                self.downloaded_bytes += len(payload)
                if self.downloaded_bytes > self.limits.max_total_bytes:
                    raise ResearchDataError("resource_byte_budget_exhausted")
                if len(payload) > self.limits.max_response_bytes:
                    raise ResearchDataError("response_too_large")
                self._pause(self.limits.pause_seconds)
                return payload
            except (OSError, ValueError) as exc:
                if attempt + 1 == self.limits.attempts:
                    raise ResearchDataError("network_failed") from exc
                self._pause(min(2 ** attempt, 8))
        raise AssertionError("unreachable")

    def _pause(self, seconds):
        if self.clock() - self.started + seconds > self.limits.max_seconds:
            raise ResearchDataError("resource_budget_exhausted")
        self.sleeper(seconds)
