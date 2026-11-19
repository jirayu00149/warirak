// Development simulation only. No GPIO/serial/network transport or production-policy adapter.
import {MemoryPoolEnv} from './navigation_memory_env.mjs';
import {rng} from '../frontend/autonomy.js';
import {SimRangeEvidence,RANGE_EVIDENCE_SCHEMA} from './mission_range_evidence.mjs';

export const MISSION_ENV_R2='warirak-pool-mission-v4r2-dev';
export const MISSION_OBSERVATION_R2='warirak.mission-sim-observation.v2';
export const MISSION_REQUEST_R2='warirak.mission-sim-request.v2';
export const MISSION_ACTIONS_R2=Object.freeze(['STOP','FORWARD','TURN_LEFT','TURN_RIGHT','PIVOT_LEFT','PIVOT_RIGHT','HOLD','RECOVERY_REQUEST']);
const TRACK={FORWARD:[.65,.65],TURN_LEFT:[.25,.65],TURN_RIGHT:[.65,.25],PIVOT_LEFT:[-.3,.3],PIVOT_RIGHT:[.3,-.3]};
const ANGLES=[0,Math.PI/4,Math.PI/2,3*Math.PI/4,Math.PI,-3*Math.PI/4,-Math.PI/2,-Math.PI/4];
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v)),wrap=a=>Math.atan2(Math.sin(a),Math.cos(a));
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const T=1800000000000,DT=.1;

export function missionRequestR2(sequence,at,action,ttl=400){
 return{schema:MISSION_REQUEST_R2,environment:MISSION_ENV_R2,source:'simulation',sequence,issued_at_ms:at,valid_until_ms:at+ttl,action,control_enabled:false};
}

