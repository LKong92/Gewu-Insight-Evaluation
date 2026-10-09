#!/usr/bin/env python3
"""Reproduce the human-review sample and compare final human choices with consensus."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE_FIELDS = ['membership', 'date', 'research_eligibility']
FIELDS = {'journal': BASE_FIELDS, 'subject': ['membership', 'broad_membership'],
          'author': ['membership']}


def read(root, path):
    return json.loads((root / path).read_text())


def keyed(rows, key):
    values = {row[key]: row for row in rows}
    assert len(values) == len(rows), 'Duplicate ' + key
    return values


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def calculate(root=ROOT):
    protocol = read(root, 'protocols/human_review_protocol.json')
    assert protocol['fields'] == FIELDS
    assert protocol['n_per_axis'] == dict.fromkeys(FIELDS, 10)
    assert protocol['no_replacement'] and not protocol['reference_labels_changed']
    for name, expected in protocol['input_file_sha256'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
    cases = keyed(read(root, 'data/cases.json')['cases'], 'case_id')
    reviewers = {}
    for reviewer in ['codex', 'deepseek']:
        rows = []
        for phase in ['base', 'broad']:
            rows.extend(read(root, 'data/reviews/' + reviewer + '_' + phase + '.json')['answers'])
        reviewers[reviewer] = keyed(rows, 'question_id')
    human_ids = {a['question_id'].rsplit(':', 1)[0]
                 for phase in ['base', 'broad']
                 for a in read(root, 'data/reviews/human_' + phase + '.json')['answers']}
    eligible = {axis: [] for axis in FIELDS}
    excluded = []
    for cid, case in sorted(cases.items()):
        scope = BASE_FIELDS + (['broad_membership'] if case['axis'] == 'subject' else [])
        if cid in human_ids:
            excluded.append({'case_id': cid, 'reason': 'prior_human_adjudication_any_field'})
            continue
        if not all(reviewers['codex'][cid + ':' + field]['label'] ==
                   reviewers['deepseek'][cid + ':' + field]['label'] for field in scope):
            excluded.append({'case_id': cid, 'reason': 'accepted_model_disagreement'})
            continue
        eligible[case['axis']].append(cid)
    frame = read(root, 'data/human_review_sampling_frame.json')
    pools = {axis: len(ids) for axis, ids in eligible.items()}
    assert frame == {'eligible': eligible, 'excluded': excluded, 'pool_counts': pools}
    seed = protocol['seed']
    selected = []
    for axis, ids in eligible.items():
        selected.extend(sorted(ids, key=lambda cid: digest(seed + '|select|' + axis + '|' + cid))[:10])
    selected.sort(key=lambda cid: digest(seed + '|display|' + cid))
    sample = read(root, 'data/human_review_sample.json')['samples']
    assert len(sample) == len(set(selected)) == 30
    assert [s['case_id'] for s in sample] == selected, 'Selection or display order differs'
    rows = read(root, 'data/reviews/human_review.json')
    assert rows['record_type'] == 'final_human_review_choices'
    assert rows['reviewer'] == protocol['reviewer']
    choices = keyed(rows['answers'], 'question_id')
    catalog = keyed(read(root, 'data/evidence_catalog.json')['entries'], 'evidence_id')
    expected_ids = set()
    by_axis = {axis: {'candidates': 0, 'judgments': 0, 'agreed': 0,
                     'candidates_with_all_fields_agreed': 0} for axis in FIELDS}
    by_field = {}
    comparisons = []
    sources = 0
    for index, s in enumerate(sample, 1):
        cid, axis = s['case_id'], s['axis']
        assert s['sample_id'] == 'P' + str(index).zfill(2)
        assert axis == cases[cid]['axis'] and s['title'] == cases[cid]['title']
        assert s['fields'] == FIELDS[axis]
        assert s['inclusion_probability'] == 10 / pools[axis]
        assert s['selection_rank_hash'] == digest(seed + '|select|' + axis + '|' + cid)
        for source in s['materials_provided']:
            assert source['source_id'] in catalog
            if source.get('sha256'):
                assert source['sha256'] == catalog[source['source_id']]['sha256']
            sources += 1
        all_agreed = True
        for field in s['fields']:
            qid = cid + ':' + field; expected_ids.add(qid)
            answer = choices[qid]
            assert answer['sample_id'] == s['sample_id']
            label = answer['label']
            assert label in protocol['allowed_labels']
            consensus = reviewers['codex'][qid]['label']
            assert consensus == reviewers['deepseek'][qid]['label']
            agrees = label == consensus
            all_agreed = all_agreed and agrees
            key = axis + ':' + field
            group = by_field.setdefault(key, {'judgments': 0, 'agreed': 0,
                                             'human_labels': dict.fromkeys(['yes', 'no', 'uncertain'], 0)})
            group['judgments'] += 1; group['agreed'] += int(agrees)
            group['human_labels'][label] += 1
            by_axis[axis]['judgments'] += 1; by_axis[axis]['agreed'] += int(agrees)
            comparisons.append({'sample_id': s['sample_id'], 'question_id': qid,
                                'axis': axis, 'field': field, 'human_label': label,
                                'consensus_label': consensus, 'agrees': agrees})
        by_axis[axis]['candidates'] += 1
        by_axis[axis]['candidates_with_all_fields_agreed'] += int(all_agreed)
    assert set(choices) == expected_ids and len(choices) == 60
    export = read(root, 'provenance/human_review_export.json')
    assert export['answers'] == len(choices) and export['sampled_candidates'] == len(sample)
    assert export['materials_provided_entries'] == sources
    return {'sampled_candidates': len(sample), 'judgments': len(choices),
            'agreed_fields': sum(row['agrees'] for row in comparisons),
            'candidates_with_all_fields_agreed': sum(g['candidates_with_all_fields_agreed'] for g in by_axis.values()),
            'eligible_pool_counts': pools, 'by_axis': by_axis, 'by_field': by_field,
            'comparison': 'Final human judgments versus accepted two-model consensus',
            'comparisons': comparisons}


def check(root=ROOT):
    summary = calculate(root)
    assert summary == read(root, 'results/human_review_summary.json'), 'Stored human-review summary differs'
    declaration = read(root, 'protocols/release_definition.json')['human_review']
    for key in ['sampled_candidates', 'judgments', 'agreed_fields']:
        assert declaration[key] == summary[key]
    assert declaration['candidate_counts'] == {k: v['candidates'] for k, v in summary['by_axis'].items()}
    assert not declaration['reference_changed']
    return {k: summary[k] for k in ['sampled_candidates', 'judgments', 'agreed_fields', 'candidates_with_all_fields_agreed']}


if __name__ == '__main__':
    print(json.dumps({'verified': True, **check()}))
