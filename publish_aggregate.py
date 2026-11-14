#!/usr/bin/env python3
"""Private-side publication of one validated aggregate file. No private checkout in public CI."""
import argparse
import base64
import json
import os
import re
import shlex
import socket
import ssl
import subprocess
import time
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from aggregate import validate_public

PUBLIC_REPO = 'xyz1367487/hl-liqmap'
BRANCH = 'aggregate'


def publish(path):
    # Double gate: preparation and private data commits never imply public publication.
    if os.environ.get('ENABLE_PUBLIC_EXPORT') != 'true':
        raise RuntimeError('Public export is not enabled')
    data = validate_public(json.loads(path.read_text()))
    key = os.environ.get('PUBLIC_AGGREGATE_SSH_KEY')
    if key:
        publish_ssh(data, key)
        print('Validated aggregate published to dedicated aggregate branch')
        return
    token = os.environ['PUBLIC_AGGREGATE_TOKEN']

    def api(method, endpoint, payload=None, missing_ok=False):
        request = urllib.request.Request('https://api.github.com/repos/' + PUBLIC_REPO + '/' + endpoint,
            data=json.dumps(payload).encode() if payload is not None else None, method=method,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise RuntimeError(f'GitHub aggregate publication failed (HTTP {error.code})') from None

    repo = api('GET', '')
    if repo['private'] or repo['full_name'] != PUBLIC_REPO:
        raise RuntimeError('Unexpected public repository')
    ref = api('GET', 'git/ref/heads/' + BRANCH, missing_ok=True)
    parent = ref['object']['sha'] if ref else None
    if parent:
        current = api('GET', 'git/trees/' + parent + '?recursive=1')
        paths = {entry['path'] for entry in current['tree'] if entry['type'] == 'blob'}
        if paths != {'data/aggregate.json'} or current.get('truncated'):
            raise RuntimeError('Aggregate branch contains unexpected files; refusing to replace them')
    encoded = base64.b64encode(json.dumps(data, separators=(',', ':'), allow_nan=False).encode()).decode()
    blob = api('POST', 'git/blobs', {'content': encoded, 'encoding': 'base64'})
    tree = api('POST', 'git/trees', {'tree': [{'path': 'data/aggregate.json', 'mode': '100644', 'type': 'blob', 'sha': blob['sha']}]})
    commit = api('POST', 'git/commits', {'message': 'Publish aggregate generation', 'tree': tree['sha'], 'parents': [parent] if parent else []})
    if parent:
        api('PATCH', 'git/refs/heads/' + BRANCH, {'sha': commit['sha'], 'force': False})
    else:
        api('POST', 'git/refs', {'ref': 'refs/heads/' + BRANCH, 'sha': commit['sha']})
    print('Validated aggregate published to dedicated aggregate branch')


class _NoMetadataRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Reject even same-host redirects; authorization stays on the fixed endpoint.
        return None


def public_metadata(endpoint):
    labels = {'repos/' + PUBLIC_REPO: 'repos', 'meta': 'meta'}
    if endpoint not in labels:
        raise RuntimeError('Public metadata lookup failed (endpoint)') from None
    label = labels[endpoint]
    headers = {'Accept': 'application/vnd.github+json',
               'User-Agent': 'liqmap-aggregate-publisher',
               'X-GitHub-Api-Version': '2022-11-28'}
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request('https://api.github.com/' + endpoint,
                                     headers=headers, method='GET')
    opener = urllib.request.build_opener(_NoMetadataRedirect())
    # Only these public GETs retry; TLS verification and caller validation remain.
    for attempt in range(3):
        retry = False
        try:
            with opener.open(request, timeout=30) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise ValueError('Expected JSON object')
            return result
        except urllib.error.HTTPError as error:
            code = error.code
            # Read only evidence of rate limiting, never log headers/body/reason.
            headers = error.headers or {}
            rate_limited = code == 429 or (code == 403 and (
                headers.get('X-RateLimit-Remaining') == '0' or
                headers.get('Retry-After') is not None))
            category = 'http-' + str(code) + ('-rate-limit' if rate_limited else '')
            retry = rate_limited or 500 <= code <= 599
            error.close()
        except ssl.SSLError:
            category = 'tls'
        except (ValueError, UnicodeError):
            category = 'invalid-json-or-schema'
        except (TimeoutError, socket.timeout):
            category, retry = 'timeout', True
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLError):
                category = 'tls'
            else:
                category = 'timeout' if isinstance(error.reason, (TimeoutError, socket.timeout)) else 'network'
                retry = True
        except ConnectionError:
            category, retry = 'connection', True
        except OSError:
            category, retry = 'network', True
        except Exception:
            category = 'unexpected'
        if not retry or attempt == 2:
            raise RuntimeError(f'Public metadata lookup failed ({label}: {category}; attempts={attempt + 1}/3)') from None
        # Do not honor unbounded server Retry-After delays.
        time.sleep(attempt + 1)


