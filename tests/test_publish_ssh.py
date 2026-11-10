"""Mock remote IO, but use real Git plumbing to inspect the resulting objects.

Only synthetic credentials/JSON are used. Temporary directories are retained under
aggregate-publish-* (no cleanup, in accordance with the no-deletion instruction).
"""
import contextlib
import io
import json
import os
import shlex
import stat
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from aggregate import aggregate
import publish_aggregate as publisher

SAMPLE = aggregate({'accounts': [], 'generated_at_unix': 1}, {'BTC': 100},
                   {'updated': '2026-11-10', 'coins': [{'n': 'BTC', 'v': 6000000}]})
FAKE_KEY = 'synthetic-test-key-never-a-credential'
REAL_RUN = subprocess.run


class RemoteHarness:
    def __init__(self, existing=False, extra=None, failure=None):
        self.existing, self.extra, self.failure = existing, extra, failure
        self.calls, self.parent, self.pushed = [], None, None
        self.base, self.kwargs = None, None

    def local(self, *args, input=None):
        options = dict(self.kwargs, input=input)
        result = REAL_RUN(self.base + list(args), **options)
        if result.returncode:
            raise AssertionError('Local test Git command failed')
        return result.stdout.strip()

    def run(self, args, **kwargs):
        self.calls.append((args, kwargs))
        self.base, self.kwargs = args[:6], kwargs
        command = args[6:]
        action = command[0]
        if self.failure == action:
            return subprocess.CompletedProcess(args, 1, FAKE_KEY.encode(), FAKE_KEY.encode())
        if action == 'ls-remote':
            if not self.existing:
                return subprocess.CompletedProcess(args, 2, b'', b'')
            blob = self.local('hash-object', '-w', '--stdin', input=b'old').decode()
            subtree = self.local('mktree', input=f'100644 blob {blob}\taggregate.json\n'.encode()).decode()
            rows = f'040000 tree {subtree}\tdata\n'
            if self.extra == 'file':
                rows += f'100644 blob {blob}\tprivate.json\n'
            if self.extra == 'submodule':
                rows += '160000 commit ' + 'a' * 40 + '\tmodule\n'
            if self.extra == 'empty-directory':
                empty = self.local('mktree', input=b'').decode()
                rows += f'040000 tree {empty}\tempty\n'
            tree = self.local('mktree', input=rows.encode()).decode()
            self.parent = self.local('commit-tree', tree, input=b'old\n').decode()
            with (Path(kwargs['cwd']) / 'objects.git' / 'FETCH_HEAD').open('x') as stream:
                stream.write(self.parent + '\n')
            return subprocess.CompletedProcess(args, 0, (self.parent + '\trefs/heads/aggregate\n').encode(), b'')
        if action == 'fetch':
            return subprocess.CompletedProcess(args, 0, b'', b'')
        if action == 'push':
            self.pushed = command[-1].split(':')[0]
            self.tree = self.local('ls-tree', '-r', '-z', self.pushed)
            self.commit = self.local('cat-file', '-p', self.pushed)
            self.payload = self.local('show', self.pushed + ':data/aggregate.json')
            return subprocess.CompletedProcess(args, 0, b'', b'')
        return REAL_RUN(args, **kwargs)


