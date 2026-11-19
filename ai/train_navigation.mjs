import fs from'node:fs';import path from'node:path';import{createHash}from'node:crypto';
import{createTrainer,evaluatePolicy,validatePolicy}from'../frontend/autonomy.js';
const out=path.resolve(process.argv[2]||'runs/navigation-public-v1');fs.mkdirSync(out,{recursive:true});const trials=[];
for(const episodes of[8000,16000,20000]){
 const trainer=createTrainer({episodes,seed:42});while(trainer.completed<episodes)trainer.batch(100);
 const policy=trainer.finish(),validation=evaluatePolicy(policy,{episodes:1000,seed:2000000}),score=validation.results[0].success_rate-2*validation.results[0].collision_rate;
 fs.writeFileSync(path.join(out,`candidate-${episodes}.json`),JSON.stringify({...policy,validation},null,2));trials.push({episodes,policy,validation,score});console.log(JSON.stringify({phase:'navigation-validation',episodes,results:validation.results}));
}
trials.sort((a,b)=>b.score-a.score||a.validation.results[0].mean_steps-b.validation.results[0].mean_steps);
const best=trials[0],policy=best.policy;policy.validation=best.validation;policy.selection={method:'validation-only',candidate_episodes:trials.map(t=>t.episodes),validation_seed:2000000,validation_episodes:1000,test_seed:3000000,test_episodes:1000};policy.evaluation=evaluatePolicy(policy,{episodes:1000,seed:3000000});validatePolicy(policy);
const content=JSON.stringify(policy,null,2);fs.writeFileSync(path.join(out,'navigation-policy.json'),content);fs.writeFileSync(path.join(out,'selection-report.json'),JSON.stringify({selected_episodes:best.episodes,trials:trials.map(t=>({episodes:t.episodes,validation:t.validation,score:t.score})),test:policy.evaluation,sha256:createHash('sha256').update(content).digest('hex'),control_enabled:false,real_world_validated:false},null,2));console.log(JSON.stringify({phase:'navigation-final-test',selected_episodes:best.episodes,test:policy.evaluation}));
