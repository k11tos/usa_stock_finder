"""Build an offline snapshot of the Nasdaq Trader symbol directory.

This module is deliberately independent from the live candidate pipeline.  It
only downloads, normalizes, and caches listing metadata for later research.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import URLError
from urllib.request import urlopen

SCHEMA_VERSION = 1
SOURCE_URLS = {
    "nasdaqlisted": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "otherlisted": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
}
SNAPSHOT_COLUMNS = (
    "symbol",
    "security_name",
    "exchange",
    "market_category",
    "financial_status",
    "round_lot_size",
    "etf",
    "test_issue",
    "next_shares",
    "cqs_symbol",
    "nasdaq_symbol",
    "source",
    "snapshot_date",
)
SOURCE_HEADERS = {
    "nasdaqlisted": frozenset(
        {
            "Symbol",
            "Security Name",
            "Market Category",
            "Test Issue",
            "Financial Status",
            "Round Lot Size",
            "ETF",
            "NextShares",
        }
    ),
    "otherlisted": frozenset(
        {
            "ACT Symbol",
            "Security Name",
            "Exchange",
            "CQS Symbol",
            "ETF",
            "Round Lot Size",
            "Test Issue",
            "NASDAQ Symbol",
        }
    ),
}

_OTHER_EXCHANGES = {
    "A": "NYSE AMERICAN",
    "N": "NYSE",
    "P": "NYSE ARCA",
    "V": "IEX",
    "Z": "CBOE BZX",
}


class UniverseSourceError(RuntimeError):
    """Raised when source download or snapshot validation fails."""


def _clean(row: dict[str, str | None], field: str) -> str:
    return (row.get(field) or "").strip()


def normalize_exchange(raw_exchange: str, source: str) -> str:
    """Return a stable exchange name for a directory exchange code."""
    value = raw_exchange.strip().upper()
    if source == "nasdaqlisted":
        return "NASDAQ"
    return _OTHER_EXCHANGES.get(value, value)


def parse_directory(text: str, source: str, snapshot_date: str) -> list[dict[str, str]]:
    """Parse one Nasdaq Trader pipe-delimited directory into normalized rows."""
    if source not in SOURCE_URLS:
        raise ValueError(f"Unsupported directory source: {source}")

    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), delimiter="|")
    expected_headers = SOURCE_HEADERS[source]
    actual_headers = reader.fieldnames or []
    missing_headers = expected_headers.difference(actual_headers)
    unexpected_headers = set(actual_headers).difference(expected_headers)
    if (
        missing_headers
        or unexpected_headers
        or len(actual_headers) != len(expected_headers)
    ):
        details = []
        if missing_headers:
            details.append(f"missing {sorted(missing_headers)}")
        if unexpected_headers:
            details.append(f"unexpected {sorted(unexpected_headers)}")
        if len(actual_headers) != len(set(actual_headers)):
            details.append("duplicate header names")
        raise UniverseSourceError(
            f"{source}: incompatible header ({'; '.join(details)})"
        )

    expected_symbol = "Symbol" if source == "nasdaqlisted" else "ACT Symbol"

    records: list[dict[str, str]] = []
    for row in reader:
        symbol = _clean(row, expected_symbol).upper()
        # The published files end with a non-tabular "File Creation Time" row.
        if not symbol or symbol.startswith("FILE CREATION TIME"):
            continue
        # DictReader uses a None key for extra values and None values for
        # structurally absent trailing fields. Empty strings remain legitimate.
        if None in row or any(row[field] is None for field in expected_headers):
            continue
        if _clean(row, "Security Name") == "Security Name":
            continue
        exchange_code = (
            "NASDAQ" if source == "nasdaqlisted" else _clean(row, "Exchange")
        )
        records.append(
            {
                "symbol": symbol,
                "security_name": _clean(row, "Security Name"),
                "exchange": normalize_exchange(exchange_code, source),
                "market_category": _clean(row, "Market Category"),
                "financial_status": _clean(row, "Financial Status"),
                "round_lot_size": _clean(row, "Round Lot Size"),
                "etf": _clean(row, "ETF").upper(),
                "test_issue": _clean(row, "Test Issue").upper(),
                "next_shares": _clean(row, "NextShares").upper(),
                "cqs_symbol": _clean(row, "CQS Symbol"),
                "nasdaq_symbol": _clean(row, "NASDAQ Symbol"),
                "source": source,
                "snapshot_date": snapshot_date,
            }
        )
    return records


def normalize_records(
    records: Iterable[dict[str, str]],
) -> tuple[list[dict[str, str]], int]:
    """Deduplicate symbols with stable source precedence and sort the result."""
    ordered = sorted(
        records,
        key=lambda row: (
            row["symbol"],
            row["source"] != "nasdaqlisted",
            row["exchange"],
            row["source"],
        ),
    )
    by_symbol: dict[str, dict[str, str]] = {}
    duplicates = 0
    for record in ordered:
        if record["symbol"] in by_symbol:
            duplicates += 1
            continue
        by_symbol[record["symbol"]] = record
    return (
        sorted(by_symbol.values(), key=lambda row: (row["symbol"], row["exchange"])),
        duplicates,
    )


def _download(url: str) -> bytes:
    try:
        with urlopen(url, timeout=30) as response:  # nosec B310 - fixed HTTPS URLs
            return response.read()
    except (OSError, URLError) as exc:
        raise UniverseSourceError(
            f"Failed to refresh Nasdaq Trader source {url}: {exc}"
        ) from exc


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}."
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _publish_generation(
    directory: Path, csv_bytes: bytes, metadata_bytes: bytes
) -> None:
    """Publish a complete immutable generation, then atomically select it.

    The CURRENT file is the commit point. A failure before its replacement
    leaves the loader selecting the previous complete generation. A failure at
    the commit point can leave an unreferenced complete generation, but cannot
    create a mixed CSV/metadata pair.
    """
    generations = directory / "generations"
    generations.mkdir(parents=True, exist_ok=True)
    generation_name = uuid.uuid4().hex
    staging = Path(tempfile.mkdtemp(dir=generations, prefix=".staging-"))
    generation = generations / generation_name
    committed = False
    try:
        _atomic_write(staging / "universe.csv", csv_bytes)
        _atomic_write(staging / "metadata.json", metadata_bytes)
        os.replace(staging, generation)
        _atomic_write(directory / "CURRENT", f"{generation_name}\n".encode("ascii"))
        committed = True
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        # A failed CURRENT publication leaves this complete generation orphaned.
        # Removing it is safe because the old CURRENT was never replaced.
        if not committed and generation.exists():
            shutil.rmtree(generation)


def build_snapshot(
    output_dir: str | Path,
    *,
    snapshot_date: str | None = None,
    downloader: Callable[[str], bytes] = _download,
) -> dict[str, Any]:
    """Refresh both directories and publish one coherent snapshot generation."""
    day = snapshot_date or date.today().isoformat()
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError("snapshot_date must use YYYY-MM-DD") from exc

    raw_sources: dict[str, bytes] = {}
    records: list[dict[str, str]] = []
    for source, url in SOURCE_URLS.items():
        try:
            payload = downloader(url)
        except UniverseSourceError:
            raise
        except Exception as exc:
            raise UniverseSourceError(
                f"Failed to refresh Nasdaq Trader source {url}: {exc}"
            ) from exc
        raw_sources[source] = payload
        try:
            records.extend(parse_directory(payload.decode("utf-8-sig"), source, day))
        except UnicodeDecodeError as exc:
            raise UniverseSourceError(f"{source}: response is not UTF-8 text") from exc

    normalized, duplicate_count = normalize_records(records)
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        csv_buffer, fieldnames=SNAPSHOT_COLUMNS, lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(normalized)
    csv_bytes = csv_buffer.getvalue().encode("utf-8")

    metadata: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_date": day,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "record_count": len(normalized),
        "duplicate_symbol_count": duplicate_count,
        "snapshot_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "sources": {
            source: {
                "url": SOURCE_URLS[source],
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
            for source, payload in raw_sources.items()
        },
    }
    directory = Path(output_dir)
    metadata_bytes = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    _publish_generation(directory, csv_bytes, metadata_bytes)
    return metadata


def load_snapshot(
    output_dir: str | Path,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Load and validate an existing snapshot without accessing the network."""
    directory = Path(output_dir)
    current_path = directory / "CURRENT"
    if not current_path.is_file():
        raise UniverseSourceError(
            f"No complete cached snapshot in {directory}; run with --refresh"
        )
    try:
        generation_name = current_path.read_text(encoding="ascii").strip()
        if not generation_name or Path(generation_name).name != generation_name:
            raise ValueError("invalid generation name")
        generation = directory / "generations" / generation_name
        csv_path = generation / "universe.csv"
        metadata_path = generation / "metadata.json"
        csv_bytes = csv_path.read_bytes()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError, ValueError) as exc:
        raise UniverseSourceError(f"Invalid snapshot generation: {exc}") from exc
    if metadata.get("schema_version") != SCHEMA_VERSION:
        raise UniverseSourceError(
            "Cached snapshot schema version is unsupported; refresh it"
        )
    if metadata.get("snapshot_sha256") != hashlib.sha256(csv_bytes).hexdigest():
        raise UniverseSourceError("Cached snapshot checksum does not match metadata")
    records = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"))))
    if len(records) != metadata.get("record_count"):
        raise UniverseSourceError(
            "Cached snapshot record count does not match metadata"
        )
    return records, metadata
