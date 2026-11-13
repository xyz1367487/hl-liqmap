"""Synthetic-only acceptance tests. State evidence is retained; no cleanup/deletion."""
import copy
import json
import os
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import harvest
from aggregate import aggregate, aggregate_v1, aggregate_v2, validate_public
from position_scan import SELECTION, prepare, plan, finish

ROOT = Path(__file__).resolve().parents[1]
COINS = {'updated': '2026-11-12', 'caliber': 'avg_7d', 'threshold': 5000000,
         'coins': [{'n': 'BTC', 'v': 6000000}, {'n': 'xyz:TEST', 'v': 7000000}]}


def position(n, coin='BTC', side='L', px=95, lev=5):
    return [coin, side, 1, 100, px, n, lev, 'cross']


def api_state(eq=1, positions=()):
    return {'marginSummary': {'accountValue': str(eq)}, 'assetPositions': [
        {'position': {'coin': p[0], 'szi': '-1' if p[1] == 'S' else '1',
                      'entryPx': '100', 'liquidationPx': p[4], 'positionValue': str(p[5]),
                      'leverage': {'value': p[6], 'type': 'cross'}}} for p in positions]}


def fixture_dir():
    # Local evidence outside the public upload whitelist; retained by explicit instruction.
    folder = Path(os.environ.get('LIQ_TEST_EVIDENCE', str(ROOT.parent / 'evidence'))) / ('state-' + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    return folder


class PositionAcceptance(unittest.TestCase):
    def test_exact_boundary_dual_dex_low_and_negative_equity(self):
        for eq in (0, 1, -10, 9999, 1000000):
            calls = []
            def post(payload):
                calls.append(payload.get('dex', 'main'))
                return api_state(eq, [position(5000), position(5000.01)]) if 'dex' not in payload else api_state(0, [position(-6000, 'xyz:TEST', 'S'), position(9000, 'OTHER')])
            rec, total = harvest.fetch_positions('synthetic', post, {'BTC', 'xyz:TEST'})
            self.assertEqual(calls, ['main', 'xyz'])
            self.assertEqual(rec['e'], eq)
            self.assertEqual([p[5] for p in rec['p']], [5000.01, 6000])
            self.assertEqual(total, 4)

    def test_two_3000_and_large_account_small_position_excluded(self):
        for eq, ps in [(1, [position(3000), position(3000)]), (1000000, [position(4999), position(5000)])]:
            rec, _ = harvest.fetch_positions('synthetic', lambda _: api_state(eq, ps), {'BTC'})
            self.assertEqual(rec['p'], [])

    def test_response_integrity_not_low_equity(self):
        for bad in ({'assetPositions': []}, {'marginSummary': {}, 'assetPositions': []}, api_state('NaN')):
            with self.assertRaises((ValueError, KeyError)):
                harvest.fetch_positions('synthetic', lambda _: bad, {'BTC'})
        def post(payload):
            if 'dex' in payload:
                raise OSError('xyz unavailable')
            return api_state(1, [position(6000)])
        with self.assertRaises(OSError):
            harvest.fetch_positions('synthetic', post, {'BTC'})

    def test_all_aggregation_paths_conserve_both_sides_without_equity_gate(self):
        sample = {'generated_at_unix': 1, 'selection': SELECTION, 'accounts': [
            {'e': -20, 'p': [position(5000), position(5000.01), position(6000, 'xyz:TEST', 'S', 110, 20)]},
            {'e': 999999, 'p': [position(3000), position(3000)]},
            {'e': 1, 'p': [position(7000, px=94, lev=None), position(8000, px=0), position(9000, 'OTHER')]}
        ]}
        for build in (aggregate_v1, aggregate_v2, aggregate):
            output = build(sample, {'BTC': 100, 'xyz:TEST': 100}, COINS)
            self.assertEqual(output['selection'], SELECTION)
            totals = {side: sum(b['notional'] for m in output['markets'].values() for b in m['buckets'] if b['side'] == side) for side in ('L', 'S')}
            self.assertEqual(totals, {'L': 12000.01, 'S': 6000})
            self.assertEqual(sum(b['positions'] for m in output['markets'].values() for b in m['buckets']), 3)
            if output['schema_version'] == 3:
                self.assertEqual(output['markets']['BTC']['lev_unknown']['notional'], 7000)
                self.assertEqual(output['markets']['xyz:TEST']['buckets'][0]['lev'], [0, 6000, 0, 0])

    def test_old_new_python_js_contract_all_versions(self):
        sample = {'generated_at_unix': 1, 'accounts': [{'e': 1, 'p': [position(6000)]}]}
        for build in (aggregate_v1, aggregate_v2, aggregate):
            old = build(sample, {'BTC': 100, 'xyz:TEST': 100}, COINS)
            self.assertNotIn('selection', old)
            new = build(dict(sample, selection=SELECTION), {'BTC': 100, 'xyz:TEST': 100}, COINS)
            for data, expected in [(old, '旧快照'), (new, '单仓位')]:
                script = "const C=new Function('module',require('fs').readFileSync('./chart-core.js','utf8')+';return module.exports;')({exports:{}});const s=C.validate(JSON.parse(process.argv[1]));console.log(C.selectionLabel(s));"
                label = subprocess.check_output(['node', '-e', script, json.dumps(data)], cwd=ROOT, text=True)
                self.assertIn(expected, label)
                self.assertEqual(validate_public(data), data)
            for mutate in ({'threshold': 5000.01}, {'operator': 'gte'}, {'unit': 'account'}, {'account_equity_min': 0}, {'arbitrary': 'no'}):
                bad = copy.deepcopy(new)
                bad['selection'].update(mutate)
                with self.assertRaises(ValueError):
                    validate_public(bad)
                script = "const C=new Function('module',require('fs').readFileSync('./chart-core.js','utf8')+';return module.exports;')({exports:{}});try{C.validate(JSON.parse(process.argv[1]));process.exit(9)}catch(e){process.exit(0)}"
                self.assertEqual(subprocess.run(['node', '-e', script, json.dumps(bad)], cwd=ROOT).returncode, 0)

    def test_full_index_multibatch_restart_retry_exit_rediscovery(self):
        folder = fixture_dir()
        addresses = {f'synthetic-{i:04}': {'fs': '2020-01-01', 'ls': '2020-02-02'} for i in range(4505)}
        original = copy.deepcopy(addresses)
        def save(name, data):
            (folder / (name + '.json')).write_text(json.dumps(data))
        save('addresses', {'addresses': addresses})
        save('accounts', {'accounts': {'synthetic-0000': {'v': 1}, 'synthetic-0001': {'v': 900000}}})
        save('coins', COINS)
        seen = set()
        fail_once = {'synthetic-0000', 'synthetic-0010'}
        stage = [0]
        def query(a, allowed):
            seen.add(a)
            if a in fail_once:
                fail_once.remove(a)
                return None, 0
            # Previously excluded low-equity address enters; old high-equity candidate exits.
            ps = [position(6000)] if a == 'synthetic-0000' and stage[0] != 2 else []
            return {'a': a, 'e': 1, 'p': ps}, len(ps)
        with patch.object(harvest, 'DATA_DIR', str(folder)), patch.object(harvest, 'SNAP_LIMIT', 0):
            harvest.snapshot_mode(query)
            self.assertIn('synthetic-0000', harvest._read_state('accounts', {})['accounts'])
            self.assertNotIn('synthetic-0001', harvest._read_state('accounts', {})['accounts'])
            self.assertEqual(harvest._read_state('position_recheck', {})['cursor'], 2000)
            self.assertIn('synthetic-0010', harvest._read_state('position_recheck', {})['retry'])
            # Every call reloads JSON: equivalent to process restart between batches.
            for _ in range(2):
                harvest.snapshot_mode(query)
            self.assertEqual(seen, set(addresses))
            q = harvest._read_state('position_recheck', {})
            self.assertEqual(q['cursor'], 4505)
            self.assertEqual(q['cycles'], 1)
            self.assertEqual(q['retry'], [])
            stage[0] = 2
            harvest.snapshot_mode(query)
            self.assertNotIn('synthetic-0000', harvest._read_state('accounts', {})['accounts'])
            stage[0] = 3
            for _ in range(3):
                harvest.snapshot_mode(query)
            self.assertIn('synthetic-0000', harvest._read_state('accounts', {})['accounts'])
            self.assertEqual(harvest._read_state('addresses', {})['addresses'], original)
            # Torn latest cursor falls back to the previous successful checkpoint.
            valid_backup = harvest._read_state('position_recheck.backup', {})
            (folder / 'position_recheck.json').write_text('{')
            self.assertEqual(harvest._read_state('position_recheck', None), valid_backup)

    def test_plan_fairness_failed_retry_and_new_discovery(self):
        state = prepare(None, {str(i): {} for i in range(5000)}, {})
        batch, start, end = plan(state)
        finish(state, start, end, dict.fromkeys(batch, None))
        state = json.loads(json.dumps(state))
        state = prepare(state, {'new': {'fs': 'old', 'ls': 'old'}}, {})
        batch, start, end = plan(state)
        self.assertEqual(end - start, 1900)
        self.assertEqual(len(batch), 2000)
        finish(state, start, end, dict.fromkeys(batch, None))
        self.assertEqual(state['retry'][-2000:], batch)
        self.assertIn('new', state['order'])

    def test_diagnostic_limit_does_not_skip_unqueried_history(self):
        folder = fixture_dir()
        (folder / 'addresses.json').write_text(json.dumps({'addresses': {str(i): {} for i in range(10)}}))
        (folder / 'coins.json').write_text(json.dumps(COINS))
        with patch.object(harvest, 'DATA_DIR', str(folder)), patch.object(harvest, 'SNAP_LIMIT', 2):
            harvest.snapshot_mode(lambda a, _: ({'a': a, 'e': 0, 'p': []}, 0))
            self.assertEqual(harvest._read_state('position_recheck', {})['cursor'], 2)

    def test_time_budget_preserves_candidates_and_cursor(self):
        folder = fixture_dir()
        (folder / 'addresses.json').write_text(json.dumps({'addresses': {'old': {}}}))
        (folder / 'coins.json').write_text(json.dumps(COINS))
        (folder / 'accounts.json').write_text(json.dumps({'accounts': {'old': {'v': 1}}}))
        with patch.object(harvest, 'DATA_DIR', str(folder)), patch.object(harvest, 'SCAN_SECONDS', -1):
            snap = harvest.snapshot_mode(lambda *_: self.fail('must not query after budget'))
            self.assertEqual(snap['stats']['unqueried'], 1)
            self.assertEqual(harvest._read_state('position_recheck', {})['cursor'], 0)
            self.assertIn('old', harvest._read_state('accounts', {})['accounts'])


if __name__ == '__main__':
    unittest.main()
