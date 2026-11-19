// Fixed, untrained simulation research heuristic. Outputs request names, never motor values.
export const SELECTOR_SCHEMA='warirak.proactive-request-selector.v1';
export const PROPOSAL_SCHEMA='warirak.proactive-request-proposal.v1';
export const SELECTOR_CONSTANTS=Object.freeze({screening_horizon_s:.6,screening_margin_m:.05,enter_screening_m:.75,release_screening_m:.95,target_bearing_deadband_rad:.18});
const ACTIONS=['STOP','FORWARD','TURN_LEFT','TURN_RIGHT','PIVOT_LEFT','PIVOT_RIGHT','HOLD'];
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const badAck=new Set(['inconsistent_report','feedback_after_command_window','invalid_issued_control_ledger']);
function proposal(action,reason,extra={}){return{schema:PROPOSAL_SCHEMA,selector:SELECTOR_SCHEMA,action,action_name:action===null?null:ACTIONS[action],reason,...extra,trained:false,certified_safe:false,ray_screening_is_not_predicted_path_or_TTC:true,command_derived_measured_motion:false,control_enabled:false,physical_motor_transport:false};}
export function selectProactiveRequest(context,history,allowed,{nowMs=context?.features?.processed_at_ms}={}){
 if(!Array.isArray(allowed)||!allowed.length||new Set(allowed).size!==allowed.length||allowed.some(a=>!Number.isInteger(a)||a<0||a>6))return proposal(null,'invalid_original_navigation_mask');
 const stop=reason=>proposal(allowed.includes(0)?0:null,reason);
 const f=context?.features;
 if(!f||f.schema!=='warirak.proactive-observation.v1'||f.plant_environment!=='warirak-pool-mission-v4r2-dev'||f.source!=='simulation'||f.control_enabled!==false||!Number.isInteger(context.epoch)||context.epoch<0||!finite(nowMs)||!finite(f.processed_at_ms)||f.processed_at_ms>nowMs||!finite(f.observation_at_ms)||nowMs<f.observation_at_ms||nowMs-f.observation_at_ms>300)return stop('new_original_context_required');
 if(f.authority!=='research_channel_armed')return stop('independent_authority_unavailable');
 if(badAck.has(f.ack?.status))return stop('original_ACK_integrity_unavailable');
 if(!Array.isArray(history)||history.length>64||history.some(h=>h.stream?.epoch!==context.epoch||h.features?.schema!==f.schema||!finite(h.features.observation_at_ms)||h.features.observation_at_ms>f.observation_at_ms)||history.some((h,i)=>i>0&&h.features.observation_at_ms<=history[i-1].features.observation_at_ms))return stop('history_epoch_or_clock_invalid');
 if(!['fresh_complete','fresh_partial'].includes(f.range?.status)){
  // Preserve only a sole common-mask intent so the UNCHANGED R2 range guard emits neutral WAIT.
  // This is a new request proposal, not authorization of actual thrust or reuse of motor output.
  return allowed.includes(0)?stop('range_unknown'):allowed.length===1?proposal(allowed[0],'sole_intent_for_independent_neutral_range_guard'):proposal(null,'range_unknown_no_neutral_request');
 }
 if(f.range.status!=='fresh_complete'||!Array.isArray(f.range.ray_m)||f.range.ray_m.length!==8||!f.range.ray_m.every(v=>finite(v)&&v>=0&&v<=1.5))return stop('surround_evidence_incomplete');
 if(context.evidence_new?.range!==true)return stop('distinct_original_range_frame_required');
 if(f.motion?.status!=='measured_projection'||!f.range_motion_synchronized||!Array.isArray(f.ray_velocity_projection_mps)||f.ray_velocity_projection_mps.length!==8||!f.ray_velocity_projection_mps.every(finite)||!finite(f.motion.projection_margin_mps)||f.motion.projection_margin_mps<0)return stop('independent_measured_motion_required');
 if(!finite(f.range.captured_at_ms)||nowMs<f.range.captured_at_ms||nowMs-f.range.captured_at_ms>300)return stop('original_range_time_expired');
 if([f.motion.original_pose_at_ms,f.motion.original_motion_at_ms].some(at=>!finite(at)||at>nowMs||nowMs-at>300))return stop('original_measured_motion_time_expired');
 const c=SELECTOR_CONSTANTS,screen=f.range.ray_m.map((r,i)=>r-Math.max(0,f.ray_velocity_projection_mps[i]+f.motion.projection_margin_mps)*c.screening_horizon_s-c.screening_margin_m);
 let limiting=0;for(let i=1;i<8;i++)if(screen[i]<screen[limiting])limiting=i;
 const previous=[...history].reverse().find(h=>h.decision?.request)?.decision.request.action;
 const pivoting=['PIVOT_LEFT','PIVOT_RIGHT'].includes(previous),avoid=screen[limiting]<c.enter_screening_m||pivoting&&screen[limiting]<c.release_screening_m;
 const choose=(a,reason)=>allowed.includes(a)?proposal(a,reason,{limiting_ray:limiting,screening_m:screen[limiting]}):null;
 if(avoid){
  if([3,4,5].includes(limiting)&&Math.min(screen[0],screen[1],screen[7])>=c.release_screening_m){const p=choose(1,'move_from_rear_hazard_into_observed_front');if(p)return p;}
  const left=Math.min(screen[1],screen[2],screen[3]),right=Math.min(screen[5],screen[6],screen[7]);
  const direction=[1,2,3].includes(limiting)?5:[5,6,7].includes(limiting)?4:left>=right?4:5;
  const pivot=choose(direction,'early_pivot_away_from_limiting_direction');if(pivot)return pivot;
  if(f.range.surround_min_m>=.65){const hold=choose(6,'early_hold_with_original_surround_permission');if(hold)return hold;}
  return stop('no_original_evasive_request_permitted');
 }
 let wanted;
 if(f.target?.visible===true&&finite(f.target.bearing_rad))wanted=f.target.bearing_rad>c.target_bearing_deadband_rad?2:f.target.bearing_rad<-c.target_bearing_deadband_rad?3:1;
 else wanted=Math.min(screen[1],screen[2],screen[3])>=Math.min(screen[5],screen[6],screen[7])?4:5;
 const track=choose(wanted,f.target?.visible?'visible_target_request':'search_with_fresh_surround_evidence');if(track)return track;
 const pivot=choose(wanted===3?5:4,'original_mask_tracking_fallback');if(pivot)return pivot;
 return stop('no_original_tracking_request_permitted');
}
