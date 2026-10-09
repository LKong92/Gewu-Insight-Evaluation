from pathlib import Path
from contextlib import ExitStack
from collections import Counter
from unittest.mock import patch
import datetime as dt, hashlib, json, os, shutil, sys, tempfile, traceback
R=Path(os.environ['GEWU_FIXED_ARCHIVE'])
P=R/'product';root=R/'runs/a-author-rebuild-001'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text())
def write(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(v,f,ensure_ascii=False,indent=2,default=str);f.write('\n')
sys.dont_write_bytecode=True;sys.path.insert(0,str(R/'tools'))
from fixed_engineering_gate import verify
from source_transport import SourceTransport,SCHEMA
_,snap=verify(R)
catalog=read(R/'control/AUTHOR_INPUT_CATALOG.json');assert len(catalog['authors'])==24
root.mkdir(exist_ok=False)
for d in ('workspace','tmp','sources/blobs'):(root/d).mkdir(parents=True)
shutil.copy2(__file__,root/'runner.py')
events=[];lineage=[];tapes={}
for author in catalog['authors']:
    source=Path(author['source_root'])
    if source not in tapes:tapes[source]={a['attempt_id']:a for a in [json.loads(l) for l in (source/'attempts.jsonl').read_text().splitlines() if l.strip()]}
    for page in author['successful_raw_pages']:
        original=tapes[source][page['attempt_id']];a=dict(original);a['attempt_id']=len(events)+1
        for part in ('request','response'):
            digest=a[part]['body_sha256'];src=source/'blobs'/digest;assert sha(src)==digest
            dst=root/'sources/blobs'/digest
            if not dst.exists():shutil.copy2(src,dst)
        events.append(a);lineage.append({'new_attempt_id':a['attempt_id'],'author_id':author['author_id'],'original_source':str(source),'original_attempt_id':original['attempt_id'],'original_started_at':original.get('started_at'),'response_sha256':a['response']['body_sha256']})
raw=''.join(json.dumps(a,ensure_ascii=False,separators=(',',':'))+'\n' for a in events).encode()
(root/'sources/attempts.jsonl').write_bytes(raw)
write(root/'sources/manifest.json',{'schema':SCHEMA,'archive_closed':True,'attempts':len(events),'attempts_sha256':hashlib.sha256(raw).hexdigest(),'derived_replay_input':True,'not_a_new_live_capture':True,'selected_successful_profile_pages_only':True,'purpose':'Rerun native author parsing, storage and UI on latest version from all 24 captured profile inputs; does not measure live service availability.','capture_lineage':'source_lineage.json'})
write(root/'sources/source_lineage.json',lineage)
config=read(R/'config/discovery_config_fixed.json');bindings=read(R/'config/author_bindings_verified_006.json')
write(root/'input_configuration.json',config);write(root/'author_bindings.json',bindings)
write(root/'DESIGN.json',{'product_commit':snap['product_baseline']['commit'],'product_snapshot_sha256':sha(R/'control/PRODUCT_SNAPSHOT.json'),'catalog_sha256':sha(R/'control/AUTHOR_INPUT_CATALOG.json'),'runner_sha256':sha(root/'runner.py'),'inputs_locked_before_run':True,'old_UI_outputs_imported':False,'source_bytes_only':True,'author_count':24,'offline_transport_only':True,'sleep_elided_no_runtime_performance_claim':True,'no_sampling_this_run':True})
os.environ['GEWU_DATA_ROOT']=str(root/'environment');os.environ['GEWU_WORKSPACE_ROOT']=str(root/'workspace');os.environ['TMPDIR']=str(root/'tmp');tempfile.tempdir=str(root/'tmp')
for key in ('OPENALEX_API_KEY','OPENALEX_MAILTO','CROSSREF_MAILTO','SEMANTIC_SCHOLAR_API_KEY','NCBI_API_KEY','GEWU_CACHE_ROOT','GEWU_STANDALONE'):os.environ.pop(key,None)
sys.path.insert(0,str(P))
from run_a import NativeCollector
from discovery_guard import guard_discovery
guard_discovery(root,allow_live=False)
collector=None
result={'product_commit':snap['product_baseline']['commit'],'mode':'offline_latest_product_reprocessing_of_24_public_author_profiles','live_acquisition_claim':False,'old_outcomes_reused':False,'complete':False,'AI_dispatched':False}
try:
    with ExitStack() as stack:
        stack.enter_context(patch('requests.sessions.get_netrc_auth',return_value=None));stack.enter_context(patch('time.sleep',return_value=None))
        transport=stack.enter_context(SourceTransport(root/'sources','replay'))
        collector=NativeCollector(P,root,config,'author',bindings)
        collector.run();collector.persist_observations()
        result['source_replay']=transport.assert_consumed()
        summaries=read(root/'native_summary.json')
        result.update(author_count=len(summaries),author_success_count=sum(a['result'].get('status')=='success' for a in summaries),observed_occurrences=len(collector.occurrences),by_author=dict(Counter(a['monitor_id'] for a in collector.occurrences)))
        result['complete']=result['author_success_count']==24
except Exception as e:
    result.update(error=repr(e),traceback=traceback.format_exc())
    if collector and not (root/'occurrences.json').exists():collector.persist_observations()
finally:
    if collector:collector.h.close()
    result['product_snapshot_unchanged']=all(sha(P/v['path'])==v['sha256'] for v in snap['product_baseline']['tracked_files'])
    write(root/'result.json',result)
print(json.dumps(result,ensure_ascii=False),flush=True)
if not result['complete']:raise SystemExit(1)
