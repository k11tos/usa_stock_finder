"""Bounded HTTP and immutable raw-response cache for quarterly research only."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from http.client import BadStatusLine, IncompleteRead, LineTooLong, UnknownProtocol, UnknownTransferEncoding
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.request import Request, urlopen


def _atomic_write(path: Path, content: bytes) -> None:
    """Publish a complete entry exclusively, including across independent processes.

    A same-directory hard link atomically creates the destination or raises
    FileExistsError. Readers never see the private file before it is complete.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(content)
        os.link(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


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

    The lifetime aggregate budget charges HTTP bytes (including failed attempts)
    and every decoded cache payload, even on repeated access. Only this call's
    own successful publication readback is credited; race winners are charged
    separately. Failed validation never refunds consumed payload bytes.
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
        self.total_bytes = 0
        self.used = {}

    def get(self, url: str) -> bytes:
        """Read a validated cache entry or explicitly fetch within resource bounds."""
        key = sha256(url.encode())
        path = self.directory / f"{key}.json"
        published_payload = None
        if not path.exists():
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
                published_payload = payload
            except FileExistsError:
                # A concurrent publisher won. Validate its bytes and provenance
                # together below; never retain this download's metadata.
                pass
            except OSError as exc:
                raise ResearchDataError("cache_write_failed") from exc
        entry, payload = self._read_entry(path, url, published_payload=published_payload)
        self.used[key] = {k: v for k, v in entry.items() if k != "body"}
        return payload

    def _read_entry(self, path: Path, url: str, *, published_payload: bytes | None = None) -> tuple[dict, bytes]:
        """Use the same validation for existing entries and publication winners."""
        remaining = self.limits.max_total_bytes - self.total_bytes
        # A credit is local to this call and only available after our exclusive
        # publication succeeds. Losing downloads do not credit a winner's read.
        allowance = remaining + (len(published_payload) if published_payload is not None else 0)
        if allowance <= 0:
            raise ResearchDataError("resource_byte_budget_exhausted")
        entry_limit = self.limits.max_response_bytes * 6 + 4096
        read_limit = min(self.limits.max_response_bytes, allowance) * 6 + 4096
        try:
            size = path.stat().st_size
            if size > entry_limit:
                raise ValueError("oversized cache entry")
            if size > read_limit:
                raise ResearchDataError("resource_byte_budget_exhausted")
            with path.open("rb") as cached_file:
                raw = cached_file.read(read_limit + 1)
            if len(raw) > read_limit:
                if read_limit < entry_limit:
                    raise ResearchDataError("resource_byte_budget_exhausted")
                raise ValueError("oversized cache entry")
            entry = json.loads(raw)
            if not isinstance(entry, dict) or not isinstance(entry["body"], str):
                raise ValueError("invalid cache format")
            payload = entry["body"].encode("utf-8")
            if payload != published_payload:
                self._record_bytes(len(payload))
            if len(payload) > self.limits.max_response_bytes:
                raise ValueError("oversized cached payload")
            observed = datetime.fromisoformat(entry["observed_at_utc"])
            if (entry["url"] != url or entry["sha256"] != sha256(payload)
                    or observed.tzinfo is None):
                raise ValueError("invalid cache provenance")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ResearchDataError("cache_invalid") from exc
        return entry, payload

    def get_asof(self, url: str, asof_date: str, *, not_before: str | None = None,
                 observed_not_before: datetime | None = None) -> bytes:
        """Validate observation dates, with an optional aware timestamp lower bound.

        Completed-session prices require the full cutoff; SEC evidence retains
        calendar-day semantics. Rejected observations remain in source lineage.
        """
        if observed_not_before is not None and observed_not_before.utcoffset() is None:
            raise ValueError("observation cutoff must be timezone-aware")
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
        if observed_not_before is not None and observed < observed_not_before:
            raise ResearchDataError("source_observed_before_cutoff")
        return payload

    def _download(self, url):
        for attempt in range(self.limits.attempts):
            remaining = self.limits.max_seconds - (self.clock() - self.started)
            if self.requests >= self.limits.max_requests or remaining <= 0:
                raise ResearchDataError("resource_budget_exhausted")
            self.requests += 1
            try:
                request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json,text/html"})
                remaining_bytes = self.limits.max_total_bytes - self.total_bytes
                if remaining_bytes <= 0:
                    raise ResearchDataError("resource_byte_budget_exhausted")
                read_limit = min(self.limits.max_response_bytes, remaining_bytes)
                with self.opener(request, timeout=min(self.limits.timeout_seconds, remaining)) as response:
                    try:
                        payload = response.read(read_limit + 1)
                    except IncompleteRead as exc:
                        self._record_bytes(len(exc.partial), downloaded=True)
                        raise
                    self._record_bytes(len(payload), downloaded=True)
                    # Bounded HTTPResponse.read(size) can return a short body
                    # without raising when a Content-Length response ends early.
                    if len(payload) <= read_limit and getattr(response, "length", None):
                        raise IncompleteRead(payload, response.length)
                self._pause(self.limits.pause_seconds)
                return payload
            except (OSError, ValueError, IncompleteRead, BadStatusLine, LineTooLong,
                    UnknownProtocol, UnknownTransferEncoding) as exc:
                if attempt + 1 == self.limits.attempts:
                    raise ResearchDataError("network_failed") from exc
                self._pause(min(2 ** attempt, 8))
        raise AssertionError("unreachable")

    def _record_bytes(self, size: int, *, downloaded=False):
        """Charge consumed payloads without refunding failures or repeated reads."""
        if downloaded:
            self.downloaded_bytes += size
        self.total_bytes += size
        if self.total_bytes > self.limits.max_total_bytes:
            raise ResearchDataError("resource_byte_budget_exhausted")
        if downloaded and size > self.limits.max_response_bytes:
            raise ResearchDataError("response_too_large")

    def _pause(self, seconds):
        if self.clock() - self.started + seconds > self.limits.max_seconds:
            raise ResearchDataError("resource_budget_exhausted")
        self.sleeper(seconds)
