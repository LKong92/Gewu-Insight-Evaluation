#!/usr/bin/env python3
"""Reconstruct the final reference and recompute retained benchmark statistics."""
from collections import Counter
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def load(name):return json.loads((ROOT/name).read_text())
def keyed(rows):
    out={r['question_id']:r for r in rows}
    assert len(out)==len(rows),'Duplicate question ID'
    return out
def agreement(a,b):
    assert set(a)==set(b)
    n=len(a);hits=sum(a[k]['label']==b[k]['label'] for k in a)
    ca=Counter(x['label'] for x in a.values());cb=Counter(x['label'] for x in b.values())
    expected=sum(ca[k]*cb[k] for k in set(ca)|set(cb))/(n*n)
    return {'agree':hits,'total':n,'rate':hits/n,'kappa':(hits/n-expected)/(1-expected) if expected<1 else None}
def proportions(rows,field):
    n=len(rows);counts=Counter(r['field_labels'][field] for r in rows)
    weights={v:sum(1/r['inclusion_probability'] for r in rows if r['field_labels'][field]==v) for v in ['yes','no','uncertain']}
    w=sum(weights.values())
    return {'total':n,'yes':counts['yes'],'no':counts['no'],'uncertain':counts['uncertain'],
            'identification_bounds':[counts['yes']/n,(counts['yes']+counts['uncertain'])/n],
            'weighted_bounds':[weights['yes']/w,(weights['yes']+weights['uncertain'])/w]}
def main():
    final=keyed(load('data/reference.json')['answers']);assert len(final)==1373
    agreements={};human_all={};merged={}
    for phase,expected,raw_agree,accepted_agree in [('base',1263,1225,1251),('broad',110,100,108)]:
        a=keyed(load('data/reviews/codex_'+phase+'.json')['answers']);b=keyed(load('data/reviews/deepseek_'+phase+'.json')['answers'])
        assert len(a)==len(b)==expected
        h=keyed(load('data/reviews/human_'+phase+'.json')['answers']);human_all.update(h)
        assert set(h)=={k for k in a if a[k]['label']!=b[k]['label']},'Human choices must match residual disagreements'
        for k in a:
            label=h[k]['label'] if k in h else a[k]['label']
            assert final[k]['label']==label,'Reference merge mismatch: '+k
            merged[k]=label
        firsta=keyed(load('data/reviews/initial/codex_'+phase+'.json')['answers'])
        firstb=keyed(load('data/reviews/initial/deepseek_'+phase+'.json')['answers'])
        agreements[phase]={'initial':agreement(firsta,firstb),'accepted_pre_human':agreement(a,b)}
        assert agreements[phase]['initial']['agree']==raw_agree
        assert agreements[phase]['accepted_pre_human']['agree']==accepted_agree
    assert set(merged)==set(final) and len(human_all)==14
    assert sum(v=='uncertain' for v in merged.values())==3
    cases=load('data/cases.json')['cases'];assert len(cases)==421
    questions={q['question_id']:q for c in cases for q in c['questions']}
    assert len(questions)==1263 and all(c['task']=='A' for c in cases)
    assert all(k.startswith('A-') for k in final)
    for qid,q in questions.items():assert merged[qid] in q['allowed_labels']
    rows=load('data/discovery_candidates.json');assert len(rows)==421
    A={}
    for r in rows:
        for field in ['membership','date','research_eligibility']:
            assert r['field_labels'][field]==merged[r['case_id']+':'+field]
        labels=list(r['field_labels'].values());joint='no' if 'no' in labels else 'uncertain' if 'uncertain' in labels else 'yes'
        assert joint==r['joint_label'];r['field_labels']['joint']=joint
    for axis in ['journal','subject','author']:
        panel=[r for r in rows if r['axis']==axis]
        A[axis]={field:proportions(panel,field) for field in ['membership','date','research_eligibility','joint']}
    assert [A[x]['membership']['total'] for x in ['journal','subject','author']]==[145,110,166]
    assert A['journal']['joint']['yes']==137 and A['author']['membership']['yes']==156 and A['subject']['membership']['yes']==78
    broad=Counter(merged[r['case_id']+':broad_membership'] for r in rows if r['axis']=='subject')
    assert broad=={'yes':104,'no':5,'uncertain':1}
    for r in rows:
        if r['axis']=='subject' and r['field_labels']['membership']=='yes':assert merged[r['case_id']+':broad_membership']=='yes'
    b=load('results/runs/b160-001/observations.json');spec=load('harness/config/task_b_cases.json')
    expected={r['case_id']:r['expected'] for r in spec['cases']}
    assert len(b['cases'])==160 and set(expected)=={r['case_id'] for r in b['cases']}
    for r in b['cases']:assert r['expected']==expected[r['case_id']] and r['passed']==(r['observed']==r['expected']) and r['passed']
    cr=load('results/runs/c-retained-001/observations.json')['results'];cc=load('results/runs/c-current-001/observations.json')['cases']
    assert len(cr)==len(cc)==52 and len({r['case_id'] for r in cr+cc})==104
    for r in cr:
        assert r['complete_success'] and not r['missing_required_steps']
        assert all(v['status']=='pass' for v in r['invariants'].values())
    for r in cc:assert r['complete_success'] and r['checks'] and all(x['passed'] for x in r['checks'])
    selected=load('data/selected_units.json');excluded=load('data/exclusions.json')['records']
    selected_ids={r['case_id'] for r in selected};excluded_ids={r['case_id'] for r in excluded}
    assert len(selected)==493 and len(excluded_ids)==72
    assert selected_ids-excluded_ids=={r['case_id'] for r in rows}
    product=load('provenance/product_snapshot.json')['product_baseline']['commit']
    for path in (ROOT/'results/runs').rglob('*.json'):
        d=json.loads(path.read_text())
        if 'product_commit' in d:assert d['product_commit']==product
    regressions=load('results/runs/additional-python-001/result.json')
    assert regressions['tests']==412 and regressions['passed'] and not any(regressions[k] for k in ['failures','errors','skipped'])
    result={'verified':True,'product_commit':product,'discovery':A,'broad_topic':dict(broad),'agreement':agreements,'reference_fields':len(final),'human_choices':len(human_all),'unresolved':3,'B160_passed':len(b['cases']),'C104_passed':len(cr)+len(cc),'screened_units':len(excluded_ids),'additional_regressions_reported_separately':regressions['tests']}
    print(json.dumps(result,indent=2));return result
if __name__=='__main__':main()
