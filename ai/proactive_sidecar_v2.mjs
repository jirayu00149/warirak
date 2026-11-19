// Versioned fork: immutable v1 parent SHA256 d78756c978e29c0f4645db7388030a191385526831ebe0a445843c209d263c8a
// Bounded observational stream recorder. Never generates, queues or transmits a command.
import {createHash} from 'node:crypto';
import {Buffer} from 'node:buffer';
import {proactiveObservation,proactiveObservationRecord,ISSUED_CONTROL_RECORD} from './proactive_observation.mjs';
export const SIDECAR_V2_SCHEMA='warirak.proactive-sidecar.v2';
const ENV='warirak-pool-mission-v4r2-dev';
const ACTIONS=['STOP','FORWARD','TURN_LEFT','TURN_RIGHT','PIVOT_LEFT','PIVOT_RIGHT','HOLD','RECOVERY_REQUEST'];
const finite=v=>typeof v==='number'&&Number.isFinite(v),uint=v=>Number.isInteger(v)&&v>=0;
function canonical(v,depth=0,seen=new Set()){
 if(depth>24)throw Error('json_depth_limit');
 if(v===null||typeof v==='string'||typeof v==='boolean')return JSON.stringify(v);
 if(typeof v==='number'&&finite(v))return JSON.stringify(v);
 if(typeof v!=='object'||seen.has(v)||!Array.isArray(v)&&![null,Object.prototype].includes(Object.getPrototypeOf(v)))throw Error('non_json_input');
 seen.add(v);
 const result=Array.isArray(v)?'['+v.map(x=>canonical(x,depth+1,seen)).join(',')+']':'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k],depth+1,seen)).join(',')+'}';
 seen.delete(v);return result;
}
const digest=v=>createHash('sha256').update(canonical(v)).digest('hex');
const copy=v=>structuredClone(v);

