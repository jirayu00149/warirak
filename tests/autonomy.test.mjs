import test from'node:test';import assert from'node:assert/strict';import fs from'node:fs';import{PoolEnv,createTrainer,evaluatePolicy,validatePolicy,greedy,ACTIONS}from'../frontend/autonomy.js';
test('simulation is deterministic, observations hide coordinates and terminal transitions stop',()=>{
 const a=new PoolEnv(10),b=new PoolEnv(10);assert.deepEqual(a.snapshot(),b.snapshot());assert.equal('target'in a.observation,false);while(!a.done){a.step(0);b.step(0);}assert.deepEqual(a.snapshot(),b.snapshot());const steps=a.steps;assert.equal(a.step(0).reward,0);assert.equal(a.steps,steps);
});
test('a target at the side is not collected; conveyor mouth and forward motion are required',()=>{
 const e=new PoolEnv(1);e.obstacles=[];e.x=5;e.y=3;e.heading=0;e.drift={x:0,y:0};e.leftGain=e.rightGain=1;e.target={x:5,y:3.4,class_id:0};e.step(0);assert.equal(e.collected,0);e.x=5;e.y=3;e.heading=0;e.target={x:5.4,y:3,class_id:0};e.step(0);assert.equal(e.collected,1);assert.equal(e.terminated,true);
});
test('Q learning updates a blank table and held-out evaluation refuses leakage',()=>{
 const train=createTrainer({episodes:100,seed:7});train.batch(100);const p=train.finish();assert.ok(p.q_values.some(v=>v!==0));validatePolicy(p);assert.throws(()=>evaluatePolicy(p,{episodes:5,seed:7}),/overlap/);const report=evaluatePolicy(p,{episodes:5,seed:900000});assert.equal(report.results.length,3);assert.equal(report.results[0].episodes,5);
});
test('bundled policy report reproduces on the exact held-out seeds',()=>{
 const p=validatePolicy(JSON.parse(fs.readFileSync(new URL('../frontend/assets/navigation-policy.json',import.meta.url))));const measured=evaluatePolicy(p,{episodes:p.evaluation.episodes,seed:p.evaluation.seed});assert.deepEqual(measured,p.evaluation);assert.ok(measured.results[0].success_rate>=.95);assert.ok(measured.results[0].collision_rate<=.02);assert.ok(p.selection.validation_seed!==p.evaluation.seed);assert.equal(p.control_enabled,false);assert.equal(p.real_world_validated,false);assert.ok(ACTIONS.every(a=>Math.abs(a.left)<=1&&Math.abs(a.right)<=1));const env=new PoolEnv(1000200);while(!env.done)env.step(greedy(p.q_values,env.observation.state));assert.equal(env.collected,1);
});
