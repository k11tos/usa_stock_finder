"""Offline admission and real daily-funnel regressions; synthetic financial evidence only."""

# pylint: disable=protected-access

import json
import socket
from datetime import date
from unittest.mock import MagicMock

import pytest

import main
from config import InvestmentConfig, TrendExpansionConfig
from live_performance_logger import build_buy_signal_rows
from tests.test_trend_expansion_watch_pool import DAY, scenario
from trend_expansion.live_watch import combine_watch
from trend_expansion.watch_pool import build_watch_pool, publish_watch_pool


@pytest.fixture
def admitted(tmp_path, monkeypatch):
    """Build genuine Stage C artifacts from frozen offline SEC/listing/price fixtures."""
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **kw: pytest.fail('network forbidden'))
    args, cache = scenario(tmp_path, ['FBRT', 'MOMO', 'FAIL'], core_symbols=['CORE'])
    result = build_watch_pool(**args, cache=cache)
    directory = publish_watch_pool(tmp_path / 'artifacts', result)
    review = tmp_path / 'review.json'
    metadata = json.loads((directory / 'metadata.json').read_bytes())
    review.write_text(json.dumps({'schema_version': 1, 'decision': 'approved', 'operator': 'fixture-only',
        'reviewed_on': DAY, 'stage_d_evidence': 'synthetic://not-production-evidence',
        'snapshot_generation': metadata['snapshot_generation'], 'core_sha256': metadata['lineage']['core']['sha256']}))
    monkeypatch.setattr(TrendExpansionConfig, 'ENABLED', True)
    monkeypatch.setattr(TrendExpansionConfig, 'ARTIFACT_DIR', str(directory))
    monkeypatch.setattr(TrendExpansionConfig, 'ACTIVATION_REVIEW', str(review))
    monkeypatch.setattr(InvestmentConfig, 'MIN_INVESTMENT', 100)
    monkeypatch.setattr(InvestmentConfig, 'MAX_INVESTMENT', 100)
    monkeypatch.setattr(InvestmentConfig, 'DISTRIBUTION_STRATEGY', 'equal')
    return args, result, directory


def combine(admitted, symbols=None, today=DAY):
    """Read fixture current Core; never touch live portfolio."""
    return combine_watch(symbols or ['CORE'], core_csv=admitted[0]['core_csv'], today=date.fromisoformat(today))


def test_true_core_first_overlap_cap_and_rollback(admitted, monkeypatch):
    symbols, sources, counts = combine(admitted, ['CORE', 'FBRT'])
    assert symbols == ['CORE', 'FBRT', 'FAIL', 'MOMO']
    assert sources['FBRT'] == 'core_quant' and sources['MOMO'] == 'trend_expansion'
    assert counts['overlap'] == 1 and counts['expansion'] == 2
    assert counts['fallback_reason'] is None
    monkeypatch.setattr(TrendExpansionConfig, 'MAX_NAMES', '0')
    assert combine(admitted)[0] == ['CORE']
    monkeypatch.setattr(TrendExpansionConfig, 'MAX_NAMES', '50')
    assert len(combine(admitted)[0]) == 4  # No forced target of 100.
    original = {p: p.read_bytes() for p in admitted[2].iterdir()}
    monkeypatch.setattr(TrendExpansionConfig, 'ENABLED', False)
    assert combine(admitted)[0] == ['CORE']
    assert original == {p: p.read_bytes() for p in admitted[2].iterdir()}


@pytest.mark.parametrize('today', ['2026-09-29', '2026-12-30', '2027-01-01'])
def test_future_stale_wrong_quarter(admitted, today, caplog):
    assert combine(admitted, today=today)[0] == ['CORE']
    assert 'future_or_stale' in caplog.text


@pytest.mark.parametrize('damage', [
    'missing', 'malformed', 'checksum', 'unknown', 'unverified', 'exchange', 'schema', 'core'])
