// Pure inspection of already-recorded inputs. No environment is constructed or stepped.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {navigationAllowed,navigationFeatures,NAV_ONLY_ACTIONS} from './navigation_action_interface.mjs';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))),out=path.join(root,'work/side-circle-window-inspection');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,'')),sha=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
assert.equal(fs.existsSync(out),false,'Preserve completed inspection');
const planFile=path.join(root,'ai/side-circle-window-inspection-plan.json'),plan=read(planFile),v1=read(path.join(root,'work/proactive-selector-v1-dev-r1/protocol.json')),audit=read(path.join(root,'outputs/Warirak_Proactive_Selector_v1_Outcome_Audit.json'));
for(const[f,h]of Object.entries(v1.source_sha256))assert.equal(sha(path.join(root,f)),h,f);
for(const input of plan.inputs)assert.equal(sha(path.join(root,input)),audit.artifact_hashes[path.basename(input)].sha256);
fs.mkdirSync(out,{recursive:true});
const frozen={...plan,frozen_before_inspection:true,frozen_at:new Date().toISOString(),plan_sha256:sha(planFile),script_sha256:sha(fileURLToPath(import.meta.url)),input_sha256:Object.fromEntries(plan.inputs.map(f=>[f,sha(path.join(root,f))])),mask_source_sha256:{'ai/navigation_action_interface.mjs':sha(path.join(root,'ai/navigation_action_interface.mjs')),'ai/navigation_mission_learning.mjs':sha(path.join(root,'ai/navigation_mission_learning.mjs'))}};
fs.writeFileSync(path.join(out,'protocol.json'),JSON.stringify(frozen,null,2),{flag:'wx'});
const rows=[];
for(const input of plan.inputs){
 const original=read(path.join(root,input)),seen=new Map(),windows=[...original.first_event_windows.map(w=>({name:w.event,records:w.records,proposals:w.proposals??[]})),{name:'final_bounded_records',records:original.final_recorder.records,proposals:[]}];
 for(const window of windows)for(let i=0;i<window.records.length;i++){
  const r=window.records[i],o=r.original_observation,at=o.timestamp_unix_ms,previous=window.records[i-1];
  assert(o.target&&typeof o.sensors.armed==='boolean'&&typeof o.sensors.manual_override==='boolean');
  let allowed=null,previousAction=null,limitation='preceding_contiguous_record_missing';
  if(previous&&previous.original_observation.timestamp_unix_ms+100===at&&previous.decision){
   if(previous.decision.request===null)previousAction=0;
   else previousAction=NAV_ONLY_ACTIONS.indexOf(previous.decision.request.action);
   if(previousAction>=0){allowed=navigationAllowed(o,navigationFeatures(o,previousAction));limitation=null;}
  }
  const c=o.sensors.clearance_m,min=indices=>Array.isArray(c)&&indices.every(j=>typeof c[j]==='number'&&Number.isFinite(c[j]))?Math.min(...indices.map(j=>c[j])):null;
  const proposal=window.proposals.find(p=>p.at_ms===at)?.proposal;
  const row={role:original.role,case_id:original.case_id,window:window.name,at_ms:at,step:(at-1800000000000)/100,previous_request:previousAction===null?null:NAV_ONLY_ACTIONS[previousAction],allowed_requests:allowed?.map(a=>NAV_ONLY_ACTIONS[a])??null,actual_original_request:r.decision?.request?.action??null,request_explicitly_null:r.decision?.request===null,range_status:o.sensors.range_evidence.status,front_min_m:min([0,1,7]),left_ray_m:Array.isArray(c)?c[2]:null,right_ray_m:Array.isArray(c)?c[6]:null,recorded_proposal_reason:proposal?.reason??null,mask_reconstruction_limitation:limitation};
  if(seen.has(at)){const old=seen.get(at);assert.deepEqual(old.original,o);if(old.row.allowed_requests===null&&row.allowed_requests!==null)old.row=row;}
  else seen.set(at,{original:o,row});
 }
 rows.push(...[...seen.values()].map(v=>v.row));
}
const summaries=Object.fromEntries(['candidate','reference'].map(role=>{const r=rows.filter(x=>x.role===role),known=r.filter(x=>x.allowed_requests!==null),forward=known.filter(x=>x.range_status==='fresh'&&x.allowed_requests.includes('FORWARD')&&x.actual_original_request==='STOP');return[role,{unique_saved_observations:r.length,first_saved_step:Math.min(...r.map(x=>x.step)),last_saved_step:Math.max(...r.map(x=>x.step)),known_masks:known.length,unknown_previous_history:r.length-known.length,fresh_frames_with_forward_permitted_and_STOP_requested:forward.length,known_mask_counts:Object.fromEntries([...new Set(known.map(x=>x.allowed_requests.join('|')))].sort().map(k=>[k,known.filter(x=>x.allowed_requests.join('|')===k).length])),recorded_no_evasive_reason_with_forward_permitted:forward.filter(x=>x.recorded_proposal_reason==='no_original_evasive_request_permitted').length}];}));
const result={schema:'warirak.side-circle-window-inspection.v1',summary:summaries,rows,new_rollouts:0,model_or_policy_updates:0,full_trajectory_reconstructed:false,initial_decision_reconstructed:false,permitted_forward_proves_safe:false,training_started:false,validation_opened:false,test_opened:false,physical_motor_transport:false,limitations:plan.limits};
fs.writeFileSync(path.join(out,'inspection.json'),JSON.stringify(result,null,2),{flag:'wx'});
console.log(JSON.stringify({summary:summaries,new_rollouts:0,initial_decision_reconstructed:false}));
