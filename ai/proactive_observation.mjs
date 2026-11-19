// Research observation/recording only. No policy, command generation, timers or transport.
export const PROACTIVE_FEATURES='warirak.proactive-observation.v1';
export const PROACTIVE_RECORD='warirak.proactive-observation-record.v1';
export const ISSUED_CONTROL_RECORD='warirak.proactive-issued-control.v1';
const ENV='warirak-pool-mission-v4r2-dev',OBS='warirak.mission-sim-observation.v2';
const MAX_AGE=300,MAX_SKEW=100;
const ANGLES=[0,Math.PI/4,Math.PI/2,3*Math.PI/4,Math.PI,-3*Math.PI/4,-Math.PI/2,-Math.PI/4];
const MODES=['STOP','TRACKING','HOLD','WATCHDOG_STOP','WAIT_RANGE_UPDATE','FAULT_STOP','HOLD_UNAVAILABLE','RECOVERY_REQUIRED','ACTUATION_UNAVAILABLE','PROGRESS_UNCERTAIN','MANUAL_OVERRIDE','DISARMED'];
const ASSIST=['FAULT_STOP','HOLD_UNAVAILABLE','RECOVERY_REQUIRED','ACTUATION_UNAVAILABLE','PROGRESS_UNCERTAIN'];
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const uint=v=>Number.isInteger(v)&&v>=0;
const age=(at,now)=>finite(at)&&at>0&&finite(now)&&now>=at?now-at:null;
const fresh=(at,now)=>age(at,now)!==null&&age(at,now)<=MAX_AGE;
const conf=v=>finite(v)&&v>=.8&&v<=1;
const eq=(a,b)=>JSON.stringify(a)===JSON.stringify(b);

