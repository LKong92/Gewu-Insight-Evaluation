"""Pre-acquisition Task A lock. Never authorizes global review or scoring."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

SCHEMA = 'gewu-A-acquisition-design-v4.1'
LOCK = 'control/formal/A_DESIGN.json'
SPEC = 'config/a_design_specification_001.json'
TOOLS = ('a_design.py', 'run_a.py', 'run_b.py', 'source_transport.py',
         'discovery_guard.py', 'discovery_frames.py', 'source_coverage.py',
         'compile_discovery_frames.py', 'compare_discovery_replay.py')


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe(root, name):
    root, rel = Path(root).resolve(), Path(name)
    target = root / rel
    if rel.is_absolute() or '..' in rel.parts or target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError('Unsafe A design input: ' + str(name))
    return target


def validate_spec(root, spec):
    if spec.get('schema') != SCHEMA or spec.get('mode') != 'formal_acquisition':
        raise ValueError('A acquisition requires its formal, versioned specification')
    if spec.get('targets') != {'journal': 150, 'subject': 150, 'author': 150}:
        raise ValueError('Task A target may not be reduced')
    if spec.get('reviewers') != ['Codex', 'DeepSeek'] or spec.get('questions_per_candidate') != 3:
        raise ValueError('Actual reviewer pair and question denominator must be fixed')
    if spec.get('authorizes_global_dispatch') is not False or spec.get('authorizes_scoring') is not False:
        raise ValueError('A design cannot authorize global dispatch or scoring')
    baseline = read(safe(root, 'control/baseline.json'))
    if spec.get('product_commit') != baseline['commit']:
        raise ValueError('Wrong frozen product')
    config = read(safe(root, spec['configuration']))
    if len(config['subjects']) != 8 or config['sampling']['n_per_axis'] != 150 or not config['sampling']['seed']:
        raise ValueError('Incomplete A sampling inputs')
    if config.get('collection_deadline_hours') != 48 or not config.get('human_audit_seed'):
        raise ValueError('Missing deadline or audit seed')
    if config['windows'] != {'journal': ['2026-09-01','2026-09-30'],
            'subject': ['2026-09-01','2026-09-30'], 'author': ['2026-01-01','2026-09-30']}:
        raise ValueError('Approved acquisition windows changed')
    bindings = read(safe(root, spec['author_bindings']))
    if len(bindings['authors']) != 24 or {r['author_id'] for r in bindings['authors']} != {'AUTHOR-%02d' % i for i in range(1,25)}:
        raise ValueError('Need all 24 fixed author identities')
    for row in bindings['authors']:
        if row.get('verified') is not True or not row.get('identity_evidence'):
            raise ValueError('Author lacks verification evidence')
        for item in row['identity_evidence']:
            if digest(safe(root, item['path'])) != item['sha256']:
                raise ValueError('Author identity evidence changed')
    policy = read(safe(root, config['source_limits_manifest']))
    if policy.get('product_commit') != baseline['commit'] or policy.get('native_limits_unchanged') is not True:
        raise ValueError('Source policy no longer matches product')
    excluded = read(safe(root, spec['exclusions']))
    if not excluded.get('dois') or not excluded.get('arxiv_ids'):
        raise ValueError('Missing exposure exclusions')
    required = {SPEC, 'control/baseline.json', spec['configuration'], spec['author_bindings'],
                spec['exclusions'], config['source_limits_manifest'], spec['amendment'], spec['questions']}
    required.update('tools/' + name for name in TOOLS)
    required.update(e['path'] for a in bindings['authors'] for e in a['identity_evidence'])
    required.update(spec['qualification_evidence'])
    if not spec['qualification_evidence'] or not required.issubset(set(spec['inputs'])):
        raise ValueError('Acquisition design leaves necessary inputs unlocked')
    return required


def verify(root):
    value = read(safe(root, LOCK))
    if value.get('schema') != SCHEMA or value.get('stage') != 'A_DESIGN':
        raise ValueError('Invalid A acquisition lock')
    rows = value['files']
    if not rows or len({r['path'] for r in rows}) != len(rows):
        raise ValueError('Empty or duplicate A design inputs')
    for row in rows:
        source = safe(root, row['path'])
        if not source.is_file() or source.stat().st_size != row['bytes'] or digest(source) != row['sha256']:
            raise ValueError('Locked A input changed: ' + row['path'])
    spec = read(safe(root, SPEC))
    validate_spec(root, spec)
    if set(spec['inputs']) != {r['path'] for r in rows}:
        raise ValueError('A lock and specification inputs differ')
    return value


def seal(root):
    root = Path(root).resolve()
    target = safe(root, LOCK)
    if target.exists() or safe(root, 'control/formal/COLLECTION_CLOCK.json').exists():
        raise FileExistsError('Never reseal a started acquisition')
    for path in (root / 'runs').glob('*/acquisition.json'):
        if read(path).get('phase') == 'record':
            raise ValueError('A pre-acquisition lock cannot be created after formal outcomes')
    spec = read(safe(root, SPEC))
    validate_spec(root, spec)
    baseline = read(safe(root, 'control/baseline.json'))
    product = root.parents[1]
    for row in baseline['tracked_files']:
        if digest(safe(product, row['path'])) != row['sha256']:
            raise ValueError('Frozen product changed: ' + row['path'])
    value = {'schema': SCHEMA, 'stage': 'A_DESIGN',
        'kind': 'local_hash_manifest_not_external_preregistration',
        'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'authorizes_global_dispatch': False, 'authorizes_scoring': False,
        'files': [{'path': name, 'sha256': digest(safe(root,name)), 'bytes': safe(root,name).stat().st_size}
                  for name in sorted(set(spec['inputs']))]}
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2); f.write('\n')
    return verify(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--action', choices=['seal','verify'], required=True)
    args = parser.parse_args()
    value = (seal if args.action == 'seal' else verify)(Path(args.archive))
    print(json.dumps({'stage': value['stage'], 'inputs': len(value['files']),
                      'created_at': value['created_at'], 'authorizes_scoring': False}))
