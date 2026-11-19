import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {PROACTIVE_FEATURES,PROACTIVE_RECORD,ISSUED_CONTROL_RECORD,proactiveObservation,proactiveObservationRecord} from '../ai/proactive_observation.mjs';
import {MissionPoolEnvR2,missionRequestR2} from '../ai/navigation_mission_env_r2.mjs';
const T=1800000000000,ENV='warirak-pool-mission-v4r2-dev';
function observation(){
 const rays=[1.1,1.2,.7,.8,.9,1,.75,1.3];
 return{schema:'warirak.mission-sim-observation.v2',environment:ENV,source:'simulation',timestamp_unix_ms:T,control_enabled:false,sensors:{source:'simulation',timestamp_unix_ms:T,armed:true,manual_override:false,battery_percent:80,clearance_m:rays,range_evidence:{schema:'warirak.range-evidence-state.v2',source:'simulation',status:'fresh',captured_at_ms:T,sequence:4,ranges:structuredClone(rays),fresh_frame_received:true,cached_for_diagnosis_only:false,control_enabled:false}},pose:{schema:'warirak.sim-pose.v1',source:'simulation',method:'simulation_truth',calibrated:true,frame:'pool_fixed',units:'m,rad',timestamp_unix_ms:T,x_m:5,y_m:3,heading_rad:Math.PI/2,position_std_m:.02,heading_std_rad:.025,confidence:.95},motion:{schema:'warirak.sim-motion.v1',source:'simulation',method:'simulation_position_difference',calibrated:true,frame:'pool_fixed',units:'m/s,rad/s',timestamp_unix_ms:T,vx_mps:.2,vy_mps:.1,yaw_rate_rps:.4,speed_std_mps:.008,confidence:.95},actuator_feedback:{schema:'warirak.sim-actuator-feedback.v1',source:'simulation',units:'normalized',timestamp_unix_ms:T,applied_control_sequence:null,request_sequence:null,left:0,right:0,digital_ack_is_not_mechanical_thrust:true},target:{source:'simulation',visible:true,bearing_rad:.2,range_m:2},mission:{mode:'STOP',reason:'explicit_neutral_stop',operator_reset_required:false}};
}
function issued(patch={}){return{schema:ISSUED_CONTROL_RECORD,plant_environment:ENV,source:'simulation',units:'normalized',control_enabled:false,physical_transport:false,control_sequence:10,request_sequence:42,issued_at_ms:T-100,valid_until_ms:T+300,left:.65,right:.65,...patch};}
function feedback(o,patch={}){Object.assign(o.actuator_feedback,{applied_control_sequence:10,request_sequence:42,left:.65,right:.65,...patch});return o;}
const approx=(a,b)=>assert(Math.abs(a-b)<1e-10,`${a} != ${b}`);

