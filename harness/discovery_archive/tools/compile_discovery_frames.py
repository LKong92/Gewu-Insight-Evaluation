#!/usr/bin/env python3
"""Validate captured UI membership, exclude teaching identities, and sample Task A.

Acquisition, offline replay, and sampled frames retain separate denominators.
The transport archive being closed is not a claim of source coverage/completion.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from discovery_frames import doi, arxiv, make_frame, sample_frame
from source_transport import SourceTransport
from source_coverage import summarize as summarize_coverage


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_occurrence(row, captured, axis, author_ids):
    if row.get('axis') != axis:
        raise ValueError('Occurrence axis differs from its acquisition')
    index = row.get('display_order')
    cards = captured['response'].get('papers', [])
    if type(index) is not int or not 0 <= index < len(cards) or cards[index] != row['card']:
        raise ValueError('Candidate is not the exact card at its recorded UI position')
    monitor = row.get('monitor_id')
    if axis == 'journal' and monitor != row['card'].get('journal'):
        raise ValueError('Journal candidate changed monitor membership')
    if axis == 'subject' and monitor not in [g['key'] for g in row['card'].get('theme_groups', [])]:
        raise ValueError('Subject candidate changed monitor membership')
    if axis == 'author':
        visible_author = parse_qs(urlsplit(captured['path']).query).get('author_id', [])
        if monitor not in author_ids or visible_author != [str(author_ids[monitor])]:
            raise ValueError('Author candidate is not from the recorded roster-author response')


def exclusions(value):
    keys = set()
    for raw in value.get('dois', []):
        parsed = doi(raw)
        if not parsed:
            raise ValueError('Invalid teaching DOI')
        keys.add('doi:' + parsed)
        if arxiv(parsed):
            keys.add('arxiv:' + arxiv(parsed))
    for raw in value.get('arxiv_ids', []):
        parsed = arxiv(raw)
        if not parsed:
            raise ValueError('Invalid teaching arXiv identifier')
        keys.add('arxiv:' + parsed)
    if not keys:
        raise ValueError('Teaching exclusion manifest must not silently be empty')
    return sorted(keys)


def compile_frames(archive, run_paths, config_path, exclusion_path, mode, design_stage='DESIGN'):
    if mode not in ('qualification', 'formal'):
        raise ValueError('Unknown study phase')
    if len(run_paths) != 3:
        raise ValueError('Require one acquisition from each of three axes')
    config = read(config_path)
    if mode == 'formal':
        from run_a import require_locked_input
        for path in [config_path, exclusion_path, Path(__file__),
                     Path(__file__).with_name('discovery_frames.py'), Path(__file__).with_name('source_transport.py'),
                     Path(__file__).with_name('source_coverage.py'), archive / config['source_limits_manifest']]:
            require_locked_input(archive, path, design_stage)
    baseline = read(archive / 'control/baseline.json')
    seen_axes, all_rows, sources, inputs = set(), [], [], []
    expected_phase = 'qualification' if mode == 'qualification' else 'record'
    for path in run_paths:
        path = path.resolve()
        if not path.is_relative_to(archive / 'runs'):
            raise ValueError('Acquisition outside the benchmark run archive')
        acquired = read(path / 'acquisition.json')
        if mode == 'formal':
            if acquired.get('design_stage', 'DESIGN') != design_stage or acquired.get('design_sha256') != sha(archive / ('control/formal/' + design_stage + '.json')):
                raise ValueError('Acquisition belongs to another design lock')
        axis = acquired['axis']
        if axis in seen_axes or axis not in ('journal', 'subject', 'author'):
            raise ValueError('Duplicate or unknown acquisition axis')
        seen_axes.add(axis)
        if acquired['phase'] != expected_phase or not acquired['complete']:
            raise ValueError('Use completed original acquisitions, never replay output or a mixed study phase')
        if acquired['product_commit'] != baseline['commit'] or read(path / 'input_configuration.json') != config:
            raise ValueError('Product or scientific input changed between acquisitions')
        SourceTransport(path / 'sources', 'replay')  # validates every log and blob hash; does not replay or connect
        source_manifest = read(path / 'sources/manifest.json')
        summary = read(path / 'native_summary.json')
        response_index = {}
        for entry in read(path / 'ui_manifest.json'):
            name = entry['path']
            target = path / name
            if not name.startswith('ui/') or not target.resolve().is_relative_to(path / 'ui') or target.is_symlink():
                raise ValueError('Unsafe captured UI path')
            if sha(target) != entry['sha256'] or entry['status'] != 200:
                raise ValueError('UI response changed or was unsuccessful')
            response_index[name] = read(target)
            inputs.append({'path': str(target.relative_to(archive)), 'sha256': sha(target)})
        author_ids = {r['roster_author_id']: r['native_monitor_id'] for r in summary} if axis == 'author' else {}
        for row in read(path / 'occurrences.json'):
            if row['response_path'] not in response_index:
                raise ValueError('Occurrence lacks a preserved UI response')
            check_occurrence(row, response_index[row['response_path']], axis, author_ids)
            row['response_path'] = str((path / row['response_path']).relative_to(archive))
            row['acquisition'] = str(path.relative_to(archive))
            all_rows.append(row)
        for name in ('acquisition.json','input_configuration.json','ui_manifest.json','occurrences.json',
                     'native_summary.json','study_window_exclusions.json','sources/manifest.json'):
            inputs.append({'path': str((path / name).relative_to(archive)), 'sha256': sha(path / name)})
        attempts = [json.loads(line) for line in (path / 'sources/attempts.jsonl').read_text().splitlines()]
        statuses = Counter((urlsplit(r['request']['url']).hostname,
                            str(r['response']['status']) if 'response' in r else r['exception']['type']) for r in attempts)
        sources.append({'axis':axis,'acquisition':str(path.relative_to(archive)),
            'attempts':source_manifest['attempts'], 'http_and_exception_counts':[
                {'host':host,'outcome':status,'attempts':count} for (host,status),count in sorted(statuses.items())],
            'native_monitor_outcomes':summary,
            'study_window_excluded_occurrences':len(read(path/'study_window_exclusions.json')),
            'coverage_complete_inferred_from_HTTP':False,
            'pagination_and_limits':summarize_coverage(path / 'sources')})
    exclusion_keys = exclusions(read(exclusion_path))
    frame = make_frame(all_rows, exclusion_keys)
    sample = sample_frame(frame, config['sampling']['seed'], config['sampling']['n_per_axis'])
    selected = {i for axis in sample['axes'].values() for i in axis['selected_candidate_ids']}
    contributions = []
    for (axis, monitor), n in sorted(Counter((u['axis'], u['monitor_id']) for u in frame['units']).items()):
        contributions.append({'axis':axis,'monitor_id':monitor,'frame_units':n,
                              'selected_units':sum(u['candidate_id'] in selected and u['axis']==axis and
                                u['monitor_id']==monitor for u in frame['units'])})
    return {'phase':mode,'formal_product_scores':False,'frame':frame,'sampling':sample,
        'selected_units':[u for u in frame['units'] if u['candidate_id'] in selected],
        'monitor_contributions':contributions,'source_outcomes':sources,'input_hashes':inputs,
        'exclusion_manifest':{'path':str(exclusion_path.relative_to(archive)),'sha256':sha(exclusion_path),
                              'normalized_identifiers':exclusion_keys},
        'limitations':['Source success is not proof of exhaustive retrieval or recall.',
            'Author date eligibility is a study filter on archived displayed dates, not a native UI date control.',
            'Teaching exclusions close over observed exact identifier relations; unobserved historical version links need separate evidence.',
            'Identity conflicts remain separate and flagged; title-only similarities never collapse units.',
            'Shortfalls are preserved and prevent a target-sized formal DATA lock; do not pad or substitute after seeing outcomes.']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',required=True);p.add_argument('--acquisitions',nargs=3,required=True)
    p.add_argument('--config',required=True);p.add_argument('--exclusions',required=True)
    p.add_argument('--design-stage',choices=['DESIGN','A_DESIGN'],default='DESIGN')
    p.add_argument('--mode',choices=['qualification','formal'],required=True);p.add_argument('--output',required=True)
    args=p.parse_args();archive=Path(args.archive).resolve();output=Path(args.output).resolve()
    if not output.is_relative_to(archive/'runs'):
        raise ValueError('Write only to a new benchmark run directory')
    result=compile_frames(archive,[Path(p) for p in args.acquisitions],Path(args.config).resolve(),Path(args.exclusions).resolve(),args.mode,args.design_stage)
    output.mkdir(parents=True,exist_ok=False)
    for name in ('compile_discovery_frames.py','discovery_frames.py','source_transport.py','source_coverage.py'):
        (output/name).write_bytes(Path(__file__).with_name(name).read_bytes())
    for name in ['frame','sampling','selected_units','monitor_contributions','source_outcomes']:
        with (output/(name+'.json')).open('x') as f:json.dump(result[name],f,ensure_ascii=False,indent=2);f.write('\n')
    with (output/'frame_manifest.json').open('x') as f:
        json.dump({k:v for k,v in result.items() if k not in ['frame','sampling','selected_units','monitor_contributions','source_outcomes']},f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'phase':args.mode,'units':result['frame']['unit_count'],
        'excluded_occurrences':len(result['frame']['excluded_occurrence_ids']),
        'axes':result['sampling']['axes'],'formal_product_scores':False}))


if __name__=='__main__':main()
