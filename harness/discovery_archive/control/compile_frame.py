import os
from pathlib import Path
from collections import Counter
import copy, datetime as dt, hashlib, json, shutil, sys
R=Path(os.environ['GEWU_FIXED_ARCHIVE'])
OLD=R.parent/'fixed-20261005-001';OUT=R/'runs/a-frame-001'
sys.path.insert(0,str(R/'tools'))
from compile_discovery_frames import check_occurrence, exclusions
from discovery_frames import make_frame
from fixed_engineering_gate import verify
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
_,snap=verify(R);commit=snap['product_baseline']['commit']
sources=[('journal','all',R/'runs/a-journal-rebuild-001')]+[('subject',f'2026-{m:02d}',R/f'runs/a-subject-rebuild-001/windows/2026-{m:02d}') for m in range(1,10)]+[('author','all',R/'runs/a-author-rebuild-001')]
outcomes=[];inputs=[];rows=[]
for axis,window,p in sources:
 result=read(p/'result.json');assert result['complete']
 assert result.get('product_commit',commit)==commit
 captured={}
 for entry in read(p/'ui_manifest.json'):
  target=p/entry['path'];assert target.resolve().is_relative_to(p/'ui') and not target.is_symlink()
  assert entry['status']==200 and sha(target)==entry['sha256']
  captured[entry['path']]=read(target);inputs.append({'path':str(target.relative_to(R)),'sha256':sha(target)})
 summary=read(p/'native_summary.json')
 ids={a['roster_author_id']:a['native_monitor_id'] for a in summary} if axis=='author' else {}
 here=read(p/'occurrences.json')
 for row in here:
  check_occurrence(row,captured[row['response_path']],axis,ids)
  row['original_occurrence_id']=row['occurrence_id'];row['occurrence_id']=axis+'-'+window+':'+row['occurrence_id']
  row['response_path']=str((p/row['response_path']).relative_to(R));row['acquisition']=str(p.relative_to(R));rows.append(row)
 for name in ('result.json','native_summary.json','ui_manifest.json','occurrences.json','input_configuration.json','study_window_exclusions.json'):
  target=p/name;inputs.append({'path':str(target.relative_to(R)),'sha256':sha(target)})
 outcomes.append({'axis':axis,'window':window,'occurrences':len(here),'ui_responses':len(captured),'acquisition':str(p.relative_to(R))})
expath=R/'config/a_exposure_exclusions_004.json';frame=make_frame(rows,exclusions(read(expath)))
old=read(OLD/'runs/a-frame-002/selected_units.json');oldids={u['candidate_id'] for u in old};newids={u['candidate_id'] for u in frame['units']}
screen=read(OLD/'control/evidence-preflight-018/SCREENING_DECISIONS.json')
screenids={e['case_id'][2:] for e in screen['exclusions']};active=oldids-screenids
late=read(R/'control/ROUND_PLAN.json')['A']['required_recovered_authors']
summary={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'product_commit':commit,'mode':'frozen_public_source_inputs_reprocessed_by_current_product','live_acquisition_claim':False,'old_product_outputs_reused':False,'exact_native_UI_card_membership_verified':True,'observed_occurrences':len(rows),'frame_units_by_axis':dict(Counter(u['axis'] for u in frame['units'])),'frame_units_by_author':dict(sorted(Counter(u['monitor_id'] for u in frame['units'] if u['axis']=='author').items())),'calibration_excluded_occurrences':len(frame['excluded_occurrence_ids']),'old_selection_n':len(oldids),'old_active_n':len(active),'old_active_missing_in_current_frame':sorted(active-newids),'old_selected_missing_in_current_frame':sorted(oldids-newids),'late_author_frame_units':sum(u['axis']=='author' and u['monitor_id'] in late for u in frame['units']),'sampling_locked':False,'no_AI_answers_used':True,'no_scores_assigned':True}
OUT.mkdir(exist_ok=False);shutil.copy2(__file__,OUT/'compiler.py')
write(OUT/'frame.json',frame);write(OUT/'SUMMARY.json',summary)
write(OUT/'frame_manifest.json',{'product_commit':commit,'inputs':inputs,'compiler_sha256':sha(OUT/'compiler.py'),'frame_sha256':sha(OUT/'frame.json'),'source_outcomes':outcomes,'calibration_manifest':{'path':str(expath.relative_to(R)),'sha256':sha(expath)},'software_snapshot_sha256':sha(R/'control/PRODUCT_SNAPSHOT.json'),'limitations':['Archived transport responses retain their original capture time. This measures current-version behavior on frozen source inputs, not current website availability or exhaustive recall.','Partial/unknown displayed dates remain eligible until independent date review.','Within-monitor exact identifiers define candidates; no title-only merging.','Source-type and user-directed exclusions remain separate from system correctness.']})
verify(R);print(json.dumps(summary,ensure_ascii=False),flush=True)
