// Freeze and run SOFTWARE REGRESSION TESTS only. No policy evaluation or training.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))),out=path.join(root,'work/proactive-sidecar-v2-repair');
const sha=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex'),read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const mode=process.argv[2];assert(['--freeze','--test'].includes(mode)&&process.argv.length===3);
const planFile=path.join(root,'ai/proactive-sidecar-v2-repair-plan.json'),plan=read(planFile),v1=read(path.join(root,'work/proactive-selector-v1-dev-r1/protocol.json'));
const files=[...new Set([...Object.keys(v1.source_sha256),'ai/proactive_sidecar_v2.mjs','ai/proactive_sidecar_r2_v2.mjs','tests/proactive-sidecar-v2.test.mjs','ai/proactive-sidecar-v2-repair-plan.json','ai/check_proactive_sidecar_v2.mjs','work/create_sidecar_v2.py'])];
const hashes=Object.fromEntries(files.map(f=>[f,sha(path.join(root,f))]));for(const [f,h]of Object.entries(v1.source_sha256))assert.equal(hashes[f],h,f);
const evidenceFiles=['outputs/Warirak_Proactive_Selector_v1_Artifact_Review.json','outputs/Warirak_Proactive_Selector_v1_Outcome_Audit.json','work/proactive-selector-v1-dev-r1/candidate-range_gap.json','work/proactive-selector-v1-dev-r1/reference-range_gap.json'];
const evidence=Object.fromEntries(evidenceFiles.map(f=>[f,sha(path.join(root,f))]));
const save=(name,data)=>fs.writeFileSync(path.join(out,name+'.json'),JSON.stringify(data,null,2));
if(mode==='--freeze'){
 assert.equal(fs.existsSync(out),false,'Preserve existing repair evidence');fs.mkdirSync(out,{recursive:true});
 save('protocol',{...plan,frozen_before_tests:true,frozen_at:new Date().toISOString(),plan_sha256:sha(planFile),source_sha256:hashes,input_evidence_sha256:evidence});
 save('status',{phase:'frozen_software_checks_pending',updated_at:new Date().toISOString(),training_started:false,performance_trial_started:false,validation_opened:false,test_partition_opened:false});
 console.log(JSON.stringify({phase:'frozen_software_checks_pending',protocol_sha256:sha(path.join(out,'protocol.json'))}));
}else{
 const protocol=read(path.join(out,'protocol.json')),status=read(path.join(out,'status.json'));
 assert.equal(status.phase,'frozen_software_checks_pending');assert(!status.review_complete&&!status.delivery_complete);
 assert.deepEqual(protocol.source_sha256,hashes);assert.deepEqual(protocol.input_evidence_sha256,evidence);assert.equal(protocol.plan_sha256,sha(planFile));
 const result=spawnSync(process.execPath,['--test','--test-reporter=tap','tests/proactive-sidecar-v2.test.mjs'],{cwd:root,encoding:'utf8',timeout:30000,maxBuffer:1024*1024});
 fs.writeFileSync(path.join(out,'tests.log'),(result.stdout??'')+(result.stderr??''));
 const passed=Number(result.stdout?.match(/# pass (\d+)/)?.[1]),failed=Number(result.stdout?.match(/# fail (\d+)/)?.[1]);
 save('checks',{protocol_sha256:sha(path.join(out,'protocol.json')),exit_code:result.status,passed,failed,success:result.status===0&&failed===0&&passed>=40,performance_trial_started:false,training_started:false,validation_opened:false,test_partition_opened:false});
 save('status',{...status,phase:result.status===0&&failed===0&&passed>=40?'software_checks_passed_needs_review':'software_checks_failed',updated_at:new Date().toISOString(),review_pending:true});
 console.log(result.stdout);if(result.status!==0||failed!==0||passed<40)throw Error('Repair checks failed; preserve protocol/log and inspect, no performance trial');
}
