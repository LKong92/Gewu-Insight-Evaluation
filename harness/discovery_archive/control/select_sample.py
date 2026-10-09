import os
from pathlib import Path
from collections import Counter
import datetime as dt,hashlib,json,random,shutil
R=Path(os.environ['GEWU_FIXED_ARCHIVE']);OLD=R.parent/'fixed-20261005-001';F=R/'runs/a-frame-001'
def read(p):return json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
frame=read(F/'frame.json');units={u['candidate_id']:u for u in frame['units']}
oldframe=read(OLD/'runs/a-frame-002/frame.json');oldsel=read(OLD/'runs/a-frame-002/selected_units.json');oldsample=read(OLD/'runs/a-frame-002/sampling.json')
base={u['candidate_id'] for u in oldsel};late=read(R/'control/ROUND_PLAN.json')['A']['required_recovered_authors']
currentbase={i for i,u in units.items() if u['axis']!='author' or u['monitor_id'] not in late}
previousbase={u['candidate_id'] for u in oldframe['units']}
assert currentbase==previousbase,'Do not transfer a sampling draw if its candidate population changed'
screen=read(OLD/'control/evidence-preflight-018/SCREENING_DECISIONS.json');excluded={e['case_id'][2:] for e in screen['exclusions']}
assert excluded<=base and base<=units.keys()
seed='gewu-v4-fixed-20261007-late-author-supplement-01';d=R/'control/expanded-sampling-001';d.mkdir(exist_ok=False)
design={'schema':'gewu-paired-base-and-stratified-author-expansion-v1','locked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'product_commit':read(R/'control/baseline.json')['commit'],'frame_sha256':sha(F/'frame.json'),'reason':'User explicitly requires inclusion of all recovered author profiles without discarding already assembled scientific evidence. Reuse original random sample identities only after confirming the same candidate population, never reuse old software results or AI labels.','base_selection':{'candidate_population_identical':True,'selection_manifest_sha256':sha(OLD/'runs/a-frame-002/sampling.json'),'original_sampling_design':oldsample['design'],'source_sample_path':str(OLD/'runs/a-frame-002/sampling.json'),'sample_identities_only':True,'pre_screening_count':len(base),'active_after_previously_authorized_screening':len(base-excluded)},'supplemental_selection':{'design':'SRS without replacement separately in each recovered author stratum','author_ids':late,'sample_size_per_author':10,'small_strata':'Take all available candidates if fewer than ten; do not fabricate or substitute another author.','seed':seed,'selection_timing':'Before reading new model answers; no new review has started.'},'screening':{'same_user_defined_document_scope_for_base_and_supplement':True,'no_replacement_after_document_type_exclusion':True,'preserve_all_raw_candidates_and_exclusions':True,'carryforward_decisions_sha256':sha(OLD/'control/evidence-preflight-018/SCREENING_DECISIONS.json'),'exclusions_are_not_test_passes':True},'estimands':{'primary':'Fixed repeated benchmark panel plus prespecified recovered-author supplement; provide per-axis and author-stratum results.','unequal_author_sampling':'Do not call a naive pooled proportion an equal-probability estimate of all 1,351 author candidates. Use recorded stratum inclusion probabilities for weighted estimates and report unweighted evaluated-panel rates separately.','scope':'Source-verified research-document panel under user-approved exclusions. It does not measure unrestricted raw-feed precision or exhaustive recall.','unknown_and_failures':'Retain unresolved judgments and current-version product failures; neither becomes success nor an outcome-driven sample exclusion.'},'AI_answers_used':False,'old_product_outputs_used':False,'final_scientific_count_pending_new_sample_material_check':True}
write(d/'DESIGN.json',design);shutil.copy2(__file__,d/'select.py')
chosen=set(base);strata=[];prob={}
for axis,v in oldsample['axes'].items():
 strata.append({'stratum':'original_'+axis,'axis':axis,'frame_size':v['frame_size'],'drawn':v['sample_size'],'inclusion_probability':v['inclusion_probability']})
 for i in base:
  if units[i]['axis']==axis:prob[i]={'stratum':'original_'+axis,'probability':v['inclusion_probability']}
for author in late:
 pop=sorted(i for i,u in units.items() if u['axis']=='author' and u['monitor_id']==author)
 rng=random.Random(int.from_bytes(hashlib.sha256((seed+':'+author).encode()).digest(),'big'))
 selected=rng.sample(pop,min(10,len(pop)));chosen.update(selected)
 strata.append({'stratum':author,'axis':'author','frame_size':len(pop),'drawn':len(selected),'inclusion_probability':len(selected)/len(pop) if pop else None,'selected_candidate_ids':selected})
 for i in selected:prob[i]={'stratum':author,'probability':len(selected)/len(pop)}
active=chosen-excluded;new=chosen-base
roster=read(R/'config/author_roster.json');write(d/'roster_snapshot.json',roster)
write(d/'selected_units.json',[units[i] for i in sorted(chosen)])
write(d/'active_units_before_new_screening.json',[units[i] for i in sorted(active)])
write(d/'new_author_units.json',[units[i] for i in sorted(new)])
write(d/'inclusion_probabilities.json',prob)
write(d/'SCREENING_CARRYFORWARD.json',screen)
summary={'design_sha256':sha(d/'DESIGN.json'),'raw_selected_count':len(chosen),'previously_screened_out':len(excluded),'active_count_before_new_screening':len(active),'new_author_cases_before_screening':len(new),'axes_before_new_screening':dict(Counter(units[i]['axis'] for i in active)),'by_author_before_new_screening':dict(sorted(Counter(units[i]['monitor_id'] for i in active if units[i]['axis']=='author').items())),'author_profile_capture_success':24,'sampled_author_count_before_new_screening':len({units[i]['monitor_id'] for i in active if units[i]['axis']=='author'}),'unsampled_roster_reasons':{'AUTHOR-10':'No native records within the declared displayed-date study window.','AUTHOR-06':'Its sole within-window candidate was source-confirmed as conference programme and excluded under the user-approved scope.'},'strata':strata,'potential_AI_questions_before_new_screening':len(active)*3,'counts_final':False,'old_outcomes_or_AI_answers_imported':False}
write(d/'SUMMARY.json',summary)
s=read(R/'control/STATUS.json');s.update(sampling_locked=True,new_author_draw=len(new),A_before_new_screening=len(active),phase='expanded_sample_materials_and_supplementary_tests');write(R/'control/STATUS.json',s)
print(json.dumps({k:v for k,v in summary.items() if k!='strata'},ensure_ascii=False))
