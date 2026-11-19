// Bounded, read-only policy diagnosis. Original R2 plant and guards remain untouched.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {MissionPoolEnvR2,missionRequestR2} from './navigation_mission_env_r2.mjs';
import {navigationPolicyController,navigationBaseline} from './navigation_only_learning.mjs';
import {navigationAllowed,navigationFeatures,NAV_ONLY_ACTIONS} from './navigation_action_interface.mjs';
const assistance=new Set(['FAULT_STOP','HOLD_UNAVAILABLE','RECOVERY_REQUIRED','ACTUATION_UNAVAILABLE','PROGRESS_UNCERTAIN']);
const finite=v=>typeof v==='number'&&Number.isFinite(v);
export function clearanceOnlyStop(observation,allowed){
 const c=observation.sensors?.clearance_m,r=observation.sensors?.range_evidence,now=observation.timestamp_unix_ms;
 return observation.sensors?.armed===true&&observation.sensors?.manual_override===false&&!assistance.has(observation.mission?.mode)&&r?.status==='fresh'&&finite(r.captured_at_ms)&&now-r.captured_at_ms>=0&&now-r.captured_at_ms<=300&&Array.isArray(c)&&c.length===8&&c.every(v=>v===null||finite(v)&&v>=0&&v<=1.5)&&[c[0],c[1],c[7]].every(finite)&&c.some(v=>finite(v)&&v<.35)&&allowed.length===1&&allowed[0]===0;
}
function snapshot(o){return{at_ms:o.timestamp_unix_ms,clearance_m:o.sensors?.clearance_m,range_evidence:o.sensors?.range_evidence,pose:o.pose,motion:o.motion,mission:o.mission,applied_feedback:o.actuator_feedback};}
export function inspectNavigationEpisode(env,decide){
 assert.equal(env.fixtureUsed,false);
 let previous=0,firstClearance=null,firstAssistance=null,window=[],terminal=null;
 const event=(o,step,x,y)=>({step,observation:snapshot(o),diagnostic_simulated_position:{x_m:x,y_m:y},window_before:structuredClone(window),subsequent_nonzero_applied_outputs:0,subsequent_steps:0});
 while(!env.done){
  const before=env.observe(),f=navigationFeatures(before,previous),allowed=navigationAllowed(before,f),action=decide(before,previous);
  assert(allowed.includes(action)&&action>=0&&action<7,'Request outside frozen navigation alphabet/mask');
  if(!firstClearance&&clearanceOnlyStop(before,allowed))firstClearance=event(before,env.steps,env.x,env.y);
  const request=missionRequestR2(env.steps,env.now(),NAV_ONLY_ACTIONS[action]);
  env.step(request);const after=env.observe(),feedback=after.actuator_feedback;
  const nonzero=!!feedback&&(Math.abs(feedback.left)>0||Math.abs(feedback.right)>0);
  for(const e of [firstClearance,firstAssistance])if(e){e.subsequent_steps++;e.subsequent_nonzero_applied_outputs+=Number(nonzero);}
  terminal={before:snapshot(before),action:NAV_ONLY_ACTIONS[action],request,after:snapshot(after),diagnostic_simulated_position:{x_m:env.x,y_m:env.y}};
  window.push(terminal);if(window.length>10)window.shift();
  if(!firstAssistance&&assistance.has(after.mission?.mode)){
   firstAssistance=event(after,env.steps,env.x,env.y);
   assert.equal(nonzero,false,'Assistance event applied nonneutral output');
  }
  previous=action;
 }
 for(const e of [firstClearance,firstAssistance])if(e){e.displacement_to_end_m=Math.hypot(env.x-e.diagnostic_simulated_position.x_m,env.y-e.diagnostic_simulated_position.y_m);e.elapsed_to_end_ms=env.now()-e.observation.at_ms;}
 if(firstAssistance)assert.equal(firstAssistance.subsequent_nonzero_applied_outputs,0,'Independent assistance failed to stay neutral');
 assert.equal(env.collected+env.collisions+Number(env.truncated),1,'Lost or censored outcome');
 const category=env.collisions?(firstAssistance?'collision_after_assistance':firstClearance?'collision_after_clearance_only_stop':'collision_without_recorded_clearance_stop_or_assistance'):'no_collision';
 return{seed:env.seed,profile:env.profile,source:'simulation',fixture_used:false,transport_delay_ms:env.delayTicks*100,first_clearance_only_stop:firstClearance,first_assistance:firstAssistance,terminal,terminal_window:window,ended_at_step:env.steps,outcome:env.collisions?'collision':env.collected?'collection':'timeout',timeline_category:category,control_enabled:false};
}
export function runNavigationPostmortem(output){
 const project=path.dirname(path.dirname(fileURLToPath(import.meta.url))),read=f=>JSON.parse(fs.readFileSync(f,'utf8').replace(/^\uFEFF/,'')),sha=f=>createHash('sha256').update(fs.readFileSync(f)).digest('hex');
 assert.equal(fs.existsSync(output),false,'Preserve existing closed diagnostic evidence');
 const planFile=path.join(project,'ai/navigation-r3-postmortem-plan.json'),plan=read(planFile),run=path.join(project,plan.closed_run),status=read(path.join(run,'status.json')),protocol=read(path.join(run,'protocol.json')),review=read(path.join(project,'outputs/Warirak_Navigation_Only_R3_Artifact_Review.json'));
 assert.equal(status.phase,'retained_baseline');assert.equal(status.test_opened,false);assert.equal(status.training_finished,true);
 assert.equal(review.protocol_sha256,sha(path.join(run,'protocol.json')));assert.equal(review.source_hashes_valid,true);
 for(const [file,hash] of Object.entries(protocol.source_sha256))assert.equal(sha(path.join(project,file)),hash,file);
 assert.equal(sha(path.join(project,'frontend/assets/navigation-policy.json')),protocol.baseline_sha256);
 assert.deepEqual(plan.training_episode_indices,Array.from({length:24},(_,i)=>i));
 assert.deepEqual(plan.contexts,['frozen_snapshot6000_greedy','fixed_rules_with_hold']);
 const policyFile=path.join(run,'policy-6000.json'),candidate=read(path.join(run,'candidate-6000.json'));
 assert.equal(sha(policyFile),candidate.policy_sha256);
 const policy=read(policyFile),legacy=read(path.join(project,'frontend/assets/navigation-policy.json'));
 const sourceFiles=[...Object.keys(protocol.source_sha256),'ai/diagnose_navigation_r3.mjs'];
 fs.mkdirSync(output,{recursive:true});
 const frozen={...plan,frozen_at:new Date().toISOString(),frozen_before_diagnostic:true,plan_sha256:sha(planFile),closed_protocol_sha256:review.protocol_sha256,policy_sha256:sha(policyFile),baseline_sha256:protocol.baseline_sha256,source_sha256:Object.fromEntries(sourceFiles.map(f=>[f,sha(path.join(project,f))]))};
 fs.writeFileSync(path.join(output,'plan.json'),JSON.stringify(frozen,null,2),{flag:'wx'});
 const cases=[];
 for(const context of plan.contexts){
  const controller=context==='frozen_snapshot6000_greedy'?navigationPolicyController(policy):navigationBaseline('rules_with_hold',legacy);
  for(const index of plan.training_episode_indices){
   assert(index>=0&&index<protocol.training.episodes);
   const env=new MissionPoolEnvR2(protocol.training.seed+index,{profile:index%4===0?'nominal':'stress'});
   cases.push({context,training_episode_index:index,...inspectNavigationEpisode(env,controller)});
  }
 }
 const count=(rows,key)=>Object.fromEntries([...new Set(rows.map(key))].sort().map(k=>[k,rows.filter(r=>key(r)===k).length]));
 const summary=Object.fromEntries(plan.contexts.map(context=>{const rows=cases.filter(c=>c.context===context);return[context,{sampled_scenes:rows.length,profiles:count(rows,r=>r.profile),timeline_categories:count(rows,r=>r.timeline_category),first_assistance_reasons:count(rows,r=>r.first_assistance?.observation.mission?.reason??'none_before_end'),latency_strata:Object.fromEntries([0,300,600].map(delay=>{const subset=rows.filter(r=>r.transport_delay_ms===delay);return[delay,{scenes:subset.length,timeline_categories:count(subset,r=>r.timeline_category),first_assistance_reasons:count(subset,r=>r.first_assistance?.observation.mission?.reason??'none_before_end')}];})),nonzero_outputs_after_assistance:rows.reduce((n,r)=>n+(r.first_assistance?.subsequent_nonzero_applied_outputs??0),0)}];}));
 const result={schema:'warirak.navigation-r3-postmortem.v1',role:plan.role,closed_run:plan.closed_run,source:'simulation',training_started:false,q_updates_performed:false,validation_opened:false,test_opened:false,historical_training_reconstructed:false,not_a_performance_benchmark:true,summary,cases,limitations:[plan.comparison_limit,'Twenty-four already-used training scenes per fixed controller. A temporal category is not attribution of validation collisions or an estimate of field performance.','Simulated coordinates are diagnostic truth only, not added controller features.'],physical_motor_transport:false};
 fs.writeFileSync(path.join(output,'diagnostic.json'),JSON.stringify(result,null,2),{flag:'wx'});
 console.log(JSON.stringify({output,summary,training_started:false,test_opened:false}));return result;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))runNavigationPostmortem(path.resolve(process.argv[2]||'work/navigation-r3-postmortem'));
