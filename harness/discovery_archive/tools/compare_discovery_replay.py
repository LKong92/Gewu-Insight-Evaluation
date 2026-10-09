#!/usr/bin/env python3
"""Compare every saved UI field, retaining differences in execution timestamps."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re


def verify_raw_capture(root, payload):
    """New captures retain exact bytes; legacy captures lack this extra evidence."""
    if 'raw_body_path' not in payload and 'raw_body_sha256' not in payload:
        return False
    name = payload.get('raw_body_path', '')
    target = root / name
    if not name.startswith('ui/') or not target.resolve().is_relative_to((root / 'ui').resolve()) or target.is_symlink():
        raise ValueError('Unsafe raw UI response path')
    raw = target.read_bytes()
    if hashlib.sha256(raw).hexdigest() != payload.get('raw_body_sha256'):
        raise ValueError('Raw UI response bytes changed')
    if json.loads(raw) != payload.get('response'):
        raise ValueError('Parsed UI response differs from retained raw bytes')
    return True


def differences(a, b, path=''):
    if type(a) is not type(b):
        return [{'path': path, 'original': a, 'replay': b}]
    if isinstance(a, dict):
        out = []
        for key in sorted(a.keys() | b.keys()):
            if key not in a or key not in b:
                out.append({'path': path + '/' + key, 'kind': 'missing_key',
                            'original_present': key in a, 'replay_present': key in b})
            else:
                out.extend(differences(a[key], b[key], path + '/' + key))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [{'path': path, 'kind': 'list_length', 'original': len(a), 'replay': len(b)}]
        return [d for i, (x, y) in enumerate(zip(a, b))
                for d in differences(x, y, path + '/' + str(i))]
    return [] if a == b else [{'path': path, 'original': a, 'replay': b}]


def is_execution_timestamp(axis, path):
    patterns = {
        'journal': [],
        'subject': [r'ui/\d+\.json/response/papers/\d+/theme_groups/\d+/searched_at',
                    r'occurrences.json/\d+/card/theme_groups/\d+/searched_at'],
        'author': [r'ui/\d+\.json/response/authors/\d+/last_(checked|success)_at',
                   r'ui/\d+\.json/response/checkedAt',
                   r'ui/\d+\.json/response/papers/\d+/author_first_seen_at',
                   r'occurrences.json/\d+/card/author_first_seen_at'],
    }
    return any(re.fullmatch(p, path) for p in patterns[axis])


def compare(original, replay):
    load = lambda p: json.loads(p.read_text())
    left, right = load(original / 'acquisition.json'), load(replay / 'acquisition.json')
    axis = left['axis']
    expected_phase = {'qualification': 'qualification-replay', 'record': 'replay'}.get(left['phase'])
    if not (left['complete'] and right['complete'] and right['axis'] == axis
            and expected_phase and right['phase'] == expected_phase):
        raise ValueError('Comparison requires a completed matching acquisition and replay')
    if left['product_commit'] != right['product_commit']:
        raise ValueError('Different frozen product versions')
    names = ['occurrences.json', 'study_window_exclusions.json', 'input_configuration.json']
    if axis == 'author':
        names.append('author_bindings.json')
    first = sorted(p.name for p in (original / 'ui').glob('*.json'))
    second = sorted(p.name for p in (replay / 'ui').glob('*.json'))
    if first != second:
        raise ValueError('Saved UI response set changed')
    names += ['ui/' + name for name in first]
    all_diffs, files = [], []
    for name in names:
        a, b = original / name, replay / name
        av, bv = load(a), load(b)
        raw_verified = False
        if name.startswith('ui/'):
            va, vb = verify_raw_capture(original, av), verify_raw_capture(replay, bv)
            raw_verified = va and vb
        files.append({'path': name, 'original_sha256': hashlib.sha256(a.read_bytes()).hexdigest(),
                      'replay_sha256': hashlib.sha256(b.read_bytes()).hexdigest()})
        for d in differences(av, bv, name):
            timestamp = is_execution_timestamp(axis, d['path']) and 'kind' not in d
            if timestamp:
                try:
                    dt.datetime.fromisoformat(d['original'])
                    dt.datetime.fromisoformat(d['replay'])
                except (ValueError, TypeError):
                    timestamp = False
            d['execution_timestamp_only'] = timestamp
            # A changed execution timestamp changes the hash of the full JSON
            # body too. Both bodies were validated above; their decoded fields
            # still undergo the complete field-by-field comparison below.
            d['validated_raw_body_checksum_only'] = raw_verified and d['path'] == name + '/raw_body_sha256' and 'kind' not in d
            all_diffs.append(d)
    return {'axis': axis, 'original_run': original.name, 'replay_run': replay.name,
            'passed': all(d['execution_timestamp_only'] or d['validated_raw_body_checksum_only'] for d in all_diffs),
            'formal_result': False, 'comparison_scope': 'all captured UI fields and ordered candidate occurrences',
            'excluded_from_equality': 'listed valid runtime timestamps and validated raw-body checksums; decoded body fields compared completely; all differences retained',
            'files': files, 'differences': all_diffs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', required=True)
    parser.add_argument('--replay', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = compare(Path(args.original), Path(args.replay))
    with Path(args.output).open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps({k: result[k] for k in ('axis', 'passed', 'original_run', 'replay_run')}))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
