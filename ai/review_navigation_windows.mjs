// Inspect existing reduced records only. Never reconstruct omitted sensor/target metadata.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const read=f=>JSON.parse(fs.readFileSync(f,'utf8').replace(/^\uFEFF/,''));
const sha=f=>createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const finite=x=>typeof x==='number'&&Number.isFinite(x);
const output=path.resolve(process.argv[2]||'work/navigation-window-review');
assert.equal(fs.existsSync(output),false,'Preserve existing analysis');
const planFile=path.join(root,'ai/navigation-window-review-plan.json'),plan=read(planFile),input=path.join(root,plan.input),data=read(input);
const prior=read(path.join(root,'outputs/Warirak_Navigation_R3_Postmortem_Audit.json'));
assert.equal(sha(input),prior.diagnostic_sha256);
assert.equal(data.test_opened,false);assert.equal(data.q_updates_performed,false);
fs.mkdirSync(output,{recursive:true});
const frozen={...plan,frozen_before_analysis:true,frozen_at:new Date().toISOString(),input_sha256:sha(input),plan_sha256:sha(planFile),script_sha256:sha(fileURLToPath(import.meta.url))};
fs.writeFileSync(path.join(output,'plan.json'),JSON.stringify(frozen,null,2),{flag:'wx'});
const rows=[];
for(const c of data.cases.filter(c=>c.timeline_category==='collision_after_clearance_only_stop')){
 const e=c.first_clearance_only_stop,o=e.observation,w=e.window_before;
 assert.equal(c.first_assistance,null);assert.equal(e.subsequent_nonzero_applied_outputs,0);
 assert(o.range_evidence.status==='fresh'&&o.range_evidence.captured_at_ms<=o.at_ms);
 const rays=o.clearance_m,near=rays.flatMap((v,i)=>finite(v)&&v<.35?[i]:[]);
 assert(near.length>0);
 assert(w.every(t=>t.request.issued_at_ms===t.before.at_ms&&t.after.at_ms>t.before.at_ms&&t.after.at_ms<=o.at_ms));
 const last=w.at(-1),m=last?.before.motion,p=last?.before.pose;
 const motionKnown=m?.method==='simulation_position_difference'&&m.source==='simulation'&&m.frame==='pool_fixed'&&m.calibrated===true&&p?.source==='simulation'&&p.frame==='pool_fixed'&&p.calibrated===true&&[m.vx_mps,m.vy_mps,p.heading_rad].every(finite)&&Math.abs(m.timestamp_unix_ms-p.timestamp_unix_ms)<=100&&last.before.at_ms-m.timestamp_unix_ms>=0&&last.before.at_ms-m.timestamp_unix_ms<=300;
 const body=motionKnown?{forward_mps:m.vx_mps*Math.cos(p.heading_rad)+m.vy_mps*Math.sin(p.heading_rad),lateral_mps:-m.vx_mps*Math.sin(p.heading_rad)+m.vy_mps*Math.cos(p.heading_rad),original_motion_at_ms:m.timestamp_unix_ms,original_pose_at_ms:p.timestamp_unix_ms}:null;
 rows.push({context:c.context,seed:c.seed,training_episode_index:c.training_episode_index,profile:c.profile,transport_delay_ms:c.transport_delay_ms,event_at_ms:o.at_ms,event_step:e.step,below_stop_threshold_ray_indices:near,front_ray_below_stop:near.some(i=>[0,1,7].includes(i)),side_or_rear_ray_below_stop:near.some(i=>[2,3,4,5,6].includes(i)),window_transitions:w.length,window_span_to_event_ms:w.length?o.at_ms-w[0].before.at_ms:0,pre_event_requests:w.map(t=>t.action),all_pre_event_requests_stop:w.length>0&&w.every(t=>t.action==='STOP'),last_pre_event_body_motion:body,exact_original_q_features_reconstructable:false,range_rate_inferred:false});
}
const count=(r,key)=>r.filter(key).length;
const summary=Object.fromEntries([...new Set(rows.map(r=>r.context))].map(context=>{const r=rows.filter(r=>r.context===context);return[context,{inspected_event_windows:r.length,front_ray_below_stop:count(r,x=>x.front_ray_below_stop),side_or_rear_ray_below_stop:count(r,x=>x.side_or_rear_ray_below_stop),nonfront_only_below_stop:count(r,x=>!x.front_ray_below_stop&&x.side_or_rear_ray_below_stop),all_pre_event_requests_stop:count(r,x=>x.all_pre_event_requests_stop),motion_projection_available:count(r,x=>x.last_pre_event_body_motion!==null),full_one_second_pre_event_window:count(r,x=>x.window_span_to_event_ms===1000&&x.window_transitions===10)}];}));
const result={schema:'warirak.navigation-window-review.v1',source:'existing simulation diagnostic records',simulation_rollouts_performed:0,training_started:false,q_updates_performed:false,validation_opened:false,test_opened:false,full_q_state_aliasing_proved:false,summary,rows,limitations:plan.limitations,physical_motor_transport:false};
assert.equal(sha(input),frozen.input_sha256);
fs.writeFileSync(path.join(output,'review.json'),JSON.stringify(result,null,2),{flag:'wx'});
console.log(JSON.stringify({output,summary,rollouts_performed:0,full_q_state_aliasing_proved:false}));
