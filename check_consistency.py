#!/usr/bin/env python3
"""Check agreement between released records, summary tables and source mappings."""
import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import score_results
import release_checks

ROOT=Path(__file__).resolve().parent
def load(name):return json.loads((ROOT/name).read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    status_checks=release_checks.check()
    with contextlib.redirect_stdout(io.StringIO()):calc=score_results.main()
    assert calc==load('results/recalculated_release.json'),'Stored recalculation differs'
    summary=load('results/summary.json');coverage=load('results/coverage.json')
    assert summary['base_AI_question_fields']==1263
    assert summary['additional_broad_AI_question_fields']==110
    assert summary['combined_AI_question_fields_per_reviewer']==calc['reference_fields']==1373
    assert summary['human_adjudications']==calc['human_choices']==14
    assert summary['explicit_unresolved_fields']==calc['unresolved']==3
    assert summary['automatic_results']['B160']==[160,160]
    assert summary['automatic_results']['C104']==[104,104]
    assert coverage['engineering_scenarios']==160 and coverage['workflow_scenarios']==104
    assert coverage['discovery_candidates']==421 and coverage['base_review_fields']==1263
    assert summary['A_axis_counts']=={'journal':145,'subject':110,'author':166}
    assert summary['journal_three_conditions']['yes']==calc['discovery']['journal']['joint']['yes']==137
    assert summary['author_membership']['confirmed']==calc['discovery']['author']['membership']['yes']==156
    assert summary['strict_topic_relevance']['yes']==calc['discovery']['subject']['membership']['yes']==78
    assert summary['broad_topic_relevance']['yes']==calc['broad_topic']['yes']==104
    for phase in ['base','broad']:
        initial=calc['agreement'][phase]['initial'];accepted=calc['agreement'][phase]['accepted_pre_human']
        assert summary['raw_agreement'][phase]==[initial['agree'],initial['total']]
        assert summary['post_supplement_agreement'][phase]==[accepted['agree'],accepted['total']]
    for row in load('results/agreement_history.json')['base']:
        a,b=[score_results.keyed(load(p)['answers']) for p in row['input_files']]
        assert len(a)==len(b)==1263
        assert row['comparison']==score_results.agreement(a,b)
    assert load('results/agreement_history.json')['broad']==calc['agreement']['broad']
    for file,key in [('results/automatic_summary.json','run_evidence'),('provenance/single_version_validation.json','files')]:
        for row in load(file)[key]:
            assert sha(ROOT/'results'/row['path'])==row['sha256'],row['path']
    for row in load('provenance/export_mapping.json')['files']:
        assert sha(ROOT/row['released_path'])==row['released_sha256'],row['released_path']
    for row in load('provenance/release_projection.json')['answers']:
        assert sha(ROOT/row['path'])==row['released_file_sha256'],row['path']
        assert len(load(row['path'])['answers'])==row['answer_count']
        assert row['answer_objects_preserved']
    for p in ['results/discovery_statistics.json','results/broad_statistics.json']:
        d=load(p);assert sha(ROOT/d['reference_file'])==d['reference_sha256']
    ref=load('data/reference.json')
    for phase in ['base','broad']:
        assert sha(ROOT/('data/'+phase+'_reference.json'))==ref[phase+'_reference_file_sha256']
    assert all(c['task']=='A' for c in load('data/cases.json')['cases'])
    assert all(a['question_id'].startswith('A-') for a in ref['answers'])
    count=0
    for p in ROOT.rglob('*'):
        if not p.is_file() or '.git' in p.parts or '__pycache__' in p.parts:continue
        if p.suffix not in ['.md','.txt','.json','.py','.cff']:continue
        content=p.read_text();count+=1
        if p.suffix=='.py':ast.parse(content,filename=str(p))
        if p.suffix=='.md':
            for link in re.findall(r'\]\(([^)]+)\)',content):
                if '://' in link or link.startswith('#'):continue
                assert (p.parent/link.split('#')[0]).exists(),link
    readme=(ROOT/'README.md').read_text()
    assert '| Engineering checks | 160/160 |' in readme
    assert '| Persistent workflows | 104/104 |' in readme
    assert '1,225/1,263' in readme and '1,251/1,263' in readme
    assert 'private during manuscript preparation' not in readme
    print(json.dumps({'consistent':True,'discovery_candidates':421,'reference_fields':1373,
                      'engineering_passed':160,'workflow_passed':104,'review_answers_changed':False,
                      'checked_text_files':count,'source_mappings_verified':True,
                      'scope_and_status':status_checks}))
if __name__=='__main__':main()
