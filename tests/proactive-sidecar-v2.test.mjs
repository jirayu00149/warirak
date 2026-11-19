import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {ProactiveSidecarV2 as ProactiveSidecar,SIDECAR_V2_SCHEMA} from '../ai/proactive_sidecar_v2.mjs';
import {ProactiveSidecarR2V2 as ProactiveSidecarR2} from '../ai/proactive_sidecar_r2_v2.mjs';
import {ISSUED_CONTROL_RECORD} from '../ai/proactive_observation.mjs';
import {MissionPoolEnvR2,missionRequestR2} from '../ai/navigation_mission_env_r2.mjs';
const T=1800000000000,ENV='warirak-pool-mission-v4r2-dev';
function observation(at=T,sequence=1){
 const rays=Array(8).fill(1.2);
 return{schema:'warirak.mission-sim-observation.v2',environment:ENV,source:'simulation',timestamp_unix_ms:at,control_enabled:false,sensors:{source:'simulation',timestamp_unix_ms:at,armed:true,manual_override:false,battery_percent:80,clearance_m:rays,range_evidence:{schema:'warirak.range-evidence-state.v2',source:'simulation',status:'fresh',captured_at_ms:at,sequence,ranges:[...rays],fresh_frame_received:true,cached_for_diagnosis_only:false,control_enabled:false}},pose:{schema:'warirak.sim-pose.v1',source:'simulation',method:'simulation_truth',calibrated:true,frame:'pool_fixed',units:'m,rad',timestamp_unix_ms:at,x_m:5,y_m:3,heading_rad:0,position_std_m:.005,heading_std_rad:.005,confidence:.95},motion:{schema:'warirak.sim-motion.v1',source:'simulation',method:'simulation_position_difference',calibrated:true,frame:'pool_fixed',units:'m/s,rad/s',timestamp_unix_ms:at,vx_mps:.08,vy_mps:.01,yaw_rate_rps:0,speed_std_mps:.002,confidence:.95},actuator_feedback:null,target:{visible:true,bearing_rad:.2,range_m:2,source:'simulation'},mission:{mode:'STOP',reason:'explicit_neutral_stop',operator_reset_required:false}};
}
const req=(sequence,at=T,action='FORWARD')=>missionRequestR2(sequence,at,action);
const issued=(sequence=1,request=0,at=T)=>({schema:ISSUED_CONTROL_RECORD,plant_environment:ENV,source:'simulation',units:'normalized',control_enabled:false,physical_transport:false,control_sequence:sequence,request_sequence:request,issued_at_ms:at,valid_until_ms:at+400,left:.65,right:.65});
function feedback(o,c){o.actuator_feedback={schema:'warirak.sim-actuator-feedback.v1',source:'simulation',units:'normalized',timestamp_unix_ms:o.timestamp_unix_ms,applied_control_sequence:c.control_sequence,request_sequence:c.request_sequence,left:c.left,right:c.right,digital_ack_is_not_mechanical_thrust:true};return o;}
function pool(patch={}){return new MissionPoolEnvR2(7,{profile:'stress',record:true,fixture:{x:5,y:3,heading:0,target:{x:9,y:3,class_id:0},obstacles:[],leftGain:1,rightGain:1,drift:{x:.08,y:.01},delayTicks:0,positionNoise:0,velocityNoise:0,headingNoise:0,clearanceNoise:0,sensorDropout:0,targetDropout:0,bearingNoise:0,rangeNoise:0,...patch}});}

