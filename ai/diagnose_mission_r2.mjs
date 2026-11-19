import fs from'node:fs';import path from'node:path';import{fileURLToPath}from'node:url';import{createHash}from'node:crypto';
import{rng}from'../frontend/autonomy.js';
import{MissionPoolEnvR2,MISSION_ACTIONS_R2,missionRequestR2}from'./navigation_mission_env_r2.mjs';
import{missionFeatures,missionAllowed,missionBaseline,missionPolicyController}from'./navigation_mission_learning.mjs';
const assistance=new Set(['FAULT_STOP','HOLD_UNAVAILABLE','RECOVERY_REQUIRED','ACTUATION_UNAVAILABLE','PROGRESS_UNCERTAIN']);
export function assistanceOwner(action,after,exploring){
 if(!assistance.has(after.mission?.mode))return null;
 const direct=action===7&&after.mission.mode==='RECOVERY_REQUIRED'&&after.mission.reason==='operator_recovery_assessment_required';
 return{owner:direct?'explicit_requested_assistance':'independent_guard',requested_during_exploration:exploring,reason:after.mission.reason,mode:after.mission.mode};
}
export function inspectMissionEpisode(env,decide){
 let previous=0,first=null,firstRecoveryRequest=null,nonzeroAfterAssistance=0,exploratoryDecisions=0;
 while(!env.done){
  const before=env.observe(),features=missionFeatures(before,previous),allowed=missionAllowed(before,features),decision=decide(before,previous,allowed),action=decision.action;
  if(!allowed.includes(action))throw Error('Diagnostic decision outside unchanged request mask');
  if(decision.exploring)exploratoryDecisions++;
  const request=missionRequestR2(env.steps,env.now(),MISSION_ACTIONS_R2[action]);
  if(action===7&&firstRecoveryRequest===null)firstRecoveryRequest={step:env.steps,at_ms:env.now(),exploring:decision.exploring,range_status:before.sensors?.range_evidence?.status};
  env.step(request);const after=env.observe(),owner=assistanceOwner(action,after,decision.exploring);
  if(first===null&&owner)first={...owner,step:env.steps,at_ms:env.now(),requested_action:MISSION_ACTIONS_R2[action],range_status:before.sensors?.range_evidence?.status,request,applied_feedback:after.actuator_feedback,position_at_assistance:{x:env.x,y:env.y},motion_at_assistance:after.motion};
  if(first&&(Math.abs(env.lastFeedback?.left??0)>0||Math.abs(env.lastFeedback?.right??0)>0))nonzeroAfterAssistance++;
  previous=action;
 }
 return{source:'simulation',seed:env.seed,profile:env.profile,fixture_used:env.fixtureUsed,delay_ms:env.delayTicks*100,exploratory_decisions:exploratoryDecisions,first_recovery_request:firstRecoveryRequest,first_assistance:first,tail:first?{steps_after_assistance:env.steps-first.step,displacement_m:Math.hypot(env.x-first.position_at_assistance.x,env.y-first.position_at_assistance.y),nonzero_applied_commands_after_assistance:nonzeroAfterAssistance,ended_with_collision:!!env.collisions,ended_at_timeout:env.truncated}:null,ended_at_step:env.steps,control_enabled:false,not_a_performance_benchmark:true};
}
export function runPostmortem(output){
 const project=path.dirname(path.dirname(fileURLToPath(import.meta.url))),read=f=>JSON.parse(fs.readFileSync(f,'utf8').replace(/^\uFEFF/,'')),sha=f=>createHash('sha256').update(fs.readFileSync(f)).digest('hex');
 if(fs.existsSync(output))throw Error('Diagnostic output exists; preserve this closed evidence');
 const planFile=path.join(project,'ai/mission-r2-postmortem-plan.json'),plan=read(planFile),run=path.join(project,plan.closed_run),status=read(path.join(run,'status.json')),protocol=read(path.join(run,'protocol.json'));
 if(status.phase!=='retained_baseline'||status.review_complete!==true||status.test_opened!==false||plan.training_episode_indices.length!==12||plan.contexts.length!==2)throw Error('Unexpected postmortem scope/closed-run status');
 for(const[file,hash]of Object.entries(protocol.source_sha256))if(sha(path.join(project,file))!==hash)throw Error('Closed experiment source changed: '+file);
 const selected=read(path.join(run,'candidate-6000.json')),policyFile=path.join(run,selected.policy_file);if(sha(policyFile)!==selected.policy_sha256)throw Error('Frozen policy hash mismatch');
 const config=read(path.join(project,'ai/navigation-mission-r2-experiment-protocol.json'));
 if(plan.training_episode_indices.some(i=>!Number.isInteger(i)||i<0||i>=config.training.episodes))throw Error('Diagnostic index outside already-used training range');
 fs.mkdirSync(output,{recursive:true});
 const frozen={...plan,frozen_before_diagnostic:true,plan_sha256:sha(planFile),script_sha256:sha(fileURLToPath(import.meta.url)),closed_protocol_sha256:sha(path.join(run,'protocol.json')),snapshot6000_sha256:sha(policyFile),frozen_source_sha256:protocol.source_sha256};
 fs.writeFileSync(path.join(output,'plan.json'),JSON.stringify(frozen,null,2),{flag:'wx'});
 const cases=[];
 for(const context of plan.contexts){
  const greedy=context.greedy==='fixed_rules'?missionBaseline('rules_with_hold'):missionPolicyController(read(policyFile));
  for(const i of plan.training_episode_indices){
   const seed=config.training.seed+i,profile=i%4===0?'nominal':'stress',env=new MissionPoolEnvR2(seed,{profile}),random=rng((config.training.seed^Math.imul(i+1,0x1a56b9))>>>0);
   const decide=(o,previous,allowed)=>{const exploring=random()<context.epsilon;return{exploring,action:exploring?allowed[Math.floor(random()*allowed.length)]:greedy(o,previous)};};
   cases.push({context:context.name,epsilon:context.epsilon,training_episode_index:i,...inspectMissionEpisode(env,decide)});
  }
 }
 const summary=Object.fromEntries(plan.contexts.map(c=>{const rows=cases.filter(r=>r.context===c.name),owners={};for(const row of rows){const key=row.first_assistance?.owner??'none_before_end';owners[key]=(owners[key]??0)+1;}return[c.name,{sampled_scenes:rows.length,first_assistance_owners:owners,explicit_request_during_exploration:rows.filter(r=>r.first_assistance?.owner==='explicit_requested_assistance'&&r.first_assistance.requested_during_exploration).length,independent_guard_reasons:rows.filter(r=>r.first_assistance?.owner==='independent_guard').map(r=>r.first_assistance.reason),nonzero_after_assistance:rows.reduce((n,r)=>n+(r.tail?.nonzero_applied_commands_after_assistance??0),0)}];}));
 const report={schema:'warirak.mission-r2-postmortem.v1',role:plan.role,closed_run:plan.closed_run,training_started:false,q_updates_performed:false,historical_training_reconstructed:false,validation_opened:false,test_opened:false,source:'simulation',summary,cases,limitations:[plan.interpretation,'Only12already-used training scenes per fixed context; not population failure attribution','No new policy was selected, trained or promoted; no success/collision-rate benchmark'],physical_motor_transport:false};
 fs.writeFileSync(path.join(output,'diagnostic.json'),JSON.stringify(report,null,2),{flag:'wx'});console.log(JSON.stringify({output,summary,training_started:false,test_opened:false}));return report;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))runPostmortem(path.resolve(process.argv[2]||'work/mission-r2-postmortem'));
