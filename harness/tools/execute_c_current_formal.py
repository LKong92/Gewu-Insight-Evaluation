#!/usr/bin/env python3
"""Fresh formal observations using unchanged qualified cases; final scoring remains gated."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--product-root',required=True)
    p.add_argument('--output',required=True);p.add_argument('--families',nargs='*');p.add_argument('--variants',nargs='*',type=int)
    args=p.parse_args();product=Path(args.product_root).resolve();root=Path(args.output).resolve()
    from fixed_engineering_gate import require
    execution_lock=require(product,root,__file__,filtered=bool(args.families or args.variants))
    from run_b import guard_writes,sha,save
    archive=Path(os.environ['GEWU_FIXED_ARCHIVE'])
    if product==Path(os.environ.get('GEWU_FORBIDDEN_PRODUCTION_ROOT', '/__forbidden_production__')) or not (archive/'control/baseline.json').is_file():raise ValueError('Require frozen isolated worktree')
    baseline=execution_lock['product_baseline']
    changed=[r['path'] for r in baseline['tracked_files'] if sha(product/r['path'])!=r['sha256']]
    if changed:raise ValueError('Frozen source changed')
    if root.exists():raise FileExistsError('Immutable run root exists')
    root.mkdir(parents=True);(root/'tmp').mkdir()
    save(root/'execution_authorization.json',execution_lock)
    for name in ('execute_c_current_formal.py','new_state_cases.py','remaining_state_cases.py','run_b.py'):
        (root/name).write_bytes((Path(__file__).resolve().parent/name).read_bytes())
    coverage=json.loads((archive/'protocol/workflow_coverage.json').read_text())
    save(root/'coverage_proposal.json',coverage)
    os.environ['GEWU_DATA_ROOT']=str(root/'environment');os.environ['GEWU_WORKSPACE_ROOT']=str(root/'workspace');os.environ['TMPDIR']=str(root/'tmp');tempfile.tempdir=str(root/'tmp')
    sys.dont_write_bytecode=True;sys.path.insert(0,str(product));guard_writes(root)
    from new_state_cases import Workflow,IMPLEMENTED
    selected=args.families or sorted(IMPLEMENTED)
    if not set(selected).issubset(IMPLEMENTED):raise ValueError('Unimplemented families: '+str(set(selected)-set(IMPLEMENTED)))
    results=[]
    for family in selected:
        for variant in args.variants or (1,2,3,4):
            cid='V4-'+family+'-V%02d'%variant;case_root=root/cid.removeprefix('V4-');case_root.mkdir()
            spec=next(c for c in coverage['C'] if c['scenario_id']==cid)
            save(case_root/'planned_case.json',spec);w=None
            value={'case_id':cid,'family':family,'variant':variant,'phase':'fixed_version_execution','formal_result':False,
                'planned_variant':spec['planned_variant'],'status':'not_started','complete_success':False}
            try:
                w=Workflow(case_root);w.observe('initial_state');IMPLEMENTED[family](w,variant);w.restart()
                value.update(status='executed',checks=w.checks,steps=w.steps,
                    trace_tip_sha256=w.previous,complete_success=bool(w.checks) and all(c['passed'] for c in w.checks))
            except Exception as exc:
                value.update(status='runner_error',error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
                if w:value.update(checks=w.checks,steps=w.steps)
            finally:
                if w:save(case_root/'product_operations.json',w.trace);w.close()
            save(case_root/'result.json',value);results.append(value)
            print(json.dumps({'case_id':cid,'status':value['status'],'passed':value['complete_success'],'error':value.get('error',''),
                'failed_checks':[r['invariant'] for r in value.get('checks',[]) if not r['passed']]},ensure_ascii=False),flush=True)
    report={'phase':'fixed_version_execution','formal_result':False,'product_commit':baseline['commit'],
        'total':len(results),'passed':sum(r['complete_success'] for r in results),'cases':results,
        'implemented_families':sorted(IMPLEMENTED),'pending_families':sorted({'C%02d'%i for i in range(14,27)}-set(IMPLEMENTED)),
        'source_files_verified':len(baseline['tracked_files']),'production_data_accessed':False,
        'source_sha256':{name:sha(root/name) for name in ('execute_c_current_formal.py','new_state_cases.py','remaining_state_cases.py','run_b.py')},
        'surfaces':['actual isolated product service','authenticated HTTP readback','SQLite','filesystem bytes','disposable-service restart'],
        'not_observed':['native mouse and keyboard interactions','real remote source availability in these synthetic cases']}
    save(root/'observations.json',report)
    print(json.dumps({k:report[k] for k in ('total','passed','pending_families')},ensure_ascii=False))


if __name__=='__main__':main()