test('Identical duplicate packets do not append history, advance capture time or create a decision context',()=>{
 const s=new ProactiveSidecar(),o=observation();assert.equal(s.capture(o).status,'accepted');
 const d=s.capture(o,{receivedAtMs:T+100});assert.equal(d.status,'duplicate');assert.equal(d.new_observation,false);assert.equal(d.decision_context,null);assert.equal(s.records().length,1);
 assert.equal(s.records()[0].features.observation_at_ms,T);assert.equal(s.records()[0].features.processed_at_ms,T);
 assert.equal(s.noteDecision(req(1,T)).status,'not_recorded');
 const reordered=Object.fromEntries(Object.entries(o).reverse());assert.equal(s.capture(reordered,{receivedAtMs:T+200}).status,'duplicate');
});
test('Conflicting same-time observations latch a recorder fault without rewriting accepted inputs',()=>{
 const s=new ProactiveSidecar(),o=observation();s.capture(o);const bad=structuredClone(o);bad.target.bearing_rad=.4;
 assert.equal(s.capture(bad).reason,'observation_timestamp_conflict');assert.equal(s.records()[0].original_observation.target.bearing_rad,.2);assert.deepEqual(s.decisionWindow(),[]);
 assert.equal(s.capture(observation(T+100,2)).status,'fault');
});
test('Processing/observation clock regression and future packets fail closed in the recorder',()=>{
 const cases=[{second:observation(T+200,3),now:T-1,reason:'processing_clock_regression'},{second:observation(T-1,2),now:T+100,reason:'observation_clock_regression'},{second:observation(T+200,2),now:T+100,reason:'future_observation'}];
 for(const c of cases){const s=new ProactiveSidecar();s.capture(observation());assert.equal(s.capture(c.second,{receivedAtMs:c.now}).reason,c.reason);assert.equal(s.snapshot().commands_generated,0);}
});
test('Range sequence regression, conflict and duplicate fresh claims are distinguished',()=>{
 for(const kind of ['regression','conflict','repeated']){
  const s=new ProactiveSidecar(),first=observation(T,5);s.capture(first);const o=observation(T+100,6);
  if(kind==='regression')o.sensors.range_evidence.sequence=4;
  else{Object.assign(o.sensors.range_evidence,{sequence:5,captured_at_ms:T,ranges:[...first.sensors.clearance_m]});if(kind==='conflict'){o.sensors.clearance_m[0]=.5;o.sensors.range_evidence.ranges[0]=.5;}}
  const r=s.capture(o);assert.equal(r.status,'fault');assert.match(r.reason,kind==='regression'?/regression/:kind==='conflict'?/conflict/:/repeated_range/);
 }
});
test('Cached body-relative ranges retain original times and remain unknown after a heading change',()=>{
 const s=new ProactiveSidecar(),first=observation();s.capture(first);const o=observation(T+100,2);o.pose.heading_rad=.5;
 o.sensors.range_evidence={...structuredClone(first.sensors.range_evidence),status:'cached_wait',fresh_frame_received:false,cached_for_diagnosis_only:true};
 const r=s.capture(o);assert.equal(r.status,'accepted');assert.equal(r.decision_context.evidence_new.range,false);assert.equal(r.decision_context.features.range.captured_at_ms,T);assert(r.decision_context.features.range.ray_m.every(v=>v===null));
});
test('A delayed original packet remains auditable but provides no fresh context or retimed evidence',()=>{
 const s=new ProactiveSidecar(),r=s.capture(observation(),{receivedAtMs:T+301});assert.equal(r.status,'accepted');assert.equal(r.decision_context,null);
 const record=s.records()[0];assert.equal(record.features.observation_at_ms,T);assert.equal(record.features.range.captured_at_ms,T);assert.equal(record.features.range.status,'unknown');assert.equal(record.features.motion.status,'unknown');assert.equal(s.decisionWindow().length,0);
});
test('A frame already stale at the sender cannot claim to be fresh',()=>{
 const s=new ProactiveSidecar(),o=observation();o.sensors.range_evidence.captured_at_ms=T-400;assert.equal(s.capture(o).reason,'invalid_fresh_range_frame');
});
test('A stream starting on cached data cannot later relabel the same frame as fresh',()=>{
 const s=new ProactiveSidecar(),o=observation();Object.assign(o.sensors.range_evidence,{status:'cached_wait',fresh_frame_received:false,cached_for_diagnosis_only:true});s.capture(o);
 const next=observation(T+100,1);next.sensors.range_evidence.captured_at_ms=T;assert.equal(s.capture(next).reason,'repeated_range_claimed_fresh');
});
test('Held motion is not new independent evidence and expires at its original deadline',()=>{
 const s=new ProactiveSidecar(),first=observation();s.capture(first);
 const a=observation(T+100,2);a.motion=structuredClone(first.motion);let r=s.capture(a);assert.equal(r.decision_context.evidence_new.motion,false);assert.equal(r.decision_context.features.motion.original_motion_at_ms,T);
 const b=observation(T+400,3);b.motion=structuredClone(first.motion);r=s.capture(b);assert.equal(r.decision_context.features.motion.status,'unknown');assert.equal(r.decision_context.features.motion.forward_mps,null);
});
test('Future, conflicting and regressing subframes latch stream errors',()=>{
 for(const [field,modify,reason] of [['motion',m=>m.timestamp_unix_ms=T+200,'motion_future_or_invalid_time'],['pose',p=>p.timestamp_unix_ms=T-1,'pose_clock_regression'],['motion',m=>{m.timestamp_unix_ms=T;m.vx_mps=.4;},'motion_timestamp_conflict']]){
  const s=new ProactiveSidecar();s.capture(observation());const o=observation(T+100,2);modify(o[field]);assert.equal(s.capture(o).reason,reason);
 }
});
test('History/ledger/events remain bounded and external mutations cannot change stored evidence',()=>{
 const s=new ProactiveSidecar({historyLimit:3,ledgerLimit:2,eventLimit:4});
 for(let i=0;i<20;i++){const at=T+i*100;s.capture(observation(at,i+1));s.noteDecision(req(i,at));s.noteIssuedControl(issued(i+1,i,at),{atMs:at});}
 const snap=s.snapshot();assert.equal(snap.records.length,3);assert.equal(snap.decision_window.length,3);assert.equal(snap.issued_controls.length,2);assert(snap.events.length<=4);
 snap.records[0].original_observation.target.range_m=99;snap.decision_window[0].features.motion.forward_mps=99;snap.issued_controls[0].left=-1;
 assert.notEqual(s.records()[0].original_observation.target.range_m,99);assert.notEqual(s.decisionWindow()[0].features.motion.forward_mps,99);assert.equal(s.issuedControls()[0].left,.65);
});
test('Oversized and non-JSON packets cannot fill retained history',()=>{
 const s=new ProactiveSidecar(),o=observation();o.extra='x'.repeat(32768);assert.equal(s.capture(o).reason,'packet_size_limit');assert.equal(s.records().length,0);
 const a=new ProactiveSidecar(),bad=observation();bad.motion.vx_mps=NaN;assert.equal(a.capture(bad).status,'fault');assert.equal(a.records().length,0);
});
test('Original control identity matches ACK and never substitutes the latest request sequence',()=>{
 const s=new ProactiveSidecar(),c=issued(7,42);s.capture(observation());s.noteDecision(req(42));s.noteIssuedControl(c,{atMs:T});
 const r=s.capture(feedback(observation(T+100,2),c));assert.equal(r.decision_context.features.ack.status,'matched_report');assert.equal(r.decision_context.features.ack.matched_control_sequence,7);assert.equal(r.decision_context.features.ack.matched_request_sequence,42);
 s.noteDecision(req(43,T+100));assert.equal(s.records().at(-1).features.ack.matched_request_sequence,42);assert.equal(s.records().at(-1).decision.request.sequence,43);
});
test('Inconsistent ACK and duplicate/conflicting issued controls never create apparent mechanical motion',()=>{
 const s=new ProactiveSidecar(),c=issued();s.capture(observation());s.noteIssuedControl(c,{atMs:T});assert.equal(s.noteIssuedControl(c,{atMs:T}).status,'duplicate_control_not_new');
 const o=feedback(observation(T+100,2),c);o.actuator_feedback.left=.2;o.motion=null;
 const r=s.capture(o);assert.equal(r.decision_context.features.ack.status,'inconsistent_report');assert.equal(r.decision_context.features.motion.forward_mps,null);
 assert.equal(s.noteIssuedControl({...c,left:.2},{atMs:T+100}).reason,'issued_control_sequence_conflict');
});
test('Manual/disarm boundaries discard active decision history and ledger while retaining diagnostic requests',()=>{
 for(const flags of [{manual_override:true},{armed:false}]){
  const s=new ProactiveSidecar();s.capture(observation());s.noteDecision(req(0));s.noteIssuedControl(issued(),{atMs:T});
  const o=observation(T+100,2);Object.assign(o.sensors,flags);const r=s.capture(o);assert.equal(r.decision_context,null);assert.equal(s.issuedControls().length,0);assert.equal(s.decisionWindow().length,0);
  assert.equal(s.noteDecision(req(1,T+100)).status,'context_suppressed');assert.equal(s.records().at(-1).decision.request.sequence,1);
  const next=s.capture(observation(T+200,3));assert.equal(next.decision_context.features.ack.status,'unknown');assert.equal(s.records().length,3);assert.equal(s.decisionWindow().length,1);
 }
});
test('Cancel requires a new observation and new original request; no cached command is restored',()=>{
 const s=new ProactiveSidecar();s.capture(observation());s.noteDecision(req(0));s.noteIssuedControl(issued(),{atMs:T});assert.equal(s.cancel(T+1).commands_generated,0);
 assert.equal(s.issuedControls().length,0);assert.equal(s.decisionWindow().length,0);assert.equal(s.noteDecision(req(1)).status,'not_recorded');
 s.capture(observation(T+100,2));assert.equal(s.decisionWindow().length,0);assert.equal(s.noteDecision(req(1,T+100)).status,'recorded_original_request');assert.equal(s.decisionWindow().length,1);assert.equal(s.issuedControls().length,0);
});
test('Old ACKs and duplicate issued controls cannot repopulate the ledger after cancel',()=>{
 const s=new ProactiveSidecar(),c=issued();s.capture(observation());s.noteDecision(req(0));s.noteIssuedControl(c,{atMs:T});s.cancel(T+1);
 s.capture(feedback(observation(T+100,2),c));assert.equal(s.records().at(-1).features.ack.status,'unmatched_report');s.noteDecision(req(1,T+100));
 assert.equal(s.noteIssuedControl(c,{atMs:T+100}).status,'duplicate_control_not_new');assert.equal(s.issuedControls().length,0);
});
test('Stream faults need an explicit fresh disarmed reset and retain monotonic watermarks',()=>{
 const s=new ProactiveSidecar();s.capture(observation());s.noteDecision(req(5));const conflict=observation();conflict.target.range_m=3;s.capture(conflict);
 assert.equal(s.reset(observation(T+100,2)).status,'reset_rejected');
 const disarmed=observation(T+100,2);disarmed.sensors.armed=false;assert.equal(s.reset(disarmed).status,'accepted');assert.equal(s.snapshot().stream_fault,null);assert.equal(s.decisionWindow().length,0);
 s.capture(observation(T+200,3));assert.equal(s.noteDecision(req(5,T+200)).status,'fault');assert.equal(s.records().at(-1).decision.status,'rejected');
});
test('Operator assistance remains distinct from AI navigation requests',()=>{
 const ai=new ProactiveSidecar();ai.capture(observation());assert.equal(ai.noteDecision(req(0,T,'RECOVERY_REQUEST')).status,'fault');
 const operator=new ProactiveSidecar();operator.capture(observation());assert.equal(operator.noteDecision(req(0,T,'RECOVERY_REQUEST'),{owner:'operator'}).status,'recorded_original_request');assert.equal(operator.records()[0].decision.owner,'operator');
});
test('Null decisions are recorded explicitly in the active history',()=>{
 const s=new ProactiveSidecar();s.capture(observation());s.noteDecision(null);assert.equal(s.decisionWindow()[0].decision.status,'no_new_request');assert.equal(s.decisionWindow()[0].decision.request,null);
});
test('Simulation wrapper preserves the complete original R2 plant/guard trajectory',()=>{
 const a=pool(),b=pool(),w=new ProactiveSidecarR2(a),actions=['FORWARD','FORWARD','TURN_LEFT','STOP','PIVOT_RIGHT','HOLD','STOP'];
 for(const action of actions){const request=req(a.steps,a.now(),action),original=structuredClone(request);w.step(request);b.step(request);assert.deepEqual(a.snapshot(),b.snapshot());assert.deepEqual(request,original);assert(a.trace.length<=1);}
 const record=w.sidecar.records().at(-1);assert(record.original_observation.target);assert.equal(typeof record.original_observation.sensors.armed,'boolean');assert(record.transition.issued);assert(record.transition.applied);assert.equal(record.transition.before.timestamp_unix_ms,record.features.observation_at_ms);
});
test('Wrapper passes null unchanged and cannot extend original request lifetime',()=>{
 const e=pool(),w=new ProactiveSidecarR2(e);w.step(req(0,e.now()));const expiry=e.lastRequest.valid_until_ms;
 for(let i=0;i<5;i++)w.step(null);
 assert.equal(e.mode,'WATCHDOG_STOP');assert.equal(e.trace[0].applied.left,0);assert(w.sidecar.records().slice(1).every(r=>r.decision.request===null));
 assert(w.sidecar.records().every(r=>r.transition.issued.request_sequence===null||r.transition.issued.valid_until_ms<=expiry));
});
test('Manual and disarm keep priority, neutral outputs and passive current in the wrapped plant',()=>{
 for(const flags of [{manual_override:true},{armed:false}]){
  const e=pool(),w=new ProactiveSidecarR2(e),x=e.x;e.setFaults(flags);const result=w.step(req(0,e.now()));
  assert.equal(e.trace[0].applied.left,0);assert.equal(e.trace[0].applied.right,0);assert(e.x>x);assert.equal(result.recorder_fault,null);assert.equal(w.sidecar.decisionWindow().length,0);
 }
});
test('600ms transport remains unavailable under 400ms TTL; recorder never changes guard behavior',()=>{
 const a=pool({delayTicks:6}),b=pool({delayTicks:6}),w=new ProactiveSidecarR2(a);
 for(let i=0;i<9;i++){const request=req(i,a.now());w.step(request);b.step(request);assert.deepEqual(a.snapshot(),b.snapshot());assert.equal(a.trace[0].applied.left,0);}
 assert.equal(a.mode,'ACTUATION_UNAVAILABLE');assert.equal(w.sidecar.snapshot().commands_generated,0);
});
test('Invalid original decisions and the resulting real simulated transition remain auditable',()=>{
 const e=pool(),w=new ProactiveSidecarR2(e),bad={...req(0,e.now()),valid_until_ms:e.now()-1};w.step(bad);
 const r=w.sidecar.records()[0];assert.equal(r.decision.status,'rejected');assert.deepEqual(r.decision.request,bad);assert.equal(e.mode,'FAULT_STOP');assert(r.transition);assert.equal(r.transition.applied.left,0);
});
test('Frozen observer and R3 evidence files are preserved',()=>{
 const observer=JSON.parse(fs.readFileSync(new URL('../outputs/Warirak_Proactive_Observation_Audit.json',import.meta.url)));
 const protocol=JSON.parse(fs.readFileSync(new URL('../work/navigation-only-r3-experiment/protocol.json',import.meta.url)));
 for(const [file,hash] of Object.entries({...observer.source_files,...protocol.source_sha256}))assert.equal(createHash('sha256').update(fs.readFileSync(new URL('../'+file,import.meta.url))).digest('hex'),hash,file);
});