def publish_ssh(data, key):
    repo = public_metadata('repos/' + PUBLIC_REPO)
    if repo.get('private') is not False or repo.get('full_name') != PUBLIC_REPO:
        raise RuntimeError('Unexpected public repository')
    meta = public_metadata('meta')
    host_keys = meta.get('ssh_keys')
    if not isinstance(host_keys, list) or not host_keys or any(
            not isinstance(k, str) or not re.fullmatch(
                r'(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) [A-Za-z0-9+/]+={0,3}', k)
            for k in host_keys):
        raise RuntimeError('Invalid SSH host metadata')

    # Intentionally retained: runner lifetime owns cleanup, never touch the checkout.
    scratch = Path(tempfile.mkdtemp(prefix='aggregate-publish-'))
    identity = scratch / 'identity'
    fd = os.open(identity, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(key.rstrip('\n') + '\n')
    hosts = scratch / 'known_hosts'
    with hosts.open('x') as stream:
        stream.write(''.join('github.com ' + k + '\n' for k in host_keys))
    # A small allowlist excludes inherited Git config, tracing, credentials and object DBs.
    env = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'TMPDIR') if k in os.environ}
    env.update({
        'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
        'GIT_TERMINAL_PROMPT': '0', 'GIT_SSH_VARIANT': 'ssh',
        'GIT_AUTHOR_NAME': 'github-actions[bot]',
        'GIT_AUTHOR_EMAIL': 'github-actions[bot]@users.noreply.github.com',
        'GIT_COMMITTER_NAME': 'github-actions[bot]',
        'GIT_COMMITTER_EMAIL': 'github-actions[bot]@users.noreply.github.com',
        'GIT_SSH_COMMAND': shlex.join([
            'ssh', '-F', os.devnull, '-i', str(identity),
            '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
            '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile=' + str(hosts),
            '-o', 'GlobalKnownHostsFile=' + os.devnull,
            '-o', 'UpdateHostKeys=no', '-o', 'ConnectTimeout=30']),
    })

    def git(*args, input=None, missing_ok=False):
        try:
            result = subprocess.run(
                ['git', '--git-dir=' + str(scratch / 'objects.git'),
                 '-c', 'core.hooksPath=' + os.devnull, '-c', 'gc.auto=0', *args],
                cwd=scratch, env=env, input=input, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=120, check=False)
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError('SSH aggregate command failed') from None
        if result.returncode and not (missing_ok and result.returncode == 2):
            # Never interpolate command, output, exception or key into diagnostics.
            raise RuntimeError('SSH aggregate command failed') from None
        return result

    def oid(output):
        value = output.strip()
        if not re.fullmatch(rb'[0-9a-f]{40}', value):
            raise RuntimeError('Invalid Git object response')
        return value.decode('ascii')

    remote = 'git@github.com:' + PUBLIC_REPO + '.git'
    ref = 'refs/heads/' + BRANCH
    git('init', '--bare', '--template=')
    advertised = git('ls-remote', '--exit-code', '--refs', remote, ref, missing_ok=True)
    parent = None
    if advertised.returncode == 0:
        fields = advertised.stdout.strip().split(b'\t')
        if len(fields) != 2 or fields[1] != ref.encode():
            raise RuntimeError('Invalid Git branch response')
        parent = oid(fields[0])
        git('fetch', '--no-tags', remote, ref)
        if oid(git('rev-parse', '--verify', 'FETCH_HEAD^{commit}').stdout) != parent:
            raise RuntimeError('Aggregate branch changed; retry next run')
        entries = git('ls-tree', '-r', '-t', '-z', parent).stdout.split(b'\0')
        if len(entries) != 3 or entries[-1] != b'':
            raise RuntimeError('Aggregate branch contains unexpected files; refusing to replace them')
        patterns = [rb'040000 tree [0-9a-f]{40}\tdata',
                    rb'100644 blob [0-9a-f]{40}\tdata/aggregate\.json']
        if any(not re.fullmatch(pattern, entry) for pattern, entry in zip(patterns, entries)):
            raise RuntimeError('Aggregate branch contains unexpected files; refusing to replace them')
    payload = json.dumps(data, separators=(',', ':'), allow_nan=False).encode()
    blob = oid(git('hash-object', '-w', '--stdin', input=payload).stdout)
    subtree = oid(git('mktree', input=f'100644 blob {blob}\taggregate.json\n'.encode()).stdout)
    tree = oid(git('mktree', input=f'040000 tree {subtree}\tdata\n'.encode()).stdout)
    parents = ['-p', parent] if parent else []
    commit = oid(git('commit-tree', tree, *parents,
                     input=b'Publish aggregate generation\n').stdout)
    # No + refspec, force flag or retry: concurrent branch changes fail normally.
    git('push', remote, commit + ':' + ref)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('aggregate', type=Path)
    publish(parser.parse_args().aggregate)
