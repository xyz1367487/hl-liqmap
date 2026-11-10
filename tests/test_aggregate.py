import copy
import json
import re
import subprocess
import unittest
from pathlib import Path

from aggregate import EDGES, aggregate, validate_public

ROOT = Path(__file__).resolve().parents[1]
COINS = {'updated': '2026-11-10', 'coins': [{'n': 'BTC', 'v': 6000000}]}


def account(identity, positions):
    return {'a': identity, 'e': 10000, 'p': [['BTC', side, 1, 100, px, n, 5, 'cross'] for side, px, n in positions]}


def original_js(rows, mark, side):
    html = (ROOT / 'index.html').read_text()
    bands = re.search(r'const BANDS=.*?;', html).group()
    function = html[html.index('function bucketize('):html.index('\nasync function refresh(')]
    program = bands + '\n' + function + '\nconsole.log(JSON.stringify(bucketize(...JSON.parse(process.argv[1]))));'
    return json.loads(subprocess.check_output(['node', '-e', program, json.dumps([rows, mark, side])], text=True))


class AggregateTests(unittest.TestCase):
    def test_all_bands_match_original_javascript(self):
        accounts, rows = [], {'L': [], 'S': []}
        # Use a mark of 1: exact boundaries exercise JS/Python IEEE-754 identically.
        for side in ('L', 'S'):
            for i, edge in enumerate(EDGES[:-1]):
                distances = [edge, (edge + EDGES[i + 1]) / 2 if i < 13 else .75]
                for d in distances:
                    px = 1 + d  # Original code buckets by absolute distance for either side.
                    for contributor in range(3):
                        accounts.append(account(f'private-{contributor}', [(side, px, (i + 1) * 100)]))
                        rows[side].append({'liqPx': px, 'n': (i + 1) * 100})
        output = aggregate({'accounts': accounts, 'generated_at_unix': 1}, {'BTC': 1}, COINS)
        for side in ('L', 'S'):
            expected = original_js(rows[side], 1, side)
            actual = output['markets']['BTC']['buckets']
            self.assertEqual(len([b for b in actual if b['side'] == side]), len(expected))
            for b in (b for b in actual if b['side'] == side):
                from aggregate import LABELS
                row = next(r for r in expected if r['tag'].startswith(LABELS[b['band']] + '·'))
                self.assertEqual(b['notional'], row['v'])
                self.assertEqual(b['positions'], int(row['tag'].split('·')[1][:-1]))
                self.assertEqual(b['px_high'] if side == 'L' else b['px_low'], row['px'])

    def test_all_nonempty_buckets_include_single_and_two_contributors(self):
        sample = {'generated_at_unix': 1, 'accounts': [
            account('one', [('L', 95, 111)] * 4 + [('S', 110, 7)]),
            account('two', [('L', 95, 222)])]}
        output = aggregate(sample, {'BTC': 100}, COINS)
        buckets = output['markets']['BTC']['buckets']
        self.assertEqual([(b['side'], b['notional'], b['positions']) for b in buckets],
                         [('L', 666, 5), ('S', 7, 1)])
        self.assertEqual(validate_public(output), output)
        sample['accounts'].append(account('three', [('L', 95, 333), ('S', 0, 999)]))
        self.assertEqual(aggregate(sample, {'BTC': 100}, COINS)['markets']['BTC']['buckets'][0]['notional'], 999)
        sample['accounts'][-1]['e'] = 9999
        self.assertEqual(aggregate(sample, {'BTC': 100}, COINS), output)
        self.assertNotIn('"one"', json.dumps(output))
        # Identity is not needed to produce public buckets.
        for row in sample['accounts']:
            row.pop('a')
        self.assertEqual(aggregate(sample, {'BTC': 100}, COINS), output)

    def test_public_schema_rejects_account_records_extra_fields_and_addresses(self):
        output = aggregate({'accounts': [], 'generated_at_unix': 1}, {'BTC': 100}, COINS)
        for field in ('accounts', 'addresses', 'positions', 'credential', 'account_ids', 'equity'):
            bad = copy.deepcopy(output)
            bad[field] = []
            with self.assertRaises(ValueError):
                validate_public(bad)
        populated = aggregate({'accounts': [account('one', [('L', 95, 1)])], 'generated_at_unix': 1}, {'BTC': 100}, COINS)
        for field in ('address', 'accounts', 'account_id', 'equity', 'position_records'):
            for level in ('market', 'bucket'):
                bad = copy.deepcopy(populated)
                target = bad['markets']['BTC'] if level == 'market' else bad['markets']['BTC']['buckets'][0]
                target[field] = []
                with self.assertRaises(ValueError):
                    validate_public(bad)
        for count in (0, -1, True, 1.5):
            bad = copy.deepcopy(populated)
            bad['markets']['BTC']['buckets'][0]['positions'] = count
            with self.assertRaises(ValueError):
                validate_public(bad)
        bad = copy.deepcopy(output)
        synthetic_address = '0x' + '1' * 40  # Synthetic, constructed in memory; never real data.
        bad['coin_list']['coins'][0]['n'] = synthetic_address
        bad['markets'] = {synthetic_address: output['markets']['BTC']}
        with self.assertRaises(ValueError):
            validate_public(bad)
        bad = copy.deepcopy(output)
        bad['markets']['BTC']['reference_mark'] = float('nan')
        with self.assertRaises(ValueError):
            validate_public(bad)

    def test_publication_disabled_before_network(self):
        from publish_aggregate import publish
        from unittest.mock import patch
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'not enabled'):
                publish(Path('unused'))

    def test_collector_requires_private_directory(self):
        import harvest
        from unittest.mock import patch
        with patch.object(harvest, 'DATA_DIR', None):
            with self.assertRaisesRegex(RuntimeError, 'PRIVATE_DATA_DIR'):
                harvest.require_private_data_dir()

    def test_publisher_sends_only_validated_aggregate_without_force(self):
        from publish_aggregate import publish, PUBLIC_REPO
        from unittest.mock import MagicMock, patch
        import io
        sample = aggregate({'accounts': [], 'generated_at_unix': 1}, {'BTC': 100}, COINS)
        responses = [
            {'private': False, 'full_name': PUBLIC_REPO},
            {'object': {'sha': 'parent'}},
            {'tree': [{'path': 'data/aggregate.json', 'type': 'blob'}]},
            {'sha': 'blob'}, {'sha': 'tree'}, {'sha': 'commit'}, {'ref': 'refs/heads/aggregate'},
        ]
        requests = []

        def open_request(request, **_):
            requests.append(request)
            return io.BytesIO(json.dumps(responses.pop(0)).encode())

        path = MagicMock()
        path.read_text.return_value = json.dumps(sample)
        with patch.dict('os.environ', {'ENABLE_PUBLIC_EXPORT': 'true', 'PUBLIC_AGGREGATE_TOKEN': 'unit-test-value'}), patch('urllib.request.urlopen', side_effect=open_request):
            publish(path)
        self.assertEqual(json.loads(requests[-1].data), {'sha': 'commit', 'force': False})
        self.assertTrue(all('/' + PUBLIC_REPO + '/' in r.full_url for r in requests))
        tree = json.loads(requests[4].data)
        self.assertEqual([entry['path'] for entry in tree['tree']], ['data/aggregate.json'])
        import base64
        blob = json.loads(requests[3].data)
        self.assertEqual(json.loads(base64.b64decode(blob['content'])), sample)

    def test_publisher_refuses_existing_branch_with_other_files(self):
        from publish_aggregate import publish, PUBLIC_REPO
        from unittest.mock import MagicMock, patch
        import io
        sample = aggregate({'accounts': [], 'generated_at_unix': 1}, {'BTC': 100}, COINS)
        responses = [{'private': False, 'full_name': PUBLIC_REPO}, {'object': {'sha': 'parent'}},
                     {'tree': [{'path': 'data/other.json', 'type': 'blob'}]}]
        path = MagicMock()
        path.read_text.return_value = json.dumps(sample)
        with patch.dict('os.environ', {'ENABLE_PUBLIC_EXPORT': 'true', 'PUBLIC_AGGREGATE_TOKEN': 'unit-test-value'}), patch('urllib.request.urlopen', side_effect=lambda *a, **k: io.BytesIO(json.dumps(responses.pop(0)).encode())) as network:
            with self.assertRaisesRegex(RuntimeError, 'unexpected files'):
                publish(path)
            self.assertEqual(network.call_count, 3)


if __name__ == '__main__':
    unittest.main()
