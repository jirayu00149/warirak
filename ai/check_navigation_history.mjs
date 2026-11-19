// Freeze and check a new software boundary. Never train or step a plant.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const out=path.join(root,'work/navigation-history-encoder');
const sha=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const read=file=>JSON.parse(fs.readFileSync(file,'utf8').replace(/^\uFEFF/,''));
const planPath=path.join(root,'ai/navigation-history-preflight-plan.json');
const plan=read(planPath);
const mode=process.argv[2];
assert(['--freeze','--test'].includes(mode)&&process.argv.length===3);
const upstream=read(path.join(root,'outputs/Warirak_Corridor_Selector_v2_Outcome_Audit.json'));
const newFiles=[
 'ai/navigation-history-layout.json','ai/navigation_history_encoder.mjs',
 'ai/navigation_inference_wire.mjs','ai/warirak_ai/navigation_wire.py',
 'tests/navigation-history.test.mjs','ai/navigation-history-preflight-plan.json',
 'ai/check_navigation_history.mjs','work/create_navigation_layout.py',
];
const hashes=Object.fromEntries([...new Set([...Object.keys(upstream.source_sha256),...newFiles])].map(f=>[f,sha(path.join(root,f))]));
for(const [file,hash]of Object.entries(upstream.source_sha256))assert.equal(hashes[file],hash,file);
const evidenceFiles=[
 'outputs/Warirak_Corridor_Selector_v2_Outcome_Audit.json',
 'outputs/Warirak_Proactive_Sidecar_v2_Repair_Audit.json',
 'ai/NAVIGATION_LEARNING_NEXT_DESIGN_TH.md',
 'work/corridor-selector-v2-dev/protocol.json',
 'work/corridor-selector-v2-dev/candidate-left_finite.json',
];
const evidence=Object.fromEntries(evidenceFiles.map(f=>[f,sha(path.join(root,f))]));
const save=(name,data)=>fs.writeFileSync(path.join(out,name+'.json'),JSON.stringify(data,null,2));
if(mode==='--freeze'){
 assert.equal(fs.existsSync(out),false,'Preserve existing component evidence');
 fs.mkdirSync(out,{recursive:true});
 save('protocol',{...plan,frozen_before_tests:true,frozen_at:new Date().toISOString(),plan_sha256:sha(planPath),source_sha256:hashes,input_evidence_sha256:evidence});
 save('status',{phase:'frozen_software_checks_pending',updated_at:new Date().toISOString(),training_started:false,performance_trial_started:false,validation_opened:false,test_partition_opened:false,physical_motor_transport:false});
 console.log(JSON.stringify({phase:'frozen_software_checks_pending',protocol_sha256:sha(path.join(out,'protocol.json'))}));
}else{
 const protocol=read(path.join(out,'protocol.json')),status=read(path.join(out,'status.json'));
 assert.equal(status.phase,'frozen_software_checks_pending');
 assert(!status.review_complete&&!status.delivery_complete);
 assert.deepEqual(protocol.source_sha256,hashes);
 assert.deepEqual(protocol.input_evidence_sha256,evidence);
 assert.equal(protocol.plan_sha256,sha(planPath));
 const result=spawnSync(process.execPath,['--test','--test-reporter=tap','tests/navigation-history.test.mjs'],{cwd:root,encoding:'utf8',timeout:45000,maxBuffer:1024*1024});
 fs.writeFileSync(path.join(out,'tests.log'),(result.stdout??'')+(result.stderr??''));
 const passed=Number(result.stdout?.match(/# pass (\d+)/)?.[1]);
 const failed=Number(result.stdout?.match(/# fail (\d+)/)?.[1]);
 const success=result.status===0&&failed===0&&passed>=plan.test_recipe.minimum_passed;
 save('checks',{protocol_sha256:sha(path.join(out,'protocol.json')),checked_at:new Date().toISOString(),node_version:process.version,exit_code:result.status,passed,failed,success,training_started:false,performance_trial_started:false,validation_opened:false,test_partition_opened:false,trained_model_loaded:false,physical_motor_transport:false});
 save('status',{...status,phase:success?'software_checks_passed_needs_review':'software_checks_failed',updated_at:new Date().toISOString(),review_pending:true});
 console.log(result.stdout);
 if(!success)throw Error('Software preflight failed: preserve source, protocol and log; no training or evaluation');
}
