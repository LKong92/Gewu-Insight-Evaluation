#!/usr/bin/env python3
"""Append-only local stage manifests for the V4 study (not external preregistration).

Manifests detect later changes; they are not an operating-system security boundary.
Formal dispatch needs DESIGN and DATA. Human review needs both validated original
AI submissions. No helper synthesizes AI answers or fills human decisions.
"""
from collections import Counter
import datetime as dt
import hashlib
from pathlib import Path

from review_bundle import canonical, digest, packet_sha, read, safe_path, validate_decisions, validate_packet, validate_provenance, write
from audit_review import make_queue, validate_human

SCHEMA = 'gewu-study-stages-v4.1'
STAGES = {'DESIGN', 'DATA', 'CODEX', 'CLAUDE', 'DEEPSEEK', 'HUMAN_QUEUE', 'REFERENCE', 'RESULTS'}
REQUIREMENTS = {'frozen_product', 'v3_coverage_mapping', 'source_configuration', 'verified_author_bindings',
    'sampling_and_calibration_exclusions', 'real_semantic_case_plan', 'engineering_specifications',
    'workflow_and_provider_coverage', 'engineering_qualification', 'review_and_statistical_validation',
    'reviewer_client_preflight', 'human_interface_validation'}


def stage_path(root, stage):
    if stage not in STAGES:
        raise ValueError('Unknown study stage')
    return safe_path(root, 'control/formal/' + stage + '.json')


def verify_stage(root, stage):
    path = stage_path(root, stage)
    value = read(path)
    if value.get('schema') != SCHEMA or value.get('stage') != stage:
        raise ValueError('Invalid stage manifest')
    for parent in value['parents']:
        verify_stage(root, parent['stage'])
        if digest(stage_path(root, parent['stage'])) != parent['sha256']:
            raise ValueError('Parent stage changed')
    if len({r['path'] for r in value['files']}) != len(value['files']) or not value['files']:
        raise ValueError('Empty/duplicate stage inputs')
    for row in value['files']:
        source = safe_path(root, row['path'])
        if not source.is_file() or source.stat().st_size != row['bytes'] or digest(source) != row['sha256']:
            raise ValueError('Locked input changed: ' + row['path'])
    return value


def _seal(root, stage, paths, parents=(), details=None):
    target = stage_path(root, stage)
    if target.exists():
        raise FileExistsError('A sealed stage cannot be overwritten')
    parent_rows = []
    for parent in parents:
        verify_stage(root, parent)
        parent_rows.append({'stage': parent, 'sha256': digest(stage_path(root, parent))})
    rows = []
    for name in sorted(set(paths)):
        path = safe_path(root, name)
        if not path.is_file():
            raise ValueError('Missing explicit stage input: ' + name)
        rows.append({'path': name, 'sha256': digest(path), 'bytes': path.stat().st_size})
    if not rows:
        raise ValueError('A stage cannot seal empty placeholders')
    value = {'schema': SCHEMA, 'stage': stage, 'kind': 'local_hash_manifest_not_external_preregistration',
        'created_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'parents': parent_rows,
        'files': rows, 'details': details or {}}
    write(target, value)
    return value


