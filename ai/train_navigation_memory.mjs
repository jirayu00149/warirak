import fs from'node:fs';import path from'node:path';import{createHash}from'node:crypto';import{fileURLToPath}from'node:url';import{trainMemory,evaluateMemory,memoryGate}from'./navigation_memory_train.mjs';
const project=path.dirname(path.dirname(fileURLToPath(import.meta.url))),root=path.resolve(process.argv[2]||'work/navigation-memory-v3'),resume=process.argv.includes('--resume'),read=p=>JSON.parse(fs.readFileSync(p)),sha=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
fs.mkdirSync(root,{recursive:true});const statusFile=path.join(root,'status.json'),lock=path.join(root,'run.lock');if(fs.existsSync(statusFile)&&!resume)throw Error('Run already exists; inspect its status/checkpoint');
if(fs.existsSync(lock)){const old=read(lock);let alive=false;try{process.kill(old.pid,0);alive=true;}catch{}if(alive)throw Error('This run still has a live lock PID');if(!resume)throw Error('Stale lock; inspect and resume');fs.unlinkSync(lock);}fs.writeFileSync(lock,JSON.stringify({pid:process.pid,started_at:new Date().toISOString()}),{flag:'wx'});
const write=(name,data)=>{const f=path.join(root,name+'.json'),tmp=f+'.tmp';fs.writeFileSync(tmp,JSON.stringify(data,null,2));fs.renameSync(tmp,f);};
const previous=fs.existsSync(statusFile)?read(statusFile):{},started=previous.started_at||new Date().toISOString();let phase=previous.failed_phase||previous.phase||'preparing';
const state=(next,fields={})=>{phase=next;write('status',{phase,pid:process.pid,started_at:started,updated_at:new Date().toISOString(),environment:'warirak-pool-memory-v3',source:'simulation',experimental:true,production_runtime_supported:false,control_enabled:false,...fields});if(next!=='training'||fields.completed_episodes%2000===0)console.log(JSON.stringify({phase:next,...fields}));};
try{
 const baselineFile=path.join(project,'frontend/assets/navigation-policy.json'),baseline=read(baselineFile),config=read(path.join(project,'ai/navigation-memory-v3-protocol.json'));
 const protocol={...config,frozen_before_training:true,baseline_sha256:sha(baselineFile),source_sha256:Object.fromEntries(['ai/navigation_memory_env.mjs','ai/navigation_memory_train.mjs','ai/train_navigation_memory.mjs'].map(f=>[f,sha(path.join(project,f))]))};
 const frozen=path.join(root,'protocol.json');if(fs.existsSync(frozen)){if(JSON.stringify(read(frozen))!==JSON.stringify(protocol))throw Error('Frozen source/protocol changed; do not resume this run');}else write('protocol',protocol);
 const measure=(policy,controller='memory')=>Object.fromEntries(['nominal','stress'].map(profile=>[profile,evaluateMemory(policy,{profile,controller,seed:config.validation[profile+'_seed'],episodes:config.validation.episodes_per_profile})]));
 let base;if(fs.existsSync(path.join(root,'baseline-validation.json')))base=read(path.join(root,'baseline-validation.json'));else{state('baseline_validation');base=measure(baseline,'legacy');write('baseline-validation',base);}
 const trials=[];
 for(const episodes of config.candidates){
  const name='candidate-'+episodes,file=path.join(root,name+'.json');let candidate;
  if(fs.existsSync(file))candidate=read(file);else{
   const checkpointFile=path.join(root,'checkpoint-'+episodes+'.json'),checkpoint=resume&&fs.existsSync(checkpointFile)?read(checkpointFile):null;state('training',{episodes,completed_episodes:checkpoint?.completed||0});
   const policy=trainMemory({episodes,seed:config.training_seed,baseline,checkpoint,onProgress:completed_episodes=>state('training',{episodes,completed_episodes}),onCheckpoint:c=>write('checkpoint-'+episodes,c)});state('validation_selection',{episodes});const metrics=measure(policy),eligible=memoryGate(base,metrics,config);candidate={episodes,policy,metrics,eligible};write(name,candidate);
  }trials.push(candidate);
 }
 const eligible=trials.filter(t=>t.eligible).sort((a,b)=>(b.metrics.stress.success_rate-2*b.metrics.stress.collision_rate)-(a.metrics.stress.success_rate-2*a.metrics.stress.collision_rate)||a.metrics.nominal.mean_steps-b.metrics.nominal.mean_steps),best=eligible[0];
 write('selection',{protocol,baseline:base,trials:trials.map(({policy,...rest})=>rest),selected_episodes:best?.episodes||null,test_used_for_selection:false});
 if(!best)state('retained_baseline',{reason:'No temporal candidate passed the frozen paired validation gates',test_opened:false,production_policy_unchanged:true});
 else{
  state('held_out_simulation_test');let evaluation;
  if(fs.existsSync(path.join(root,'evaluation.json')))evaluation=read(path.join(root,'evaluation.json'));else{
   const testMeasure=(policy,controller)=>Object.fromEntries(['nominal','stress'].map(profile=>[profile,evaluateMemory(policy,{profile,controller,seed:config.test[profile+'_seed'],episodes:config.test.episodes_per_profile})]));
   evaluation={source:'simulation',environment:config.environment,baseline:testMeasure(baseline,'legacy'),candidate:testMeasure(best.policy,'memory'),rules:testMeasure(baseline,'rule'),selected_episodes:best.episodes,test_used_for_selection:false,real_world_validated:false};write('evaluation',evaluation);
  }write('navigation-memory-policy',best.policy);state('candidate_ready_for_review',{selected_episodes:best.episodes,production_policy_unchanged:true,requires_new_runtime_adapter:true});
 }
}catch(error){const failed=phase;state('needs_repair',{failed_phase:failed,error:error.message});throw error;}finally{fs.unlinkSync(lock);}
