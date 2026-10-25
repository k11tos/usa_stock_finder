"""Read-only, fail-closed admission of a bounded quarterly watch. No network."""

from __future__ import annotations

import calendar
import csv
import io
import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from config import InvestmentConfig, TrendExpansionConfig
from trend_expansion.research_cache import sha256
from trend_expansion.watch_pool import inspect_watch_pool

logger = logging.getLogger(__name__)


def _key(symbol):
    return symbol.upper().replace('.', '-')


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def validate_watch(directory: Path, core_csv: Path, today: date) -> tuple[list[str], dict]:
    """Validate Stage C v2 checksums, final instrument proof and listing epoch."""
    for name, maximum in (("metadata.json", 2_000_000), ("watch.csv", 200_000), ("audit.json", 64_000_000)):
        _require((directory / name).stat().st_size <= maximum, 'artifact_resource_bound')
    metadata = inspect_watch_pool(directory)
    _require(metadata['schema_version'] == 2
             and metadata['finalist_verification'] == 'SEC_operating_common_equity'
             and metadata['rebalance_cadence'] == 'quarterly_manual', 'unsupported_schema')
    asof = date.fromisoformat(metadata['asof_date'])
    month_index = asof.year * 12 + asof.month - 1 + 3
    expiry = date(month_index // 12, month_index % 12 + 1,
                  min(asof.day, calendar.monthrange(month_index // 12, month_index % 12 + 1)[1]))
    _require(asof <= today < expiry, 'future_or_stale_quarterly_snapshot')
    timestamp = datetime.fromisoformat(metadata['asof_timestamp'])
    session = date.fromisoformat(metadata['session_date'])
    now = (datetime.now(timezone.utc) if today == date.today()
           else datetime.combine(today, datetime.max.time(), timezone.utc))
    _require(timestamp.tzinfo is not None and timestamp.astimezone(ZoneInfo('America/New_York')).date() == session
             and 0 <= (asof - session).days <= 4 and timestamp <= now, 'invalid_timestamp')
    core = metadata['lineage']['core']
    _require(core['sha256'] == sha256(core_csv.read_bytes())
             and date.fromisoformat(core['asof_date']) == asof, 'core_snapshot_epoch_mismatch')
    listing_metadata = metadata['lineage']['stage_a']['metadata']
    _require(0 <= (asof - date.fromisoformat(listing_metadata['snapshot_date'])).days <= 7,
             'listing_snapshot_epoch_mismatch')
    captured = datetime.fromisoformat(listing_metadata['created_at_utc'])
    _require(captured.tzinfo is not None
             and captured.astimezone(ZoneInfo('America/New_York')).date() <= asof, 'future_listing_capture')
    for raw in metadata['raw_sources'].values():
        observed = datetime.fromisoformat(raw['observed_at_utc'])
        _require(observed.tzinfo is not None
                 and observed.astimezone(ZoneInfo('America/New_York')).date() <= asof, 'future_source_capture')
    rows = list(csv.DictReader(io.StringIO((directory / 'watch.csv').read_text())))
    audit = json.loads((directory / 'audit.json').read_bytes())
    selected = [row for row in audit if row['reason'] == 'selected']
    expansion = [row for row in rows if row['source_pool'] == 'trend_expansion']
    _require(all(row['source_pool'] in {'core_quant', 'trend_expansion'} for row in rows), 'unknown_source')
    _require(len(rows) == metadata['counts']['watch'], 'invalid_watch_count')
    _require(len(expansion) == len(selected) == metadata['counts']['expansion'] <= 50,
             'invalid_expansion_count')
    _require(len({_key(row['symbol']) for row in expansion}) == len(expansion), 'duplicate_expansion')
    evidence = {row['symbol']: row for row in selected}
    for row in rows:
        _require(row['asof_date'] == asof.isoformat() and row['asof_timestamp'] == metadata['asof_timestamp']
                 and row['universe_type'] == 'quarterly_watch', 'row_epoch_or_schema_mismatch')
    for row in expansion:
        symbol = row['symbol']
        _require(re.fullmatch(r'[A-Z][A-Z0-9.-]{0,19}', symbol) is not None, 'invalid_symbol')
        proof = evidence[symbol]
        verification, listing = proof['verification'], proof['listing']
        _require(proof['source_pool'] == 'trend_expansion'
                 and proof['asof_timestamp'] == metadata['asof_timestamp']
                 and proof['ohlcv_validity'] == row['ohlcv_validity'] == 'valid', 'invalid_finalist_provenance')
        _require(row['verification_status'] == verification['status'] == 'verified'
                 and verification['authority'] == 'SEC EDGAR'
                 and verification['classification'] == 'operating_common_equity'
                 and verification['shell_status'] == 'explicit_false'
                 and verification['entity_type'] == 'operating'
                 and verification['sic'] not in {'6722', '6726', '6770'}
                 and len(verification['sources']) == 3
                 and all(any(source['url'] == raw['url'] and source['sha256'] == raw['sha256']
                             for raw in metadata['raw_sources'].values())
                         for source in verification['sources']), 'unverified_finalist')
        _require(listing['symbol'] == symbol and listing['exchange'] in {'NYSE', 'NASDAQ', 'AMEX'}
                 and listing['snapshot_date'] == listing_metadata['snapshot_date']
                 and listing['test_issue'] == 'N' and listing['etf'] == 'N'
                 and listing['financial_status'] in {'', 'N'}, 'invalid_listing')
    _require(inspect_watch_pool(directory) == metadata, 'artifact_changed_while_reading')
    _require(core['sha256'] == sha256(core_csv.read_bytes()), 'core_changed_while_reading')
    return [row['symbol'] for row in expansion], metadata


def combine_watch(core_symbols: list[str], *, core_csv: Path = Path('portfolio/portfolio.csv'),
                  today: date | None = None) -> tuple[list[str], dict[str, str], dict]:
    """Preserve disabled input exactly; any enabled admission error returns Core only."""
    sources = dict.fromkeys(core_symbols, 'core_quant')
    diagnostics = {'core': len(core_symbols), 'expansion': 0, 'overlap': 0,
                   'combined_watch': len(core_symbols), 'fallback_reason': None,
                   'artifact': TrendExpansionConfig.ARTIFACT_DIR}
    if not TrendExpansionConfig.ENABLED:
        return core_symbols, sources, diagnostics
    try:
        cap = int(TrendExpansionConfig.MAX_NAMES)
        _require(0 <= cap <= 50, 'invalid_expansion_cap')
        expansion, metadata = validate_watch(
            Path(TrendExpansionConfig.ARTIFACT_DIR), core_csv, today or date.today())
        diagnostics['generation'] = metadata['snapshot_generation']
        # This is a compatibility gate, not a sizing change. Minimum != fixed target.
        _require(InvestmentConfig.MIN_INVESTMENT == InvestmentConfig.MAX_INVESTMENT == 100
                 and InvestmentConfig.DISTRIBUTION_STRATEGY == 'equal', 'fixed_100_sizing_mismatch')
        review = json.loads(Path(TrendExpansionConfig.ACTIVATION_REVIEW).read_bytes())
        _require(review['schema_version'] == 1 and review['decision'] == 'approved'
                 and review['stage_d_evidence'] and review['operator']
                 and date.fromisoformat(review['reviewed_on']) <= (today or date.today())
                 and review['snapshot_generation'] == metadata['snapshot_generation']
                 and review['core_sha256'] == metadata['lineage']['core']['sha256'], 'stage_d_review_required')
        keys = {_key(symbol) for symbol in core_symbols}
        diagnostics['overlap'] = sum(_key(symbol) in keys for symbol in expansion)
        additions = [symbol for symbol in expansion if _key(symbol) not in keys][:cap]
        combined = list(dict.fromkeys(core_symbols)) + additions
        sources.update(dict.fromkeys(additions, 'trend_expansion'))
        diagnostics.update(expansion=len(additions), combined_watch=len(combined))
        return combined, sources, diagnostics
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, csv.Error,
            OverflowError, AttributeError, IndexError) as exc:
        diagnostics['fallback_reason'] = f'{type(exc).__name__}: {exc}'
        logger.warning('EXPANSION_CORE_ONLY %s', json.dumps(diagnostics, sort_keys=True))
        return core_symbols, sources, diagnostics