test('Body velocity uses independent measured motion and heading, including lateral motion during neutral STOP',()=>{
 const f=proactiveObservation(observation());assert.equal(f.schema,PROACTIVE_FEATURES);
 approx(f.motion.forward_mps,.1);approx(f.motion.lateral_mps,-.2);
 assert.equal(f.motion.yaw_rate_rps,.4);assert.equal(f.ack.status,'neutral_report_without_matched_command');
 assert.equal(f.motion.command_derived_velocity,false);assert.equal(f.motion.margin_is_certified_bound,false);
 assert.equal(f.control_enabled,false);assert.equal(f.physical_motor_transport,false);
});
test('Nonzero motor reports cannot manufacture missing mechanical motion',()=>{
 const o=feedback(observation());o.motion=null;
 const f=proactiveObservation(o,{issuedControls:[issued()]});assert.equal(f.ack.status,'matched_report');
 assert.equal(f.motion.status,'unknown');assert.equal(f.motion.forward_mps,null);assert.equal(f.motion.lateral_mps,null);
 assert(f.ray_velocity_projection_mps.every(v=>v===null));
});
test('Range groups retain side/rear evidence and missing rays stay unknown',()=>{
 const o=observation();let f=proactiveObservation(o);
 assert.equal(f.range.front_min_m,1.1);assert.equal(f.range.left_min_m,.7);assert.equal(f.range.rear_min_m,.8);assert.equal(f.range.right_min_m,.75);
 o.sensors.clearance_m[4]=null;o.sensors.range_evidence.ranges[4]=null;f=proactiveObservation(o);
 assert.equal(f.range.status,'fresh_partial');assert.equal(f.range.rear_min_m,null);assert.equal(f.range.surround_min_m,null);assert.equal(f.range.front_min_m,1.1);
 assert.equal(f.range.gap_between_rays_certified_clear,false);
});
test('Cached, missing and inconsistent range packets cannot provide fresh range features',()=>{
 for(const status of ['cached_wait','missing_wait','invalid','stale']){
  const o=observation();o.sensors.range_evidence.status=status;
  const f=proactiveObservation(o,{nowMs:T+100});assert.equal(f.range.status,'unknown');assert(f.range.ray_m.every(v=>v===null));assert.equal(f.range.captured_at_ms,T);
 }
 const o=observation();o.sensors.range_evidence.ranges[0]=.5;assert.equal(proactiveObservation(o).range.status,'unknown');
});
test('Freshness is derived from original times without retiming old evidence',()=>{
 const o=observation();const before=structuredClone(o),f=proactiveObservation(o,{nowMs:T+301});
 assert.equal(f.observation_at_ms,T);assert.equal(f.processed_at_ms,T+301);assert.equal(f.range.captured_at_ms,T);
 assert.equal(f.range.status,'unknown');assert.equal(f.motion.status,'unknown');assert.equal(f.authority,'unknown');assert.equal(f.target.visible,false);assert.deepEqual(o,before);
 const future=proactiveObservation(o,{nowMs:T-1});assert.equal(future.observation_age_ms,null);assert.equal(future.range.status,'unknown');
});
test('Future subframes and invalid frames/calibration/motion methods are rejected as unknown',()=>{
 for(const change of [o=>o.pose.timestamp_unix_ms=T+1,o=>o.motion.timestamp_unix_ms=T+1,o=>o.pose.frame='body',o=>o.motion.method='command_estimate',o=>o.motion.calibrated=false,o=>o.motion.speed_std_mps=.016,o=>o.pose.heading_std_rad=.11]){
  const o=observation();change(o);assert.equal(proactiveObservation(o).motion.status,'unknown');
 }
 const o=observation();o.sensors.range_evidence.captured_at_ms=T+1;assert.equal(proactiveObservation(o).range.status,'unknown');
});
test('Pose/motion and ray projections require bounded original-time skew',()=>{
 const o=observation();o.pose.timestamp_unix_ms=T-200;
 let f=proactiveObservation(o);assert.equal(f.motion.status,'unknown');assert.equal(f.range_motion_synchronized,false);
 o.motion.timestamp_unix_ms=T-200;f=proactiveObservation(o);assert.equal(f.motion.status,'measured_projection');assert.equal(f.range_motion_synchronized,false);assert(f.ray_velocity_projection_mps.every(v=>v===null));
 o.pose.timestamp_unix_ms=T-100;o.motion.timestamp_unix_ms=T-100;f=proactiveObservation(o);assert.equal(f.range_motion_synchronized,true);
});
test('Ray velocity projection is explicitly not a measured range rate or time to collision',()=>{
 const f=proactiveObservation(observation());approx(f.ray_velocity_projection_mps[0],.1);approx(f.ray_velocity_projection_mps[2],-.2);
 assert.equal(f.ray_projection_is_not_range_rate_or_time_to_collision,true);assert.equal(f.range.range_rate_mps,null);
});
test('Manual override, disarm, low battery and assistance are never observation-based movement authorization',()=>{
 const o=observation();o.sensors.manual_override=true;o.sensors.armed=false;assert.equal(proactiveObservation(o).authority,'manual');
 o.sensors.manual_override=false;assert.equal(proactiveObservation(o).authority,'disarmed');
 o.sensors.armed=true;o.sensors.battery_percent=24;assert.equal(proactiveObservation(o).authority,'low_battery');
 o.sensors.battery_percent=80;o.mission.mode='ACTUATION_UNAVAILABLE';assert.equal(proactiveObservation(o).authority,'assistance_required');
 o.mission.mode='STOP';o.mission.operator_reset_required=true;assert.equal(proactiveObservation(o).authority,'assistance_required');
 delete o.sensors.manual_override;assert.equal(proactiveObservation(o).authority,'unknown');
 assert.equal(proactiveObservation(o).control_enabled,false);
});
test('A matched ACK requires the original issued control identity, values and time window',()=>{
 const o=feedback(observation()),c=issued(),f=proactiveObservation(o,{issuedControls:[c]});
 assert.equal(f.ack.status,'matched_report');assert.equal(f.ack.issued_at_ms,T-100);assert.equal(f.ack.original_feedback_at_ms,T);assert.equal(f.ack.feedback_after_issue_ms,100);
 assert.equal(f.ack.matched_command_still_valid_at_processing,true);assert.equal(f.ack.digital_ack_is_not_mechanical_motion,true);
 assert.equal(f.ack.feedback_delay_is_not_transport_latency_measurement,true);
 for(const change of [o=>o.actuator_feedback.request_sequence=99,o=>o.actuator_feedback.left=.5]){const bad=structuredClone(o);change(bad);assert.equal(proactiveObservation(bad,{issuedControls:[c]}).ack.status,'inconsistent_report');}
 assert.equal(proactiveObservation(o).ack.status,'unmatched_report');
});
test('Feedback at expiry may match historical R2 evidence but never refreshes command lifetime',()=>{
 const o=feedback(observation()),c=issued({issued_at_ms:T-400,valid_until_ms:T});
 const f=proactiveObservation(o,{issuedControls:[c]});assert.equal(f.ack.status,'matched_report');assert.equal(f.ack.matched_command_still_valid_at_processing,false);assert.equal(f.ack.valid_until_ms,T);
});
test('600ms feedback cannot validate a 400ms command or extend its lifetime',()=>{
 const o=feedback(observation()),c=issued({issued_at_ms:T-600,valid_until_ms:T-200});
 const f=proactiveObservation(o,{issuedControls:[c]});assert.equal(f.ack.status,'feedback_after_command_window');assert.equal(f.ack.matched_command_still_valid_at_processing,false);assert.equal(f.ack.matched_control_sequence,null);
});
test('Conflicting/oversized/foreign ledgers and future ACKs remain unverified',()=>{
 const o=feedback(observation());
 for(const controls of [[issued(),issued({left:.2})],[issued({source:'hardware'})],Array.from({length:17},(_,i)=>issued({control_sequence:i}))])assert.equal(proactiveObservation(o,{issuedControls:controls}).ack.status,'invalid_issued_control_ledger');
 o.actuator_feedback.timestamp_unix_ms=T+1;assert.equal(proactiveObservation(o,{issuedControls:[issued()]}).ack.status,'unknown');
});
test('Full audit records preserve omitted target/sensor/ledger fields without exposing position as a feature',()=>{
 const o=feedback(observation()),controls=[issued()],before=structuredClone(o),r=proactiveObservationRecord(o,{issuedControls:controls});
 assert.equal(r.schema,PROACTIVE_RECORD);assert.deepEqual(r.original_observation,before);assert.deepEqual(r.original_issued_controls,controls);assert.equal(r.original_inputs_retained,true);
 assert.equal(r.features.target.bearing_rad,.2);assert.equal(r.features.motion.absolute_position_in_features,false);assert.equal(r.features.motion.x_m,undefined);
 r.original_observation.target.bearing_rad=9;r.original_issued_controls[0].left=-1;assert.deepEqual(o,before);assert.equal(controls[0].left,.65);
});
test('Reduced postmortem snapshots and other environments cannot masquerade as full packets',()=>{
 assert.throws(()=>proactiveObservation({at_ms:T,clearance_m:Array(8).fill(1)}));
 const o=observation();o.environment='warirak-pool-mission-v4-dev';assert.throws(()=>proactiveObservation(o));
});
test('Integration with unchanged synthetic STOP retains independently measured current motion',()=>{
 const e=new MissionPoolEnvR2(7,{profile:'stress',record:true,fixture:{x:5,y:3,heading:0,target:{x:9,y:3,class_id:0},obstacles:[],leftGain:1,rightGain:1,drift:{x:.08,y:0},delayTicks:0,positionNoise:0,velocityNoise:0,headingNoise:0,clearanceNoise:0,sensorDropout:0,targetDropout:0,bearingNoise:0,rangeNoise:0}});
 e.step(missionRequestR2(0,e.now(),'STOP'));
 const f=proactiveObservation(e.observe());approx(f.motion.forward_mps,.08);assert.equal(f.ack.status,'neutral_report_without_matched_command');assert.equal(e.trace[0].applied.left,0);assert(e.x>5);assert.equal(f.control_enabled,false);
});
test('Frozen R3 sources, policies and diagnostic evidence remain unchanged',()=>{
 const protocol=JSON.parse(fs.readFileSync(new URL('../work/navigation-only-r3-experiment/protocol.json',import.meta.url)));
 for(const [file,hash] of Object.entries(protocol.source_sha256))assert.equal(createHash('sha256').update(fs.readFileSync(new URL('../'+file,import.meta.url))).digest('hex'),hash,file);
});
