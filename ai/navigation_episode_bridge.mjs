// R2 simulation/reward/credit ownership only. No neural training or physical transport.
import {createHash} from 'node:crypto';
import {MissionPoolEnvR2,missionRequestR2,MISSION_ACTIONS_R2} from './navigation_mission_env_r2.mjs';
import {navigationAllowed,navigationFeatures} from './navigation_action_interface.mjs';
import {ProactiveSidecarV2} from './proactive_sidecar_v2.mjs';
import {ISSUED_CONTROL_RECORD} from './proactive_observation.mjs';
import {encodeNavigationHistory} from './navigation_history_encoder.mjs';
import {NavigationInferenceClient} from './navigation_inference_wire.mjs';
export const EPISODE_BRIDGE_SCHEMA='warirak.navigation-r2-episode-bridge.v1';
export const DURATION_CREDIT_SCHEMA='warirak.navigation-duration-credit.v1';
const ASSIST=new Set(['FAULT_STOP','HOLD_UNAVAILABLE','RECOVERY_REQUIRED','ACTUATION_UNAVAILABLE','PROGRESS_UNCERTAIN']);
const owners=new WeakSet(),finite=v=>typeof v==='number'&&Number.isFinite(v);
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const clone=value=>structuredClone(value);

export function r2Reward({beforeDistance,afterDistance,collection,collision,firstAssistance}){
 if(![beforeDistance,afterDistance].every(v=>finite(v)&&v>=0)||![collection,collision,firstAssistance].every(v=>typeof v==='boolean')||collection&&collision)throw Error('Invalid R2 reward evidence');
 const terms={distance_progress:3*(beforeDistance-afterDistance),step:-.015,collection:collection?40:0,collision:collision?-30:0,first_assistance:firstAssistance?-10:0};
 return{reward:Object.values(terms).reduce((a,b)=>a+b,0),terms};
}
export function durationCreditToOneStep(credit){
 if(credit?.schema!==DURATION_CREDIT_SCHEMA||credit.duration_steps!==1||credit.next_request.observation_at_ms-credit.state_request.observation_at_ms!==100)throw Error('One-step learner cannot consume duration credit; do not split, drop or relabel wait rewards');
 return{schema:'warirak.navigation-history-transition.v1',source:'simulation',plant_environment:'warirak-pool-mission-v4r2-dev',episode_id:credit.episode_id,state_request:clone(credit.state_request),action:credit.action,reward:credit.reward,next_request:clone(credit.next_request),terminal:credit.terminal,terminal_reason:credit.terminal_reason};
}

