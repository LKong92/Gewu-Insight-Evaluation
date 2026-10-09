from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
import argparse,calendar,copy,datetime as dt,hashlib,json,os,sys,tempfile,traceback
R=Path(os.environ['GEWU_FIXED_ARCHIVE'])
OLD=R.parent/'fixed-20261005-001';P=R/'product'
sys.dont_write_bytecode=True;sys.path.insert(0,str(R/'tools'))
from fixed_engineering_gate import verify,sha
from run_a import NativeCollector,write
from source_transport import SourceTransport
import source_transport
from clock_tape import ClockTape
from discovery_guard import guard_discovery
ap=argparse.ArgumentParser();ap.add_argument('axis',choices=['journal','subject']);ap.add_argument('--attempt',default='001');args=ap.parse_args()
_,snap=verify(R);axis=args.axis;original=OLD/('runs/a-'+axis+'-001');root=R/('runs/a-'+axis+'-rebuild-'+args.attempt)
assert not root.exists();root.mkdir()
for d in ('tmp','workspace'):(root/d).mkdir()
(root/'workspace/config').mkdir()
(root/'workspace/config/journals.json').write_bytes((P/'config/journals.json').read_bytes())
config=json.loads((R/'config/discovery_config_fixed.json').read_text());write(root/'base_input_configuration.json',config)
(root/'runner.py').write_bytes(Path(__file__).read_bytes())
write(root/'DESIGN.json',{'product_commit':snap['product_baseline']['commit'],'snapshot_sha256':sha(R/'control/PRODUCT_SNAPSHOT.json'),'runner_sha256':sha(root/'runner.py'),'source_manifest':str(original/'sources/manifest.json'),'source_manifest_sha256':sha(original/'sources/manifest.json'),'source_transport':'archived raw HTTP responses only, native current-version queries/pagination/parsers/filtering/UI','historical_product_outputs_imported':False,'new_native_clock_recorded':True,'native_limits_unchanged':True,'old_archive_capture_dates_preserved':True,'not_live_acquisition':True,'scores_assigned':False})
os.environ['GEWU_DATA_ROOT']=str(root/'environment');os.environ['GEWU_WORKSPACE_ROOT']=str(root/'workspace');os.environ['TMPDIR']=str(root/'tmp');tempfile.tempdir=str(root/'tmp')
for key in ('OPENALEX_API_KEY','OPENALEX_MAILTO','CROSSREF_MAILTO','SEMANTIC_SCHOLAR_API_KEY','NCBI_API_KEY','GEWU_CACHE_ROOT','GEWU_STANDALONE'):os.environ.pop(key,None)
sys.path.insert(0,str(P));guard_discovery(root,allow_live=False)
from paper_monitor import ui_server,time_utils
from paper_monitor.sources import publisher
report={'product_commit':snap['product_baseline']['commit'],'mode':'latest_product_offline_source_reprocessing','axis':axis,'complete':False,'live_acquisition_claim':False,'old_outcomes_reused':False,'windows':[],'no_final_score':True}
collector=None
try:
    with ExitStack() as stack:
        stack.enter_context(patch('requests.sessions.get_netrc_auth',return_value=None));stack.enter_context(patch('time.sleep',return_value=None))
        rejected=None
        if axis=='journal':
            sys.path.insert(0,str(OLD/'control/replay-boundary-repair-001'))
            from guard_replay import RejectedRequestReplay
            mapping=json.loads((OLD/'control/replay-boundary-repair-001/REJECTION_MAP.json').read_text())
            rejected=stack.enter_context(RejectedRequestReplay(source_transport,mapping['rows']))
        transport=stack.enter_context(SourceTransport(original/'sources','replay'))
        clock=stack.enter_context(ClockTape(root/'clock','record',P,[ui_server,time_utils,publisher]))
        collector=NativeCollector(P,root,config,axis,{})
        for window in config['subject_months'] if axis=='subject' else ['all']:
            effective=copy.deepcopy(config);folder=root
            if axis=='subject':
                y,m=map(int,window.split('-'));effective['windows']['subject']=[window+'-01',window+'-%02d'%calendar.monthrange(y,m)[1]];folder=root/'windows'/window;folder.mkdir(parents=True)
            write(folder/'input_configuration.json',effective)
            collector.root,collector.config=folder,effective
            collector.occurrences,collector.responses,collector.date_exclusions=[],[],[]
            row={'window':window,'complete':False}
            try:collector.run();row['complete']=True
            except Exception as e:row.update(error=repr(e),traceback=traceback.format_exc())
            finally:collector.persist_observations()
            row.update(observed_occurrences=len(collector.occurrences),ui_responses=len(collector.responses),date_exclusions=len(collector.date_exclusions));report['windows'].append(row)
            if axis=='subject':write(folder/'result.json',row)
            print(json.dumps({k:v for k,v in row.items() if k!='traceback'}),flush=True)
        collector.h.close();collector=None
        report['source_replay']=transport.assert_consumed()
        if rejected:
            report['benchmark_pre_network_rejections']=rejected.events
            assert {r['request_key_without_cookie'] for r in rejected.events}=={r['request_key_without_cookie'] for r in mapping['rows']}
        report['complete']=all(w['complete'] for w in report['windows'])
except Exception as e:report.update(complete=False,error=repr(e),traceback=traceback.format_exc())
finally:
    if collector:collector.h.close()
    report['product_snapshot_unchanged']=all(sha(P/r['path'])==r['sha256'] for r in snap['product_baseline']['tracked_files'])
    report['observed_occurrences']=sum(w['observed_occurrences'] for w in report['windows'])
    write(root/'result.json',report)
print(json.dumps({k:v for k,v in report.items() if k not in ('benchmark_pre_network_rejections','traceback','source_replay','windows')},ensure_ascii=False),flush=True)
if not report['complete']:raise SystemExit(1)
