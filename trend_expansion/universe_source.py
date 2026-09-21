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
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
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
    expected_symbol = "Symbol" if source == "nasdaqlisted" else "ACT Symbol"
    if not reader.fieldnames or expected_symbol not in reader.fieldnames:
        raise UniverseSourceError(f"{source}: missing or malformed header")

    records: list[dict[str, str]] = []
    for row in reader:
        symbol = _clean(row, expected_symbol).upper()
        # The published files end with a non-tabular "File Creation Time" row.
        if not symbol or symbol.startswith("FILE CREATION TIME") or None in row:
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


def build_snapshot(
    output_dir: str | Path,
    *,
    snapshot_date: str | None = None,
    downloader: Callable[[str], bytes] = _download,
) -> dict[str, object]:
    """Refresh both directories and atomically write CSV and metadata files."""
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

    metadata: dict[str, object] = {
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
    _atomic_write(directory / "universe.csv", csv_bytes)
    _atomic_write(
        directory / "metadata.json",
        (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return metadata


def load_snapshot(
    output_dir: str | Path,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Load and validate an existing snapshot without accessing the network."""
    directory = Path(output_dir)
    csv_path, metadata_path = directory / "universe.csv", directory / "metadata.json"
    if not csv_path.is_file() or not metadata_path.is_file():
        raise UniverseSourceError(
            f"No complete cached snapshot in {directory}; run with --refresh"
        )
    csv_bytes = csv_path.read_bytes()
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise UniverseSourceError(f"Invalid snapshot metadata: {exc}") from exc
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
