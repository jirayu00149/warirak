// Local simulation wire contract. No model or physical command execution.
import {NAVIGATION_LAYOUT as L,NAVIGATION_LAYOUT_SHA256,HISTORY_VECTOR_SCHEMA,FRAME_FIELDS,vectorDigest} from './navigation_history_encoder.mjs';
export const INFERENCE_REQUEST_SCHEMA='warirak.navigation-inference-request.v1';
export const INFERENCE_REPLY_SCHEMA='warirak.navigation-inference-reply.v1';
export const VALIDATION_MODEL_SCHEMA='warirak.navigation-validation-fixture.v1';
const reqKeys=['schema','source','plant_environment','encoder_schema','layout_sha256','session_id','request_id','stream_epoch','record_sequence','observation_at_ms','encoded_at_ms','valid_until_ms','history_frames','frame_size','vector_size','vector_sha256','vector','allowed_mask','control_enabled','physical_motor_transport'];
const replyKeys=['schema','source','plant_environment','encoder_schema','layout_sha256','session_id','request_id','stream_epoch','record_sequence','observation_at_ms','valid_until_ms','vector_sha256','model_schema','action','control_enabled','physical_motor_transport'];
const safe=v=>Number.isSafeInteger(v)&&v>=0,stamp=v=>safe(v)&&v>0;
const id=v=>typeof v==='string'&&/^[A-Za-z0-9_.:-]{1,96}$/.test(v);
const exact=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&keys.every(k=>Object.hasOwn(value,k));
const index=Object.fromEntries(FRAME_FIELDS.map((f,i)=>[f,i]));
const signed=new Set(['target.bearing','motion.forward','motion.lateral','motion.yaw']);
const numerics=new Set(['frame.age',...Array.from({length:8},(_,i)=>'range.'+i+'.value'),'range.age','target.bearing','target.range','motion.forward','motion.lateral','motion.yaw','motion.margin','pose.age','motion.age','ack.age']);
const pairs=[...Array.from({length:8},(_,i)=>['range.'+i+'.value','range.'+i+'.known']),['target.bearing','target.bearing_known'],['target.range','target.range_known'],['motion.margin','motion.margin_known'],['range.age','range.age_known'],['pose.age','pose.age_known'],['motion.age','motion.age_known'],['ack.age','ack.age_known']];
export function validateNavigationVector(vector){
 vectorDigest(vector);
 for(let frame=0;frame<L.frame_count;frame++){
  const row=vector.slice(frame*L.frame_size,(frame+1)*L.frame_size),get=name=>row[index[name]];
  for(let i=0;i<row.length;i++)if(!signed.has(FRAME_FIELDS[i])&&row[i]<0||!numerics.has(FRAME_FIELDS[i])&&row[i]!==0&&row[i]!==1)throw Error('Invalid vector domain or binary flag');
  if(get('frame.present')===0){if(row.some(v=>v!==0))throw Error('Padding frame contains data');continue;}
  for(const [prefix,values]of [['authority',L.authority_order],['mission',L.mission_order],['ack',L.ack_order],['previous_request',L.previous_request_order]])if(values.reduce((n,v)=>n+get(prefix+'.'+v),0)!==1)throw Error('Invalid categorical one-hot group');
  for(const [v,k]of pairs)if(get(k)===0&&get(v)!==0)throw Error('Unknown value is not canonical zero');
  if(get('motion.known')===0&&['motion.forward','motion.lateral','motion.yaw','motion.margin_known','pose.new_at_observation','motion.new_at_observation','motion.range_synchronized'].some(f=>get(f)!==0))throw Error('Motion data without measured-motion evidence');
 }
 return vector;
}
export function validateInferenceRequest(r,{nowMs=null}={}){
 if(!exact(r,reqKeys)||r.schema!==INFERENCE_REQUEST_SCHEMA||r.source!=='simulation'||r.plant_environment!==L.plant_environment||r.encoder_schema!==HISTORY_VECTOR_SCHEMA||r.layout_sha256!==NAVIGATION_LAYOUT_SHA256||r.control_enabled!==false||r.physical_motor_transport!==false||!id(r.session_id)||!id(r.request_id)||!safe(r.stream_epoch)||!safe(r.record_sequence)||!stamp(r.observation_at_ms)||!stamp(r.encoded_at_ms)||!stamp(r.valid_until_ms)||r.encoded_at_ms<r.observation_at_ms||r.valid_until_ms!==r.observation_at_ms+L.maximum_age_ms||r.encoded_at_ms>=r.valid_until_ms||r.history_frames!==L.frame_count||r.frame_size!==L.frame_size||r.vector_size!==L.vector_size||!Array.isArray(r.allowed_mask)||r.allowed_mask.length!==7||r.allowed_mask.some(v=>typeof v!=='boolean')||!r.allowed_mask.some(Boolean))throw Error('Invalid simulation inference request');
 validateNavigationVector(r.vector);if(vectorDigest(r.vector)!==r.vector_sha256)throw Error('Vector digest mismatch');
 if(nowMs!==null&&(!stamp(nowMs)||nowMs<r.encoded_at_ms||nowMs>=r.valid_until_ms))throw Error('Inference request expired or clock regressed');
 return r;
}
export function makeInferenceRequest(encoded,{sessionId,requestId,nowMs=encoded?.encoded_at_ms}={}){
 if(encoded?.schema!==HISTORY_VECTOR_SCHEMA||encoded.layout_sha256!==NAVIGATION_LAYOUT_SHA256||encoded.source!=='simulation'||encoded.plant_environment!==L.plant_environment||encoded.control_enabled!==false||encoded.physical_motor_transport!==false||encoded.command_authorization!==false)throw Error('Canonical simulation encoding required');
 const r={schema:INFERENCE_REQUEST_SCHEMA,source:'simulation',plant_environment:L.plant_environment,encoder_schema:HISTORY_VECTOR_SCHEMA,layout_sha256:NAVIGATION_LAYOUT_SHA256,session_id:sessionId,request_id:requestId,stream_epoch:encoded.stream_epoch,record_sequence:encoded.record_sequence,observation_at_ms:encoded.observation_at_ms,encoded_at_ms:encoded.encoded_at_ms,valid_until_ms:encoded.observation_at_ms+L.maximum_age_ms,history_frames:encoded.history_frames,frame_size:encoded.frame_size,vector_size:encoded.vector_size,vector_sha256:encoded.vector_sha256,vector:[...encoded.vector],allowed_mask:[...encoded.allowed_mask],control_enabled:false,physical_motor_transport:false};
 validateInferenceRequest(r,{nowMs});return r;
}
export function acceptInferenceReply(reply,request,{nowMs,expectedModelSchema,allowValidationFixture=false}={}){
 validateInferenceRequest(request,{nowMs});
 if(!exact(reply,replyKeys)||reply.schema!==INFERENCE_REPLY_SCHEMA||reply.source!=='simulation'||reply.plant_environment!==L.plant_environment||reply.encoder_schema!==HISTORY_VECTOR_SCHEMA||reply.layout_sha256!==NAVIGATION_LAYOUT_SHA256||reply.control_enabled!==false||reply.physical_motor_transport!==false||typeof expectedModelSchema!=='string'||reply.model_schema!==expectedModelSchema||!allowValidationFixture&&reply.model_schema===VALIDATION_MODEL_SCHEMA||!Number.isInteger(reply.action)||reply.action<0||reply.action>6||request.allowed_mask[reply.action]!==true)throw Error('Invalid/unapproved model reply or action');
 for(const key of ['session_id','request_id','stream_epoch','record_sequence','observation_at_ms','valid_until_ms','vector_sha256'])if(reply[key]!==request[key])throw Error('Reply request binding mismatch');
 return{schema:'warirak.navigation-model-proposal.v1',source:'simulation',action:reply.action,action_name:L.navigation_actions[reply.action],model_schema:reply.model_schema,request_id:reply.request_id,observation_at_ms:request.observation_at_ms,valid_until_ms:request.valid_until_ms,control_enabled:false,physical_motor_transport:false};
}
export class NavigationInferenceClient{
 constructor(sessionId){if(!id(sessionId)||sessionId.length>64)throw Error('Explicit bounded simulation session id required');this.sessionId=sessionId;this.counter=0;this.pending=null;this.lastNow=null;this.lastEpoch=-1;this.lastRecord=-1;this.lastObservation=null;this.fault=null;}
 _clock(now){if(!stamp(now)||this.lastNow!==null&&now<this.lastNow){this.pending=null;this.fault='client_clock_regression';throw Error(this.fault);}if(this.fault)throw Error(this.fault);this.lastNow=now;}
 issue(encoded,{nowMs=encoded?.encoded_at_ms}={}){
  this._clock(nowMs);
  if(this.counter>=Number.MAX_SAFE_INTEGER)throw Error('New inference client session required');
  const request=makeInferenceRequest(encoded,{sessionId:this.sessionId,requestId:this.sessionId+':inference:'+(this.counter+1),nowMs});
  if(request.stream_epoch<this.lastEpoch||request.record_sequence<=this.lastRecord||this.lastObservation!==null&&request.observation_at_ms<=this.lastObservation)throw Error('New original record/session required');
  this.pending=null;this.lastEpoch=request.stream_epoch;this.lastRecord=request.record_sequence;this.lastObservation=request.observation_at_ms;this.counter++;this.pending=request;
  return structuredClone(request);
 }
 receive(reply,options={}){
  this._clock(options.nowMs);const request=this.pending;
  if(!request||reply?.request_id!==request.request_id)throw Error('Reply is cancelled, replayed or not the latest request');
  this.pending=null;return acceptInferenceReply(reply,request,options);
 }
 cancel(nowMs){this._clock(nowMs);this.pending=null;return{cancelled:true,commands_generated:0,physical_motor_transport:false};}
 snapshot(){return{session_id:this.sessionId,pending_request_id:this.pending?.request_id??null,last_epoch:this.lastEpoch,last_record_sequence:this.lastRecord,last_observation_at_ms:this.lastObservation,fault:this.fault,commands_generated:0,physical_motor_transport:false};}
}
