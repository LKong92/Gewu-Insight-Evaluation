"""Record native datetime observations unchanged; replay the same external clock input."""
from collections import defaultdict, deque
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import threading
from unittest.mock import patch

class ClockTape:
    def __init__(self, root, mode, product, modules):
        if mode not in ('record', 'replay'):
            raise ValueError('Unknown clock mode')
        self.root, self.mode, self.product, self.modules = Path(root), mode, Path(product).resolve(), modules
        self.lock = threading.Lock()
        self.rows = []
        self.queues = defaultdict(deque)
        self.used = []
        self.patches = []
        if mode == 'replay':
            manifest = json.loads((self.root / 'manifest.json').read_text())
            raw = (self.root / 'events.jsonl').read_bytes()
            if not manifest['closed'] or hashlib.sha256(raw).hexdigest() != manifest['events_sha256']:
                raise ValueError('Clock tape incomplete or modified')
            self.rows = [json.loads(line) for line in raw.splitlines()]
            if len(self.rows) != manifest['calls']:
                raise ValueError('Clock call count mismatch')
            for row in self.rows:
                self.queues[row['key']].append(row)

    def observe(self, module, method, tz, frame, real_value):
        filename = Path(frame.f_code.co_filename).resolve()
        try:
            filename = filename.relative_to(self.product)
        except ValueError:
            raise ValueError('Clock called from outside the fixed product')
        key = json.dumps([module, method, str(filename), frame.f_code.co_name,
                          frame.f_lineno, str(tz) if tz is not None else None], separators=(',', ':'))
        with self.lock:
            if self.mode == 'record':
                row = {'id': len(self.rows) + 1, 'key': key, 'value': real_value.isoformat(), 'fold': real_value.fold}
                self.rows.append(row)
                self.events.write(json.dumps(row, separators=(',', ':')) + '\n')
                self.events.flush()
                return real_value
            if not self.queues[key]:
                raise ValueError('Unrecorded native clock call: ' + key)
            row = self.queues[key].popleft()
            self.used.append(row['id'])
            value = dt.datetime.fromisoformat(row['value']).replace(fold=row['fold'])
            if tz is not None:
                value = value.astimezone(tz)
            return value

    def proxy(self, name):
        tape = self
        class NativeDateTime(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                value = tape.observe(name, 'now', tz, sys._getframe(1), dt.datetime.now(tz))
                return cls.fromisoformat(value.isoformat()).replace(tzinfo=value.tzinfo, fold=value.fold)
            @classmethod
            def utcnow(cls):
                value = tape.observe(name, 'utcnow', None, sys._getframe(1), dt.datetime.utcnow())
                return cls.fromisoformat(value.isoformat()).replace(fold=value.fold)
            @classmethod
            def today(cls):
                value = tape.observe(name, 'today', None, sys._getframe(1), dt.datetime.today())
                return cls.fromisoformat(value.isoformat()).replace(fold=value.fold)
        return NativeDateTime

    def __enter__(self):
        if self.mode == 'record':
            self.root.mkdir(exist_ok=False)
            self.events = (self.root / 'events.jsonl').open('x')
        for module in self.modules:
            if getattr(module, 'datetime', None) is not dt.datetime:
                raise ValueError('Expected native datetime class before instrumentation')
            obj = patch.object(module, 'datetime', self.proxy(module.__name__))
            obj.start()
            self.patches.append(obj)
        return self

    def assert_consumed(self):
        left = sum(len(v) for v in self.queues.values())
        if left:
            raise ValueError('Unconsumed native clock observations: ' + str(left))
        return {'calls_consumed': len(self.used), 'remaining': left, 'live_clock_values_used_for_product': False}

    def __exit__(self, exc_type, exc, tb):
        for obj in reversed(self.patches):
            obj.stop()
        if self.mode == 'record':
            self.events.close()
            raw = (self.root / 'events.jsonl').read_bytes()
            value = {'closed': exc_type is None, 'calls': len(self.rows), 'events_sha256': hashlib.sha256(raw).hexdigest(),
                     'modules': [x.__name__ for x in self.modules],
                     'boundary': 'Native datetime calls observed without changing returned wall time; each callsite/timezone has an ordered replay queue. Monotonic clocks, sleeps, limits and network responses are not changed.'}
            with (self.root / 'manifest.json').open('x') as f:
                json.dump(value, f, indent=2)