def test_invalid_artifact_falls_back(admitted, damage, tmp_path, monkeypatch, caplog):
    args, result, directory = admitted
    if damage == 'missing':
        monkeypatch.setattr(TrendExpansionConfig, 'ARTIFACT_DIR', str(tmp_path / 'missing'))
    elif damage == 'malformed':
        (directory / 'metadata.json').write_text('[]')
    elif damage == 'checksum':
        (directory / 'watch.csv').write_text('corrupted')
    elif damage == 'core':
        args['core_csv'].write_text('symbol\nNEW\n')
    else:
        if damage in {'unknown', 'unverified'}:
            result['audit'][0]['verification']['status'] = damage
        elif damage == 'exchange':
            result['audit'][0]['listing']['exchange'] = 'OTC'
        else:
            result['metadata']['schema_version'] = 1
        directory = publish_watch_pool(tmp_path / damage, result)
        monkeypatch.setattr(TrendExpansionConfig, 'ARTIFACT_DIR', str(directory))
    symbols, sources, counts = combine(admitted)
    assert symbols == ['CORE'] and sources == {'CORE': 'core_quant'}
    assert counts['fallback_reason'] and counts['expansion'] == 0
    assert 'EXPANSION_CORE_ONLY' in caplog.text


def test_review_and_sizing_blockers(admitted, monkeypatch):
    monkeypatch.setattr(InvestmentConfig, 'MAX_INVESTMENT', 0)
    assert 'fixed_100_sizing_mismatch' in str(combine(admitted)[2]['fallback_reason'])
    monkeypatch.setattr(InvestmentConfig, 'MAX_INVESTMENT', 100)
    monkeypatch.setattr(TrendExpansionConfig, 'ACTIVATION_REVIEW', '')
    assert combine(admitted)[0] == ['CORE']


