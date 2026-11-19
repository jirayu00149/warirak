import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {evaluateSnapshotPartition,evaluationMetrics,rankValidationMetrics,frozenResearchGates,selectValidationSnapshots,REFERENCE_ROLES} from '../ai/navigation_snapshot_evaluation.mjs';
import {runNavigationResearch} from '../ai/navigation_research_pipeline.mjs';
import {MissionPoolEnvR2} from '../ai/navigation_mission_env_r2.mjs';
import {NavigationEpisodeBridge} from '../ai/navigation_episode_bridge.mjs';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))),work=fs.realpathSync(path.join(root,'work'));
const protocolPath=path.join(work,'navigation-evaluation-preflight/protocol.json');
const python='C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350/work/warirak_training_runtime/Scripts/python.exe';
const scratch=()=>fs.mkdtempSync(path.join(work,'navigation-evaluator-unit-'));
const sha=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
function cleanup(dir){const p=fs.realpathSync(dir);assert.equal(path.dirname(p),work);assert(path.basename(p).startsWith('navigation-evaluator-unit-'));fs.rmSync(p,{recursive:true,force:false});}
function snapshot(dir,optimizer=false){const folder=path.join(dir,'source-run/snapshots/episode-000001'),r=spawnSync(python,['-X','utf8',path.join(work,'create_evaluation_unit_snapshot.py'),'--protocol',protocolPath,'--folder',folder,...(optimizer?['--with-optimizer']:[])],{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'ai')},encoding:'utf8',timeout:30000,maxBuffer:1048576});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);}
function writeReceipt(p,v){fs.mkdirSync(path.dirname(p),{recursive:true});const hash=createHash('sha256').update(JSON.stringify(v)).digest('hex');fs.writeFileSync(p,JSON.stringify({...v,payload_sha256:hash}));}
test('All references/candidate share new software scenes; read-only receipts and closed-cache reuse',async()=>{
 const dir=scratch();try{const info=snapshot(dir,true),outputRoot=path.join(dir,'evaluation'),before=fs.statSync(path.join(info.snapshot_path,'checkpoint.pt')).mtimeMs;
  const options={protocolPath,snapshotPath:info.snapshot_path,expectedSnapshotSha256:info.snapshot_sha256,partition:'software',outputRoot};
  const r=await evaluateSnapshotPartition(options);assert.deepEqual(Object.keys(r.baselines),[...REFERENCE_ROLES]);assert.equal(r.software_preflight,true);assert.equal(r.not_a_performance_benchmark,true);
  assert.equal(r.read_only.before_state_sha256,info.initial_state_sha256);assert.equal(r.read_only.after_state_sha256,info.initial_state_sha256);assert.equal(r.read_only.choices,0);assert.equal(r.read_only.updates,1);
  for(const role of [...REFERENCE_ROLES,'candidate'])for(const profile of ['nominal','stress']){const m=role==='candidate'?r.candidate[profile]:r.baselines[role][profile];assert.equal(m.episodes,1);assert.equal(m.collections+m.collisions+m.timeouts,1);assert.equal(m.continues_physics_after_assistance,true);}
  const reportPath=path.join(outputRoot,'candidates',info.snapshot_sha256,'report.json'),mtime=fs.statSync(reportPath).mtimeMs;
  const cached=await evaluateSnapshotPartition(options);assert.equal(cached.from_cache,true);assert.deepEqual(cached.candidate,r.candidate);assert.equal(fs.statSync(reportPath).mtimeMs,mtime);assert.equal(fs.statSync(path.join(info.snapshot_path,'checkpoint.pt')).mtimeMs,before);
 }finally{cleanup(dir);}
});
test('A full960step timeout is counted with original nominal current, no thrust and no shortened horizon',()=>{
 const seed=11602,profile='nominal',probe=new MissionPoolEnvR2(seed,{profile}),d=probe.drift;
 const env=new MissionPoolEnvR2(seed,{profile,record:true,fixture:{x:5-48*d.x,y:3-48*d.y,heading:0,target:{x:9,y:3,class_id:0},obstacles:[]}});
 const bridge=new NavigationEpisodeBridge(env,{episodeId:'timeout-unit-11602',sessionId:'timeout-unit-11602'});
 while(!env.done)bridge.advance(0);
 const r=bridge.summary(),m=evaluationMetrics([r],profile,seed,1);assert.equal(r.steps,960);assert.equal(r.timeouts,1);assert.equal(r.collisions,0);assert.equal(r.nonzero_applied_steps,0);assert.equal(m.mean_steps,960);assert.equal(m.timeout_rate,1);assert.equal(m.all_fault_cases_in_denominator,true);assert.deepEqual(env.drift,probe.drift);assert(Math.abs(d.x)+Math.abs(d.y)>0);assert(Math.hypot(env.observe().motion.vx_mps,env.observe().motion.vy_mps)>0);
});
test('Synthetic metric ranking uses all reference gates and cannot weaken prior thresholds',()=>{
 const nominal={success_rate:.7,collision_rate:.1,timeout_rate:.2,assistance_rate:.1,hard_unavailable_rate:.02,range_wait_observation_fraction:.05,mean_steps:100},stress={success_rate:.5,collision_rate:.3,timeout_rate:.2,assistance_rate:.4,hard_unavailable_rate:.2,range_wait_observation_fraction:.1,mean_steps:120};
 const refs=Object.fromEntries(REFERENCE_ROLES.map(role=>[role,{nominal:{...nominal,success_rate:.65,collision_rate:.12,timeout_rate:.23},stress:{...stress,success_rate:.4,collision_rate:.35,timeout_rate:.25}}]));
 const r=rankValidationMetrics([{episode:2000,metrics:{nominal,stress}},{episode:500,metrics:{nominal,stress}},{episode:1000,metrics:{nominal,stress:{...stress,success_rate:.41,timeout_rate:.29}}}],refs,frozenResearchGates());
 assert.equal(r.selected.episode,500);assert.equal(r.ranking.find(x=>x.episode===1000).gate.eligible,false);assert.equal(r.test_used_for_selection,false);assert.equal(r.production_ready,false);
 const weaker=frozenResearchGates();weaker.research.nominal.max_collision=.9;assert.throws(()=>rankValidationMetrics([],refs,weaker));
});
test('Model selection refuses test/software reports before any protected scenario access',()=>{
 const dir=scratch();try{for(const partition of ['test','software']){const file=path.join(dir,partition+'.json');writeReceipt(file,{partition});assert.throws(()=>selectValidationSnapshots({protocolPath,reportPaths:[file],outputPath:path.join(dir,'selection.json')}),/Validation only/);}}finally{cleanup(dir);}
});
test('Changed closed receipt is rejected instead of silently rerunning cases',async()=>{
 const dir=scratch();try{const info=snapshot(dir),outputRoot=path.join(dir,'evaluation');const file=path.join(outputRoot,'candidates',info.snapshot_sha256,'report.json');fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,JSON.stringify({complete:true,payload_sha256:'wrong'}));await assert.rejects(evaluateSnapshotPartition({protocolPath,snapshotPath:info.snapshot_path,expectedSnapshotSha256:info.snapshot_sha256,partition:'software',outputRoot}),/checksum/);assert.equal(fs.existsSync(path.join(outputRoot,'evaluation.lock')),false);}finally{cleanup(dir);}
});
test('Research train→validation pipeline cannot execute a software-preflight protocol',async()=>{
 const dir=scratch();try{await assert.rejects(runNavigationResearch({protocolPath,runRoot:path.join(dir,'not-a-real-training-job'),operation:'initialize'}),/research training protocol/);assert.equal(fs.existsSync(path.join(dir,'not-a-real-training-job')),false);}finally{cleanup(dir);}
});
