#!/usr/bin/env python3
"""Validate current scope and state by joining actual identities and evidence."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent
def read(name): return json.loads((ROOT/name).read_text())
def unique(rows,key):
    result={r[key]:r for r in rows}
    assert len(result)==len(rows), 'Duplicate '+key
    return result
def resolve(ref):
    value=read(ref['path'])
    for part in ref['pointer'].split('/')[1:]:
        part=part.replace('~1','/').replace('~0','~')
        value=value[int(part)] if isinstance(value,list) else value[part]
    return value
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def canon(value): return json.dumps(value,sort_keys=True,separators=(',',':'))

def check():
    definition=read('protocols/release_definition.json')
    product=read('provenance/product_snapshot.json')['product_baseline']['commit']
    assert definition['status']=='current_publication_scope'
    assert definition['product_commit']==product and definition['product_schema']==22
    cases=unique(read('data/cases.json')['cases'],'case_id')
    candidates=unique(read('data/discovery_candidates.json'),'case_id')
    assert cases.keys()==candidates.keys() and all(r['task']=='A' for r in cases.values())
    base={q['question_id'] for c in cases.values() for q in c['questions']}
    assert len(base)==sum(len(c['questions']) for c in cases.values())==3*len(cases)
    for cid,c in cases.items():
        assert {q['question_id'] for q in c['questions']}=={cid+':'+f for f in ['membership','date','research_eligibility']}
    subjects={k for k,r in candidates.items() if r['axis']=='subject'}
    broad={k+':broad_membership' for k in subjects}
    reference=unique(read('data/reference.json')['answers'],'question_id')
    assert reference.keys()==base|broad
    unresolved={k for k,r in reference.items() if r['label']=='uncertain'}
    assert {r['question_id'] for r in read('data/unresolved_items.json')}==unresolved
    axes=dict(Counter(r['axis'] for r in candidates.values()))
    discovery=definition['discovery']
    assert discovery=={'candidates':len(cases),'axis_counts':axes,
        'base_question_fields':len(base),'broad_question_fields':len(broad),
        'reference_fields':len(reference),
        'human_choices':sum(len(read('data/reviews/human_'+p+'.json')['answers']) for p in ['base','broad']),
        'unresolved_question_ids':discovery['unresolved_question_ids']}
    assert set(discovery['unresolved_question_ids'])==unresolved
    for phase,fields in [('base',base),('broad',broad)]:
        for prefix in ['', 'initial/']:
            for reviewer in ['codex','deepseek']:
                assert unique(read('data/reviews/'+prefix+reviewer+'_'+phase+'.json')['answers'],'question_id').keys()==fields
    sampling=read('data/sampling.json')
    assert sampling['schema']=='evaluation-current-sampling-v1'
    assert sampling['A_evaluated_panel_count']==len(cases) and sampling['A_counts_by_axis']==axes
    assert sampling['base_questions_per_reviewer']==len(base)
    assert sampling['broad_questions_per_reviewer']==len(broad)
    assert sampling['combined_reference_fields']==len(reference)
    assert set(sampling['unresolved_question_ids'])==unresolved
    assert sampling['reference_status']=='human_adjudication_complete_three_unresolved_fields_retained'
    assert unique(sampling['A_inclusion_probabilities'],'case_id').keys()==cases.keys()
    # Current sampling may describe only the published tasks and fields.
    assert {k for k in sampling if k.startswith('B_')}=={'B_engineering_cases'}

    selected=unique(read('data/selected_units.json'),'case_id')
    events=read('data/exclusions.json')['records']; groups=defaultdict(list)
    for i,r in enumerate(events):groups[r['case_id']].append(i)
    assert set(groups)<=selected.keys() and selected.keys()-groups.keys()==cases.keys()
    screening=read('data/screening_current.json')
    expected_counts={'selected_candidates':len(selected),'retained_candidates':len(cases),
        'excluded_candidates':len(groups),'exclusion_events':len(events),
        'candidates_with_multiple_events':sum(len(v)>1 for v in groups.values())}
    assert definition['screening']==expected_counts
    assert {k:screening[k] for k in expected_counts}==expected_counts
    screened=unique(screening['candidates'],'case_id');assert screened.keys()==groups.keys()
    for cid,indices in groups.items():
        assert screened[cid]['event_indices']==indices
        assert screened[cid]['event_count']==len(indices)
        assert screened[cid]['stages']==[events[i]['stage'] for i in indices]

    bspec=read('harness/config/task_b_cases.json')
    bcases=unique(bspec['cases'],'case_id')
    assert bspec['status']=='current_definitions_with_separate_observed_status'
    raw_b=read(bspec['source_definition'])
    assert unique(raw_b['cases'],'case_id').keys()==bcases.keys()
    status=read('results/execution_status.json')
    assert status['product_commit']==product and status['product_schema']==22
    adoption=read(status['adoption_evidence'])
    assert adoption['all_required_product_executions_complete'] and adoption['all_listed_checks_passed']
    bobs=unique(read('results/runs/b160-001/observations.json')['cases'],'case_id')
    brows=unique(status['B'],'case_id');assert brows.keys()==bcases.keys()==bobs.keys()
    for cid,row in brows.items():
        obs=resolve(row['observation']);current=resolve(row['definition']);old=resolve(row['source_definition'])
        assert obs==bobs[cid] and current==bcases[cid] and old['case_id']==cid
        assert row['execution_status']==obs['status']=='executed'
        assert row['passed'] is obs['passed'] is True
        assert canon(obs['observed'])==canon(obs['expected'])==canon(current['expected'])
        expected_current={k:v for k,v in old.items() if k not in ['phase','execution_status']}
        assert {k:v for k,v in current.items() if k not in ['source_definition','observed_status']}==expected_current
        assert resolve(current['source_definition'])==old and resolve(current['observed_status'])==row
        assert row['family']==obs['family']==current['family']
    bcounts=dict(Counter(r['family'] for r in bobs.values()))
    assert definition['engineering']=={'cases':len(bobs),'family_counts':bcounts}
    assert bspec['counts']==bcounts and sampling['B_engineering_cases']==len(bobs)

    cr=read('results/runs/c-retained-001/observations.json')['results']
    cc=read('results/runs/c-current-001/observations.json')['cases']
    cobs=unique(cr+cc,'case_id');crows=unique(status['C'],'case_id')
    assert crows.keys()==cobs.keys()
    for cid,row in crows.items():
        obs=resolve(row['observation']);assert obs==cobs[cid]
        assert row['execution_status']==obs['status'] and obs['status'] in ['executed','completed']
        assert row['passed'] is obs['complete_success'] is True
        if 'checks' in obs:
            assert obs['checks'] and all(c['passed'] for c in obs['checks'])
        else:
            assert not obs['missing_required_steps'] and obs['invariants']
            assert all(v['status']=='pass' for v in obs['invariants'].values())
    ccounts=dict(Counter(r['family'] for r in crows.values()))
    assert definition['workflows']=={'scenarios':len(cobs),'family_counts':ccounts}
    assert all(v==4 for v in ccounts.values()) and sampling['C_workflow_cases']==len(cobs)
    assert adoption['automatic_B160_passed']==len(bobs) and adoption['automatic_C104_passed']==len(cobs)
    coverage=read('harness/protocol/workflow_coverage.json')
    assert coverage['status']=='current_release_coverage'
    assert coverage['targets']=={'a_candidates':len(cases),'a_questions_per_rater':len(base),
        'broad_topic_questions_per_rater':len(broad),'total_main_judgments_per_ai':len(reference),
        'b_product_cases':len(bobs),'b_families':len(bcounts),
        'c_scenarios':len(cobs),'c_families':len(ccounts)}
    assert unique(coverage['B'],'case_id').keys()==bobs.keys()
    for row in coverage['B']:
        assert resolve(row['definition'])==bcases[row['case_id']]
        assert resolve(row['observed_status'])==brows[row['case_id']]
    ccov=unique(coverage['C'],'scenario_id');assert ccov.keys()==cobs.keys()
    families=unique(coverage['new_C_families'],'family')
    for cid,row in ccov.items():
        assert resolve(row['observed_status'])==crows[cid]
        obs=cobs[cid]
        if 'planned_variant' in obs:
            assert row['planned_variant']==obs['planned_variant']==families[row['family']]['variants'][obs['variant']-1]
        else:
            assert row['fixture_id']==obs['fixture_id'] and row['invariant_names']==obs['applicable_invariants']
    for path in ['data/sampling.json','harness/config/task_b_cases.json','harness/protocol/workflow_coverage.json']:
        assert read(path)['product_commit']==product

    roster=read('data/author_roster.json');processing=read('data/author_processing_status.json')
    original_roster=read(roster['source_roster'])
    old_authors=unique(original_roster['authors'],'author_id')
    authors=unique(roster['authors'],'author_id');processed=unique(processing['authors'],'author_id')
    assert authors.keys()==old_authors.keys()==processed.keys()
    arun=read('results/runs/a-author-rebuild-001/result.json')
    assert arun['complete'] and arun['author_count']==arun['author_success_count']==len(authors)
    assert set(arun['by_author'])<=authors.keys()
    assert sum(arun['by_author'].values())==arun['observed_occurrences']
    panel=Counter(r['monitor_id'] for r in candidates.values() if r['axis']=='author')
    for aid,row in processed.items():
        assert resolve(row['processing_evidence'])==arun
        assert row['processing_status']=='success_reported_by_complete_aggregate'
        assert row['observed_occurrences']==arun['by_author'].get(aid,0)
        assert row['evaluated_candidates']==panel[aid] and row['name']==authors[aid]['name']
        assert resolve(row['source_roster'])==old_authors[aid]
        assert resolve(authors[aid]['processing_status'])==row
        assert {k:v for k,v in authors[aid].items() if k!='processing_status'}=={k:v for k,v in old_authors[aid].items() if k!='provider_binding_status'}
    assert sampling['configured_author_monitors']==sampling['author_profiles_reprocessed_successfully']==len(authors)
    assert sampling['author_monitors_represented_in_evaluated_panel']==len(panel)
    assert sampling['A_author_panel_counts']==dict(panel)
    assert processing['product_commit']==product and not processing['live_acquisition_claim']

    preparation=read('provenance/publication_preparation.json')
    assert not preparation['product_reexecuted'] and not preparation['review_answers_rejudged']
    for row in preparation['preserved_files']+preparation['original_stage_inputs']:
        assert sha(ROOT/row['path'])==row['sha256'], 'Changed preserved evidence: '+row['path']
    assert {r['path'] for r in preparation['original_stage_inputs']}==set(definition['raw_stage_inputs'])
    for p in (ROOT/'results/runs').rglob('*.json'):
        obj=json.loads(p.read_text())
        if 'product_commit' in obj:assert obj['product_commit']==product
    for section,counts,total in [('B160',bcounts,len(bobs)),('C104',ccounts,len(cobs))]:
        summary=read('results/automatic_summary.json')[section]
        assert summary['total']==summary['passed']==total
        assert {r['family']:r['total'] for r in summary['families']}==counts
        assert all(r['passed']==counts[r['family']] for r in summary['families'])
    for name in ['README.md','CITATION.cff','DATA_AVAILABILITY.md']:
        assert definition['repository_url'] in (ROOT/name).read_text()
    assert '/releases/tag/'+definition['release_tag'] in (ROOT/'CITATION.cff').read_text()
    readme=(ROOT/'README.md').read_text()
    assert '| Additional product regressions |' not in readme and '412' not in readme
    assert '**'+str(len(cases))+' candidates**' in readme
    dictionary=(ROOT/'DATA_DICTIONARY.md').read_text()
    assert f"{len(events)} historical screening events concerning {len(groups)} unique discovery candidates" in dictionary
    assert 'formal_result=false' in dictionary and 'scores_authorized=false' in dictionary
    assert 'pending_verified_profile_id' in dictionary and 'not_complete_104_workflows' in dictionary
    return {'scope_and_status_verified':True,'candidate_ids':len(cases),
        'reference_fields':len(reference),'excluded_candidates':len(groups),'exclusion_events':len(events),
        'engineering_observation_links':len(brows),'workflow_observation_links':len(crows),
        'author_processing_links':len(authors),'preserved_files':len(preparation['preserved_files'])}

if __name__=='__main__':print(json.dumps(check()))
