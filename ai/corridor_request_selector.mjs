// Untrained, evidence-gated request ranking. No geometry class or safety certificate inferred.
import {selectProactiveRequest} from './proactive_request_selector.mjs';
export const CORRIDOR_SELECTOR_SCHEMA='warirak.proactive-request-selector.v2';
export const CORRIDOR_PROPOSAL_SCHEMA='warirak.proactive-request-proposal.v2';
export const CORRIDOR_CONSTANTS=Object.freeze({required_frames:3,min_span_ms:200,max_span_ms:300,max_gap_ms:150,simulated_range_noise_allowance_m:.1,min_front_lower_m:1,min_other_side_lower_m:.65,max_abs_yaw_rate_rps:.35,max_forward_speed_mps:.9,max_abs_lateral_speed_mps:.15,min_side_approach_mps:.01,max_target_bearing_rad:.35});
const finite=v=>typeof v==='number'&&Number.isFinite(v);
function wrap(base){return{...base,schema:CORRIDOR_PROPOSAL_SCHEMA,selector:CORRIDOR_SELECTOR_SCHEMA,based_on_selector:base.selector,base_reason:base.reason,corridor_extension_used:false,geometry_classification:null,corridor_is_certified_safe:false};}
function inspectEvidence(context,history,allowed,now){
 const c=CORRIDOR_CONSTANTS;
 if(!allowed.includes(1)||allowed.some(a=>[4,5,6].includes(a)))return{ok:false,reason:'original_evasive_options_or_no_forward'};
 const latest=context.features,target=latest.target;
 if(target?.visible!==true||!finite(target.bearing_rad)||Math.abs(target.bearing_rad)>c.max_target_bearing_rad)return{ok:false,reason:'current_target_not_in_forward_sector'};
 const records=history.slice(-c.required_frames);
 if(records.length!==c.required_frames)return{ok:false,reason:'three_original_frames_required'};
 if(!Number.isInteger(context.record_sequence)||records.at(-1).stream?.record_sequence!==context.record_sequence||JSON.stringify(records.at(-1).features)!==JSON.stringify(latest))return{ok:false,reason:'latest_history_context_mismatch'};
 let side=null,lastCapture=null,lastSequence=null,lastMotion=null,minFront=Infinity,maxYaw=0;
 for(const r of records){
  const f=r.features,e=r.stream?.evidence_new,range=f.range,m=f.motion;
  if(r.stream?.epoch!==context.epoch||f.authority!=='research_channel_armed'||range?.status!=='fresh_complete'||e?.range!==true||e?.motion!==true||e?.pose!==true||m?.status!=='measured_projection'||f.range_motion_synchronized!==true)return{ok:false,reason:'fresh_independent_evidence_required'};
  const at=range.captured_at_ms,seq=range.original_sequence,mt=m.original_motion_at_ms,pt=m.original_pose_at_ms;
  if(![at,mt,pt].every(t=>finite(t)&&t<=now&&now-t<=300)||!Number.isInteger(seq)||seq<0||lastCapture!==null&&(at<=lastCapture||at-lastCapture>c.max_gap_ms)||lastSequence!==null&&seq<=lastSequence||lastMotion!==null&&mt<=lastMotion)return{ok:false,reason:'original_frame_clock_or_identity_invalid'};
  const rays=range.ray_m;
  if(!Array.isArray(rays)||rays.length!==8||!rays.every(v=>finite(v)&&v>=0&&v<=1.5))return{ok:false,reason:'complete_surround_required'};
  const thisSide=rays[2]>.35&&rays[2]<.65&&rays[6]>=.65?2:rays[6]>.35&&rays[6]<.65&&rays[2]>=.65?6:null;
  if(thisSide===null||side!==null&&side!==thisSide)return{ok:false,reason:'one_consistent_lateral_hazard_required'};
  const front=Math.min(rays[0],rays[1],rays[7])-c.simulated_range_noise_allowance_m,other=rays[thisSide===2?6:2]-c.simulated_range_noise_allowance_m;
  if(front<c.min_front_lower_m||other<c.min_other_side_lower_m)return{ok:false,reason:'forward_or_opposite_side_evidence_insufficient'};
  if(![m.forward_mps,m.lateral_mps,m.yaw_rate_rps].every(finite)||m.forward_mps<-.04||m.forward_mps>c.max_forward_speed_mps||Math.abs(m.lateral_mps)>c.max_abs_lateral_speed_mps||Math.abs(m.yaw_rate_rps)>c.max_abs_yaw_rate_rps||m.lateral_mps*(thisSide===2?1:-1)<c.min_side_approach_mps)return{ok:false,reason:'measured_motion_not_consistent'};
  side=thisSide;lastCapture=at;lastSequence=seq;lastMotion=mt;minFront=Math.min(minFront,front);maxYaw=Math.max(maxYaw,Math.abs(m.yaw_rate_rps));
 }
 const first=records[0].features.range.captured_at_ms,last=records.at(-1).features.range.captured_at_ms;
 if(last!==context.features.range.captured_at_ms||last!==context.features.observation_at_ms||last-first<c.min_span_ms||last-first>c.max_span_ms)return{ok:false,reason:'current_continuous_frame_span_required'};
 return{ok:true,frames:records.length,first_capture_at_ms:first,last_capture_at_ms:last,lateral_hazard_ray:side,min_front_lower_m:minFront,max_measured_yaw_rate_rps:maxYaw,simulator_noise_allowance_only:true,range_rate_inferred:false};
}
export function selectCorridorRequest(context,history,allowed,options={}){
 const base=selectProactiveRequest(context,history,allowed,options),result=wrap(base);
 if(base.action!==0||base.reason!=='no_original_evasive_request_permitted')return result;
 const now=options.nowMs??context?.features?.processed_at_ms,evidence=inspectEvidence(context,history,allowed,now);
 if(!evidence.ok)return{...result,corridor_decline_reason:evidence.reason};
 return{...result,action:1,action_name:'FORWARD',reason:'supported_forward_corridor_request',corridor_extension_used:true,corridor_evidence:evidence};
}
