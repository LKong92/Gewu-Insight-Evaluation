#!/usr/bin/env python3
"""Construct reproducible monitor/work frames from preserved native UI responses.

No semantic labels or product-quality decisions. Exact disclosed identifiers link
occurrences; titles alone never merge works. Preserve every contributing card and
its monitor, display order and response locator. Missing identity stays explicit.
"""
from collections import defaultdict
import hashlib
import json
import random
import re
from urllib.parse import unquote


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def doi(value):
    value = unquote(str(value or '')).strip().lower()
    value = re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', value)
    return value if re.fullmatch(r'10\.\d{4,9}/\S+', value) else ''


def arxiv(value):
    value = unquote(str(value or '')).strip().lower()
    value = re.sub(r'^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:\s*|10\.48550/arxiv\.)', '', value)
    value = re.sub(r'\.pdf$', '', value)
    value = re.sub(r'v\d+$', '', value)
    return value if re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})', value) else ''


def anchors(card):
    result = set()
    d = doi(card.get('doi'))
    if d:
        result.add('doi:' + d)
        a = arxiv(d)
        if a:
            result.add('arxiv:' + a)
    a = arxiv(card.get('preprint_id'))
    if a:
        result.add('arxiv:' + a)
    if not result and card.get('paper_id'):
        # This is a provider/product record identifier, explicitly not independent
        # proof of semantic identity. Only use it when no DOI/arXiv exists;
        # a reused product ID must not collapse two conflicting explicit DOIs.
        result.add('record:' + str(card['paper_id']))
    return result


def author_window_includes(card, start, end):
    """Study eligibility using displayed date, not an Author Monitor UI filter.

All original cards remain archived. Unknown/partial dates that may intersect the
window stay in the frame; external date verification belongs to the AI question.
"""
    value = str(card.get('publication_date') or '')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return start <= value <= end
    if re.fullmatch(r'\d{4}(?:-\d{2})?', value):
        return start[:len(value)] <= value <= end[:len(value)]
    return True


def make_frame(occurrences, exclusion_identifiers=()):
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)
    ids = set()
    for row in occurrences:
        oid = row['occurrence_id']
        if oid in ids or row['axis'] not in ('journal', 'subject', 'author') or not row.get('monitor_id'):
            raise ValueError('Duplicate occurrence or missing axis/monitor')
        ids.add(oid)
        keys = sorted(anchors(row['card'])) or ['unidentified:' + oid]
        for k in keys:
            union(keys[0], k)
    components = defaultdict(set)
    for key in parent:
        components[find(key)].add(key)
    excluded_roots = {find(key) for key in exclusion_identifiers if key in parent}
    conflicts = {root: sorted(k for k in keys if k.startswith('doi:') and not arxiv(k[4:]))
                 for root, keys in components.items()}
    conflicts = {root: keys for root, keys in conflicts.items() if len(keys) > 1}
    groups, excluded = defaultdict(list), []
    for row in occurrences:
        keys = sorted(anchors(row['card'])) or ['unidentified:' + row['occurrence_id']]
        root = find(keys[0])
        if root in excluded_roots:
            excluded.append(row['occurrence_id'])
            continue
        # A shared arXiv ID does not justify silently collapsing contradictory
        # publication DOIs. Keep each explicit DOI group, and an arXiv-only group,
        # while retaining their possible relationship for the final audit.
        split = ''
        if root in conflicts:
            publication_dois = [k for k in keys if k.startswith('doi:') and not arxiv(k[4:])]
            split = publication_dois[0] if publication_dois else 'unresolved:' + keys[0]
        groups[(row['axis'], row['monitor_id'], root, split)].append(row)
    frame = []
    for (axis, monitor, root, split), rows in groups.items():
        identifiers = sorted(set().union(*(anchors(r['card']) or {'unidentified:' + r['occurrence_id']} for r in rows))) if split else sorted(components[root])
        cluster = hashlib.sha256(canonical(identifiers)).hexdigest()
        unit = hashlib.sha256(canonical([axis, monitor, cluster])).hexdigest()
        frame.append({'candidate_id': 'CAN-' + unit[:24], 'axis': axis, 'monitor_id': monitor,
            'work_cluster_id': cluster, 'identity_anchors': identifiers,
            'identity_basis': 'exact_disclosed_identifiers_and_repeat_record_ID_not_semantic_reference',
            'identity_ambiguity': 'shared_identifier_connects_distinct_publication_DOIs' if split else '',
            'possible_identity_cluster_id': hashlib.sha256(canonical(sorted(components[root]))).hexdigest(),
            'occurrences': sorted(rows, key=lambda x: x['occurrence_id'])})
    return {'units': sorted(frame, key=lambda x: x['candidate_id']), 'excluded_occurrence_ids': sorted(excluded),
        'occurrence_count': len(occurrences), 'unit_count': len(frame),
        'cross_monitor_clusters': len({r['work_cluster_id'] for r in frame}),
        'ambiguous_identifier_components': len(conflicts),
        'title_based_merges': False}


def sample_frame(frame, seed, n_per_axis=150):
    if not seed or not isinstance(n_per_axis, int) or n_per_axis <= 0:
        raise ValueError('Need prespecified seed and positive sample size')
    samples = {}
    for axis in ('journal', 'subject', 'author'):
        units = [u for u in frame['units'] if u['axis'] == axis]
        units = sorted(units, key=lambda x: x['candidate_id'])
        rng = random.Random(int.from_bytes(hashlib.sha256((seed + ':' + axis).encode()).digest(), 'big'))
        chosen = rng.sample(units, min(n_per_axis, len(units)))
        samples[axis] = {'frame_size': len(units), 'target': n_per_axis, 'sample_size': len(chosen),
            'shortfall': max(0, n_per_axis - len(chosen)),
            'inclusion_probability': min(n_per_axis, len(units)) / len(units) if units else None,
            'selected_candidate_ids': [u['candidate_id'] for u in chosen]}
    return {'seed': seed, 'design': 'SRS_without_replacement_separately_per_axis',
        'frame_sha256': hashlib.sha256(canonical(frame)).hexdigest(), 'axes': samples,
        'formal_scope_complete': all(s['shortfall'] == 0 for s in samples.values())}