def test_daily_selection_real_safety_sizing_and_sources(admitted, monkeypatch):
    combined, sources, _ = combine(admitted)
    metadata = {'exchange': 'NYSE', 'quoteType': 'EQUITY', 'longName': 'Franklin BSP Realty Trust',
                'regularMarketPrice': 30, 'volume': 100000}
    assert main.is_tradable_common_stock(metadata)[0] is False
    assert main.is_tradable_common_stock(metadata, verified_common_equity=True) == (True, None)
    for name in ['Closed End Fund Trust', 'Preferred Trust', 'SPAC Trust', 'Warrant Trust']:
        assert not main.is_tradable_common_stock({**metadata, 'longName': name}, verified_common_equity=True)[0]
    monkeypatch.setattr(main, '_fetch_symbol_metadata', lambda symbol: metadata)
    assert main._filter_entry_symbols_by_exchange(combined, verified_symbols={'FBRT', 'MOMO', 'FAIL'}) == combined[1:]
    finder = MagicMock(symbols=combined)
    finder.source_pool_by_symbol = sources
    finder.current_price = {'CORE': 30, 'FBRT': 30, 'MOMO': 101, 'FAIL': 20}
    finder.has_valid_trend_template.return_value = {'CORE': True, 'FBRT': True, 'MOMO': True, 'FAIL': False}
    buy, hold = main.select_stocks(finder, {str(days): dict.fromkeys(combined, 60) for days in (50, 100, 200)})
    assert buy == ['CORE', 'FBRT', 'MOMO'] and not hold
    allocations = main.calculate_investment_per_stock(
        buy, account_balance={'available_cash': 1000, 'total_balance': 1000})
    assert allocations == dict.fromkeys(buy, 100.0)
    quantities = main.calculate_share_quantities(allocations, finder, current_holdings=[])
    assert quantities['FBRT']['shares_to_buy'] == 3 and 'MOMO' not in quantities and 'FAIL' not in quantities
    rows = build_buy_signal_rows(
        run_id='fixture', run_date=DAY, share_quantities=quantities, source_pool_by_symbol=sources)
    assert next(row for row in rows if row['symbol'] == 'FBRT')['source'] == 'trend_expansion'


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('mode', ['normal', 'pinned', 'event', 'cooldown'])
def test_real_daily_main_with_expansion_and_rollback(admitted, monkeypatch, enabled, mode):
    """Real trend/correlation, safety filters, sizing, formatter and turnover holdings."""
    import numpy as np
    import pandas as pd
    from sell_signals import SellDecision, SellReason

    args, _, _ = admitted
    monkeypatch.setattr(TrendExpansionConfig, 'ENABLED', enabled)
    monkeypatch.setattr(main, 'combine_watch', lambda symbols: combine_watch(
        symbols, core_csv=args['core_csv'], today=date.fromisoformat(DAY)))
    monkeypatch.setattr(main, '_load_and_validate_runtime_prerequisites', lambda: True)
    monkeypatch.setattr(main, 'fetch_us_stock_holdings', lambda: ['OLD'])
    monkeypatch.setattr(main, 'read_csv_first_column', lambda _: ['CORE'])
    monkeypatch.setattr(main, '_load_previous_tracked_items', lambda _: ['FBRT'])
    metadata = {'exchange': 'NYSE', 'quoteType': 'EQUITY', 'regularMarketPrice': 30, 'volume': 100000}
    monkeypatch.setattr(main, '_fetch_symbol_metadata', lambda _: metadata)
    arrays = {}
    for symbol in ['CORE', 'FBRT', 'MOMO', 'FAIL', 'OLD']:
        close = np.linspace(10, 30, 260) if symbol != 'FAIL' else np.linspace(30, 10, 260)
        if symbol == 'FBRT' and mode == 'pinned':
            close = np.concatenate([np.linspace(10, 20, 249), np.full(11, 26.0)])
        if symbol == 'FBRT' and mode == 'event':
            close = np.concatenate([np.linspace(10, 20, 258), [26.0, 26.01]])
        for field, values in [('Open', close), ('Close', close), ('High', close*(1.001 if mode == 'pinned' else 1.01)),
                              ('Low', close*(.999 if mode == 'pinned' else .99)),
                              ('Volume', np.linspace(100000, 200000, 260))]:
            arrays[field, symbol] = values
    frame = pd.DataFrame(arrays, index=pd.bdate_range(end=DAY, periods=260))
    monkeypatch.setattr('stock_analysis.yf.download', lambda *a, **kw: frame)
    monkeypatch.setattr(main, 'is_in_cooldown', lambda symbol, *_: mode == 'cooldown' and symbol == 'FBRT')
    # Real sell engine's holding persistence and priority have separate full-suite regressions.
    monkeypatch.setattr(main, '_prepare_sell_decisions_and_quantities', lambda *a: (
        {'OLD': SellDecision('OLD', SellReason.NONE, 0)}, None, 0, []))
    monkeypatch.setattr(main, 'fetch_account_balance', lambda: {'available_cash': 1000, 'total_balance': 1000})
    allocations = main.calculate_investment_per_stock
    sizing_inputs = []
    def record_sizing(symbols, **kwargs):
        sizing_inputs.append(symbols)
        return allocations(symbols, **kwargs)
    monkeypatch.setattr(main, 'calculate_investment_per_stock', record_sizing)
    trade_log, state_save, report = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(main, 'append_trade_signals', trade_log)
    monkeypatch.setattr(main, 'append_account_snapshots', MagicMock())
    monkeypatch.setattr(main, 'save_json', state_save)
    monkeypatch.setattr(main, '_send_daily_report', report)
    monkeypatch.setattr(main, '_run_performance_report_after_trade_alert', lambda: None)
    monkeypatch.setattr(main, 'collect_broker_equity_snapshot_safely', lambda *_: None)
    main.main()
    expected = (['CORE', 'FBRT', 'MOMO'] if mode == 'normal' else ['CORE', 'MOMO']) if enabled else ['CORE']
    assert sizing_inputs == [expected]
    rows = trade_log.call_args.args[0]
    assert [row['symbol'] for row in rows] == expected
    assert all(row['quantity'] == 3 for row in rows)
    assert 'FAIL' not in report.call_args.args[0]
    assert 'OLD' in state_save.call_args.args[0]
    if enabled:
        assert [row['source'] for row in rows] == ['core_quant'] + ['trend_expansion'] * (len(expected) - 1)


