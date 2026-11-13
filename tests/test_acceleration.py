"""Synthetic acceleration regressions; retain evidence, never query the live API."""
import copy
import json
import threading
import unittest
from unittest.mock import patch

import harvest
from position_scan import BATCH_SIZE, RETRY_SIZE, prepare, plan
from test_position_selection import COINS, fixture_dir


class AccelerationAcceptance(unittest.TestCase):
    def run_snapshot(self, addresses, candidates=(), queue=None, query=None, seconds=1200):
        folder = fixture_dir()
        for name, data in [('addresses', {'addresses': dict.fromkeys(addresses, {})}),
                           ('accounts', {'accounts': {a: {'v': 1} for a in candidates}}),
                           ('coins', COINS)]:
            (folder / (name + '.json')).write_text(json.dumps(data))
        if queue is not None:
            (folder / 'position_recheck.json').write_text(json.dumps(queue))
        seen = []
        lock = threading.Lock()
        def wrapped(a, allowed):
            with lock:
                seen.append(a)
            return query(a, allowed) if query else ({'a': a, 'e': 1, 'p': []}, 0)
        with patch.object(harvest, 'DATA_DIR', str(folder)), patch.object(harvest, 'SNAP_LIMIT', 0), patch.object(harvest, 'SCAN_SECONDS', seconds):
            snap = harvest.snapshot_mode(wrapped)
        state = json.loads((folder / 'position_recheck.json').read_text())
        accounts = json.loads((folder / 'accounts.json').read_text())['accounts']
        return seen, state, accounts, snap

    def test_default_2000_reaches_real_snapshot_and_progress(self):
        addresses = [f'h-{i:05}' for i in range(4500)]
        seen, state, _, snap = self.run_snapshot(addresses)
        self.assertEqual((BATCH_SIZE, RETRY_SIZE), (2000, 100))
        self.assertEqual(len(seen), 2000)
        self.assertEqual(set(seen), set(addresses[:2000]))
        self.assertEqual(state['cursor'], 2000)
        self.assertEqual(snap['pool_scanned'], 2000)
        self.assertEqual(harvest.progress(state)['batch_size'], 2000)
        self.assertEqual((harvest.SNAP_CONCURRENCY, harvest.SNAP_PACE, harvest.SCAN_SECONDS), (6, 0.35, 1200))

    def test_retry_100_is_inside_total_2000_and_failure_is_retained(self):
        addresses = [f'h-{i:05}' for i in range(4500)]
        queue = prepare(None, dict.fromkeys(addresses), {})
        queue['retry'] = [f'r-{i:03}' for i in range(150)]
        original = copy.deepcopy(queue)
        batch, start, end = plan(queue)
        self.assertEqual((len(batch), start, end), (2000, 0, 1900))
        self.assertEqual(sum(a.startswith('r-') for a in batch), 100)
        seen, state, accounts, _ = self.run_snapshot(addresses, ['candidate'], queue, lambda *_: (None, 0))
        self.assertEqual(len(seen), 2001)  # Candidate is outside the historical quota.
        self.assertEqual(sum(a.startswith('r-') for a in seen), 100)
        self.assertEqual(state['cursor'], 1900)
        self.assertIn('candidate', accounts)
        self.assertEqual(set(state['retry']), set(original['retry']) | set(seen))

    def test_candidate_overlap_deduplicates_and_drains_before_history(self):
        addresses = [f'h-{i:05}' for i in range(2500)]
        candidates = addresses[100:163]  # Crosses the 60-address chunk boundary.
        completed = set()
        lock = threading.Lock()
        def query(a, _):
            with lock:
                if a not in candidates:
                    self.assertEqual(completed, set(candidates))
                else:
                    completed.add(a)
            return {'a': a, 'e': 1, 'p': []}, 0
        seen, state, _, _ = self.run_snapshot(addresses, candidates, query=query)
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(set(seen[:len(candidates)]), set(candidates))
        self.assertEqual(len(seen), 2000)
        self.assertEqual(state['cursor'], 2000)

    def test_budget_exhausted_during_candidates_never_starts_history(self):
        addresses = [f'h-{i:05}' for i in range(2500)]
        candidates = [f'z-{i:03}' for i in range(70)]
        clock = [0]
        def query(*_):
            clock[0] = 1201
            return None, 0
        with patch.object(harvest.time, 'monotonic', side_effect=lambda: clock[0]):
            seen, state, accounts, snap = self.run_snapshot(addresses, candidates, query=query)
        self.assertEqual(set(seen), set(candidates[:60]))
        self.assertEqual(state['candidate_cursor'], 60)
        self.assertEqual(state['cursor'], 0)
        self.assertEqual(set(accounts), set(candidates))
        self.assertEqual(set(state['retry']), set(seen))
        self.assertEqual(snap['stats']['failed'], 60)

    def test_history_cursor_advances_only_contiguous_executed_prefix(self):
        addresses = [f'h-{i:05}' for i in range(2500)]
        clock = [0]
        def query(*_):
            clock[0] = 1201
            return None, 0
        with patch.object(harvest.time, 'monotonic', side_effect=lambda: clock[0]):
            seen, state, _, _ = self.run_snapshot(addresses, [addresses[100]], query=query)
        self.assertEqual(seen, [addresses[100]])
        self.assertEqual(state['cursor'], 0)  # Overlap beyond an unexecuted gap cannot jump it.
        queue = prepare(None, dict.fromkeys(addresses), {})
        queue['cursor'] = 2000
        clock[0] = 0
        with patch.object(harvest.time, 'monotonic', side_effect=lambda: clock[0]):
            seen, state, _, _ = self.run_snapshot(addresses, queue=queue, query=query)
        self.assertEqual(set(seen), set(addresses[2000:2060]))
        self.assertEqual(state['cursor'], 2060)
        self.assertEqual(set(state['retry']), set(seen))
        self.assertEqual(state['cycles'], 0)


if __name__ == '__main__':
    unittest.main()
