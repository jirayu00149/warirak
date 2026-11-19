// New bounded simulation/unit storage checks only; never launch project training.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))),out=path.join(root,'work/navigation-episode-preflight');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,'')),sha=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const planFile=path.join(root,'ai/navigation-episode-preflight-plan.json'),plan=read(planFile),upstream=read(path.join(root,'outputs/Warirak_Navigation_DQN_Foundation_Audit.json'));
const mode=process.argv[2];assert(['--freeze','--test'].includes(mode)&&process.argv.length===3);
const added=['ai/navigation_episode_bridge.mjs','ai/warirak_ai/navigation_commit.py','tests/navigation-episode-bridge.test.mjs','tests/test_navigation_commit.py','ai/navigation-episode-preflight-plan.json','ai/check_navigation_episode.mjs'];
const hashes=Object.fromEntries([...new Set([...Object.keys(upstream.source_sha256),...added])].map(f=>[f,sha(path.join(root,f))]));
for(const[f,h]of Object.entries(upstream.source_sha256))assert.equal(hashes[f],h,f);
const evidence=Object.fromEntries(['outputs/Warirak_Navigation_DQN_Foundation_Audit.json','ai/NAVIGATION_DQN_FOUNDATION_TH.md','work/navigation-dqn-preflight/protocol.json','work/navigation-dqn-preflight/checks.json'].map(f=>[f,sha(path.join(root,f))]));
const save=(name,data)=>fs.writeFileSync(path.join(out,name+'.json'),JSON.stringify(data,null,2));
if(mode==='--freeze'){
 assert.equal(fs.existsSync(out),false,'Preserve frozen evidence');fs.mkdirSync(out,{recursive:true});
 save('protocol',{...plan,frozen_at:new Date().toISOString(),frozen_before_tests_and_plant_steps:true,plan_sha256:sha(planFile),source_sha256:hashes,input_evidence_sha256:evidence});
 save('status',{phase:'frozen_software_checks_pending',updated_at:new Date().toISOString(),actual_training_started:false,plant_performance_trial_started:false,validation_opened:false,test_opened:false,physical_motor_transport:false});
 console.log(JSON.stringify({phase:'frozen_software_checks_pending',protocol_sha256:sha(path.join(out,'protocol.json'))}));
}else{
 const protocol=read(path.join(out,'protocol.json')),status=read(path.join(out,'status.json'));
 assert.equal(status.phase,'frozen_software_checks_pending');assert(!status.review_complete&&!status.delivery_complete);
 assert.deepEqual(protocol.source_sha256,hashes);assert.deepEqual(protocol.input_evidence_sha256,evidence);assert.equal(protocol.plan_sha256,sha(planFile));
 save('status',{...status,phase:'running_software_checks',pid:process.pid,updated_at:new Date().toISOString()});
 const n=spawnSync(process.execPath,['--test','--test-reporter=tap','tests/navigation-episode-bridge.test.mjs'],{cwd:root,encoding:'utf8',timeout:60000,maxBuffer:1024*1024});
 const nodeLog=(n.stdout??'')+(n.stderr??'');fs.writeFileSync(path.join(out,'node-tests.log'),nodeLog);
 const nodePassed=Number(nodeLog.match(/# pass (\d+)/)?.[1]),nodeFailed=Number(nodeLog.match(/# fail (\d+)/)?.[1]),nodeSuccess=n.status===0&&nodePassed>=11&&nodeFailed===0;
 let p=null;if(nodeSuccess){const python=process.env.WARIRAK_TRAINING_PYTHON??'C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350/work/warirak_training_runtime/Scripts/python.exe';
  p=spawnSync(python,['-X','utf8','-m','unittest','discover','-s','tests','-p','test_navigation_commit.py','-v'],{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'ai')},encoding:'utf8',timeout:180000,maxBuffer:1024*1024});}
 const pyLog=(p?.stdout??'')+(p?.stderr??'');fs.writeFileSync(path.join(out,'python-tests.log'),pyLog);
 const pyPassed=Number(pyLog.match(/Ran (\d+) tests? in/)?.[1]),success=nodeSuccess&&p?.status===0&&pyPassed>=9&&/\nOK\s*$/.test(pyLog);
 save('checks',{protocol_sha256:sha(path.join(out,'protocol.json')),checked_at:new Date().toISOString(),node_version:process.version,node_exit_code:n.status,node_passed:nodePassed,node_failed:nodeFailed,python_exit_code:p?.status??null,python_passed:pyPassed,success,bridge_examples_sha256:fs.existsSync(path.join(out,'bridge-transitions.json'))?sha(path.join(out,'bridge-transitions.json')):null,synthetic_optimizer_unit_updates_only:true,actual_training_started:false,plant_performance_trial_started:false,validation_opened:false,test_opened:false,physical_motor_transport:false});
 save('status',{...status,phase:success?'software_checks_passed_needs_review':'software_checks_failed',updated_at:new Date().toISOString(),review_pending:true});
 console.log(nodeLog+pyLog);if(!success)throw Error('Preflight failed: preserve protocol/source/log; no actual training or held-out evaluation');
}
