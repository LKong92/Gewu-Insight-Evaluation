#!/usr/bin/env python3
"""Public-source HTTP recording/replay at requests' adapter boundary.

Leaves product query construction, pagination, parsing, filtering and storage intact.
Stores each native attempt, including HTTP errors and transport exceptions. These
archives are inputs and availability observations, never semantic reference labels.
No original App credentials, cookies, SQLite or managed paper files are accessed.
"""
from collections import defaultdict, deque
from contextlib import AbstractContextManager
import datetime as dt
import hashlib
import io
import ipaddress
import json
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from unittest.mock import patch

import requests

SCHEMA = 'gewu-public-source-transport-v4.1'
SENSITIVE_QUERY = {'api_key', 'apikey', 'api-key', 'key', 'token', 'access_token', 'authorization', 'password'}
SENSITIVE_HEADERS = {'authorization', 'proxy-authorization', 'cookie', 'x-api-key', 'api-key'}
RESPONSE_HEADERS = {'content-type', 'content-encoding', 'content-length', 'etag', 'last-modified',
                    'retry-after', 'location', 'date', 'link', 'x-ratelimit-limit', 'x-ratelimit-remaining',
                    'x-ratelimit-reset', 'ratelimit-limit', 'ratelimit-remaining', 'ratelimit-reset'}
_ACTIVE = threading.Lock()
_SOURCE_IO = threading.local()


def public_source_io_active():
    return bool(getattr(_SOURCE_IO, 'active', False))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def request_record(request, allow_loopback=False):
    parsed = urlsplit(request.url)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Public HTTP(S) sources only; embedded credentials prohibited')
    if any(k.lower() in SENSITIVE_QUERY for k, _ in parse_qsl(parsed.query)):
        raise ValueError('Credential-bearing source URL prohibited by anonymous collection configuration')
    if any(k.lower() in SENSITIVE_HEADERS and v for k, v in request.headers.items()):
        raise ValueError('Credentials/cookies must not be copied into a benchmark acquisition')
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    local_name = parsed.hostname.lower() in ('localhost', 'localhost.localdomain') or parsed.hostname.lower().endswith('.local')
    if (address and not address.is_global) or local_name:
        if not (allow_loopback and ((address and address.is_loopback) or parsed.hostname == 'localhost')):
            raise ValueError('Nonpublic source destination prohibited')
    if not allow_loopback and parsed.port not in (None, 80, 443):
        raise ValueError('Unexpected public source port')
    body = request.body or b''
    if isinstance(body, str):
        body = body.encode()
    if not isinstance(body, bytes):
        raise ValueError('Streaming request bodies cannot be archived reproducibly')
    if request.method not in ('GET', 'HEAD', 'POST'):
        raise ValueError('Unsupported source-query method')
    # Public requests only. Preserve response-affecting validators, Accept and UA.
    headers = {k.lower(): str(v) for k, v in request.headers.items() if k.lower() not in ('connection',)}
    value = {'method': request.method, 'url': request.url, 'headers': headers,
             'body_sha256': sha(body), 'body_bytes': len(body)}
    return value, sha(canonical(value)), body


