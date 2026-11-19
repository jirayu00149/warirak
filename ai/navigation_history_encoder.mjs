// Canonical Node encoder. No model, reward, geometry labels or actuator I/O.
import fs from 'node:fs';
import {createHash} from 'node:crypto';
const layoutBytes=fs.readFileSync(new URL('./navigation-history-layout.json',import.meta.url));
function immutable(value){if(value&&typeof value==='object'){for(const child of Object.values(value))immutable(child);Object.freeze(value);}return value;}
export const NAVIGATION_LAYOUT=immutable(JSON.parse(layoutBytes.toString('utf8')));
export const NAVIGATION_LAYOUT_SHA256=createHash('sha256').update(layoutBytes).digest('hex');
export const HISTORY_VECTOR_SCHEMA=NAVIGATION_LAYOUT.encoder_schema;
export const FRAME_FIELDS=Object.freeze([...NAVIGATION_LAYOUT.field_order]);
const L=NAVIGATION_LAYOUT,MAX=L.maximum_age_ms;
const finite=v=>typeof v==='number'&&Number.isFinite(v),uint=v=>Number.isSafeInteger(v)&&v>=0;
const stamp=v=>Number.isSafeInteger(v)&&v>0;
const zero=v=>v===0?0:v;
function age(at,now,frameAt){const known=stamp(at)&&at<=frameAt&&at<=now;return{known,fresh:known&&now-at<=MAX,value:known?Math.min(1,(now-at)/MAX):0};}
function numeric(v,scale,valid=true,signed=false){const known=valid&&finite(v)&&v>=(signed?-scale:0)&&v<=scale;return[known?zero(v/scale):0,Number(known)];}
const oneHot=(value,list)=>{const i=list.includes(value)?list.indexOf(value):0;return list.map((_,n)=>Number(n===i));};
function checkRow(r,epoch,now){
 const f=r?.features,s=r?.stream;
 if(f?.schema!==L.upstream_feature_schema||f.plant_environment!==L.plant_environment||f.source!=='simulation'||f.control_enabled!==false||s?.schema!==L.upstream_stream_schema||s.epoch!==epoch||!uint(s.record_sequence)||s.evidence_new?.observation!==true||!stamp(f.observation_at_ms)||!stamp(f.processed_at_ms)||f.observation_at_ms>now||f.processed_at_ms>now||f.processed_at_ms<f.observation_at_ms)throw Error('Unsupported observation/stream identity or clock');
}
function identity(r){
 const f=r.features,m=f.motion??{},range=f.range??{},a=f.ack??{},t=f.target??{},s=r.stream;
 return JSON.stringify({schema:f.schema,environment:f.plant_environment,source:f.source,at:f.observation_at_ms,processed:f.processed_at_ms,authority:f.authority,mission:f.mission_mode,range:[range.status,range.captured_at_ms,range.original_sequence,range.ray_m],motion:[m.status,m.original_pose_at_ms,m.original_motion_at_ms,m.forward_mps,m.lateral_mps,m.yaw_rate_rps,m.projection_margin_mps],sync:f.range_motion_synchronized,ack:[a.status,a.original_feedback_at_ms,a.valid_until_ms,a.matched_command_still_valid_at_processing],target:[t.visible,t.bearing_rad,t.range_m,t.observation_envelope_at_ms],stream:[s.schema,s.epoch,s.record_sequence,s.evidence_new?.range,s.evidence_new?.motion,s.evidence_new?.pose]});
}
function previousRequest(previous,current){
 if(!previous||previous.stream.epoch!==current.stream.epoch||previous.stream.record_sequence+1!==current.stream.record_sequence||current.features.observation_at_ms-previous.features.observation_at_ms>L.maximum_history_gap_ms)return'UNKNOWN';
 const d=previous.decision;
 if(!d||d.status==='rejected')return'UNKNOWN';
 if(d.request===null&&d.status==='no_new_request')return'NONE';
 if(d.owner==='operator'&&d.request?.action==='RECOVERY_REQUEST')return'OPERATOR_RECOVERY';
 return ['navigation','operator'].includes(d.owner)&&L.navigation_actions.includes(d.request?.action)?d.request.action:'UNKNOWN';
}
function encodeFrame(row,previous,now){
 const f=row.features,at=f.observation_at_ms;
 if(now-at>MAX)return Array(L.frame_size).fill(0);
 const e=row.stream.evidence_new??{},r=f.range??{},m=f.motion??{},t=f.target??{},a=f.ack??{};
 const rangeAge=age(r.captured_at_ms,now,at),poseAge=age(m.original_pose_at_ms,now,at),motionAge=age(m.original_motion_at_ms,now,at),ackAge=age(a.original_feedback_at_ms,now,at);
 const rangeFresh=['fresh_complete','fresh_partial'].includes(r.status)&&rangeAge.fresh&&Array.isArray(r.ray_m)&&r.ray_m.length===8&&r.ray_m.some(v=>finite(v)&&v>=0&&v<=L.scales.range_m);
 const motionFresh=m.status==='measured_projection'&&poseAge.fresh&&motionAge.fresh&&Math.abs(m.original_pose_at_ms-m.original_motion_at_ms)<=100&&[m.forward_mps,m.lateral_mps].every(v=>finite(v)&&Math.abs(v)<=3)&&finite(m.yaw_rate_rps)&&Math.abs(m.yaw_rate_rps)<=10;
 const out=[1,zero((now-at)/MAX)];
 for(let i=0;i<8;i++)out.push(...numeric(r.ray_m?.[i],L.scales.range_m,rangeFresh));
 out.push(rangeAge.value,Number(rangeAge.known),Number(rangeFresh&&e.range===true));
 const visible=t.visible===true&&t.observation_envelope_at_ms===at;
 out.push(Number(visible),...numeric(t.bearing_rad,Math.PI,visible,true),...numeric(t.range_m,L.scales.target_range_m,visible));
 out.push(numeric(m.forward_mps,L.scales.linear_velocity_mps,motionFresh,true)[0],numeric(m.lateral_mps,L.scales.linear_velocity_mps,motionFresh,true)[0],numeric(m.yaw_rate_rps,L.scales.yaw_rate_rps,motionFresh,true)[0],Number(motionFresh));
 out.push(...numeric(m.projection_margin_mps,L.scales.projection_margin_mps,motionFresh),poseAge.value,Number(poseAge.known),motionAge.value,Number(motionAge.known),Number(motionFresh&&e.pose===true),Number(motionFresh&&e.motion===true),Number(rangeFresh&&motionFresh&&f.range_motion_synchronized===true&&Math.max(r.captured_at_ms,m.original_pose_at_ms,m.original_motion_at_ms)-Math.min(r.captured_at_ms,m.original_pose_at_ms,m.original_motion_at_ms)<=100));
 out.push(...oneHot(f.authority,L.authority_order),...oneHot(f.mission_mode,L.mission_order),...oneHot(ackAge.fresh?a.status:'unknown',L.ack_order));
 out.push(ackAge.value,Number(ackAge.known),Number(ackAge.fresh&&a.status==='matched_report'&&a.matched_command_still_valid_at_processing===true&&stamp(a.valid_until_ms)&&now<a.valid_until_ms));
 out.push(...oneHot(previousRequest(previous,row),L.previous_request_order));
 if(out.length!==L.frame_size||out.some(v=>!finite(v)||v< -1||v>1))throw Error('Encoder layout/value invariant failed');
 return out;
}
export function vectorDigest(vector){
 if(!Array.isArray(vector)||vector.length!==L.vector_size||vector.some(v=>!finite(v)||v< -1||v>1))throw Error('Invalid finite vector');
 const bytes=Buffer.alloc(vector.length*8);vector.forEach((v,i)=>bytes.writeDoubleLE(zero(v),i*8));return createHash('sha256').update(bytes).digest('hex');
}
export function encodeNavigationHistory(current,history,allowed,{nowMs=current?.features?.processed_at_ms}={}){
 if(!stamp(nowMs)||!uint(current?.stream?.epoch)||!Array.isArray(history)||history.length>L.maximum_history_rows||!Array.isArray(allowed)||!allowed.length||new Set(allowed).size!==allowed.length||allowed.some(a=>!Number.isInteger(a)||a<0||a>=L.navigation_actions.length))throw Error('Invalid clock/history/original request mask');
 const epoch=current.stream.epoch;
 checkRow(current,epoch,nowMs);
 if(nowMs-current.features.observation_at_ms>MAX)throw Error('Current observation expired');
 const rows=history.map(r=>({features:r.features,stream:r.stream,decision:r.decision}));
 for(let i=0;i<rows.length;i++){
  checkRow(rows[i],epoch,nowMs);
  if(rows[i].features.observation_at_ms>current.features.observation_at_ms||rows[i].stream.record_sequence>current.stream.record_sequence||i>0&&(rows[i].features.observation_at_ms<=rows[i-1].features.observation_at_ms||rows[i].stream.record_sequence<=rows[i-1].stream.record_sequence))throw Error('History clock/sequence conflict');
 }
 const last=rows.at(-1);
 if(last?.stream.record_sequence===current.stream.record_sequence){if(identity(last)!==identity(current))throw Error('Current/history packet mismatch');rows[rows.length-1]={features:current.features,stream:current.stream,decision:null};}
 else{if(last&&(last.features.observation_at_ms>=current.features.observation_at_ms||last.stream.record_sequence>=current.stream.record_sequence))throw Error('Current identity not newer');rows.push({features:current.features,stream:current.stream,decision:null});}
 let cut=0;for(let i=1;i<rows.length;i++)if(rows[i].features.observation_at_ms-rows[i-1].features.observation_at_ms>L.maximum_history_gap_ms||rows[i].stream.record_sequence!==rows[i-1].stream.record_sequence+1)cut=i;
 const recent=rows.slice(cut),start=Math.max(0,recent.length-L.frame_count),chosen=recent.slice(start),vector=Array((L.frame_count-chosen.length)*L.frame_size).fill(0);
 for(let i=0;i<chosen.length;i++){const prior=i>0?chosen[i-1]:start>0?recent[start-1]:null;vector.push(...encodeFrame(chosen[i],prior,nowMs));}
 if(vector.length!==L.vector_size)throw Error('Stack dimension mismatch');
 return{schema:HISTORY_VECTOR_SCHEMA,layout_sha256:NAVIGATION_LAYOUT_SHA256,plant_environment:L.plant_environment,source:'simulation',history_frames:L.frame_count,frame_size:L.frame_size,vector_size:L.vector_size,vector,vector_sha256:vectorDigest(vector),allowed_mask:L.navigation_actions.map((_,i)=>allowed.includes(i)),stream_epoch:epoch,record_sequence:current.stream.record_sequence,observation_at_ms:current.features.observation_at_ms,encoded_at_ms:nowMs,history_boundary_applied:cut>0,command_authorization:false,control_enabled:false,physical_motor_transport:false};
}