def seal_design(root, specification_path):
    spec = read(safe_path(root, specification_path))
    if spec.get('schema') != SCHEMA or spec.get('mode') not in ('test', 'formal'):
        raise ValueError('Invalid design specification')
    checks = spec.get('prerequisites', {})
    if set(checks) != REQUIREMENTS:
        raise ValueError('Incomplete design prerequisites')
    paths = [specification_path]
    for name, result in checks.items():
        if result.get('complete') is not True or not result.get('evidence_paths'):
            raise ValueError('Design prerequisite is not evidenced: ' + name)
        paths += result['evidence_paths']
    if not spec.get('human_audit_seed') or spec.get('confidence_threshold') != .8:
        raise ValueError('Prespecify the human audit and risk threshold')
    sentinel_ids = spec.get('sentinel_case_ids', [])
    if len(sentinel_ids) != len(set(sentinel_ids)):
        raise ValueError('Duplicate sentinel IDs')
    if spec['mode'] == 'formal':
        expected = {'A_journal': 150, 'A_subject': 150, 'A_author': 150, 'B_semantic': 96, 'B_engineering': 160, 'C_workflow': 104}
        if spec.get('targets') != expected or len(sentinel_ids) != 16:
            raise ValueError('Formal scope does not match approved V4 replacement design')
        if spec.get('configured_monitors') != {'journal': 12, 'subject': 8, 'author': 24}:
            raise ValueError('Formal monitor coverage incomplete')
        if not isinstance(spec.get('product_commit'), str) or len(spec['product_commit']) != 40:
            raise ValueError('Missing frozen product commit')
    pair = spec.get('reviewers', ['Codex', 'Claude'] if spec['mode'] == 'test' else None)
    if pair not in (['Codex', 'Claude'], ['Codex', 'DeepSeek']) or (spec['mode'] == 'formal' and pair != ['Codex', 'DeepSeek']):
        raise ValueError('Lock the actual Codex + DeepSeek pair for this formal study')
    if spec['mode'] == 'formal':
        from a_design import verify as verify_a, LOCK as A_LOCK
        a_lock = verify_a(root)
        # Preserve the earlier acquisition lock and all its underlying inputs.
        paths += [A_LOCK] + [row['path'] for row in a_lock['files']]
    return _seal(root, 'DESIGN', paths, details={'specification_path': specification_path, 'mode': spec['mode']})


def design(root):
    stage = verify_stage(root, 'DESIGN')
    return read(safe_path(root, stage['details']['specification_path']))


def configured_reviewers(root):
    spec = design(root)
    pair = spec.get('reviewers', ['Codex', 'Claude'] if spec['mode'] == 'test' else None)
    if pair not in (['Codex', 'Claude'], ['Codex', 'DeepSeek']):
        raise ValueError('Invalid locked reviewer pair')
    return pair


def seal_data(root, packet_path, evidence_directory, acquisition_paths):
    spec = design(root)
    packet = read(safe_path(root, packet_path))
    stats = validate_packet(packet)
    if packet['product_commit'] != spec['product_commit']:
        raise ValueError('Packet and frozen product mismatch')
    if (packet['phase'] == 'formal') != (spec['mode'] == 'formal'):
        raise ValueError('Formal and qualification inputs must stay separate')
    if not acquisition_paths:
        raise ValueError('Data requires acquisition/frame/sampling evidence')
    if not set(spec['sentinel_case_ids']).issubset({c['case_id'] for c in packet['cases']}):
        raise ValueError('Prespecified sentinel cases are missing')
    if spec['mode'] == 'formal':
        a = Counter(c.get('axis') for c in packet['cases'] if c['task'] == 'A')
        b = Counter(c.get('group') for c in packet['cases'] if c['task'] == 'B')
        if a != {'journal': 150, 'subject': 150, 'author': 150} or len(b) != 12 or set(b.values()) != {8}:
            raise ValueError('Formal scientific cases do not meet locked scope')
        if any(len(c['questions']) != (3 if c['task'] == 'A' else 1) for c in packet['cases']):
            raise ValueError('Formal primary-question denominator changed')
    evidence_root = safe_path(root, evidence_directory)
    paths = [packet_path, *acquisition_paths]
    for row in packet['evidence']:
        path = safe_path(evidence_root, row['path'])
        if not path.is_file() or digest(path) != row['sha256'] or path.stat().st_size != row['bytes']:
            raise ValueError('Scientific evidence changed')
        paths.append(str(path.relative_to(Path(root).resolve())))
    return _seal(root, 'DATA', paths, ('DESIGN',), {'packet_path': packet_path,
        'evidence_directory': evidence_directory, 'packet_sha256': packet_sha(packet), **stats})


def locked_packet(root):
    stage = verify_stage(root, 'DATA')
    packet = read(safe_path(root, stage['details']['packet_path']))
    if packet_sha(packet) != stage['details']['packet_sha256']:
        raise ValueError('Sealed packet digest mismatch')
    return packet


def require_formal_packet(root, packet):
    if root is None:
        raise ValueError('Formal dispatch requires verified DESIGN and DATA manifests')
    if design(root)['mode'] != 'formal' or packet.get('phase') != 'formal':
        raise ValueError('Qualification cannot authorize a formal package')
    if packet_sha(locked_packet(root)) != packet_sha(packet):
        raise ValueError('Dispatch packet differs from DATA lock')


