"""Mock remote IO, but use real Git plumbing to inspect the resulting objects.

Only synthetic credentials/JSON are used. Temporary directories are retained under
aggregate-publish-* (no cleanup, in accordance with the no-deletion instruction).
"""
import contextlib
import io
import json
import os
import shlex
import socket
import stat
import ssl
import subprocess
import traceback
import urllib.error
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
                patch.object(publisher.urllib.request.OpenerDirector, 'open', side_effect=network), \
                patch.object(publisher.subprocess, 'run', side_effect=harness.run):
            publisher.publish(path)
        self.assertEqual([request.full_url for request, _ in urls],
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


class PublicMetadataTests(unittest.TestCase):
    sensitive = 'synthetic-sensitive-marker'

    def http_error(self, code, headers=None):
        return urllib.error.HTTPError('https://invalid.example/' + self.sensitive,
                                      code, self.sensitive, headers or {},
                                      io.BytesIO(self.sensitive.encode()))

    def lookup(self, effects, endpoint='meta', expected=None, attempts=1):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(publisher.urllib.request.OpenerDirector, 'open', side_effect=effects) as network, \
                patch.object(publisher.time, 'sleep') as sleep, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if expected is None:
                result = publisher.public_metadata(endpoint)
            else:
                with self.assertRaises(RuntimeError) as caught:
                    publisher.public_metadata(endpoint)
                self.assertEqual(str(caught.exception),
                                 'Public metadata lookup failed (' + expected + f'; attempts={attempts}/3)')
                self.assertIsNone(caught.exception.__cause__)
                self.assertTrue(caught.exception.__suppress_context__)
                rendered = ''.join(traceback.format_exception(
                    type(caught.exception), caught.exception, caught.exception.__traceback__))
                self.assertNotIn(self.sensitive, rendered)
                result = None
        self.assertNotIn(self.sensitive, out.getvalue() + err.getvalue())
        self.assertEqual(network.call_count, attempts)
        self.assertEqual(sleep.call_args_list,
                         [unittest.mock.call(i + 1) for i in range(attempts - 1)])
        for args, kwargs in network.call_args_list:
            self.assertEqual(len(args), 1)
            self.assertIsInstance(args[0], publisher.urllib.request.Request)
            self.assertEqual(args[0].full_url, 'https://api.github.com/' + endpoint)
            self.assertEqual(args[0].get_method(), 'GET')
            self.assertEqual(kwargs, {'timeout': 30})
        return result

    def test_transient_failure_then_complete_object_success(self):
        obj = {'ssh_keys': ['ssh-ed25519 AAAA'], 'extra': {'retained': True}}
        self.assertEqual(self.lookup([self.http_error(503),
                                     io.BytesIO(json.dumps(obj).encode())], attempts=2), obj)
        repo = {'private': False, 'full_name': publisher.PUBLIC_REPO, 'extra': 7}
        self.assertEqual(self.lookup([io.BytesIO(json.dumps(repo).encode())],
                                    endpoint='repos/' + publisher.PUBLIC_REPO), repo)

    def test_three_attempts_exhausted_for_429_and_all_5xx(self):
        for code in (429, 500, 502, 503, 504, 599):
            with self.subTest(code=code):
                category = 'http-429-rate-limit' if code == 429 else 'http-' + str(code)
                self.lookup([self.http_error(code) for _ in range(3)],
                            expected='meta: ' + category, attempts=3)

    def test_permission_403_and_404_do_not_retry(self):
        for code in (400, 401, 403, 404):
            with self.subTest(code=code):
                self.lookup([self.http_error(code, {'X-RateLimit-Remaining': '5'})],
                            expected='repos: http-' + str(code),
                            endpoint='repos/' + publisher.PUBLIC_REPO)

    def test_evidenced_403_rate_limit_has_bounded_backoff(self):
        for headers in ({'X-RateLimit-Remaining': '0'}, {'Retry-After': '36000'}):
            with self.subTest(headers=headers):
                self.lookup([self.http_error(403, headers) for _ in range(3)],
                            expected='meta: http-403-rate-limit', attempts=3)

    def test_timeout_urlerror_and_connection_failures(self):
        for make_error, category in (
                (lambda: TimeoutError(self.sensitive), 'timeout'),
                (lambda: socket.timeout(self.sensitive), 'timeout'),
                (lambda: urllib.error.URLError(socket.timeout(self.sensitive)), 'timeout'),
                (lambda: urllib.error.URLError(TimeoutError(self.sensitive)), 'timeout'),
                (lambda: urllib.error.URLError(self.sensitive), 'network'),
                (lambda: ConnectionResetError(self.sensitive), 'connection'),
                (lambda: OSError(self.sensitive), 'network')):
            with self.subTest(category=category):
                self.lookup([make_error() for _ in range(3)],
                            expected='meta: ' + category, attempts=3)
                self.assertEqual(self.lookup([make_error(), io.BytesIO(b'{"ok": true}')],
                                             attempts=2), {'ok': True})

    def test_invalid_json_encoding_and_non_object_do_not_retry(self):
        for payload in (b'{', b'[]', b'null', b'"text"', b'1', b'\xff'):
            with self.subTest(payload=payload):
                self.lookup([io.BytesIO(payload)], expected='meta: invalid-json-or-schema')

    def test_tls_and_unexpected_errors_are_safe_and_permanent(self):
        for error, category in (
                (ssl.SSLCertVerificationError(self.sensitive), 'tls'),
                (urllib.error.URLError(ssl.SSLCertVerificationError(self.sensitive)), 'tls'),
                (RuntimeError(self.sensitive), 'unexpected')):
            with self.subTest(category=category):
                self.lookup([error], expected='meta: ' + category)

    def test_unknown_endpoint_refused_before_network(self):
        with patch.object(publisher.urllib.request.OpenerDirector, 'open') as network:
            with self.assertRaisesRegex(RuntimeError, r'failed \(endpoint\)'):
                publisher.public_metadata('repos/private-example')
            network.assert_not_called()

    def test_wrong_repository_and_host_schema_are_not_retried(self):
        for responses, message, attempts in (
                ([{'private': True, 'full_name': publisher.PUBLIC_REPO}],
                 'Unexpected public repository', 1),
                ([{'private': False, 'full_name': 'wrong'}],
                 'Unexpected public repository', 1),
                ([{'private': False, 'full_name': publisher.PUBLIC_REPO}, {'ssh_keys': []}],
                 'Invalid SSH host metadata', 2)):
            with self.subTest(message=message), \
                    patch.object(publisher.urllib.request.OpenerDirector, 'open', side_effect=[
                        io.BytesIO(json.dumps(obj).encode()) for obj in responses]) as network, \
                    patch.object(publisher.time, 'sleep') as sleep, \
                    patch.object(publisher.subprocess, 'run') as git:
                with self.assertRaisesRegex(RuntimeError, message):
                    publisher.publish_ssh(SAMPLE, FAKE_KEY)
                self.assertEqual(network.call_count, attempts)
                sleep.assert_not_called()
                git.assert_not_called()


class MetadataAuthenticationTests(unittest.TestCase):
    sensitive = PublicMetadataTests.sensitive
    http_error = PublicMetadataTests.http_error
    lookup = PublicMetadataTests.lookup

    def test_request_headers_and_anonymous_mode(self):
        for token in (None, '', self.sensitive):
            env = {'PUBLIC_AGGREGATE_SSH_KEY': 'synthetic-ssh-not-http',
                   'PUBLIC_AGGREGATE_TOKEN': 'synthetic-pat-not-http'}
            if token is not None:
                env['GITHUB_TOKEN'] = token
            for endpoint in ('meta', 'repos/' + publisher.PUBLIC_REPO):
                with self.subTest(token_present=bool(token), endpoint=endpoint), \
                        patch.dict(os.environ, env, clear=True), \
                        patch.object(publisher.urllib.request.OpenerDirector, 'open',
                                     return_value=io.BytesIO(b'{}')) as network:
                    publisher.public_metadata(endpoint)
                    request = network.call_args.args[0]
                    self.assertEqual(request.full_url, 'https://api.github.com/' + endpoint)
                    self.assertEqual(request.get_method(), 'GET')
                    self.assertIsNone(request.data)
                    headers = dict((k.lower(), v) for k, v in request.header_items())
                    expected = {'accept': 'application/vnd.github+json',
                                'user-agent': 'liqmap-aggregate-publisher',
                                'x-github-api-version': '2022-11-28'}
                    if token:
                        expected['authorization'] = 'Bearer ' + token
                    self.assertEqual(headers, expected)
                    self.assertEqual(network.call_args.kwargs, {'timeout': 30})

    def test_untrusted_endpoints_are_refused_before_opener(self):
        for endpoint in ('https://attacker.example/meta', '//attacker.example/meta',
                         'meta?redirect=1', 'meta/../meta', 'repos/' + publisher.PUBLIC_REPO + '/extra'):
            with self.subTest(endpoint=endpoint), \
                    patch.dict(os.environ, {'GITHUB_TOKEN': self.sensitive}, clear=True), \
                    patch.object(publisher.urllib.request, 'build_opener') as build:
                with self.assertRaisesRegex(RuntimeError, r'failed \(endpoint\)'):
                    publisher.public_metadata(endpoint)
                build.assert_not_called()

    def test_opener_keeps_default_https_verification(self):
        build = publisher.urllib.request.build_opener
        openers = []
        def capture(*handlers):
            result = build(*handlers)
            openers.append(result)
            return result
        with patch.object(publisher.urllib.request, 'build_opener', side_effect=capture), \
                patch.object(publisher.urllib.request.OpenerDirector, 'open',
                             return_value=io.BytesIO(b'{}')):
            publisher.public_metadata('meta')
        https = [h for h in openers[0].handlers
                 if isinstance(h, publisher.urllib.request.HTTPSHandler)]
        self.assertEqual(len(https), 1)
        self.assertIsNone(https[0]._context)
        defaults = ssl.create_default_context()
        self.assertEqual(defaults.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(defaults.check_hostname)

    def test_authenticated_permission_failure_never_falls_back(self):
        with patch.dict(os.environ, {'GITHUB_TOKEN': self.sensitive}, clear=True):
            for code in (401, 403):
                self.lookup([self.http_error(code, {'X-RateLimit-Remaining': '5'})],
                            expected='meta: http-' + str(code))

    def test_authenticated_retries_keep_authorization(self):
        with patch.dict(os.environ, {'GITHUB_TOKEN': self.sensitive}, clear=True), \
                patch.object(publisher.urllib.request.OpenerDirector, 'open', side_effect=[
                    self.http_error(403, {'X-RateLimit-Remaining': '0'}),
                    io.BytesIO(b'{}')]) as network, \
                patch.object(publisher.time, 'sleep') as sleep:
            self.assertEqual(publisher.public_metadata('meta'), {})
            self.assertEqual(network.call_count, 2)
            for call in network.call_args_list:
                self.assertEqual(call.args[0].get_header('Authorization'),
                                 'Bearer ' + self.sensitive)
            sleep.assert_called_once_with(1)

    def test_real_opener_rejects_redirects_before_second_request(self):
        # Exercise urllib's actual redirect/error processing with synthetic transport.
        from email.message import Message
        from urllib.response import addinfourl
        for code in (301, 302, 303, 307, 308):
            for target in ('https://attacker.example/' + self.sensitive,
                           'https://api.github.com/meta?redirected=1'):
                calls = []

                class Transport(publisher.urllib.request.HTTPSHandler):
                    def https_open(self, request):
                        calls.append(request)
                        headers = Message()
                        headers['Location'] = target
                        response = addinfourl(io.BytesIO(b''), headers, request.full_url, code)
                        response.msg = 'synthetic redirect'
                        return response

                build = publisher.urllib.request.build_opener
                def opener(*handlers):
                    return build(Transport(), *handlers)

                with self.subTest(code=code, target=target), \
                        patch.dict(os.environ, {'GITHUB_TOKEN': self.sensitive}, clear=True), \
                        patch.object(publisher.urllib.request, 'build_opener', side_effect=opener), \
                        patch.object(publisher.time, 'sleep') as sleep:
                    with self.assertRaises(RuntimeError) as caught:
                        publisher.public_metadata('meta')
                    self.assertEqual(str(caught.exception),
                                     f'Public metadata lookup failed (meta: http-{code}; attempts=1/3)')
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0].full_url, 'https://api.github.com/meta')
                    self.assertNotIn(self.sensitive, str(caught.exception))
                    sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