class SourceTransport(AbstractContextManager):
    def __init__(self, root, mode, *, allow_loopback=False, deadline_epoch=None):
        if mode not in ('record', 'replay'):
            raise ValueError('Mode must be record or replay')
        self.root, self.mode = Path(root).resolve(), mode
        self.allow_loopback = allow_loopback
        self.deadline_epoch = deadline_epoch
        self.lock = threading.Lock()
        self.counter = 0
        self.used = []
        self.queues = defaultdict(deque)
        self.patch = None
        self.started_at = utc()
        if mode == 'record':
            self.root.mkdir(parents=True, exist_ok=False)
            (self.root / 'blobs').mkdir()
            self.events = (self.root / 'attempts.jsonl').open('x', encoding='utf-8')
        else:
            self.manifest = json.loads((self.root / 'manifest.json').read_text())
            if self.manifest['schema'] != SCHEMA or not self.manifest['archive_closed']:
                raise ValueError('Recording archive has not been finalized')
            raw = (self.root / 'attempts.jsonl').read_bytes()
            if sha(raw) != self.manifest['attempts_sha256']:
                raise ValueError('Source attempt log changed')
            rows = [json.loads(line) for line in raw.splitlines()]
            ids = [row['attempt_id'] for row in rows]
            if len(rows) != self.manifest['attempts'] or sorted(ids) != list(range(1, len(rows) + 1)):
                raise ValueError('Incomplete or duplicate source attempts')
            for row in sorted(rows, key=lambda x: x['attempt_id']):
                if ('response' in row) == ('exception' in row):
                    raise ValueError('Recorded attempt lacks one unambiguous terminal outcome')
                if sha(canonical(row['request'])) != row['request_key']:
                    raise ValueError('Request key changed')
                self._blob(row['request']['body_sha256'], row['request']['body_bytes'])
                if 'response' in row:
                    self._blob(row['response']['body_sha256'], row['response']['body_bytes'])
                self.queues[row['request_key']].append(row)

    def _blob(self, digest, size):
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Invalid source blob digest')
        path = self.root / 'blobs' / digest
        if path.is_symlink():
            raise ValueError('Source blob must not be a symlink')
        data = path.read_bytes()
        if len(data) != size or sha(data) != digest:
            raise ValueError('Source response bytes changed')
        return data

    def _store(self, body):
        digest = sha(body)
        path = self.root / 'blobs' / digest
        try:
            with path.open('xb') as f:
                f.write(body)
        except FileExistsError:
            if path.read_bytes() != body:
                raise ValueError('Source archive hash collision or corrupted blob')
        return digest

    def __enter__(self):
        if not _ACTIVE.acquire(blocking=False):
            raise RuntimeError('Only one transport adapter may be active in a process')
        original = requests.adapters.HTTPAdapter.send
        owner = self

        def adapter_send(adapter, request, **kwargs):
            req, key, body = request_record(request, owner.allow_loopback)
            with owner.lock:
                if owner.mode == 'replay':
                    if not owner.queues[key]:
                        raise RuntimeError('Offline replay has no recorded response for this native request: ' + key)
                    row = owner.queues[key].popleft()
                    owner.used.append(row['attempt_id'])
                else:
                    owner.counter += 1
                    row = {'attempt_id': owner.counter, 'request_key': key, 'request': req, 'started_at': utc()}
                    owner._store(body)
            if owner.mode == 'replay':
                if 'exception' in row:
                    cls = getattr(requests.exceptions, row['exception']['type'], requests.exceptions.RequestException)
                    if not isinstance(cls, type) or not issubclass(cls, requests.exceptions.RequestException):
                        cls = requests.exceptions.RequestException
                    raise cls(row['exception']['message'], request=request)
                result = row['response']
                response = requests.Response()
                response.status_code, response.reason, response.url = result['status'], result['reason'], result['url']
                response.headers.update(result['headers'])
                response.encoding = result['encoding']
                response._content = owner._blob(result['body_sha256'], result['body_bytes'])
                response._content_consumed = True
                response.raw = io.BytesIO(response._content)
                response.request = request
                response.connection = adapter
                response.elapsed = dt.timedelta(seconds=row['elapsed_seconds'])
                return response
            start = time.monotonic()
            try:
                if owner.deadline_epoch is not None and time.time() >= owner.deadline_epoch:
                    raise requests.exceptions.Timeout('Prespecified acquisition deadline reached; no live request sent', request=request)
                _SOURCE_IO.active = True
                response = original(adapter, request, **kwargs)
                content = response.content  # Decoded transfer body, exactly what the native parser consumes.
                with owner.lock:
                    body_sha = owner._store(content)
                row['response'] = {'status': response.status_code, 'reason': response.reason, 'url': response.url,
                    'headers': {k: v for k, v in response.headers.items() if k.lower() in RESPONSE_HEADERS},
                    'encoding': response.encoding, 'body_sha256': body_sha, 'body_bytes': len(content),
                    'body_representation': 'requests_decoded_content'}
                return response
            except requests.exceptions.RequestException as exc:
                row['exception'] = {'type': type(exc).__name__, 'message': str(exc)}
                raise
            except BaseException as exc:
                # A broken recorder or interruption is never a replayable source
                # error, even when the caller catches it and keeps collecting.
                row['recording_failure'] = {'type': type(exc).__name__, 'message': str(exc)}
                raise
            finally:
                _SOURCE_IO.active = False
                row.update(finished_at=utc(), elapsed_seconds=time.monotonic() - start)
                with owner.lock:
                    owner.events.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
                    owner.events.flush()

        self.patch = patch.object(requests.adapters.HTTPAdapter, 'send', adapter_send)
        self.patch.start()
        return self

    def assert_consumed(self):
        remaining = {key: len(rows) for key, rows in self.queues.items() if rows}
        if remaining:
            raise ValueError('Offline replay left %d recorded requests unused' % sum(remaining.values()))
        return {'used_attempt_ids': list(self.used), 'remaining': 0, 'live_adapter_called': False}

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.patch:
                self.patch.stop()
            if self.mode == 'record':
                self.events.close()
                raw = (self.root / 'attempts.jsonl').read_bytes()
                rows = [json.loads(line) for line in raw.splitlines()]
                complete = all(('response' in r) != ('exception' in r) for r in rows)
                report = {'schema': SCHEMA, 'archive_closed': complete, 'started_at': self.started_at,
                    'finished_at': utc(), 'attempts': len(rows), 'attempts_sha256': sha(raw),
                    'collector_raised': exc_type.__name__ if exc_type else None,
                    'http_responses': sum('response' in r for r in rows),
                    'transport_exceptions': sum('exception' in r for r in rows),
                    'loopback_fixture_mode': self.allow_loopback,
                    'deadline_epoch': self.deadline_epoch,
                    'scientific_reference_labels': False,
                    'limits': ['Archive records native attempts; source completion requires separate pagination/monitor outcomes.',
                               'A recorded HTTP success does not establish historical coverage or correct literature membership.',
                               'Cookie-bearing requests are prohibited; an access challenge is recorded, never bypassed.']}
                with (self.root / 'manifest.json').open('x', encoding='utf-8') as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
                    f.write('\n')
        finally:
            _ACTIVE.release()
        return False