function checkEnvelope(o,now){
 if(o?.schema!==OBS||o.environment!==ENV||o.source!=='simulation'||o.control_enabled!==false||!finite(o.timestamp_unix_ms)||o.timestamp_unix_ms<=0||!finite(now)||now<=0)throw Error('Full synthetic R2 observation and original clock required');
}
function rangeFeatures(o,now,packetFresh){
 const s=o.sensors,r=s?.range_evidence,c=s?.clearance_m;
 const valid=packetFresh&&s?.source==='simulation'&&fresh(s.timestamp_unix_ms,now)&&r?.schema==='warirak.range-evidence-state.v2'&&r.source==='simulation'&&r.control_enabled===false&&r.status==='fresh'&&r.fresh_frame_received===true&&r.cached_for_diagnosis_only===false&&uint(r.sequence)&&fresh(r.captured_at_ms,now)&&r.captured_at_ms<=s.timestamp_unix_ms&&r.captured_at_ms<=o.timestamp_unix_ms&&Array.isArray(c)&&c.length===8&&c.every(v=>v===null||finite(v)&&v>=0&&v<=1.5)&&eq(c,r.ranges);
 const rays=valid?structuredClone(c):Array(8).fill(null);
 const min=indices=>indices.every(i=>finite(rays[i]))?Math.min(...indices.map(i=>rays[i])):null;
 return{status:valid?(rays.every(finite)?'fresh_complete':'fresh_partial'):'unknown',original_status:r?.status??null,original_sequence:uint(r?.sequence)?r.sequence:null,captured_at_ms:finite(r?.captured_at_ms)?r.captured_at_ms:null,age_ms:age(r?.captured_at_ms,now),ray_m:rays,front_min_m:min([0,1,7]),left_min_m:min([1,2,3]),rear_min_m:min([3,4,5]),right_min_m:min([5,6,7]),surround_min_m:min([0,1,2,3,4,5,6,7]),gap_between_rays_certified_clear:false,range_rate_mps:null,range_rate_reason:'No aligned same-surface temporal estimator is implemented'};
}
function motionFeatures(o,now,packetFresh){
 const p=o.pose,m=o.motion;
 const pose=packetFresh&&p?.schema==='warirak.sim-pose.v1'&&p.source==='simulation'&&p.method==='simulation_truth'&&p.calibrated===true&&p.frame==='pool_fixed'&&p.units==='m,rad'&&fresh(p.timestamp_unix_ms,now)&&p.timestamp_unix_ms<=o.timestamp_unix_ms&&conf(p.confidence)&&[p.x_m,p.y_m,p.heading_rad,p.position_std_m,p.heading_std_rad].every(finite)&&p.x_m>=-.1&&p.x_m<=10.1&&p.y_m>=-.1&&p.y_m<=6.1&&Math.abs(p.heading_rad)<=Math.PI&&p.position_std_m>=0&&p.position_std_m<=.05&&p.heading_std_rad>=0&&p.heading_std_rad<=.1;
 const motion=packetFresh&&m?.schema==='warirak.sim-motion.v1'&&m.source==='simulation'&&m.method==='simulation_position_difference'&&m.calibrated===true&&m.frame==='pool_fixed'&&m.units==='m/s,rad/s'&&fresh(m.timestamp_unix_ms,now)&&m.timestamp_unix_ms<=o.timestamp_unix_ms&&conf(m.confidence)&&[m.vx_mps,m.vy_mps,m.yaw_rate_rps,m.speed_std_mps].every(finite)&&Math.hypot(m.vx_mps,m.vy_mps)<=3&&Math.abs(m.yaw_rate_rps)<=10&&m.speed_std_mps>=0&&m.speed_std_mps<=.015;
 const synced=pose&&motion&&Math.abs(p.timestamp_unix_ms-m.timestamp_unix_ms)<=MAX_SKEW;
 const forward=synced?m.vx_mps*Math.cos(p.heading_rad)+m.vy_mps*Math.sin(p.heading_rad):null;
 const lateral=synced?-m.vx_mps*Math.sin(p.heading_rad)+m.vy_mps*Math.cos(p.heading_rad):null;
 // Engineering margin from declared synthetic uncertainty; NOT a certified probability bound.
 const margin=synced?2*Math.SQRT2*m.speed_std_mps+(Math.hypot(m.vx_mps,m.vy_mps)+2*Math.SQRT2*m.speed_std_mps)*Math.sin(2*p.heading_std_rad):null;
 return{status:synced?'measured_projection':'unknown',original_pose_at_ms:finite(p?.timestamp_unix_ms)?p.timestamp_unix_ms:null,original_motion_at_ms:finite(m?.timestamp_unix_ms)?m.timestamp_unix_ms:null,pose_motion_skew_ms:pose&&motion?Math.abs(p.timestamp_unix_ms-m.timestamp_unix_ms):null,forward_mps:forward,lateral_mps:lateral,yaw_rate_rps:synced?m.yaw_rate_rps:null,declared_speed_std_mps:motion?m.speed_std_mps:null,declared_heading_std_rad:pose?p.heading_std_rad:null,projection_margin_mps:margin,margin_is_certified_bound:false,command_derived_velocity:false,absolute_position_in_features:false};
}
function validIssued(c,now){
 return c?.schema===ISSUED_CONTROL_RECORD&&c.plant_environment===ENV&&c.source==='simulation'&&c.units==='normalized'&&c.control_enabled===false&&c.physical_transport===false&&uint(c.control_sequence)&&uint(c.request_sequence)&&finite(c.issued_at_ms)&&c.issued_at_ms>0&&c.issued_at_ms<=now&&finite(c.valid_until_ms)&&c.valid_until_ms>c.issued_at_ms&&c.valid_until_ms-c.issued_at_ms<=400&&[c.left,c.right].every(v=>finite(v)&&Math.abs(v)<=1);
}
function ackFeatures(o,now,controls,packetFresh){
 const f=o.actuator_feedback;
 const result={status:'unknown',original_feedback_at_ms:finite(f?.timestamp_unix_ms)?f.timestamp_unix_ms:null,feedback_age_ms:age(f?.timestamp_unix_ms,now),matched_control_sequence:null,matched_request_sequence:null,issued_at_ms:null,valid_until_ms:null,matched_command_still_valid_at_processing:false,feedback_after_issue_ms:null,digital_ack_is_not_mechanical_motion:true,feedback_delay_is_not_transport_latency_measurement:true};
 const valid=packetFresh&&f?.schema==='warirak.sim-actuator-feedback.v1'&&f.source==='simulation'&&f.units==='normalized'&&fresh(f.timestamp_unix_ms,now)&&f.timestamp_unix_ms<=o.timestamp_unix_ms&&[f.left,f.right].every(v=>finite(v)&&Math.abs(v)<=1)&&f.digital_ack_is_not_mechanical_thrust===true;
 if(!valid)return result;
 if(!Array.isArray(controls)||controls.length>16||controls.some(c=>!validIssued(c,now))||new Set(controls.map(c=>c.control_sequence)).size!==controls.length)return{...result,status:'invalid_issued_control_ledger'};
 if(!uint(f.applied_control_sequence)||!uint(f.request_sequence))return{...result,status:f.left===0&&f.right===0?'neutral_report_without_matched_command':'unmatched_report'};
 const c=controls.find(c=>c.control_sequence===f.applied_control_sequence);
 if(!c)return{...result,status:'unmatched_report'};
 if(c.request_sequence!==f.request_sequence||c.left!==f.left||c.right!==f.right||f.timestamp_unix_ms<c.issued_at_ms)return{...result,status:'inconsistent_report'};
 // R2 feedback is stamped after its integration step, not at receiver application.
 // The frozen R2 ACK contract permits equality. Neither equality nor a match grants thrust.
 if(f.timestamp_unix_ms>c.valid_until_ms)return{...result,status:'feedback_after_command_window'};
 return{...result,status:'matched_report',matched_control_sequence:c.control_sequence,matched_request_sequence:c.request_sequence,issued_at_ms:c.issued_at_ms,valid_until_ms:c.valid_until_ms,matched_command_still_valid_at_processing:now<c.valid_until_ms,feedback_after_issue_ms:f.timestamp_unix_ms-c.issued_at_ms};
}