def seal_reviewer(root, reviewer, submission_path, provenance_path, raw_output_paths, receipt_path):
    if reviewer not in configured_reviewers(root) or not raw_output_paths or not receipt_path:
        raise ValueError('Need actual reviewer and preserved original output files')
    packet = locked_packet(root)
    submission = read(safe_path(root, submission_path))
    if submission.get('reviewer') != reviewer:
        raise ValueError('Wrong reviewer identity')
    checked = validate_decisions(packet, submission)
    provenance = read(safe_path(root, provenance_path))
    validate_provenance(packet, provenance, reviewer)
    receipt = read(safe_path(root, receipt_path))
    if receipt.get('reviewer') != reviewer or not receipt.get('session_reference') or not receipt.get('capture_method'):
        raise ValueError('Missing actual session reference/original-output provenance')
    if receipt.get('raw_output_sha256') != {p: digest(safe_path(root, p)) for p in raw_output_paths}:
        raise ValueError('Original-output provenance does not match preserved bytes')
    return _seal(root, reviewer.upper(), [submission_path, provenance_path, receipt_path, *raw_output_paths], ('DATA',),
        {'reviewer': reviewer, 'submission_path': submission_path, 'provenance_path': provenance_path,
         'validation': checked, 'validation_limit': 'Completeness, format and recorded provenance; not a guarantee of scientific correctness.'})


def prepare_human(root):
    packet = locked_packet(root)
    spec = design(root)
    submissions = []
    reviewer_stages = tuple(r.upper() for r in configured_reviewers(root))
    for reviewer in reviewer_stages:
        stage = verify_stage(root, reviewer)
        submissions.append(read(safe_path(root, stage['details']['submission_path'])))
    if stage_path(root, 'HUMAN_QUEUE').exists():
        raise FileExistsError('Human queue already sealed')
    queue = make_queue(packet, *submissions, spec['human_audit_seed'], spec['sentinel_case_ids'], spec['confidence_threshold'])
    queue_path = 'review/formal/human/queue.json'
    write(safe_path(root, queue_path), queue)
    return _seal(root, 'HUMAN_QUEUE', [queue_path], reviewer_stages, {'queue_path': queue_path, **queue['counts']})


def seal_reference(root, human_record_path):
    stage = verify_stage(root, 'HUMAN_QUEUE')
    queue = read(safe_path(root, stage['details']['queue_path']))
    human = read(safe_path(root, human_record_path))
    validate_human(queue, human)
    if human.get('submitted_via') != 'human_review_ui' or not human.get('received_at'):
        raise ValueError('Reference requires an actual saved human submission')
    human_answers = {a['question_id']: a['label'] for a in human['answers']}
    packet = locked_packet(root)
    ai_stage = verify_stage(root, 'CODEX')
    ai = read(safe_path(root, ai_stage['details']['submission_path']))
    ai_answers = {a['question_id']: a['label'] for a in ai['answers']}
    selected = {c['case']['case_id'] for c in queue['cards']}
    final = {'packet_sha256': packet_sha(packet), 'human_queue_sha256': hashlib.sha256(canonical(queue)).hexdigest(),
        'reference_type': 'dual_ai_with_developer_adjudication_and_probability_audit', 'answers': []}
    for case in packet['cases']:
        for q in case['questions']:
            qid = q['question_id']
            label = human_answers[qid] if case['case_id'] in selected else ai_answers[qid]
            final['answers'].append({'question_id': qid, 'label': label,
                'source': 'human_adjudicated' if case['case_id'] in selected else 'dual_ai_consensus',
                'unresolved': label == 'uncertain'})
    reference_path = 'review/formal/reference.json'
    write(safe_path(root, reference_path), final)
    return _seal(root, 'REFERENCE', [human_record_path, reference_path], ('HUMAN_QUEUE',), {'reference_path': reference_path})


def seal_results(root, result_paths):
    verify_stage(root, 'REFERENCE')
    if not result_paths:
        raise ValueError('Cannot publish an empty result stage')
    # Numerical/coverage validation belongs to the final scorer. This function
    # seals its actual report files; it makes no success or statistical claim.
    return _seal(root, 'RESULTS', result_paths, ('REFERENCE',), {'validation_limit': 'Hash sealing only; use the scorer validation report.'})
