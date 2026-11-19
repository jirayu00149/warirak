// New software-only preflight. No environment/episode runner is imported or launched.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const out=path.join(root,'work/navigation-dqn-preflight');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const sha=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const planFile=path.join(root,'ai/navigation-dqn-preflight-plan.json'),plan=read(planFile);
const upstream=read(path.join(root,'outputs/Warirak_Navigation_History_Encoder_Audit.json'));
const mode=process.argv[2];assert(['--freeze','--test'].includes(mode)&&process.argv.length===3);
const added=['ai/navigation-dqn-recipe.json','ai/warirak_ai/__init__.py','ai/warirak_ai/navigation_dqn.py','ai/warirak_ai/navigation_dqn_stream.py','tests/test_navigation_dqn.py','tests/navigation-dqn-stream.test.mjs','tests/fixtures/navigation-dqn-vectors.json','ai/navigation-dqn-preflight-plan.json','ai/check_navigation_dqn.mjs','work/create_navigation_dqn_fixtures.mjs'];
const hashes=Object.fromEntries([...new Set([...Object.keys(upstream.source_sha256),...added])].map(f=>[f,sha(path.join(root,f))]));
for(const [f,h]of Object.entries(upstream.source_sha256))assert.equal(hashes[f],h,f);
const evidence=Object.fromEntries(['outputs/Warirak_Navigation_History_Encoder_Audit.json','ai/NAVIGATION_HISTORY_ENCODER_TH.md','work/navigation-history-encoder/protocol.json','work/navigation-history-encoder/checks.json'].map(f=>[f,sha(path.join(root,f))]));
const save=(name,data)=>fs.writeFileSync(path.join(out,name+'.json'),JSON.stringify(data,null,2));
if(mode==='--freeze'){
 assert.equal(fs.existsSync(out),false,'Preserve preflight evidence');fs.mkdirSync(out,{recursive:true});
 save('protocol',{...plan,frozen_at:new Date().toISOString(),frozen_before_tests:true,plan_sha256:sha(planFile),recipe_sha256:sha(path.join(root,plan.recipe)),source_sha256:hashes,input_evidence_sha256:evidence});
 save('status',{phase:'frozen_software_checks_pending',updated_at:new Date().toISOString(),actual_training_started:false,plant_rollout_started:false,validation_opened:false,test_opened:false,physical_motor_transport:false});
 console.log(JSON.stringify({phase:'frozen_software_checks_pending',protocol_sha256:sha(path.join(out,'protocol.json'))}));
}else{
 const protocol=read(path.join(out,'protocol.json')),status=read(path.join(out,'status.json'));
 assert.equal(status.phase,'frozen_software_checks_pending');assert(!status.review_complete&&!status.delivery_complete);
 assert.deepEqual(protocol.source_sha256,hashes);assert.deepEqual(protocol.input_evidence_sha256,evidence);assert.equal(protocol.plan_sha256,sha(planFile));
 save('status',{...status,phase:'running_software_checks',pid:process.pid,updated_at:new Date().toISOString()});
 const python=process.env.WARIRAK_TRAINING_PYTHON??'C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350/work/warirak_training_runtime/Scripts/python.exe';
 const p=spawnSync(python,['-X','utf8','-m','unittest','discover','-s','tests','-p','test_navigation_dqn.py','-v'],{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'ai')},encoding:'utf8',timeout:180000,maxBuffer:1024*1024});
 const pyLog=(p.stdout??'')+(p.stderr??'');fs.writeFileSync(path.join(out,'python-tests.log'),pyLog);
 const passedPython=Number(pyLog.match(/Ran (\d+) tests? in/)?.[1]),pythonSuccess=p.status===0&&/\nOK\s*$/.test(pyLog)&&passedPython>=18;
 let n=null;if(pythonSuccess)n=spawnSync(process.execPath,['--test','--test-reporter=tap','tests/navigation-dqn-stream.test.mjs'],{cwd:root,encoding:'utf8',timeout:150000,maxBuffer:1024*1024});
 const nodeLog=(n?.stdout??'')+(n?.stderr??'');fs.writeFileSync(path.join(out,'node-tests.log'),nodeLog);
 const passedNode=Number(nodeLog.match(/# pass (\d+)/)?.[1]),failedNode=Number(nodeLog.match(/# fail (\d+)/)?.[1]);
 const success=pythonSuccess&&n?.status===0&&passedNode>=4&&failedNode===0;
 save('checks',{protocol_sha256:sha(path.join(out,'protocol.json')),checked_at:new Date().toISOString(),node_version:process.version,python_exit_code:p.status,python_passed:passedPython,python_success:pythonSuccess,node_exit_code:n?.status??null,node_passed:passedNode,node_failed:failedNode,success,synthetic_unit_optimizer_updates_only:true,actual_training_started:false,plant_rollout_started:false,validation_opened:false,test_opened:false,physical_motor_transport:false});
 save('status',{...status,phase:success?'software_checks_passed_needs_review':'software_checks_failed',updated_at:new Date().toISOString(),review_pending:true});
 console.log(pyLog+nodeLog);if(!success)throw Error('Preflight failed: preserve frozen source/log/protocol; no training or evaluation');
}
