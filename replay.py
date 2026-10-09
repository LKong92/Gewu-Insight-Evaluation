#!/usr/bin/env python3
"""Prepare and run released synthetic tests against a verified source snapshot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2)+'\n')
def within(path, parent):
    return path == parent or parent in path.parents

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product-source', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--task', choices=['B','C'], required=True)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--production-root', help='Optional existing production checkout to forbid')
    args=parser.parse_args()
    source=Path(args.product_source).expanduser().resolve()
    output=Path(args.output_root).expanduser().resolve()
    forbidden=Path(args.production_root).expanduser().resolve() if args.production_root else None
    if output.exists() or within(output, source) or within(source, output) or within(output, ROOT) or within(ROOT, output):
        raise ValueError('Output must be a new directory separate from source and release.')
    if forbidden and any(within(x,forbidden) or within(forbidden,x) for x in [source,output]):
        raise ValueError('Production checkout is forbidden.')
    if any((source/x).exists() for x in ['data/paper_monitor.sqlite','data/Associated Files','metadata']):
        raise ValueError('Use a source-only snapshot, not an active research workspace.')
    manifest=json.loads((ROOT/'provenance/product_snapshot.json').read_text())
    baseline=manifest['product_baseline']
    for row in baseline['tracked_files']:
        path=source/row['path']
        if not within(path.resolve(),source) or path.is_symlink() or digest(path)!=row['sha256']:
            raise ValueError('Frozen source mismatch: '+row['path'])
    if sys.platform!='darwin' and not args.prepare_only:
        raise RuntimeError('Execution is supported on macOS; cross-platform equivalence is not claimed.')
    output.mkdir(parents=True)
    product=output/'product';product.mkdir()
    for row in baseline['tracked_files']:
        dest=product/row['path'];dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/row['path'],dest)
    for folder in ['tools','config','protocol','fixtures']:
        shutil.copytree(ROOT/'harness'/folder,output/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    manifest['product_root']=str(product)
    write(output/'control/PRODUCT_SNAPSHOT.json',manifest)
    write(output/'control/baseline.json',{'product_baseline':baseline,'purpose':'Isolated publication-replay preparation'})
    locked=[]
    for folder in ['tools','config','protocol','fixtures']:
        for file in sorted((output/folder).rglob('*')):
            if file.is_file():locked.append({'path':str(file.relative_to(output)),'sha256':digest(file)})
    write(output/'control/FIXED_DESIGN.json',{'product_commit':baseline['commit'],'snapshot_sha256':digest(output/'control/PRODUCT_SNAPSHOT.json'),'files':locked,'purpose':'Publication replay of released synthetic cases; not a replacement historical result.'})
    (output/'runs').mkdir()
    write(output/'PREPARATION.json',{'source_files_verified':len(baseline['tracked_files']),'product_commit':baseline['commit'],'task':args.task,'prepare_only':args.prepare_only,'python':sys.version,'historical_observations_overwritten':False})
    if args.prepare_only:
        print(json.dumps({'prepared':True,'source_files_verified':len(baseline['tracked_files'])}));return
    env=os.environ.copy()
    env['GEWU_FIXED_ARCHIVE']=str(output)
    env['PYTHONDONTWRITEBYTECODE']='1'
    if forbidden:env['GEWU_FORBIDDEN_PRODUCTION_ROOT']=str(forbidden)
    scripts=['execute_b_formal.py'] if args.task=='B' else ['execute_c_retained_formal.py','execute_c_current_formal.py']
    for script in scripts:
        name={'execute_b_formal.py':'b160','execute_c_retained_formal.py':'c-retained','execute_c_current_formal.py':'c-current'}[script]
        cmd=[sys.executable,str(output/'tools'/script),'--product-root',str(product),'--output',str(output/'runs'/name)]
        if args.task=='B':cmd+=['--cases',str(output/'config/task_b_cases.json')]
        subprocess.run(cmd,env=env,cwd=output,check=True)
    rows=[]
    for script in scripts:
        name={'execute_b_formal.py':'b160','execute_c_retained_formal.py':'c-retained','execute_c_current_formal.py':'c-current'}[script]
        d=json.loads((output/'runs'/name/'observations.json').read_text())
        rows.append({'run':name,'total':d['total'],'passed':d['passed']})
    result={'task':args.task,'product_commit':baseline['commit'],'runs':rows,'all_passed':all(x['total']==x['passed'] for x in rows),'scope':'New packaging replay; historical records unchanged.'}
    write(output/'REPLAY_RESULT.json',result)
    print(json.dumps(result))
    if not result['all_passed']:sys.exit(1)

if __name__=='__main__':main()
