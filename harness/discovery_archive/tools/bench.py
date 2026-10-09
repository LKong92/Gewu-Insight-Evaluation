#!/usr/bin/env python3
"""Archive/validation tooling. Never imports or patches product code."""
import argparse
from collections import Counter
import datetime
import hashlib
import json
import math
from pathlib import Path
import subprocess

B = Path(__file__).resolve().parents[1]
ROOT = B.parents[1]
LABELS = ('yes', 'no', 'uncertain')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def inside(path):
    p=Path(path).resolve()
    if not p.is_relative_to(B.resolve()):
        raise ValueError('Path escapes benchmark archive')
    return p

def load(path):
    return json.loads(Path(path).read_text())

def write_new(path, obj):
    path=inside(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False)
        f.write('\n')

def baseline_check():
    baseline=load(B/'control/baseline.json')
    actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    changed=[r['path'] for r in baseline['tracked_files']
             if not (ROOT/r['path']).is_file() or sha(ROOT/r['path'])!=r['sha256']]
    current=set(filter(None,subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')))
    expected={r['path'] for r in baseline['tracked_files']}
    report={'commit':actual,'expected':baseline['commit'],'files_checked':len(expected),
            'changed':changed,'tracked_added':sorted(current-expected),'tracked_removed':sorted(expected-current)}
    report['ok']=actual==baseline['commit'] and not changed and current==expected
    return report

def validate_review(packet, review):
    human_selection=review.get('review_schema')=='human-selection-v1'
    if human_selection and review.get('reviewer')!='human':raise ValueError('Human schema requires human reviewer')
    expected=[q['question_id'] for q in packet['questions']]
    if len(expected)!=len(set(expected)):raise ValueError('Duplicate packet IDs')
    if review.get('packet_id')!=packet['packet_id']:raise ValueError('Wrong packet')
    if not isinstance(review.get('reviewer'),str) or not review['reviewer'].strip():raise ValueError('Missing reviewer')
    answers=review.get('answers')
    if not isinstance(answers,list):raise ValueError('answers is not a list')
    ids=[x.get('question_id') for x in answers if isinstance(x,dict)]
    if len(ids)!=len(answers) or len(ids)!=len(set(ids)) or set(ids)!=set(expected):
        raise ValueError('Missing, duplicate or unexpected question IDs')
    for x in answers:
        if x.get('label') not in LABELS:raise ValueError('Invalid label')
        c=x.get('confidence')
        if isinstance(c,bool) or not isinstance(c,(int,float)) or not math.isfinite(c) or not 0<=c<=1:
            raise ValueError('Invalid confidence')
        if human_selection:
            if 'rationale' in x and not isinstance(x['rationale'],str):raise ValueError('Invalid optional rationale')
            if 'evidence' in x and (not isinstance(x['evidence'],list) or not all(isinstance(e,str) and e.strip() for e in x['evidence'])):
                raise ValueError('Invalid optional evidence')
            continue
        if not isinstance(x.get('rationale'),str) or not x['rationale'].strip():raise ValueError('Missing rationale')
        if not isinstance(x.get('evidence'),list) or not x['evidence'] or not all(isinstance(e,str) and e.strip() for e in x['evidence']):
            raise ValueError('Missing evidence locator')
    return {'valid':True,'questions':len(expected),'reviewer':review['reviewer']}

def wilson(k,n):
    if not isinstance(k,int) or not isinstance(n,int) or n<0 or not 0<=k<=n:raise ValueError('Bad counts')
    if n==0:return None
    z=1.959963984540054;p=k/n;d=1+z*z/n
    center=(p+z*z/(2*n))/d
    radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [max(0.,center-radius),min(1.,center+radius)]

def summarize(labels):
    if any(x not in LABELS for x in labels):raise ValueError('Invalid labels')
    counts=Counter(labels);n=len(labels);c=counts['yes'];u=counts['uncertain'];i=counts['no']
    return {'n':n,'correct':c,'incorrect':i,'uncertain':u,
            'confirmed_correct':c/n if n else None,
            'identification_bounds':[c/n,(c+u)/n] if n else None,
            'conditional_adjudicated':c/(c+i) if c+i else None,
            'wilson_confirmed':wilson(c,n),
            'wilson_sensitivity_envelope':[wilson(c,n)[0],wilson(c+u,n)[1]] if n else None}

def finite_population_interval(k,n,N,alpha=.05):
    """Equal-tail hypergeometric inversion for a fixed frame sampled without replacement."""
    if any(isinstance(x,bool) or not isinstance(x,int) for x in (k,n,N)) or not 0<=k<=n<=N or not 0<alpha<1:
        raise ValueError('Invalid finite population counts')
    if n==0:return None
    if n==N:return [k/N,k/N]
    logden=math.log(math.comb(N,n))
    def tail(K,upper):
        lo=max(0,n-(N-K));hi=min(n,K)
        vals=range(max(lo,k),hi+1) if upper else range(lo,min(hi,k)+1)
        return min(1.,sum(math.exp(math.log(math.comb(K,x))+math.log(math.comb(N-K,n-x))-logden) for x in vals))
    lo,hi=k,N-n+k
    while lo<hi:
        mid=(lo+hi)//2
        if tail(mid,True)>=alpha/2:hi=mid
        else:lo=mid+1
    lower=lo
    lo,hi=k,N-n+k
    while lo<hi:
        mid=(lo+hi+1)//2
        if tail(mid,False)>=alpha/2:lo=mid
        else:hi=mid-1
    return [lower/N,lo/N]

def agreement(a,b):
    if len(a)!=len(b) or any(x not in LABELS for x in a+b):raise ValueError('Unmatched labels')
    n=len(a)
    if not n:return {'n':0,'agreement':None,'kappa':None}
    pa=sum(x==y for x,y in zip(a,b))/n
    ca=Counter(a);cb=Counter(b);pe=sum(ca[x]*cb[x] for x in LABELS)/(n*n)
    return {'n':n,'agreement':pa,'kappa':(pa-pe)/(1-pe) if pe<1 else None,
            'counts':{x:{y:sum(l==x and r==y for l,r in zip(a,b)) for y in LABELS} for x in LABELS}}

def select(frame,n,seed):
    ids=[x['unit_id'] for x in frame]
    if len(ids)!=len(set(ids)):raise ValueError('Frame unit IDs must be unique')
    if n<0:raise ValueError('Negative n')
    return sorted(frame,key=lambda x:(hashlib.sha256((seed+'\0'+x['unit_id']).encode()).hexdigest(),x['unit_id']))[:n]

def seal(name,paths):
    if name not in ('CALIBRATION-R1','PROTOCOL-DRAFT-0.1'):
        raise ValueError('Formal locking is not enabled before calibration and prerequisites')
    if not baseline_check()['ok']:raise ValueError('Frozen product has changed')
    items=[]
    for raw in paths:
        p=inside(B/raw)
        if not p.is_file():raise ValueError('Lock requires explicit files')
        items.append({'path':str(p.relative_to(B)),'sha256':sha(p),'bytes':p.stat().st_size})
    lock={'name':name,'kind':'local_hash_manifest_not_external_preregistration','created_at':utc(),'files':items}
    path=B/'control'/f'{name}.lock.json'
    write_new(path,lock)
    return {'path':str(path),'sha256':sha(path),'files':len(items)}

def verify_lock(path):
    lock=load(inside(path));bad=[]
    for x in lock['files']:
        p=inside(B/x['path'])
        if not p.is_file() or sha(p)!=x['sha256']:bad.append(x['path'])
    return {'ok':not bad,'changed':bad,'files':len(lock['files'])}

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='cmd',required=True)
    s.add_parser('baseline')
    q=s.add_parser('validate-review');q.add_argument('packet');q.add_argument('review')
    q=s.add_parser('seal');q.add_argument('name');q.add_argument('paths',nargs='+')
    q=s.add_parser('verify-lock');q.add_argument('path')
    s.add_parser('status')
    a=p.parse_args()
    if a.cmd=='baseline':r=baseline_check()
    elif a.cmd=='validate-review':r=validate_review(load(inside(B/a.packet)),load(inside(B/a.review)))
    elif a.cmd=='seal':r=seal(a.name,a.paths)
    elif a.cmd=='verify-lock':r=verify_lock(B/a.path)
    else:r=load(B/'control/STATUS.json')
    print(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False))
    if r.get('ok') is False:raise SystemExit(1)

if __name__=='__main__':main()
