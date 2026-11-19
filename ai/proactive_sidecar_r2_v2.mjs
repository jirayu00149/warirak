// Simulation-only wrapper. Caller supplies every request; R2 retains all physical/guard logic.
import {MissionPoolEnvR2} from './navigation_mission_env_r2.mjs';
import {ISSUED_CONTROL_RECORD} from './proactive_observation.mjs';
import {ProactiveSidecarV2} from './proactive_sidecar_v2.mjs';
export class ProactiveSidecarR2V2{
 constructor(env,{sidecar=new ProactiveSidecarV2()}={}){
  if(!(env instanceof MissionPoolEnvR2)||env.record!==true||env.maxSteps!==960||!(sidecar instanceof ProactiveSidecarV2))throw Error('Owned recorded R2 simulation and bounded sidecar required');
  this.env=env;this.sidecar=sidecar;
 }
 step(request=null,{owner='navigation'}={}){
  if(this.env.done)return{schema:'warirak.proactive-sidecar-r2-step.v2',done:true,advanced:false,control_enabled:false};
  const captured=this.sidecar.capture(this.env.observe(),{receivedAtMs:this.env.now()});
  const decision=this.sidecar.noteDecision(request,{owner,atMs:this.env.now()});
  // Recorder outcomes never replace or reissue the caller's request, including null/manual/STOP.
  const result=this.env.step(request),trace=this.env.trace.at(-1),c=trace.issued;
  const transition=this.sidecar.attachTransition(trace,{recordSequence:captured.record_sequence});
  const issued=Number.isInteger(c.request_sequence)&&c.request_sequence>=0?this.sidecar.noteIssuedControl({schema:ISSUED_CONTROL_RECORD,plant_environment:'warirak-pool-mission-v4r2-dev',source:'simulation',units:'normalized',control_enabled:false,physical_transport:false,control_sequence:c.sequence,request_sequence:c.request_sequence,issued_at_ms:c.issued_at_ms,valid_until_ms:c.valid_until_ms,left:c.left,right:c.right},{atMs:this.env.now()}):{status:'unmatched_neutral_control_retained_in_transition',control_enabled:false};
  // The wrapper owns trace consumption. Full bounded records already contain the copied step.
  if(this.env.trace.length>1)this.env.trace.splice(0,this.env.trace.length-1);
  return{schema:'warirak.proactive-sidecar-r2-step.v2',done:result.done,advanced:true,capture:captured,decision,transition,issued,observation:result.observation,recorder_fault:this.sidecar.snapshot().stream_fault,control_enabled:false,physical_motor_transport:false};
 }
}