export class MissionPoolEnvR2{
 constructor(seed=7,{profile='stress',record=false,fixture=null}={}){
  // Reuse only the frozen v3 scene/gain/current generator; this v4 plant and observations differ.
  const base=new MemoryPoolEnv(seed,{profile});
  Object.assign(this,{seed,profile,record,width:base.width,height:base.height,radius:base.radius,x:base.x,y:base.y,heading:base.heading,target:structuredClone(base.target),obstacles:structuredClone(base.obstacles),leftGain:base.leftGain,rightGain:base.rightGain,drift:structuredClone(base.drift),delayTicks:base.domain.delay*3});
  this.surgeTimeConstant=.35;this.dt=DT;this.maxSteps=960;this.steps=0;this.surge=0;this.done=false;this.collisions=0;this.collected=0;this.truncated=false;this.noise=rng((seed^0x59c31b)>>>0);
  this.positionNoise=profile==='stress'?.02:.005;this.velocityNoise=profile==='stress'?.008:.002;this.headingNoise=profile==='stress'?.025:.005;
  this.clearanceNoise=base.domain.clearanceNoise;this.sensorDropout=base.domain.sensorDropout;this.targetDropout=base.domain.targetDropout;this.bearingNoise=base.domain.bearingNoise;this.rangeNoise=base.domain.rangeNoise;
  this.faults={armed:true,manual_override:false,battery_percent:80,sensor_dropout:false,range_packet_loss:false,range_invalid:false,pose_dropout:false,motion_dropout:false,rear_unknown:false,freeze_motion:false,feedback_loss:false,jammed:false};
  if(fixture!==null){
   if(!fixture||typeof fixture!=='object')throw Error('Invalid development fixture');
   const allowed=['x','y','heading','target','obstacles','leftGain','rightGain','drift','delayTicks','surgeTimeConstant','positionNoise','velocityNoise','headingNoise','clearanceNoise','sensorDropout','targetDropout','bearingNoise','rangeNoise'];
   for(const [key,value]of Object.entries(fixture)){if(!allowed.includes(key))throw Error('Unknown fixture property');this[key]=structuredClone(value);}
  }
  this.fixtureUsed=fixture!==null;this._validateWorld();this.queue=[];this.lastRequest=null;this.lastRequestSequence=-1;this.controlSequence=0;this.anchor=null;this.holdIntegral={x:0,y:0};this.lastIntent='STOP';this.latched=null;this.mode='STOP';this.reason='initial_neutral';this.lastMotion=null;this.lastFeedback=null;this.stallEvidence=null;this.trace=[];
  this.rangeEvidence=new SimRangeEvidence();this.rangeSequence=0;this.progressEvidence=null;this.progressAssessment={status:'not_tracking',confirmed_stall:false};
  this.observation=this._sample();
  this.actuationSince=null;this.actuationFirstSequence=null;this.lastAckStamp=null;this.sentControls=new Map();
 }
 _validateWorld(){
  if(![this.x,this.y,this.heading,this.leftGain,this.rightGain,this.drift?.x,this.drift?.y,this.surgeTimeConstant,this.positionNoise,this.velocityNoise,this.headingNoise].every(finite)||this.x<this.radius||this.x>this.width-this.radius||this.y<this.radius||this.y>this.height-this.radius||!Number.isInteger(this.delayTicks)||this.delayTicks<0||this.delayTicks>6||this.leftGain<.5||this.leftGain>1.5||this.rightGain<.5||this.rightGain>1.5||this.surgeTimeConstant<.1||this.surgeTimeConstant>1||Math.max(Math.abs(this.drift.x),Math.abs(this.drift.y))>.2||Math.min(this.positionNoise,this.velocityNoise,this.headingNoise)<0||Math.max(this.positionNoise,this.velocityNoise,this.headingNoise)>.1)throw Error('Invalid development world parameters');
  if(!this.target||![this.target.x,this.target.y].every(finite)||!Array.isArray(this.obstacles)||this.obstacles.some(o=>![o.x,o.y,o.r].every(finite)||o.r<=0))throw Error('Invalid world geometry');
  if(![this.clearanceNoise,this.sensorDropout,this.targetDropout,this.bearingNoise,this.rangeNoise].every(v=>finite(v)&&v>=0&&v<=1))throw Error('Invalid development observation noise');
 }
 now(){return T+this.steps*100;}
 ray(angle){
  const dx=Math.cos(angle),dy=Math.sin(angle);let best=1.5;
  for(const [t,ok]of [[(this.radius-this.x)/dx,dx<0],[(this.width-this.radius-this.x)/dx,dx>0],[(this.radius-this.y)/dy,dy<0],[(this.height-this.radius-this.y)/dy,dy>0]])if(ok&&t>=0)best=Math.min(best,t);
  for(const o of this.obstacles){const ox=this.x-o.x,oy=this.y-o.y,b=ox*dx+oy*dy,c=ox*ox+oy*oy-(o.r+this.radius)**2,d=b*b-c;if(d>=0){const t=-b-Math.sqrt(d);if(t>=0)best=Math.min(best,t);}}
  return Math.max(0,best);
 }
 _sample(){
  const at=this.now(),jitter=scale=>(this.noise()-.5)*2*scale;
  const ranges=this.faults.sensor_dropout||this.faults.range_invalid||this.faults.range_packet_loss||this.noise()<this.sensorDropout?null:ANGLES.map(a=>clamp(this.ray(this.heading+a)+jitter(this.clearanceNoise),0,1.5));
  if(ranges&&this.faults.rear_unknown)for(const i of [3,4,5])ranges[i]=null;
  const rangeState=this.rangeEvidence.ingest(ranges?{schema:RANGE_EVIDENCE_SCHEMA,source:'simulation',units:'m',frame:'body',calibrated:true,sequence:++this.rangeSequence,timestamp_unix_ms:at,ranges}:null,at,{invalid:this.faults.sensor_dropout||this.faults.range_invalid});
  const pose=this.faults.pose_dropout?null:{schema:'warirak.sim-pose.v1',source:'simulation',method:'simulation_truth',calibrated:true,frame:'pool_fixed',units:'m,rad',timestamp_unix_ms:at,x_m:this.x+jitter(this.positionNoise),y_m:this.y+jitter(this.positionNoise),heading_rad:wrap(this.heading+jitter(this.headingNoise)),position_std_m:this.positionNoise,heading_std_rad:this.headingNoise,confidence:.95};
  let motion=null;
  if(!this.faults.motion_dropout&&this.lastMotion){
   if(this.faults.freeze_motion&&this.observation?.motion)motion=structuredClone(this.observation.motion);
   else motion={schema:'warirak.sim-motion.v1',source:'simulation',method:'simulation_position_difference',calibrated:true,frame:'pool_fixed',units:'m/s,rad/s',timestamp_unix_ms:at,vx_mps:this.lastMotion.vx+jitter(this.velocityNoise),vy_mps:this.lastMotion.vy+jitter(this.velocityNoise),yaw_rate_rps:this.lastMotion.yaw_rate,speed_std_mps:this.velocityNoise,confidence:.95};
  }
  const distance=Math.hypot(this.target.x-this.x,this.target.y-this.y),bearing=wrap(Math.atan2(this.target.y-this.y,this.target.x-this.x)-this.heading),visible=Math.abs(bearing)<Math.PI*.48&&distance<4.8&&this.noise()>=this.targetDropout;
  return{schema:MISSION_OBSERVATION_R2,environment:MISSION_ENV_R2,source:'simulation',timestamp_unix_ms:at,extra_sensors_are_simulated:true,sensors:{source:'simulation',timestamp_unix_ms:at,armed:this.faults.armed,manual_override:this.faults.manual_override,battery_percent:this.faults.battery_percent,clearance_m:rangeState.ranges,range_evidence:rangeState},pose,motion,actuator_feedback:this.faults.feedback_loss?null:structuredClone(this.lastFeedback),target:{visible,bearing_rad:visible?wrap(bearing+jitter(this.bearingNoise)):null,range_m:visible?Math.max(0,distance+jitter(this.rangeNoise)):null,source:'simulation'},mission:{mode:this.mode,reason:this.reason,operator_reset_required:this.latched!==null,progress_evidence:structuredClone(this.progressAssessment)},control_enabled:false};
 }
 observe(){return structuredClone(this.observation);}
 setFaults(patch){
  for(const [key,value]of Object.entries(patch)){if(!(key in this.faults)||key!=='battery_percent'&&typeof value!=='boolean'||key==='battery_percent'&&(!finite(value)||value<0||value>100))throw Error('Invalid simulated fault');this.faults[key]=value;}
  this.observation=this._sample();
 }
 _fresh(value){return finite(value)&&this.now()-value>=0&&this.now()-value<=300;}
 _poseValid(p){return p?.schema==='warirak.sim-pose.v1'&&p.source==='simulation'&&p.method==='simulation_truth'&&p.calibrated===true&&p.frame==='pool_fixed'&&p.units==='m,rad'&&this._fresh(p.timestamp_unix_ms)&&[p.x_m,p.y_m,p.heading_rad,p.position_std_m,p.confidence].every(finite)&&p.x_m>=-.1&&p.x_m<=this.width+.1&&p.y_m>=-.1&&p.y_m<=this.height+.1&&Math.abs(p.heading_rad)<=Math.PI&&p.confidence>=.8&&p.confidence<=1&&p.position_std_m>=0&&p.position_std_m<=.05;}
 _motionValid(m){return m?.schema==='warirak.sim-motion.v1'&&m.source==='simulation'&&m.method==='simulation_position_difference'&&m.calibrated===true&&m.frame==='pool_fixed'&&m.units==='m/s,rad/s'&&this._fresh(m.timestamp_unix_ms)&&[m.vx_mps,m.vy_mps,m.yaw_rate_rps,m.speed_std_mps,m.confidence].every(finite)&&Math.hypot(m.vx_mps,m.vy_mps)<=3&&Math.abs(m.yaw_rate_rps)<=10&&m.confidence>=.8&&m.confidence<=1&&m.speed_std_mps>=0&&m.speed_std_mps<=.015;}
 _zero(mode,reason,latch=false){
  this.mode=mode;this.reason=reason;if(latch)this.latched={mode,reason};this.queue=[];this.anchor=null;this.holdIntegral={x:0,y:0};this.stallEvidence=null;this.actuationSince=null;this.actuationFirstSequence=null;this.lastAckStamp=null;
  if(mode==='WAIT_RANGE_UPDATE'){
   if(this.progressEvidence)this.progressEvidence.last_active_ms=null;
   this.progressAssessment={...this.progressAssessment,status:'paused_without_new_range',confirmed_stall:false};
  }else{this.progressEvidence=null;if(mode!=='PROGRESS_UNCERTAIN')this.progressAssessment={status:'not_tracking',confirmed_stall:false};}
  return{left:0,right:0,mode,reason};
 }
 resetSupervisor(){
  const s=this.observation.sensors;if(s?.armed!==false||!this._fresh(s.timestamp_unix_ms))throw Error('Reset requires fresh disarmed simulation sensors');
  this.latched=null;this.lastRequest=null;this._zero('DISARMED','operator_reset');this.observation=this._sample();
 }
 _accept(request){
  if(request===null)return;
  if(!request||request.schema!==MISSION_REQUEST_R2||request.environment!==MISSION_ENV_R2||request.source!=='simulation'||request.control_enabled!==false||!MISSION_ACTIONS_R2.includes(request.action)||!Number.isInteger(request.sequence)||request.sequence<=this.lastRequestSequence||!finite(request.issued_at_ms)||!finite(request.valid_until_ms)||request.issued_at_ms>this.now()||request.valid_until_ms<=this.now()||request.valid_until_ms-request.issued_at_ms>400||request.valid_until_ms<=request.issued_at_ms){this.lastRequest=null;this._zero('FAULT_STOP','invalid_or_replayed_request',true);return;}
  this.lastRequestSequence=request.sequence;this.lastRequest=structuredClone(request);
 }
 _clearance(control){
  const evidence=this.observation.sensors?.range_evidence;
  if(evidence?.status!=='fresh'||!this._fresh(evidence.captured_at_ms))return'range_frame_not_fresh';
  const c=this.observation.sensors?.clearance_m;
  if(!Array.isArray(c)||c.length!==8||![c[0],c[1],c[7]].every(v=>finite(v)&&v>=0&&v<=1.5))return'front_sensor_invalid';
  if(c.some(v=>v!==null&&(!finite(v)||v<0||v>1.5)))return'clearance_invalid';
  if(c.some(v=>finite(v)&&v<.35))return'obstacle_stop';
  const surge=(control.left+control.right)/2,yaw=control.right-control.left;
  if(surge>.005&&Math.min(c[0],c[1],c[7])<.65)return'forward_clearance';
  if(surge<-.005&&![c[3],c[4],c[5]].every(v=>finite(v)&&v>=.65))return'rear_clearance';
  if(Math.abs(yaw)>.01&&![c[2],c[6]].every(v=>finite(v)&&v>=.65))return'turn_clearance';
  return null;
 }
 _hold(){
  const {pose:p,motion:m,sensors:s}=this.observation;
  if(!this._poseValid(p)||!this._motionValid(m)||!Array.isArray(s.clearance_m)||s.clearance_m.length!==8||!s.clearance_m.every(v=>finite(v)&&v>=.65&&v<=1.5))return this._zero('HOLD_UNAVAILABLE','independent_pose_motion_and_surround_clearance_required',true);
  if(!this.anchor)this.anchor={x:p.x_m,y:p.y_m};
  const ex=this.anchor.x-p.x_m,ey=this.anchor.y-p.y_m;
  this.holdIntegral.x=clamp(this.holdIntegral.x+ex*DT,-.5,.5);this.holdIntegral.y=clamp(this.holdIntegral.y+ey*DT,-.5,.5);
  // Synthetic bounded feedback, not a learned model or hardware-calibrated thrust conversion.
  const vx=.6*ex+.08*this.holdIntegral.x-.35*m.vx_mps,vy=.6*ey+.08*this.holdIntegral.y-.35*m.vy_mps;
  const norm=Math.hypot(vx,vy);if(norm<.001)return{left:0,right:0,mode:'HOLD',reason:'synthetic_position_feedback'};
  let error=wrap(Math.atan2(vy,vx)-p.heading_rad),sign=1;
  if(Math.abs(error)>Math.PI/2){error=wrap(error+Math.PI);sign=-1;}
  const surge=sign*Math.min(.25,norm)*Math.max(0,Math.cos(error)),yaw=clamp(.18*error,-.14,.14);
  return{left:clamp(surge-yaw,-.25,.25),right:clamp(surge+yaw,-.25,.25),mode:'HOLD',reason:'synthetic_position_feedback'};
 }
 _possibleStall(){
  const m=this.observation.motion,f=this.observation.actuator_feedback;
  if(this.lastIntent!=='FORWARD'||!this._motionValid(m)||!this._ackValid(f)||Math.min(f.left,f.right)<.1||Math.hypot(m.vx_mps,m.vy_mps)+2*m.speed_std_mps>.015){this.stallEvidence=null;return false;}
  const e=this.stallEvidence,at=m.timestamp_unix_ms;
  if(!e||at-e.last>300)this.stallEvidence={first:at,last:at,count:1};else if(at>e.last){e.last=at;e.count++;}
  return this.stallEvidence.count>=3&&at-this.stallEvidence.first>=2000;
 }
 _ackValid(f){
  const expected=f&&this.sentControls.get(f.applied_control_sequence);
  return !!expected&&f.schema==='warirak.sim-actuator-feedback.v1'&&f.source==='simulation'&&f.units==='normalized'&&this._fresh(f.timestamp_unix_ms)&&f.request_sequence===expected.request_sequence&&f.left===expected.left&&f.right===expected.right&&f.timestamp_unix_ms>=expected.issued_at_ms&&f.timestamp_unix_ms<=expected.valid_until_ms&&f.applied_control_sequence>=this.actuationFirstSequence;
 }
 _ackTimedOut(){
  if(this.actuationSince===null)return false;
  const f=this.observation.actuator_feedback;
  if(this._ackValid(f))this.lastAckStamp=f.timestamp_unix_ms;
  return this.now()-(this.lastAckStamp??this.actuationSince)>=500;
 }
 _progressUncertain(){
  const f=this.observation.actuator_feedback,p=this.observation.pose;
  if(this.lastRequest?.action!=='FORWARD'||this.lastIntent!=='FORWARD'){this.progressEvidence=null;this.progressAssessment={status:'not_tracking',confirmed_stall:false};return false;}
  if(!this._ackValid(f)||Math.min(f.left,f.right)<.1){if(this.progressEvidence)this.progressEvidence.last_active_ms=null;this.progressAssessment={...this.progressAssessment,status:'awaiting_forward_ack',confirmed_stall:false};return false;}
  const poseValid=this._poseValid(p)&&finite(p.heading_std_rad)&&p.heading_std_rad>=0&&p.heading_std_rad<=.1;
  if(!this.progressEvidence)this.progressEvidence={started_at_ms:this.now(),active_ms:0,last_active_ms:null,anchor:poseValid?structuredClone(p):null,last_pose_stamp:null,count:0};
  const e=this.progressEvidence;
  if(e.last_active_ms!==null&&this.now()-e.last_active_ms<=300)e.active_ms+=this.now()-e.last_active_ms;
  e.last_active_ms=this.now();
  if(poseValid&&!e.anchor)e.anchor=structuredClone(p);
  let lower=null,along=null,span=0;
  if(poseValid&&e.anchor&&(e.last_pose_stamp===null||p.timestamp_unix_ms>e.last_pose_stamp)){
   const dx=p.x_m-e.anchor.x_m,dy=p.y_m-e.anchor.y_m,distance=Math.hypot(dx,dy);
   along=dx*Math.cos(e.anchor.heading_rad)+dy*Math.sin(e.anchor.heading_rad);
   lower=along-2*(p.position_std_m+e.anchor.position_std_m)-distance*2*(p.heading_std_rad+e.anchor.heading_std_rad);
   span=p.timestamp_unix_ms-e.anchor.timestamp_unix_ms;
   if(e.last_pose_stamp===null||p.timestamp_unix_ms>e.last_pose_stamp){e.count++;e.last_pose_stamp=p.timestamp_unix_ms;}
  }
  this.progressAssessment={status:'collecting_independent_progress',elapsed_ms:this.now()-e.started_at_ms,matched_forward_active_ms:e.active_ms,pose_samples:e.count,projected_displacement_m:along,conservative_progress_lower_m:lower,confirmed_stall:false};
  if(lower!==null&&lower>=.08&&e.count>=3&&span>=300){
   this.progressAssessment.status='independent_forward_progress_observed';this.progressEvidence={started_at_ms:this.now(),active_ms:0,last_active_ms:this.now(),anchor:structuredClone(p),last_pose_stamp:p.timestamp_unix_ms,count:1};return false;
  }
  if(e.active_ms>=2000){this.progressAssessment.status='independent_progress_inconclusive';return true;}
  return false;
 }
 _decide(){
  const s=this.observation.sensors;
  if(s?.manual_override===true){this.lastRequest=null;return this._zero('MANUAL_OVERRIDE','manual_control_has_priority');}
  if(s?.armed===false){this.lastRequest=null;return this._zero('DISARMED','autonomous_channel_disarmed');}
  if(this.latched)return this._zero(this.latched.mode,this.latched.reason);
  if(!s||s.source!=='simulation'||!this._fresh(s.timestamp_unix_ms)||s.armed!==true||s.manual_override!==false||!finite(s.battery_percent)||s.battery_percent<25||s.battery_percent>100)return this._zero('FAULT_STOP','sensor_watchdog_or_battery',true);
  const request=this.lastRequest;
  if(!request||this.now()>=request.valid_until_ms){this.lastRequest=null;return this._zero('WATCHDOG_STOP','fresh_mission_request_required');}
  if(request.action==='STOP')return this._zero('STOP','explicit_neutral_stop');
  if(this._ackTimedOut())return this._zero('ACTUATION_UNAVAILABLE','actuator_ack_missing_or_inconsistent',true);
  const range=s.range_evidence;
  if(!range||['invalid','stale'].includes(range.status))return this._zero('FAULT_STOP',range?.reason??'range_evidence_missing',true);
  if(range.status!=='fresh'){
   this.lastRequest=null;return this._zero('WAIT_RANGE_UPDATE','new_range_and_new_request_required');
  }
  const base=this._clearance({left:0,right:0});if(base)return this._zero('FAULT_STOP',base,true);
  if(request.action==='RECOVERY_REQUEST')return this._zero('RECOVERY_REQUIRED','operator_recovery_assessment_required',true);
  if(this._possibleStall())return this._zero('RECOVERY_REQUIRED','sustained_low_motion_with_forward_ack',true);
  if(this._progressUncertain())return this._zero('PROGRESS_UNCERTAIN','independent_progress_evidence_insufficient',true);
  if(request.action==='HOLD')return this._hold();
  const [left,right]=TRACK[request.action];this.anchor=null;this.holdIntegral={x:0,y:0};return{left,right,mode:'TRACKING',reason:'synthetic_navigation_request'};
 }
 step(request=null){
  if(this.done)return{observation:this.observe(),done:true};
  const prior=this.observe();this._accept(request);
  const nextIntent=this.lastRequest?.action??'STOP';
  if((nextIntent==='HOLD')!==(this.lastIntent==='HOLD')){this.queue=[];this.anchor=null;this.holdIntegral={x:0,y:0};this.stallEvidence=null;this.actuationSince=null;this.actuationFirstSequence=null;this.lastAckStamp=null;}
  let issued=this._decide();this.mode=issued.mode;this.reason=issued.reason;
  const blocked=(issued.left||issued.right)?this._clearance(issued):null;if(blocked)issued=this._zero('FAULT_STOP',blocked,true);
  const control={...issued,sequence:++this.controlSequence,request_sequence:this.lastRequest?.sequence??null,issued_at_ms:this.now(),valid_until_ms:Math.min(this.now()+400,this.lastRequest?.valid_until_ms??this.now()+100)};
  let applied={left:0,right:0,sequence:null,request_sequence:null};let receiverReason='neutral';
  if(issued.left===0&&issued.right===0){this.queue=[];this.actuationSince=null;this.actuationFirstSequence=null;this.lastAckStamp=null;}
  else{
   if(this.actuationSince===null){this.actuationSince=this.now();this.actuationFirstSequence=control.sequence;}
   this.sentControls.set(control.sequence,structuredClone(control));while(this.sentControls.size>16)this.sentControls.delete(this.sentControls.keys().next().value);
   this.queue.push(control);
   if(this.queue.length>this.delayTicks){
    const queued=this.queue.shift(),guard=this._clearance(queued);
    if(this.now()>=queued.valid_until_ms){receiverReason='queued_command_expired';this._zero('ACTUATION_UNAVAILABLE',receiverReason,true);}
    else if(guard){receiverReason=guard;this._zero('FAULT_STOP',guard,true);}
    else{applied=queued;receiverReason='applied_after_receiver_check';}
   }else receiverReason='neutral_delay_startup';
  }
  const x=this.x,y=this.y,heading=this.heading;
  const left=applied.left*this.leftGain,right=applied.right*this.rightGain;
  const desired=this.faults.jammed?0:(left+right)/2;
  this.surge+=(desired-this.surge)*(1-Math.exp(-DT/this.surgeTimeConstant));
  if(!this.faults.jammed)this.heading=wrap(this.heading+(right-left)/.4*DT);
  this.x+=(Math.cos(this.heading)*this.surge+this.drift.x)*DT;this.y+=(Math.sin(this.heading)*this.surge+this.drift.y)*DT;this.steps++;
  // Independent simulated displacement measurement; no command-to-velocity substitution.
  this.lastMotion={vx:(this.x-x)/DT,vy:(this.y-y)/DT,yaw_rate:wrap(this.heading-heading)/DT};
  this.lastFeedback={schema:'warirak.sim-actuator-feedback.v1',source:'simulation',units:'normalized',timestamp_unix_ms:this.now(),applied_control_sequence:applied.sequence,request_sequence:applied.request_sequence,left:applied.left,right:applied.right,digital_ack_is_not_mechanical_thrust:true};
  const collision=this.x<this.radius||this.x>this.width-this.radius||this.y<this.radius||this.y>this.height-this.radius||this.obstacles.some(o=>Math.hypot(this.x-o.x,this.y-o.y)<o.r+this.radius);
  if(collision){this.collisions=1;this.done=true;}
  else if(this.mode==='TRACKING'&&this.surge>.15&&Math.hypot(this.target.x-this.x,this.target.y-this.y)<.5&&Math.abs(wrap(Math.atan2(this.target.y-this.y,this.target.x-this.x)-this.heading))<.58){this.collected=1;this.done=true;}
  this.truncated=!this.done&&this.steps>=this.maxSteps;this.done=this.done||this.truncated;this.lastIntent=nextIntent;
  if(this.record)this.trace.push({source:'simulation',before:prior,request:structuredClone(request),issued:structuredClone(control),applied:structuredClone(applied),receiver_reason:receiverReason,after:{x:this.x,y:this.y,heading:this.heading,surge:this.surge},control_enabled:false});
  this.observation=this._sample();return{observation:this.observe(),done:this.done};
 }
 snapshot(){return{schema:'warirak.mission-sim-snapshot.v2',environment:MISSION_ENV_R2,source:'simulation',seed:this.seed,profile:this.profile,fixture_used:this.fixtureUsed,observation_noise:{clearance_m:this.clearanceNoise,sensor_dropout:this.sensorDropout,target_dropout:this.targetDropout,bearing_rad:this.bearingNoise,range_m:this.rangeNoise,position_m:this.positionNoise,velocity_mps:this.velocityNoise,heading_rad:this.headingNoise},steps:this.steps,x:this.x,y:this.y,heading:this.heading,surge:this.surge,drift:structuredClone(this.drift),delay_ticks:this.delayTicks,queue:structuredClone(this.queue),anchor:structuredClone(this.anchor),mode:this.mode,reason:this.reason,latched:structuredClone(this.latched),collisions:this.collisions,collected:this.collected,truncated:this.truncated,done:this.done,observation:this.observe(),control_enabled:false,field_validated:false};}
}
