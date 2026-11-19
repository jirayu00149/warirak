import fs from'node:fs';import path from'node:path';import{fileURLToPath}from'node:url';import{createHash}from'node:crypto';
import{createMissionTrainer,missionBaseline,missionPolicyController,evaluateMission,missionResearchGate,assertMissionPartitions,validateMissionPolicy}from'./navigation_mission_learning.mjs';
const project=path.dirname(path.dirname(fileURLToPath(import.meta.url))),args=process.argv.slice(2),resume=args.includes('--resume');
if(args.filter(x=>x.startsWith('--')).some(x=>x!=='--resume'))throw Error('Unknown runner option');
const root=path.resolve(args.find(x=>!x.startsWith('--'))||'work/navigation-mission-r2-experiment'),read=f=>JSON.parse(fs.readFileSync(f,'utf8').replace(/^\uFEFF/,'')),sha=f=>createHash('sha256').update(fs.readFileSync(f)).digest('hex');
fs.mkdirSync(root,{recursive:true});
const statusFile=path.join(root,'status.json'),lock=path.join(root,'run.lock'),exists=name=>fs.existsSync(path.join(root,name+'.json'));
const previous=fs.existsSync(statusFile)?read(statusFile):{};
if(previous.review_complete||previous.delivery_complete||['retained_baseline','candidate_ready_for_review'].includes(previous.phase))throw Error('Experiment already finished; review the evidence rather than restarting');
if(fs.existsSync(statusFile)&&!resume)throw Error('Existing run; inspect status and use --resume only for an interrupted run');
if(fs.existsSync(lock)){const old=read(lock);let alive=false;try{process.kill(old.pid,0);alive=true;}catch{}if(alive)throw Error('Run lock PID is still alive; do not start another process');if(!resume)throw Error('Stale lock requires explicit resume');fs.unlinkSync(lock);}
fs.writeFileSync(lock,JSON.stringify({pid:process.pid,started_at:new Date().toISOString()}),{flag:'wx'});
const save=(name,data)=>{const file=path.join(root,name+'.json'),tmp=file+'.tmp';fs.writeFileSync(tmp,JSON.stringify(data,null,2));fs.renameSync(tmp,file);};
const started=previous.started_at||new Date().toISOString();let phase='preparing',lastCompleted=previous.completed_episodes||0;
const state=(next,fields={})=>{phase=next;save('status',{schema:'warirak.mission-training-status.v1',phase:next,pid:process.pid,started_at:started,updated_at:new Date().toISOString(),environment:'warirak-pool-mission-v4r2-dev',source:'simulation',compute:'local CPU',completed_episodes:lastCompleted,total_episodes:6000,experimental:true,production_policy_unchanged:true,test_opened:false,physical_motor_transport:false,control_enabled:false,...fields});console.log(JSON.stringify({phase:next,completed_episodes:lastCompleted,...fields}));};
try{
 const configFile=path.join(project,'ai/navigation-mission-r2-experiment-protocol.json'),baselineFile=path.join(project,'frontend/assets/navigation-policy.json'),config=read(configFile),legacy=read(baselineFile);
 const partitions=assertMissionPartitions(config);
 if(config.environment!=='warirak-pool-mission-v4r2-dev'||config.selection_split!=='validation'||config.test_used_for_selection!==false||config.test_requires_explicit_engineering_review!==true||config.training.episodes!==6000||JSON.stringify(config.candidates)!=='[2000,6000]')throw Error('Unsupported frozen experiment definition');
 const sourceFiles=['ai/navigation_mission_env_r2.mjs','ai/mission_range_evidence.mjs','ai/navigation_mission_learning.mjs','ai/train_navigation_mission.mjs','ai/navigation_memory_env.mjs','frontend/autonomy.js','ai/navigation-mission-v4r2-contract.json'];
 const protocol={...config,frozen_before_training:true,config_sha256:sha(configFile),baseline_sha256:sha(baselineFile),source_sha256:Object.fromEntries(sourceFiles.map(f=>[f,sha(path.join(project,f))])),partitions};
 if(exists('protocol')){if(JSON.stringify(read(path.join(root,'protocol.json')))!==JSON.stringify(protocol))throw Error('Frozen source/protocol/baseline changed; cannot resume this run');}else save('protocol',protocol);
 const protocolHash=sha(path.join(root,'protocol.json')),excluded=[...partitions.filter(p=>p.name==='train').map(p=>p.range),legacy.training.train_seeds];
 const measure=controller=>Object.fromEntries(['nominal','stress'].map(profile=>{state('validation',{controller_role:'validation_only',profile});return[profile,evaluateMission(controller,{profile,seed:config.validation[profile+'_seed'],episodes:config.validation.episodes_per_profile,excludedRanges:excluded})];}));
 let baselines;
 if(exists('baseline-validation')){const saved=read(path.join(root,'baseline-validation.json'));if(saved.protocol_sha256!==protocolHash)throw Error('Baseline protocol reference mismatch');baselines=saved.metrics;}
 else{state('baseline_validation');baselines=Object.fromEntries(config.baselines.map(kind=>[kind,measure(missionBaseline(kind,legacy))]));save('baseline-validation',{protocol_sha256:protocolHash,metrics:baselines,test_used_for_selection:false});}
 let checkpoint=exists('checkpoint')?read(path.join(root,'checkpoint.json')):null;
 if(checkpoint&&checkpoint.protocol_sha256!==protocolHash)throw Error('Checkpoint protocol reference mismatch');
 if(!checkpoint&&resume&&config.candidates.some(n=>exists('policy-'+n)))throw Error('Candidate artifacts exist without a recoverable checkpoint; do not retrain from zero');
 const trainer=createMissionTrainer({...config.training,checkpoint});lastCompleted=trainer.completed;
 const trials=[];
 for(const target of config.candidates){
  const name='candidate-'+target,policyName='policy-'+target;
  while(trainer.completed<target){
   state('training',{candidate_snapshot:target});trainer.batch(Math.min(config.checkpoint_every_episodes,target-trainer.completed));lastCompleted=trainer.completed;
   save('checkpoint',{...trainer.checkpoint(),protocol_sha256:protocolHash});state('training',{candidate_snapshot:target});
  }
  let policy;if(exists(policyName))policy=validateMissionPolicy(read(path.join(root,policyName+'.json')));else{if(trainer.completed!==target)throw Error('Earlier candidate snapshot is missing; a later table cannot be substituted');policy=trainer.policy();save(policyName,policy);}
  if(policy.training.episodes!==target||policy.training.budget_episodes!==config.training.episodes)throw Error('Candidate snapshot/budget mismatch');
  let trial;
  if(exists(name)){trial=read(path.join(root,name+'.json'));if(trial.protocol_sha256!==protocolHash||trial.policy_sha256!==sha(path.join(root,policyName+'.json')))throw Error('Candidate evidence/protocol mismatch');}
  else{state('candidate_validation',{snapshot:target});const metrics=measure(missionPolicyController(policy)),gate=missionResearchGate(baselines,metrics,config.gates);trial={protocol_sha256:protocolHash,episodes:target,policy_file:policyName+'.json',policy_sha256:sha(path.join(root,policyName+'.json')),metrics,gate,test_used_for_selection:false};save(name,trial);}
  trials.push(trial);
 }
 const score=t=>t.metrics.stress.success_rate-2*t.metrics.stress.collision_rate-.25*t.metrics.stress.hard_unavailable_rate;
 const eligible=trials.filter(t=>t.gate.eligible).sort((a,b)=>score(b)-score(a)||b.metrics.nominal.success_rate-a.metrics.nominal.success_rate||a.metrics.nominal.mean_steps-b.metrics.nominal.mean_steps),best=eligible[0];
 save('selection',{schema:'warirak.mission-selection.v1',protocol_sha256:protocolHash,baselines,trials,selected_episodes:best?.episodes??null,selection_split:'validation',test_used_for_selection:false,test_opened:false,production_policy_unchanged:true});
 if(!best)state('retained_baseline',{reason:'No candidate passed all frozen absolute and comparative validation gates',review_pending:true,training_finished:true});
 else{save('selected-policy-reference',{policy_file:best.policy_file,policy_sha256:best.policy_sha256,selected_episodes:best.episodes,protocol_sha256:protocolHash});state('candidate_ready_for_review',{selected_episodes:best.episodes,training_finished:true,review_pending:true,test_requires_explicit_engineering_review:true,production_runtime_supported:false});}
}catch(error){const failed=phase;state('needs_repair',{failed_phase:failed,error:error.message});throw error;}
finally{if(fs.existsSync(lock)&&read(lock).pid===process.pid)fs.unlinkSync(lock);}