@pytest.mark.parametrize('value', [None, 'false', 'False'])
def test_default_and_false_do_not_read_artifacts(monkeypatch, value):
    import os
    import subprocess
    import sys
    env = os.environ.copy()
    if value is None:
        env.pop('TREND_EXPANSION_ENABLED', None)
    else:
        env['TREND_EXPANSION_ENABLED'] = value
    actual = subprocess.check_output(
        [sys.executable, '-c', 'from config import TrendExpansionConfig; print(TrendExpansionConfig.ENABLED)'], env=env)
    assert actual.strip() == b'False'
    monkeypatch.setattr(TrendExpansionConfig, 'ENABLED', False)
    monkeypatch.setattr('trend_expansion.live_watch.validate_watch', lambda *a: pytest.fail('read disabled artifact'))
    original = ['BRK.B', 'CORE', 'CORE']
    assert combine_watch(original)[0] is original


def test_cli_off_on_rollback_has_no_state_writes(admitted, monkeypatch, tmp_path):
    """The documented CLI prints admission only; fixture approval is never production evidence."""
    import os
    import subprocess
    import sys

    args, _, directory = admitted
    monkeypatch.setenv('TREND_EXPANSION_ARTIFACT_DIR', str(directory))
    monkeypatch.setenv('TREND_EXPANSION_ACTIVATION_REVIEW', str(tmp_path / 'review.json'))
    monkeypatch.setenv('MIN_INVESTMENT', '100')
    monkeypatch.setenv('MAX_INVESTMENT', '100')
    monkeypatch.setenv('DISTRIBUTION_STRATEGY', 'equal')
    monkeypatch.setenv('TREND_EXPANSION_MAX_NAMES', '50')
    (tmp_path / 'holding_state.json').write_text('["OLD", "FBRT"]')
    (tmp_path / 'trades.csv').write_text('symbol,quantity\nOLD,3\n')
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    outputs = []
    for enabled in ['False', 'True', 'False']:
        monkeypatch.setenv('TREND_EXPANSION_ENABLED', enabled)
        output = subprocess.check_output([sys.executable, '-m', 'tools.inspect_live_watch',
            '--core-csv', str(args['core_csv']), '--today', DAY], env=os.environ.copy())
        outputs.append(json.loads(output))
    assert outputs[0] == outputs[2]
    assert outputs[0]['symbols'] == ['CORE']
    assert outputs[1]['counts']['expansion'] == 3
    assert outputs[1]['counts']['combined_watch'] == 4
    assert outputs[1]['counts']['fallback_reason'] is None
    assert before == {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


@pytest.mark.parametrize('broker_held', [False, True])
def test_expansion_quarantine_uses_broker_holdings_not_tracking(admitted, broker_held):
    """Source metadata never grants an event exemption; only real broker ownership does."""
    assert combine(admitted)[1]['FBRT'] == 'trend_expansion'
    finder = MagicMock()
    finder.source_pool_by_symbol = {'FBRT': 'trend_expansion'}
    finder.get_event_quarantine_metrics.return_value = {
        'is_event_quarantine': True, 'max_gap_up_pct': .3, 'days_since_gap': 1,
        'current_vs_gap_close_pct': 0, 'drawdown_from_post_gap_high_pct': 0}
    buy, _ = main._filter_buy_candidates_by_event_quarantine(
        ['FBRT'], finder, existing_symbols={'FBRT'} if broker_held else set())
    assert buy == (['FBRT'] if broker_held else [])