export class ProactiveSidecarV2{
 constructor({historyLimit=12,ledgerLimit=16,eventLimit=32,maxPacketBytes=32768}={}){
  if(!Number.isInteger(historyLimit)||historyLimit<1||historyLimit>64||!Number.isInteger(ledgerLimit)||ledgerLimit<1||ledgerLimit>16||!Number.isInteger(eventLimit)||eventLimit<1||eventLimit>128||!Number.isInteger(maxPacketBytes)||maxPacketBytes<4096||maxPacketBytes>65536)throw Error('Invalid bounded sidecar limits');
  Object.assign(this,{historyLimit,ledgerLimit,eventLimit,maxPacketBytes});
  this._records=[];this._window=[];this._ledger=[];this._events=[];
  this._lastNow=null;this._lastObservation=null;this._lastSignature=null;this._components={};
  this._range=null;this._requestSequence=-1;this._controlSequence=-1;this._controlSignature=null;
  this._current=null;this._fault=null;this._cancelled=false;this._epoch=0;this._recordSequence=0;this._authority=null;
 }
 _event(type,reason,at,extra={}){
  this._events.push({type,reason,at_ms:finite(at)?at:null,epoch:this._epoch,...extra});
  if(this._events.length>this.eventLimit)this._events.shift();
 }
 _boundary(reason,at){this._epoch++;this._window=[];this._ledger=[];this._current=null;this._event('boundary',reason,at);}
 _fail(reason,at){
  if(!this._fault){this._fault=reason;this._boundary(reason,at);}
  this._event('rejected',reason,at);
  return this._result('fault',reason,at);
 }
 _result(status,reason,at,record=null){
  return{schema:SIDECAR_V2_SCHEMA,status,reason,received_at_ms:finite(at)?at:null,record_sequence:record?.stream.record_sequence??null,new_observation:status==='accepted',stream_fault:this._fault,epoch:this._epoch,history_length:this._records.length,active_window_length:this._window.length,decision_context:status==='accepted'&&record&&record._context_allowed?copy({features:record.features,evidence_new:record.stream.evidence_new,epoch:record.stream.epoch,record_sequence:record.stream.record_sequence}):null,control_enabled:false,physical_motor_transport:false};
 }
 _component(name,packet,observationAt,now,next){
  if(!packet||!finite(packet.timestamp_unix_ms))return false;
  const at=packet.timestamp_unix_ms;
  if(at<=0||at>observationAt||at>now)throw Error(name+'_future_or_invalid_time');
  const hash=digest(packet),old=next[name];
  if(old&&at<old.at)throw Error(name+'_clock_regression');
  if(old&&at===old.at){if(hash!==old.hash)throw Error(name+'_timestamp_conflict');return false;}
  next[name]={at,hash};return true;
 }
 capture(observation,{receivedAtMs=observation?.timestamp_unix_ms}={}){
  const now=receivedAtMs;
  if(!finite(now)||now<=0)return this._fail('invalid_processing_clock',now);
  if(this._lastNow!==null&&now<this._lastNow)return this._fail('processing_clock_regression',now);
  this._lastNow=now;
  if(this._fault)return this._result('fault',this._fault,now);
  let signature,record;
  try{
   signature=canonical(observation);
   if(Buffer.byteLength(signature,'utf8')>this.maxPacketBytes)return this._fail('packet_size_limit',now);
   record=proactiveObservationRecord(observation,{nowMs:now,issuedControls:this._ledger});
  }catch(error){return this._fail(error.message,now);}
  const at=observation.timestamp_unix_ms,hash=createHash('sha256').update(signature).digest('hex');
  if(at>now)return this._fail('future_observation',now);
  if(this._lastObservation!==null&&at<this._lastObservation)return this._fail('observation_clock_regression',now);
  if(at===this._lastObservation){
   if(hash!==this._lastSignature)return this._fail('observation_timestamp_conflict',now);
   this._event('duplicate','identical_observation_not_new_evidence',now);
   this._current=null;
   return this._result('duplicate','identical_observation_not_new_evidence',now);
  }
  const components=copy(this._components),newEvidence={observation:true,pose:false,motion:false,range:false,cached_metadata_advanced:false};
  let nextRange=this._range;
  try{
   newEvidence.pose=this._component('pose',observation.pose,at,now,components);
   newEvidence.motion=this._component('motion',observation.motion,at,now,components);
   this._component('feedback',observation.actuator_feedback,at,now,components);
   const r=observation.sensors?.range_evidence;
   if(r&&finite(r.captured_at_ms)&&uint(r.sequence)){
    if(r.captured_at_ms<=0||r.captured_at_ms>at||r.captured_at_ms>now)throw Error('range_future_or_invalid_time');
    const payload={sequence:r.sequence,captured_at_ms:r.captured_at_ms,ranges:r.ranges},rangeHash=digest(payload);
    if(this._range){
     if(r.sequence<this._range.sequence||r.captured_at_ms<this._range.at)throw Error('range_sequence_or_clock_regression');
     if(r.sequence===this._range.sequence&&rangeHash!==this._range.hash)throw Error('range_sequence_conflict');
    }
    if(r.status==='fresh'){
     // A packet can be valid at original capture and stale on arrival. Retain it as unknown,
     // rather than relabeling its original sender-time fresh flag as a stream conflict.
     const originalRange=record.features.range.status.startsWith('fresh')?record.features.range:proactiveObservation(observation,{nowMs:at}).range;
     if(!originalRange.status.startsWith('fresh'))throw Error('invalid_fresh_range_frame');
     if(this._range&&(r.sequence===this._range.sequence||r.captured_at_ms===this._range.at))throw Error('repeated_range_claimed_fresh');
     nextRange={sequence:r.sequence,at:r.captured_at_ms,hash:rangeHash};newEvidence.range=true;
    }else if(!this._range||r.sequence!==this._range.sequence||r.captured_at_ms!==this._range.at){
     // A frame may have been cached internally without ever being observed fresh here.
     // Its monotonic metadata is diagnostic only; it NEVER supplies fresh ray features.
     const validCache=r.schema==='warirak.range-evidence-state.v2'&&r.source==='simulation'&&r.control_enabled===false&&['cached_wait','stale'].includes(r.status)&&r.fresh_frame_received===false&&r.cached_for_diagnosis_only===true&&Array.isArray(r.ranges)&&r.ranges.length===8&&r.ranges.every(v=>v===null||finite(v)&&v>=0&&v<=1.5)&&canonical(r.ranges)===canonical(observation.sensors.clearance_m);
     if(!validCache)throw Error('invalid_cached_range_metadata');
     nextRange={sequence:r.sequence,at:r.captured_at_ms,hash:rangeHash};
     newEvidence.cached_metadata_advanced=true;
    }
   }else if(r?.status==='fresh')throw Error('invalid_fresh_range_frame');
  }catch(error){return this._fail(error.message,now);}
  const authority=record.features.authority,blocked=authority!=='research_channel_armed'||now-at>300;
  if(blocked&&this._authority!==authority)this._boundary('observation_context_'+authority,now);
  this._authority=authority;
  this._components=components;this._range=nextRange;this._lastObservation=at;this._lastSignature=hash;
  record.stream={schema:SIDECAR_V2_SCHEMA,record_sequence:++this._recordSequence,epoch:this._epoch,received_at_ms:now,evidence_new:newEvidence};
  record.decision=null;record.transition=null;record._context_allowed=!blocked&&!this._cancelled;
  this._records.push(record);if(this._records.length>this.historyLimit)this._records.shift();
  this._current=record;
  if(record._context_allowed)this._appendWindow(record);
  this._event('accepted',blocked?'context_unavailable':'full_original_observation_recorded',now,{record_sequence:this._recordSequence});
  return this._result('accepted',blocked?'context_unavailable':'full_original_observation_recorded',now,record);
 }
 _appendWindow(record){
  this._window.push({features:copy(record.features),stream:copy(record.stream),decision:copy(record.decision)});
  if(this._window.length>this.historyLimit)this._window.shift();
 }
 noteDecision(request,{owner='navigation',atMs=this._lastNow}={}){
  const record=this._current;
  if(!record||this._fault)return{status:'not_recorded',reason:this._fault??'new_observation_required',control_enabled:false};
  if(record.decision!==null)return this._fail('multiple_decisions_for_observation',atMs);
  if(!finite(atMs)||atMs<this._lastNow)return this._fail('decision_clock_regression',atMs);
  this._lastNow=atMs;
  if(request===null){record.decision={owner:'none',request:null,status:'no_new_request',recorded_at_ms:atMs};const last=this._window.at(-1);if(last?.stream.record_sequence===record.stream.record_sequence)last.decision=copy(record.decision);this._event('decision','no_new_request',atMs);return copy(record.decision);}
  try{if(Buffer.byteLength(canonical(request),'utf8')>4096)throw Error('decision_size_limit');}catch(error){return this._fail(error.message,atMs);}
  const valid=['navigation','operator'].includes(owner)&&request?.schema==='warirak.mission-sim-request.v2'&&request.environment===ENV&&request.source==='simulation'&&request.control_enabled===false&&uint(request.sequence)&&request.sequence>this._requestSequence&&ACTIONS.includes(request.action)&&(owner==='operator'||request.action!=='RECOVERY_REQUEST')&&finite(request.issued_at_ms)&&request.issued_at_ms>0&&request.issued_at_ms<=record.features.observation_at_ms&&request.issued_at_ms<=atMs&&finite(request.valid_until_ms)&&request.valid_until_ms>atMs&&request.valid_until_ms-request.issued_at_ms>0&&request.valid_until_ms-request.issued_at_ms<=400&&atMs-record.features.observation_at_ms<=300;
  if(!valid){record.decision={owner,request:copy(request),status:'rejected',recorded_at_ms:atMs};return this._fail('invalid_replayed_or_expired_decision',atMs);}
  this._requestSequence=request.sequence;
  const usable=record.features.authority==='research_channel_armed';
  if(this._cancelled&&usable){this._cancelled=false;record._context_allowed=true;this._appendWindow(record);}
  record.decision={owner,request:copy(request),status:usable?'recorded_original_request':'context_suppressed',recorded_at_ms:atMs};
  const last=this._window.at(-1);if(last?.stream.record_sequence===record.stream.record_sequence)last.decision=copy(record.decision);
  this._event('decision',record.decision.status,atMs,{request_sequence:request.sequence});
  return copy(record.decision);
 }
 noteIssuedControl(control,{atMs=this._lastNow}={}){
  if(!finite(atMs)||this._lastNow!==null&&atMs<this._lastNow)return this._fail('control_clock_regression',atMs);
  this._lastNow=atMs;
  try{if(Buffer.byteLength(canonical(control),'utf8')>4096)throw Error('control_size_limit');}catch(error){return this._fail(error.message,atMs);}
  const valid=control?.schema===ISSUED_CONTROL_RECORD&&control.plant_environment===ENV&&control.source==='simulation'&&control.control_enabled===false&&control.physical_transport===false&&control.units==='normalized'&&uint(control.control_sequence)&&uint(control.request_sequence)&&finite(control.issued_at_ms)&&control.issued_at_ms>0&&control.issued_at_ms<=atMs&&finite(control.valid_until_ms)&&control.valid_until_ms>control.issued_at_ms&&control.valid_until_ms-control.issued_at_ms<=400&&[control.left,control.right].every(v=>finite(v)&&Math.abs(v)<=1);
  if(!valid)return this._fail('invalid_issued_control',atMs);
  const hash=digest(control);
  if(control.control_sequence<this._controlSequence)return this._fail('issued_control_sequence_regression',atMs);
  if(control.control_sequence===this._controlSequence){if(hash!==this._controlSignature)return this._fail('issued_control_sequence_conflict',atMs);return{status:'duplicate_control_not_new',control_enabled:false};}
  this._controlSequence=control.control_sequence;this._controlSignature=hash;
  if(this._fault||this._cancelled||this._authority!=='research_channel_armed')return{status:'context_suppressed',control_enabled:false};
  this._ledger.push(copy(control));if(this._ledger.length>this.ledgerLimit)this._ledger.shift();
  return{status:'recorded_original_control',control_enabled:false};
 }
 attachTransition(transition,{recordSequence=this._current?.stream.record_sequence}={}){
  const record=this._records.find(r=>r.stream.record_sequence===recordSequence);
  if(!record)return{status:'no_current_record',control_enabled:false};
  try{if(Buffer.byteLength(canonical(transition),'utf8')>this.maxPacketBytes)throw Error('transition_size_limit');}catch(error){return this._fail(error.message,this._lastNow);}
  record.transition=copy(transition);return{status:'recorded_original_transition',control_enabled:false};
 }
 cancel(atMs=this._lastNow){
  if(!finite(atMs)||atMs<=0||this._lastNow!==null&&atMs<this._lastNow)return this._fail('cancel_clock_regression',atMs);
  this._lastNow=atMs;this._cancelled=true;this._boundary('explicit_recording_cancel',atMs);
  return{status:'cancelled',commands_generated:0,control_enabled:false,physical_motor_transport:false};
 }
 reset(disarmedObservation,{receivedAtMs=disarmedObservation?.timestamp_unix_ms}={}){
  const o=disarmedObservation,now=receivedAtMs;
  const valid=finite(now)&&now>0&&(this._lastNow===null||now>=this._lastNow)&&finite(o?.timestamp_unix_ms)&&o.timestamp_unix_ms<=now&&now-o.timestamp_unix_ms<=300&&(this._lastObservation===null||o.timestamp_unix_ms>this._lastObservation)&&o.sensors?.source==='simulation'&&o.sensors.armed===false&&o.sensors.manual_override===false&&finite(o.sensors.timestamp_unix_ms)&&o.sensors.timestamp_unix_ms<=o.timestamp_unix_ms&&now-o.sensors.timestamp_unix_ms<=300;
  if(!valid)return this._result('reset_rejected','fresh_new_disarmed_observation_required',now);
  this._fault=null;this._cancelled=false;this._boundary('explicit_disarmed_recorder_reset',now);
  return this.capture(o,{receivedAtMs:now});
 }
 records(){return copy(this._records.map(({_context_allowed,...record})=>record));}
 decisionWindow(){return copy(this._window);}
 issuedControls(){return copy(this._ledger);}
 snapshot(){return{schema:SIDECAR_V2_SCHEMA,epoch:this._epoch,stream_fault:this._fault,cancelled:this._cancelled,last_processing_at_ms:this._lastNow,last_observation_at_ms:this._lastObservation,records:this.records(),decision_window:this.decisionWindow(),issued_controls:this.issuedControls(),events:copy(this._events),control_enabled:false,physical_motor_transport:false,commands_generated:0};}
}
