#!/usr/bin/env python3
"""Fresh formal observations using unchanged qualified cases; final scoring remains gated."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--product-root',required=True)
    p.add_argument('--output',required=True);p.add_argument('--families',nargs='*');p.add_argument('--variants',type=int,nargs='*')
    a=p.parse_args();product=Path(a.product_root).resolve();root=Path(a.output).resolve()
    from fixed_engineering_gate import require
    execution_lock=require(product,root,__file__,filtered=bool(a.families or a.variants))
    from run_b import guard_writes,sha,save
    if root.exists():raise FileExistsError('Immutable run root exists')
    archive=Path(os.environ['GEWU_FIXED_ARCHIVE'])
    if product==Path(os.environ.get('GEWU_FORBIDDEN_PRODUCTION_ROOT', '/__forbidden_production__')) or not (archive/'control/baseline.json').is_file():
        raise ValueError('Require isolated benchmark worktree')
    baseline=execution_lock['product_baseline']
    changed=[r['path'] for r in baseline['tracked_files'] if sha(product/r['path'])!=r['sha256']]
    if changed:raise ValueError('Frozen source changed')
    root.mkdir(parents=True);(root/'tmp').mkdir()
    save(root/'execution_authorization.json',execution_lock)
    scriptdir=Path(__file__).resolve().parent;specdir=scriptdir.parent
    for name in ('execute_c_retained_formal.py','retained_state_cases.py','state_support.py','run_b.py'):
        (root/name).write_bytes((scriptdir/name).read_bytes())
    (root/'requirements.json').write_bytes((specdir/'config/retained_c_requirements.json').read_bytes())
    os.environ['GEWU_DATA_ROOT']=str(root/'environment');os.environ['GEWU_WORKSPACE_ROOT']=str(root/'workspace');os.environ['TMPDIR']=str(root/'tmp')
    tempfile.tempdir=str(root/'tmp');sys.dont_write_bytecode=True;sys.path.insert(0,str(product))
    guard_writes(root)
    import state_support as support
    support.RUN_ROOT=root
    import retained_state_cases as state
    families=support.read_json(root/'requirements.json')['families']
    profile=support.Profile(run_id=root.name,root=root)
    for directory in (profile.library,profile.spaces,profile.publications,profile.associated,profile.pdfs,
        profile.cache/'pdf_thumbs',profile.cache/'web',profile.config,profile.logs,profile.raw_network/'blobs',
        profile.outputs,profile.traces,profile.reports,profile.trash):directory.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(product/'config/journals.json',profile.config/'journals.json')
    support.write_json_new(profile.marker,{'run_id':profile.run_id,'root':str(root),'phase':'fixed_version_execution'})
    structure=state.require_state_variant_structure(families,fixture_count=4)
    save(root/'structural_coverage_audit.json',structure)
    results=[]
    for family in families:
        if a.families and family['id'][:3] not in a.families:continue
        for variant in range(4):
            if a.variants and variant+1 not in a.variants:continue
            case_id='V4-'+family['id'][:3]+'-V%02d'%(variant+1)
            try:
                value=state.run_fixture(profile,family,variant,0,0)
                value.update(case_id=case_id,phase='fixed_version_execution',formal_result=False)
            except Exception as exc:
                value={'case_id':case_id,'phase':'fixed_version_execution','formal_result':False,'complete_success':False,
                    'status':'runner_error','error':type(exc).__name__+': '+str(exc),'traceback':traceback.format_exc()}
            results.append(value)
            save(root/(case_id.removeprefix('V4-')+'.json'),value)
            print(json.dumps({'case_id':case_id,'passed':value['complete_success'],'status':value['status'],'error':value.get('error','')},ensure_ascii=False),flush=True)
    report={'phase':'fixed_version_execution','formal_result':False,'scope':'retained_52_only',
        'not_complete_104_workflows':True,'product_commit':baseline['commit'],'source_files_verified':len(baseline['tracked_files']),
        'total':len(results),'passed':sum(r['complete_success'] for r in results),'results':results,
        'production_data_accessed':False,'original_app_restarted':False,
        'observation_surfaces':['authenticated workspace HTTP payloads','SQLite state','filesystem bytes','restart of disposable server'],
        'not_observed':['native desktop interactions','real Finder/Preview usability'],
        'fixture_adaptations':['legacy source SQL, no historical database','safe disposable Trash sink in place of OS Trash','ephemeral authenticated server']}
    save(root/'observations.json',report)
    print(json.dumps({k:report[k] for k in ('scope','total','passed')},ensure_ascii=False))


if __name__=='__main__':main()