function cached(at,sequence,captureAt=at,status='cached_wait'){
 const o=observation(at,sequence);Object.assign(o.sensors.range_evidence,{status,captured_at_ms:captureAt,fresh_frame_received:false,cached_for_diagnosis_only:true});return o;
}
test('Versioned results, records and wrapper expose v2 schemas explicitly',()=>{
 const s=new ProactiveSidecar(),r=s.capture(observation());assert.equal(SIDECAR_V2_SCHEMA,'warirak.proactive-sidecar.v2');assert.equal(r.schema,SIDECAR_V2_SCHEMA);assert.equal(s.records()[0].stream.schema,SIDECAR_V2_SCHEMA);assert.equal(s.snapshot().schema,SIDECAR_V2_SCHEMA);
 const e=pool(),w=new ProactiveSidecarR2(e);assert.equal(w.step(req(0,e.now(),'STOP')).schema,'warirak.proactive-sidecar-r2-step.v2');
});
test('Seen fresh19, unseen cached20, then fresh21 counts exactly two fresh range frames',()=>{
 const s=new ProactiveSidecar();s.capture(observation(T+1900,19));const middle=s.capture(cached(T+2000,20));
 assert.equal(middle.status,'accepted');assert.equal(middle.stream_fault,null);assert.equal(middle.decision_context.features.range.status,'unknown');assert.equal(middle.decision_context.features.range.captured_at_ms,T+2000);assert.equal(middle.decision_context.evidence_new.range,false);assert.equal(middle.decision_context.evidence_new.cached_metadata_advanced,true);assert(middle.decision_context.features.range.ray_m.every(v=>v===null));
 const last=s.capture(observation(T+2100,21));assert.equal(last.status,'accepted');assert.equal(last.decision_context.evidence_new.range,true);assert.equal(s.records().filter(r=>r.stream.evidence_new.range).length,2);assert.equal(s.snapshot().commands_generated,0);
});
test('A first cached stream and successive unseen cache metadata stay unknown until a distinct fresh frame',()=>{
 const s=new ProactiveSidecar();for(const [at,n]of [[T,20],[T+100,21]]){const r=s.capture(cached(at,n));assert.equal(r.status,'accepted');assert.equal(r.decision_context.features.range.status,'unknown');assert.equal(r.decision_context.evidence_new.range,false);}
 const r=s.capture(observation(T+200,22));assert.equal(r.decision_context.evidence_new.range,true);assert.equal(s.records().filter(r=>r.stream.evidence_new.range).length,1);
});
test('Unseen cached body rays remain unknown after heading rotates',()=>{
 const s=new ProactiveSidecar();s.capture(observation());const o=cached(T+100,2);o.pose.heading_rad=Math.PI/2;
 const r=s.capture(o);assert.equal(r.status,'accepted');assert.equal(r.decision_context.features.range_motion_synchronized,false);assert(r.decision_context.features.range.ray_m.every(v=>v===null));assert(r.decision_context.features.ray_velocity_projection_mps.every(v=>v===null));assert.equal(s.records().at(-1).original_observation.pose.heading_rad,Math.PI/2);
});
test('Unseen-cache acceptance preserves same-sequence payload conflict protection',()=>{
 const s=new ProactiveSidecar();s.capture(observation());s.capture(cached(T+100,2));const o=cached(T+200,2,T+100);o.sensors.clearance_m[0]=.4;o.sensors.range_evidence.ranges[0]=.4;
 assert.equal(s.capture(o).reason,'range_sequence_conflict');assert.equal(s.decisionWindow().length,0);
});
test('New cached metadata still rejects regressing sequence/capture time and future frames',()=>{
 for(const [packet,reason]of [[cached(T+200,1,T+200),'range_sequence_or_clock_regression'],[cached(T+200,3,T-1),'range_sequence_or_clock_regression'],[cached(T+200,3,T+201),'range_future_or_invalid_time']]){
  const s=new ProactiveSidecar();s.capture(observation(T,1));s.capture(cached(T+100,2));assert.equal(s.capture(packet).reason,reason);
 }
});
test('New cache metadata requires valid source, flags, schema and an unchanged bounded ray payload',()=>{
 const changes=[o=>o.sensors.range_evidence.source='hardware',o=>o.sensors.range_evidence.schema='unknown',o=>o.sensors.range_evidence.fresh_frame_received=true,o=>o.sensors.range_evidence.cached_for_diagnosis_only=false,o=>o.sensors.range_evidence.ranges[0]=.1,o=>o.sensors.range_evidence.ranges[0]=2];
 for(const change of changes){const s=new ProactiveSidecar();s.capture(observation());const o=cached(T+100,2);change(o);assert.equal(s.capture(o).reason,'invalid_cached_range_metadata');}
});
test('An unseen cached frame cannot later be relabeled fresh with the same sequence',()=>{
 const s=new ProactiveSidecar();s.capture(observation());s.capture(cached(T+100,2));const o=observation(T+200,2);o.sensors.range_evidence.captured_at_ms=T+100;
 assert.equal(s.capture(o).reason,'repeated_range_claimed_fresh');assert.equal(s.records().filter(r=>r.stream.evidence_new.range).length,1);
});
test('A newer cached sequence at an equal capture time cannot inflate fresh capture counts',()=>{
 const s=new ProactiveSidecar();s.capture(observation(T,1));assert.equal(s.capture(cached(T+100,2,T)).status,'accepted');const o=observation(T+200,3);o.sensors.range_evidence.captured_at_ms=T;assert.equal(s.capture(o).reason,'repeated_range_claimed_fresh');
});
test('Monotonic stale cache is retained as diagnosis without renewing its original clock',()=>{
 const s=new ProactiveSidecar();s.capture(observation(T,1));const r=s.capture(cached(T+500,2,T+100,'stale'));assert.equal(r.status,'accepted');assert.equal(r.decision_context.features.range.captured_at_ms,T+100);assert.equal(r.decision_context.features.range.age_ms,400);assert.equal(r.decision_context.features.range.status,'unknown');assert.equal(r.decision_context.evidence_new.range,false);
});
test('Recorded original v1 failure packets are accepted diagnostically by v2 without any plant rollout',()=>{
 for(const role of ['reference','candidate']){
  const original=JSON.parse(fs.readFileSync(new URL('../work/proactive-selector-v1-dev-r1/'+role+'-range_gap.json',import.meta.url)));
  const w=original.first_event_windows.find(x=>x.event==='first_recorder_fault'),s=new ProactiveSidecar();
  for(const record of w.records)assert.equal(s.capture(record.original_observation,{receivedAtMs:record.stream.received_at_ms}).status,'accepted');
  const r=s.capture(w.trigger_original_observation,{receivedAtMs:w.at_ms});assert.equal(r.status,'accepted');assert.equal(r.decision_context.features.range.status,'unknown');assert.equal(r.decision_context.evidence_new.range,false);assert.equal(r.stream_fault,null);
 }
});
test('Unchanged R2 internally generated frame survives cache transition without recorder fault or extra thrust',()=>{
 const fixture={x:5,y:3,heading:0,target:{x:9,y:3,class_id:0},obstacles:[],drift:{x:.08,y:0},delayTicks:0,sensorDropout:0};
 const a=new MissionPoolEnvR2(7,{profile:'stress',record:true,fixture}),b=new MissionPoolEnvR2(7,{profile:'stress',record:true,fixture}),w=new ProactiveSidecarR2(a);
 let request=req(0,a.now(),'STOP');w.step(request);b.step(request);assert.deepEqual(a.snapshot(),b.snapshot());const oldRange=w.sidecar.records()[0].original_observation.sensors.range_evidence;
 a.setFaults({range_packet_loss:true});b.setFaults({range_packet_loss:true});assert(a.observe().sensors.range_evidence.sequence>oldRange.sequence);
 request=req(1,a.now(),'FORWARD');const r=w.step(request);b.step(request);assert.equal(r.recorder_fault,null);assert.equal(r.capture.decision_context.features.range.status,'unknown');assert.equal(r.capture.decision_context.evidence_new.range,false);assert.equal(a.trace[0].applied.left,0);assert.equal(a.trace[0].applied.right,0);assert.equal(a.mode,'WAIT_RANGE_UPDATE');assert.deepEqual(a.snapshot(),b.snapshot());assert(a.x>5);
 a.setFaults({range_packet_loss:false});b.setFaults({range_packet_loss:false});request=req(2,a.now(),'FORWARD');const fresh=w.step(request);b.step(request);assert.equal(fresh.recorder_fault,null);assert.equal(fresh.capture.decision_context.evidence_new.range,true);assert.deepEqual(a.snapshot(),b.snapshot());
});
test('Manual/disarm and cancellation still clear active context after unseen-cache acceptance',()=>{
 for(const flags of [{manual_override:true},{armed:false}]){
  const s=new ProactiveSidecar();s.capture(observation());s.noteDecision(req(0));s.noteIssuedControl(issued(),{atMs:T});const o=cached(T+100,2);Object.assign(o.sensors,flags);const r=s.capture(o);assert.equal(r.status,'accepted');assert.equal(r.decision_context,null);assert.equal(s.issuedControls().length,0);assert.equal(s.decisionWindow().length,0);
 }
 const s=new ProactiveSidecar();s.capture(observation());s.capture(cached(T+100,2));assert.equal(s.cancel(T+101).commands_generated,0);assert.equal(s.decisionWindow().length,0);
});
test('Selector-v1 trial sources, results and original sidecar hashes are unchanged',()=>{
 const protocol=JSON.parse(fs.readFileSync(new URL('../work/proactive-selector-v1-dev-r1/protocol.json',import.meta.url))),review=JSON.parse(fs.readFileSync(new URL('../outputs/Warirak_Proactive_Selector_v1_Outcome_Audit.json',import.meta.url)));
 for(const [file,hash]of Object.entries(protocol.source_sha256))assert.equal(createHash('sha256').update(fs.readFileSync(new URL('../'+file,import.meta.url))).digest('hex'),hash,file);
 for(const [file,info]of Object.entries(review.artifact_hashes))assert.equal(createHash('sha256').update(fs.readFileSync(new URL('../work/proactive-selector-v1-dev-r1/'+file,import.meta.url))).digest('hex'),info.sha256,file);
});