export class NavigationEpisodeBridge{
 constructor(env,{episodeId,sessionId,faultSchedule=[]}={}){
  if(!(env instanceof MissionPoolEnvR2)||!env.record||env.steps!==0||env.maxSteps!==960||env.dt!==.1||owners.has(env)||typeof episodeId!=='string'||!/^[A-Za-z0-9_.:-]{1,96}$/.test(episodeId)||!Array.isArray(faultSchedule)||faultSchedule.length>16)throw Error('New owned recorded R2 simulation and bounded identity/schedule required');
  for(const e of faultSchedule)if(!Number.isInteger(e.step)||e.step<0||e.step>960||Object.keys(e).some(k=>!['step','patch','cancel_recording'].includes(k))||e.cancel_recording!==undefined&&e.cancel_recording!==true||e.patch!==undefined&&(e.patch===null||typeof e.patch!=='object'||Array.isArray(e.patch)))throw Error('Invalid exogenous software fault schedule');
  owners.add(env);this.env=env;this.episodeId=episodeId;this.schedule=clone(faultSchedule);this.appliedEvents=new Set();
  this.recorder=new ProactiveSidecarV2();this.client=new NavigationInferenceClient(sessionId);
  this.previousAction=0;this.current=null;this.pendingCredit=null;this.cancelledCurrent=false;
  this.stats={steps:0,reward:0,assistance:false,hard_unavailable:false,range_wait_steps:0,nonzero_applied_steps:0,integrity_failures:0,ttl_violations:0,null_request_steps:0,reply_rejections:0,completed_credits:0,duration_credits:0,credited_steps:0,credited_raw_reward:0,passive_prefix_steps:0,passive_prefix_reward:0};
  this._scheduled();this._capture();
 }
 _scheduled(){
  for(let i=0;i<this.schedule.length;i++)if(!this.appliedEvents.has(i)&&this.schedule[i].step===this.env.steps){
   const e=this.schedule[i];if(e.patch)this.env.setFaults(e.patch);
   if(e.cancel_recording){this.recorder.cancel(this.env.now());this.client.cancel(this.env.now());}
   this.appliedEvents.add(i);
  }
 }
 _capture(){
  const o=this.env.observe(),captured=this.recorder.capture(o,{receivedAtMs:this.env.now()});
  if(captured.status!=='accepted'||captured.stream_fault)throw Error('Unencodable R2 stream: '+captured.reason+'; preserve checkpoint and repair, never count this as a completed episode');
  const row=this.recorder.records().at(-1),allowed=navigationAllowed(o,navigationFeatures(o,this.previousAction));
  const encoded=encodeNavigationHistory(row,captured.decision_context?this.recorder.decisionWindow():[],allowed,{nowMs:this.env.now()});
  const request=this.client.issue(encoded);
  this.current={request,allowed,observation:o,observation_hash:hash(o),record_sequence:row.stream.record_sequence};
  this.cancelledCurrent=false;
  if(this.env.done)this.client.cancel(this.env.now());
 }
 request(){return clone(this.current.request);}
 allowed(){return[...this.current.allowed];}
 cancelRecording(){
  const a=this.recorder.cancel(this.env.now()),b=this.client.cancel(this.env.now());this.cancelledCurrent=true;
  return{schema:EPISODE_BRIDGE_SCHEMA,commands_generated:a.commands_generated+b.commands_generated,physical_motor_transport:false};
 }
 _observationStats(o){
  const range=o.sensors?.range_evidence?.status;
  if(range!=='fresh')this.stats.range_wait_steps++;
  if(['stale','invalid'].includes(range)||o.mission?.mode==='ACTUATION_UNAVAILABLE')this.stats.hard_unavailable=true;
  if(ASSIST.has(o.mission?.mode))this.stats.assistance=true;
 }
 _finishCredit(next,terminal,reason){
  const p=this.pendingCredit;if(!p)return null;
  if(p.duration_steps<1)throw Error('Credit without any physical step');
  const result={schema:DURATION_CREDIT_SCHEMA,source:'simulation',plant_environment:'warirak-pool-mission-v4r2-dev',episode_id:this.episodeId,state_request:clone(p.state_request),action:p.action,reward:p.reward,undiscounted_reward:p.raw_reward,duration_steps:p.duration_steps,continuation_discount:.985**p.duration_steps,next_request:clone(next),terminal,terminal_reason:reason,physical_motor_transport:false};
  this.stats.completed_credits++;this.stats.duration_credits+=Number(p.duration_steps>1);this.stats.credited_steps+=p.duration_steps;this.stats.credited_raw_reward+=p.raw_reward;this.pendingCredit=null;return result;
 }
 advance(action=null,{decisionSource='explicit_navigation_request'}={}){
  if(this.env.done)throw Error('Completed episode must not advance');
  if(typeof decisionSource!=='string'||decisionSource.length>256)throw Error('Bounded decision provenance required');
  const c=this.current,env=this.env;
  if(hash(env.observe())!==c.observation_hash||env.now()!==c.request.observation_at_ms)throw Error('Prepared simulation observation changed outside driver ownership');
  if(action!==null&&(!Number.isInteger(action)||!c.allowed.includes(action)||action>6||this.cancelledCurrent))throw Error('Cancelled or prohibited navigation request');
  const credits=[];
  if(action!==null){
   const previous=this._finishCredit(c.request,false,'none');if(previous)credits.push(previous);
   this.pendingCredit={state_request:clone(c.request),action,reward:0,raw_reward:0,duration_steps:0};
  }
  this._observationStats(c.observation);
  const before=Math.hypot(env.target.x-env.x,env.target.y-env.y),seenAssist=this.stats.assistance;
  const originalRequest=action===null?null:missionRequestR2(env.steps,c.request.observation_at_ms,MISSION_ACTIONS_R2[action],400);
  const decision=this.recorder.noteDecision(originalRequest,{atMs:env.now()});
  if(originalRequest&&decision.status!=='recorded_original_request'&&decision.status!=='context_suppressed')throw Error('Decision recording failed before physics');
  env.step(originalRequest);
  const trace=env.trace.at(-1),control=trace.issued;
  this.recorder.attachTransition(trace,{recordSequence:c.record_sequence});
  if(Number.isInteger(control.request_sequence)&&control.request_sequence>=0)this.recorder.noteIssuedControl({schema:ISSUED_CONTROL_RECORD,plant_environment:'warirak-pool-mission-v4r2-dev',source:'simulation',units:'normalized',control_enabled:false,physical_transport:false,control_sequence:control.sequence,request_sequence:control.request_sequence,issued_at_ms:control.issued_at_ms,valid_until_ms:control.valid_until_ms,left:control.left,right:control.right},{atMs:env.now()});
  const firstAssistance=!seenAssist&&ASSIST.has(env.mode);
  const reward=r2Reward({beforeDistance:before,afterDistance:Math.hypot(env.target.x-env.x,env.target.y-env.y),collection:env.collected===1,collision:env.collisions===1,firstAssistance});
  this.stats.steps++;this.stats.reward+=reward.reward;this.stats.assistance||=firstAssistance;
  this.stats.null_request_steps+=Number(action===null);
  const moved=trace.applied.left!==0||trace.applied.right!==0;this.stats.nonzero_applied_steps+=Number(moved);
  if(moved&&(c.observation.sensors.manual_override||!c.observation.sensors.armed||env.faults.range_packet_loss))this.stats.integrity_failures++;
  if(control.valid_until_ms-control.issued_at_ms>400)this.stats.ttl_violations++;
  if(this.pendingCredit){const p=this.pendingCredit;p.reward+=(.985**p.duration_steps)*reward.reward;p.raw_reward+=reward.reward;p.duration_steps++;}
  else{this.stats.passive_prefix_steps++;this.stats.passive_prefix_reward+=reward.reward;}
  this.previousAction=action??0;
  if(env.trace.length>1)env.trace.splice(0,env.trace.length-1);
  this._scheduled();this._capture();this._observationStats(this.current.observation);
  const reason=env.collected?'collection':env.collisions?'collision':env.truncated?'time_limit':'none';
  if(env.done){const final=this._finishCredit(this.current.request,true,reason);if(final)credits.push(final);}
  const accounted=this.stats.credited_raw_reward+this.stats.passive_prefix_reward+(this.pendingCredit?.raw_reward??0);
  if(Math.abs(accounted-this.stats.reward)>1e-7)throw Error('Reward accounting lost physical steps');
  if(this.stats.credited_steps+this.stats.passive_prefix_steps+(this.pendingCredit?.duration_steps??0)!==this.stats.steps)throw Error('Physical step accounting gap');
  return{schema:'warirak.navigation-r2-step-ledger.v1',source:'simulation',state_request:clone(c.request),requested_action:action,original_request:originalRequest,decision_source:decisionSource,decision_recording_status:decision.status,reward:reward.reward,reward_terms:reward.terms,next_request:this.request(),terminal:env.done,terminal_reason:reason,completed_credits:credits,issued:clone(trace.issued),applied:clone(trace.applied),physical_motor_transport:false};
 }
 advanceFromReply(reply,options={}){
  let action=null,source='accepted_model_reply';
  try{action=this.client.receive(reply,{...options,nowMs:this.env.now()}).action;}
  catch(error){this.stats.reply_rejections++;source='no_new_request_rejected_reply:'+error.message;}
  return this.advance(action,{decisionSource:source});
 }
 summary(){
  const env=this.env;
  if(env.done&&env.collected+env.collisions+Number(env.truncated)!==1)throw Error('Missing natural episode outcome');
  return{schema:'warirak.navigation-r2-episode-result.v1',source:'simulation',episode_id:this.episodeId,seed:env.seed,profile:env.profile,fixture_used:env.fixtureUsed,...clone(this.stats),collections:env.collected,collisions:env.collisions,timeouts:Number(env.truncated),done:env.done,terminal_reason:env.collected?'collection':env.collisions?'collision':env.truncated?'time_limit':'none',transport_delay_ms:env.delayTicks*100,pending_credit_steps:this.pendingCredit?.duration_steps??0,reward_conservation_error:this.stats.reward-this.stats.credited_raw_reward-this.stats.passive_prefix_reward-(this.pendingCredit?.raw_reward??0),all_physical_steps_accounted:true,assistance_not_early_termination:true,real_world_validated:false,physical_motor_transport:false};
 }
}
