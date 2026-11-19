import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {MissionPoolEnvR2,missionRequestR2,MISSION_ACTIONS_R2} from '../ai/navigation_mission_env_r2.mjs';
import {NavigationEpisodeBridge,r2Reward,durationCreditToOneStep} from '../ai/navigation_episode_bridge.mjs';
import {FRAME_FIELDS} from '../ai/navigation_history_encoder.mjs';
import {VALIDATION_MODEL_SCHEMA} from '../ai/navigation_inference_wire.mjs';
const collected=[],multi=[];
const output=new URL('../work/navigation-episode-preflight/bridge-transitions.json',import.meta.url);
function pool(seed,{delay=0,nearBank=false}={}){
 const probe=new MissionPoolEnvR2(seed,{profile:'stress'}),d=probe.drift;
 const fixture={x:5,y:3,heading:0,target:{x:9,y:3,class_id:0},obstacles:[],delayTicks:delay};
 if(nearBank){
  const alongX=Math.abs(d.x)>=Math.abs(d.y),speed=Math.abs(alongX?d.x:d.y);assert(speed>0);
  // Analytical four-step drift collision fixture. Current/noise/gains remain original.
  if(alongX)fixture.x=d.x>0?probe.width-probe.radius-speed*.35:probe.radius+speed*.35;
  else fixture.y=d.y>0?probe.height-probe.radius-speed*.35:probe.radius+speed*.35;
 }
 return new MissionPoolEnvR2(seed,{profile:'stress',record:true,fixture});
}
const bridge=(env,options={})=>new NavigationEpisodeBridge(env,{episodeId:'unit-'+env.seed,sessionId:'unit-'+env.seed,...options});
function keep(ledger){for(const c of ledger.completed_credits){if(c.duration_steps===1){collected.push(durationCreditToOneStep(c));if(collected.length>12)collected.shift();}else if(c.duration_steps>1&&multi.length<3)multi.push(c);}}
function fakeReply(r,action){return{schema:'warirak.navigation-inference-reply.v1',source:r.source,plant_environment:r.plant_environment,encoder_schema:r.encoder_schema,layout_sha256:r.layout_sha256,session_id:r.session_id,request_id:r.request_id,stream_epoch:r.stream_epoch,record_sequence:r.record_sequence,observation_at_ms:r.observation_at_ms,valid_until_ms:r.valid_until_ms,vector_sha256:r.vector_sha256,model_schema:VALIDATION_MODEL_SCHEMA,action,control_enabled:false,physical_motor_transport:false};}
test('Reward uses unchanged R2 terms; assistance reward is distinct from terminal reward',()=>{
 const r=r2Reward({beforeDistance:2,afterDistance:1.9,collection:false,collision:false,firstAssistance:true});
 assert(Math.abs(r.reward-(.3-.015-10))<1e-12);assert.equal(r.terms.collision,0);
 assert.throws(()=>r2Reward({beforeDistance:2,afterDistance:1,collection:true,collision:true,firstAssistance:false}));
});
for(const delay of [0,3,6])test('Driver and unchanged bare R2 snapshots match with actuator delay '+delay*100+'ms',()=>{
 const env=pool(11100+delay,{delay}),reference=pool(11100+delay,{delay}),b=bridge(env);
 for(let i=0;i<10&&!env.done;i++){
  assert.deepEqual(env.observe(),reference.observe());const action=b.allowed().includes(1)?1:b.allowed()[0];
  const request=missionRequestR2(reference.steps,reference.now(),MISSION_ACTIONS_R2[action],400);
  keep(b.advance(action));reference.step(request);assert.deepEqual(env.snapshot(),reference.snapshot());
 }
 assert.equal(b.summary().integrity_failures,0);assert.equal(b.summary().ttl_violations,0);
 if(delay===6)assert.equal(b.summary().nonzero_applied_steps,0);
 assert(env.maxSteps===960);assert(Math.abs(env.drift.x)+Math.abs(env.drift.y)>0);
});
test('Manual/disarm/recording cancellation cut history but keep consecutive physical steps',()=>{
 const b=bridge(pool(11120),{faultSchedule:[{step:1,patch:{manual_override:true}},{step:2,patch:{manual_override:false,armed:false}},{step:3,patch:{armed:true},cancel_recording:true}]});
 let epoch=b.request().stream_epoch;
 for(let i=0;i<5;i++){
  const r=b.advance(0);keep(r);assert.equal(r.next_request.observation_at_ms-r.state_request.observation_at_ms,100);
  if(i<3){assert(r.next_request.stream_epoch>epoch);assert(r.next_request.vector.slice(0,156).every(v=>v===0));assert.equal(r.next_request.vector[156+FRAME_FIELDS.indexOf('previous_request.UNKNOWN')],1);}
  epoch=r.next_request.stream_epoch;
 }
 assert.equal(b.summary().steps,5);assert.equal(b.summary().integrity_failures,0);assert.equal(b.summary().reward_conservation_error,0);
});
test('STOP remains neutral while original current naturally carries the boat into a collision',()=>{
 const b=bridge(pool(11130,{nearBank:true}));let collisionLedger;
 while(!b.env.done){const r=b.advance(0);keep(r);if(r.terminal)collisionLedger=r;}
 assert.equal(b.summary().collisions,1);assert.equal(b.summary().nonzero_applied_steps,0);
 assert.equal(collisionLedger.terminal_reason,'collision');assert.equal(collisionLedger.reward_terms.collision,-30);
 assert.equal(b.summary().steps,4);assert(Math.abs(b.summary().reward_conservation_error)<1e-10);
 assert(b.env.observe().motion!==null);
});
test('First assistance is penalized once; drift/collision tail stays in outcome and credit',()=>{
 const b=bridge(pool(11131,{nearBank:true}),{faultSchedule:[{step:0,patch:{battery_percent:20}}]});
 const first=b.advance(0);keep(first);assert.equal(first.reward_terms.first_assistance,-10);assert.equal(first.terminal,false);
 let assistTerms=first.reward_terms.first_assistance,terminal;
 while(!b.env.done){const r=b.advance(0);keep(r);assistTerms+=r.reward_terms.first_assistance;terminal=r;}
 assert.equal(assistTerms,-10);assert.equal(terminal.terminal_reason,'collision');assert.equal(terminal.reward_terms.collision,-30);
 assert.equal(b.summary().collisions,1);assert.equal(b.summary().steps,4);assert.equal(b.summary().pending_credit_steps,0);
 assert(Math.abs(b.summary().reward-b.summary().credited_raw_reward)<1e-10);
});
test('Null-request waits are assigned to the real preceding request with duration and discount',()=>{
 const b=bridge(pool(11140));const a=b.advance(0),wait=b.advance(null),next=b.advance(0);keep(next);
 const c=next.completed_credits[0];assert.equal(c.duration_steps,2);
 assert(Math.abs(c.reward-(a.reward+.985*wait.reward))<1e-10);
 assert(Math.abs(c.undiscounted_reward-(a.reward+wait.reward))<1e-10);
 assert.equal(c.continuation_discount,.985**2);assert.equal(c.next_request.observation_at_ms-c.state_request.observation_at_ms,200);
 assert.throws(()=>durationCreditToOneStep(c));assert.equal(wait.original_request,null);assert.equal(wait.requested_action,null);
 assert(Math.abs(b.summary().reward_conservation_error)<1e-10);
});
test('Cancelled/replaced model replies issue no new mission request and do not restamp evidence',()=>{
 const b=bridge(pool(11150)),old=b.request();assert.equal(b.cancelRecording().commands_generated,0);
 const result=b.advanceFromReply(fakeReply(old,old.allowed_mask.findIndex(Boolean)),{expectedModelSchema:VALIDATION_MODEL_SCHEMA,allowValidationFixture:true});
 assert.equal(result.original_request,null);assert.equal(result.state_request.observation_at_ms,old.observation_at_ms);assert.equal(result.next_request.observation_at_ms,old.observation_at_ms+100);
 assert.equal(b.summary().passive_prefix_steps,1);assert.equal(b.summary().reply_rejections,1);
 const again=b.advanceFromReply(fakeReply(old,0),{expectedModelSchema:VALIDATION_MODEL_SCHEMA,allowValidationFixture:true});assert.equal(again.original_request,null);
 assert.equal(b.summary().steps,2);assert.equal(b.summary().reply_rejections,2);
});
test('Prepared packets are immutable to callers and unowned world changes fail before movement',()=>{
 const b=bridge(pool(11160)),r=b.request();r.vector[0]=99;assert.notEqual(b.request().vector[0],99);
 assert.throws(()=>b.advance(7));assert.equal(b.env.steps,0);
 b.env.observation.target.visible=!b.env.observation.target.visible;assert.throws(()=>b.advance(0));assert.equal(b.env.steps,0);
});
test('Write bounded real-bridge software examples for Python validation, with no performance benchmark',()=>{
 assert(collected.length>=5);assert(multi.length>=1);
 const protocol=JSON.parse(fs.readFileSync(new URL('../work/navigation-episode-preflight/protocol.json',import.meta.url)));
 assert.equal(protocol.scope_type,'software_only');assert.equal(fs.existsSync(output),false);
 fs.writeFileSync(output,JSON.stringify({schema:'warirak.navigation-bridge-software-examples.v1',software_unit_examples:true,training_dataset:false,plant_performance_trial:false,one_step:collected,duration:multi},null,2));
});