export function proactiveObservation(o,{nowMs=o?.timestamp_unix_ms,issuedControls=[]}={}){
 checkEnvelope(o,nowMs);
 const packetFresh=fresh(o.timestamp_unix_ms,nowMs),s=o.sensors;
 const sensorFresh=packetFresh&&s?.source==='simulation'&&fresh(s.timestamp_unix_ms,nowMs)&&s.timestamp_unix_ms<=o.timestamp_unix_ms;
 const flagsKnown=sensorFresh&&typeof s.armed==='boolean'&&typeof s.manual_override==='boolean'&&finite(s.battery_percent)&&s.battery_percent>=0&&s.battery_percent<=100;
 const mode=MODES.includes(o.mission?.mode)?o.mission.mode:null;
 let authority='unknown';
 if(sensorFresh&&s.manual_override===true)authority='manual';
 else if(sensorFresh&&s.armed===false)authority='disarmed';
 else if(flagsKnown&&s.armed&&s.manual_override===false)authority=ASSIST.includes(mode)||o.mission?.operator_reset_required===true?'assistance_required':s.battery_percent<25?'low_battery':'research_channel_armed';
 const range=rangeFeatures(o,nowMs,packetFresh),motion=motionFeatures(o,nowMs,packetFresh),ack=ackFeatures(o,nowMs,issuedControls,packetFresh);
 const paired=range.status.startsWith('fresh')&&motion.status==='measured_projection'&&Math.max(range.captured_at_ms,motion.original_pose_at_ms,motion.original_motion_at_ms)-Math.min(range.captured_at_ms,motion.original_pose_at_ms,motion.original_motion_at_ms)<=MAX_SKEW;
 const radial=paired?ANGLES.map(a=>motion.forward_mps*Math.cos(a)+motion.lateral_mps*Math.sin(a)):Array(8).fill(null);
 const t=o.target,visible=packetFresh&&t?.source==='simulation'&&t.visible===true&&finite(t.bearing_rad)&&Math.abs(t.bearing_rad)<=Math.PI&&finite(t.range_m)&&t.range_m>=0;
 return{schema:PROACTIVE_FEATURES,plant_environment:ENV,source:'simulation',observation_at_ms:o.timestamp_unix_ms,processed_at_ms:nowMs,observation_age_ms:age(o.timestamp_unix_ms,nowMs),authority,mission_mode:mode,range,motion,ray_velocity_projection_mps:radial,ray_projection_is_not_range_rate_or_time_to_collision:true,range_motion_synchronized:paired,ack,target:{visible,bearing_rad:visible?t.bearing_rad:null,range_m:visible?t.range_m:null,observation_envelope_at_ms:o.timestamp_unix_ms,independent_camera_capture_timestamp_available:false},full_sensor_metadata_present:flagsKnown,observation_only:true,policy_implemented:false,control_enabled:false,physical_motor_transport:false};
}

export function proactiveObservationRecord(o,options={}){
 const features=proactiveObservation(o,options);
 return{schema:PROACTIVE_RECORD,source:'simulation',features,original_observation:structuredClone(o),original_issued_controls:structuredClone(options.issuedControls??[]),original_inputs_retained:true,full_record_is_diagnostic_not_policy_input:true,physical_motor_transport:false,control_enabled:false};
}