class SSHPublisherTests(unittest.TestCase):
    def execute(self, harness, host_keys=None):
        path = MagicMock()
        path.read_text.return_value = json.dumps(SAMPLE)
        responses = [{'private': False, 'full_name': publisher.PUBLIC_REPO},
                     {'ssh_keys': host_keys if host_keys is not None else ['ssh-ed25519 AAAA']}]
        urls = []

        def network(url, **kwargs):
            urls.append((url, kwargs))
            return io.BytesIO(json.dumps(responses.pop(0)).encode())

        with patch.dict(os.environ, {'ENABLE_PUBLIC_EXPORT': 'true',
                        'PUBLIC_AGGREGATE_SSH_KEY': FAKE_KEY,
                        'PUBLIC_AGGREGATE_TOKEN': 'synthetic-unused-token',
                        'GIT_TRACE': '1', 'GIT_OBJECT_DIRECTORY': '/untrusted'}, clear=True), \
                patch.object(publisher.urllib.request, 'urlopen', side_effect=network), \
                patch.object(publisher.subprocess, 'run', side_effect=harness.run):
            publisher.publish(path)
        self.assertEqual([url for url, _ in urls],
                         ['https://api.github.com/repos/' + publisher.PUBLIC_REPO,
                          'https://api.github.com/meta'])
        self.assertTrue(all('context' not in kwargs for _, kwargs in urls))

    def check_result(self, harness):
        self.assertEqual(json.loads(harness.payload), SAMPLE)
        self.assertRegex(harness.tree, rb'^100644 blob [0-9a-f]{40}\tdata/aggregate\.json\x00$')
        for args, kwargs in harness.calls:
            self.assertNotIn('add', args)
            self.assertNotIn('--force', args)
            self.assertNotIn(FAKE_KEY, repr(args))
            self.assertNotIn('GIT_TRACE', kwargs['env'])
            self.assertNotIn('GIT_OBJECT_DIRECTORY', kwargs['env'])
            self.assertNotIn('PUBLIC_AGGREGATE_TOKEN', kwargs['env'])
        pushes = [args[6:] for args, _ in harness.calls if args[6] == 'push']
        self.assertEqual(pushes, [['push', 'git@github.com:' + publisher.PUBLIC_REPO + '.git',
                                 harness.pushed + ':refs/heads/aggregate']])
        env = harness.kwargs['env']
        ssh = shlex.split(env['GIT_SSH_COMMAND'])
        self.assertIn('StrictHostKeyChecking=yes', ssh)
        self.assertIn('IdentitiesOnly=yes', ssh)
        self.assertIn('IdentityAgent=none', ssh)
        identity = Path(ssh[ssh.index('-i') + 1])
        self.assertEqual(stat.S_IMODE(identity.stat().st_mode), 0o600)
        self.assertEqual(identity.read_text(), FAKE_KEY + '\n')
        self.assertEqual((identity.parent / 'known_hosts').read_text(), 'github.com ssh-ed25519 AAAA\n')
        self.assertEqual(stat.S_IMODE(identity.parent.stat().st_mode), 0o700)

    def test_missing_branch_is_single_file_orphan_commit(self):
        harness = RemoteHarness()
        self.execute(harness)
        self.check_result(harness)
        self.assertNotIn(b'\nparent ', harness.commit)

    def test_existing_branch_retains_tip_as_only_parent(self):
        harness = RemoteHarness(existing=True)
        self.execute(harness)
        self.check_result(harness)
        parents = [row for row in harness.commit.splitlines() if row.startswith(b'parent ')]
        self.assertEqual(parents, [('parent ' + harness.parent).encode()])

    def test_other_files_submodules_and_empty_directories_refused(self):
        for extra in ('file', 'submodule', 'empty-directory'):
            with self.subTest(extra=extra):
                harness = RemoteHarness(existing=True, extra=extra)
                with self.assertRaisesRegex(RuntimeError, 'unexpected files'):
                    self.execute(harness)
                self.assertFalse(any(args[6] in ('push', 'hash-object', 'commit-tree')
                                     for args, _ in harness.calls))

    def test_push_rejection_is_safe_no_force_no_retry(self):
        harness = RemoteHarness(existing=True, failure='push')
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(RuntimeError) as caught:
                self.execute(harness)
        self.assertEqual(str(caught.exception), 'SSH aggregate command failed')
        self.assertNotIn(FAKE_KEY, out.getvalue() + err.getvalue() + str(caught.exception))
        self.assertEqual(sum(args[6] == 'push' for args, _ in harness.calls), 1)
        self.assertFalse(any('--force' in args or any(a.startswith('+') for a in args)
                             for args, _ in harness.calls))

    def test_subprocess_exception_is_redacted(self):
        harness = RemoteHarness()
        harness.run = MagicMock(side_effect=subprocess.TimeoutExpired(FAKE_KEY, 120,
                                   output=FAKE_KEY.encode(), stderr=FAKE_KEY.encode()))
        with self.assertRaises(RuntimeError) as caught:
            self.execute(harness)
        self.assertEqual(str(caught.exception), 'SSH aggregate command failed')
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)

    def test_branch_change_before_fetch_refuses_publication(self):
        harness = RemoteHarness(existing=True)
        original = harness.run

        def changed(args, **kwargs):
            result = original(args, **kwargs)
            if args[6] == 'rev-parse':
                return subprocess.CompletedProcess(args, 0, b'f' * 40 + b'\n', b'')
            return result

        harness.run = changed
        with self.assertRaisesRegex(RuntimeError, 'changed; retry next run'):
            self.execute(harness)
        self.assertFalse(any(args[6] == 'push' for args, _ in harness.calls))

    def test_invalid_host_keys_fail_before_key_or_git(self):
        harness = RemoteHarness()
        with self.assertRaisesRegex(RuntimeError, 'Invalid SSH host metadata'):
            self.execute(harness, ['ssh-ed25519 AAAA\nattacker invalid'])
        self.assertEqual(harness.calls, [])

    def test_schema_and_address_validation_precedes_ssh(self):
        for invalid in ({'accounts': []}, {'coin_list': []}):
            path = MagicMock()
            path.read_text.return_value = json.dumps(invalid)
            with patch.dict(os.environ, {'ENABLE_PUBLIC_EXPORT': 'true',
                            'PUBLIC_AGGREGATE_SSH_KEY': FAKE_KEY}, clear=True), \
                    patch.object(publisher, 'publish_ssh') as ssh:
                with self.assertRaises(ValueError):
                    publisher.publish(path)
                ssh.assert_not_called()
        address = '0x' + '1' * 40
        invalid = json.loads(json.dumps(SAMPLE))
        invalid['coin_list']['coins'][0]['n'] = address
        invalid['markets'] = {address: invalid['markets']['BTC']}
        path = MagicMock()
        path.read_text.return_value = json.dumps(invalid)
        with patch.dict(os.environ, {'ENABLE_PUBLIC_EXPORT': 'true',
                        'PUBLIC_AGGREGATE_SSH_KEY': FAKE_KEY}, clear=True), \
                patch.object(publisher, 'publish_ssh') as ssh:
            with self.assertRaises(ValueError):
                publisher.publish(path)
            ssh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
