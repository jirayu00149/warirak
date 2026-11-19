// One frozen bounded DEVELOPMENT trial. No training, automatic tuning or held-out evaluation.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {selectProactiveRequest as selectReferenceRequest} from './proactive_request_selector.mjs';
import {selectCorridorRequest,CORRIDOR_CONSTANTS} from './corridor_request_selector.mjs';
import {ProactiveSidecarV2 as ProactiveSidecar} from './proactive_sidecar_v2.mjs';
import {ISSUED_CONTROL_RECORD} from './proactive_observation.mjs';
import {MissionPoolEnvR2,missionRequestR2,MISSION_ACTIONS_R2} from './navigation_mission_env_r2.mjs';
import {navigationAllowed,navigationFeatures} from './navigation_action_interface.mjs';
const project=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const root=path.join(project,'work/corridor-selector-v2-dev'),configFile=path.join(project,'ai/corridor-selector-v2-plan.json');
const read=f=>JSON.parse(fs.readFileSync(f,'utf8').replace(/^\uFEFF/,'')),sha=f=>createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const save=(name,data)=>{const p=path.join(root,name+'.json'),tmp=p+'.tmp';fs.writeFileSync(tmp,JSON.stringify(data,null,2));fs.renameSync(tmp,p);};
const config=read(configFile),mode=process.argv[2];
if(!['--freeze','--preflight','--execute','--resume'].includes(mode)||process.argv.length!==3)throw Error('Use exactly --freeze, --preflight, --execute or interrupted-run --resume');
assert.deepEqual(config.constants,CORRIDOR_CONSTANTS);assert.equal(config.cases.length,20);assert.equal(config.profile,'stress');
assert(config.cases.every(c=>/^[a-z0-9_]+$/.test(c.id)&&c.seed>=37000000&&c.seed<=37000009));
const old=read(path.join(project,'work/proactive-selector-v1-dev-r1/protocol.json'));
const sources=[...new Set([...Object.keys(old.source_sha256),'ai/proactive_sidecar_v2.mjs','ai/corridor_request_selector.mjs','ai/run_corridor_selector_dev.mjs','tests/corridor-selector.test.mjs','ai/corridor-selector-v2-plan.json'])];
const sourceHashes=Object.fromEntries(sources.map(f=>[f,sha(path.join(project,f))]));
for(const [f,h] of Object.entries(old.source_sha256))assert.equal(sourceHashes[f],h,f);
const baseline=path.join(project,'frontend/assets/navigation-policy.json');assert.equal(sha(baseline),old.baseline_sha256);
if(mode==='--freeze'){
 assert.equal(fs.existsSync(root),false,'Preserve existing frozen trial');fs.mkdirSync(root,{recursive:true});
 const repair=read(path.join(project,'outputs/Warirak_Proactive_Sidecar_v2_Repair_Audit.json'));assert(repair.review_complete&&repair.cached_ranges_remain_unknown);
 save('protocol',{...config,frozen_before_preflight_and_rollout:true,frozen_at:new Date().toISOString(),config_sha256:sha(configFile),source_sha256:sourceHashes,baseline_sha256:sha(baseline),sidecar_repair_audit_sha256:sha(path.join(project,'outputs/Warirak_Proactive_Sidecar_v2_Repair_Audit.json')),window_inspection_sha256:sha(path.join(project,'work/side-circle-window-inspection/inspection.json'))});
 save('status',{phase:'frozen_preflight_pending',updated_at:new Date().toISOString(),training_started:false,validation_opened:false,test_opened:false,physical_motor_transport:false});
 console.log(JSON.stringify({phase:'frozen_preflight_pending',protocol_sha256:sha(path.join(root,'protocol.json'))}));
}else{
 const protocol=read(path.join(root,'protocol.json')),status=read(path.join(root,'status.json')),protocolHash=sha(path.join(root,'protocol.json'));
 assert.deepEqual(protocol.source_sha256,sourceHashes,'Frozen sources changed');assert.equal(protocol.config_sha256,sha(configFile));assert.equal(protocol.baseline_sha256,sha(baseline));
 assert(!status.review_complete&&!status.delivery_complete&&status.phase!=='development_complete_needs_review','Closed/complete trial must not be repeated');
 if(mode==='--preflight'){
  assert.equal(status.phase,'frozen_preflight_pending');
  const r=spawnSync(process.execPath,['--test','--test-reporter=tap','tests/corridor-selector.test.mjs'],{cwd:project,encoding:'utf8',timeout:30000,maxBuffer:1024*1024});
  fs.writeFileSync(path.join(root,'preflight-tests.log'),(r.stdout??'')+(r.stderr??''));
  const passed=Number(r.stdout?.match(/# pass (\d+)/)?.[1]),failed=Number(r.stdout?.match(/# fail (\d+)/)?.[1]);
  save('preflight',{protocol_sha256:protocolHash,test_source_sha256:sha(path.join(project,'tests/corridor-selector.test.mjs')),exit_code:r.status,passed,failed,success:r.status===0&&failed===0&&passed>0});
  save('status',{...status,phase:r.status===0&&failed===0?'preflight_passed':'preflight_failed',updated_at:new Date().toISOString()});
  console.log(r.stdout);if(r.status!==0||failed!==0)throw Error('Frozen preflight failed: do not execute fixtures');
 }else{
  const preflight=read(path.join(root,'preflight.json'));assert(preflight.success&&preflight.protocol_sha256===protocolHash);
  assert(['preflight_passed','needs_repair','running_development'].includes(status.phase));
  if(mode==='--execute')assert.equal(status.phase,'preflight_passed','Inspect interrupted run before --resume');
  const lock=path.join(root,'run.lock');
  if(fs.existsSync(lock)){const l=read(lock);let alive=false;try{process.kill(l.pid,0);alive=true;}catch{}assert(!alive,'Healthy trial already running');assert.equal(mode,'--resume');fs.unlinkSync(lock);}
  const disk=fs.statfsSync(project);assert(Number(disk.bavail)*Number(disk.bsize)>=config.minimum_free_disk_mib*1024*1024,'Insufficient free disk');
  fs.writeFileSync(lock,JSON.stringify({pid:process.pid,started_at:new Date().toISOString()}),{flag:'wx'});
  const results=[];
  const badAck=new Set(['inconsistent_report','feedback_after_command_window','invalid_issued_control_ledger']);
  const assist=new Set(['FAULT_STOP','HOLD_UNAVAILABLE','RECOVERY_REQUIRED','ACTUATION_UNAVAILABLE','PROGRESS_UNCERTAIN']);
  let current=null;
  try{
   for(const role of ['reference','candidate'])for(const fixture of config.cases){
    current=role+'-'+fixture.id;const output=path.join(root,current+'.json');
    if(fs.existsSync(output)){const saved=read(output);assert.equal(saved.protocol_sha256,protocolHash);assert.equal(saved.role,role);assert.equal(saved.case_id,fixture.id);results.push(saved);continue;}
    save('status',{phase:'running_development',pid:process.pid,updated_at:new Date().toISOString(),current_case:current,completed_cases:results.length,total_cases:40,training_started:false,validation_opened:false,test_opened:false,physical_motor_transport:false});
    const env=new MissionPoolEnvR2(fixture.seed,{profile:'stress',record:true,fixture:fixture.fixture}),recorder=new ProactiveSidecar();
    let previous=0,nearSteps=0,nonzero=0,integrityFailures=0,maskFailures=0,ttlFailures=0,firstNear=false,firstAssist=false,firstFault=false,firstDecline=false,firstExtension=false;
    const windows=[],recentProposals=[],reasons={};
    const applyFaults=()=>{
     const n=env.steps,patch={};
     if(fixture.fault==='range_gap')patch.range_packet_loss=n>=20&&n<=24;
     if(fixture.fault==='motion_gap')patch.motion_dropout=n>=20&&n<=45;
     if(fixture.fault==='feedback_gap')patch.feedback_loss=n>=15&&n<=30;
     if(fixture.fault==='operator_schedule'){patch.manual_override=n>=10&&n<=19;patch.armed=!(n>=25&&n<=34);}
     const changed=Object.fromEntries(Object.entries(patch).filter(([k,v])=>env.faults[k]!==v));if(Object.keys(changed).length)env.setFaults(changed);
     if(fixture.fault==='pose_clock_fault'&&n===15&&env.observation.pose)env.observation.pose.timestamp_unix_ms=env.now()+100;
     if(fixture.fault==='ack_mismatch'&&n===15&&env.observation.actuator_feedback)env.observation.actuator_feedback.request_sequence=(env.observation.actuator_feedback.request_sequence??0)+1000;
     if(fixture.fault==='operator_schedule'&&n===40)recorder.cancel(env.now());
    };
    while(!env.done){
     applyFaults();const o=env.observe(),captured=recorder.capture(o,{receivedAtMs:env.now()}),allowed=navigationAllowed(o,navigationFeatures(o,previous)),ctx=captured.decision_context;
     const operatorStop=fixture.fault==='operator_schedule'&&env.steps>=40&&env.steps<=49;
     let proposal;
     if(operatorStop||captured.stream_fault||badAck.has(ctx?.features?.ack?.status))proposal={action:allowed.includes(0)?0:null,reason:operatorStop?'common_operator_STOP':'common_recording_or_ACK_integrity_override'};
     else proposal=role==='candidate'?selectCorridorRequest(ctx,recorder.decisionWindow(),allowed,{nowMs:env.now()}):selectReferenceRequest(ctx,recorder.decisionWindow(),allowed,{nowMs:env.now()});
     let action=proposal.action;
     if(action!==null&&!allowed.includes(action)){maskFailures++;action=allowed.includes(0)?0:null;}
     reasons[proposal.reason]=(reasons[proposal.reason]??0)+1;
     const at=env.now(),request=action===null?null:missionRequestR2(env.steps,at,MISSION_ACTIONS_R2[action]);
     recorder.noteDecision(request,{atMs:at});
     const c=o.sensors?.clearance_m,near=o.sensors?.range_evidence?.status==='fresh'&&Array.isArray(c)&&c.some(v=>typeof v==='number'&&v<.35)&&allowed.length===1&&allowed[0]===0&&!assist.has(o.mission.mode)&&o.sensors.armed&&!o.sensors.manual_override;
     if(near)nearSteps++;
     env.step(request);const trace=env.trace.at(-1),issued=trace.issued;
     recorder.attachTransition(trace,{recordSequence:captured.record_sequence});
     if(Number.isInteger(issued.request_sequence)&&issued.request_sequence>=0)recorder.noteIssuedControl({schema:ISSUED_CONTROL_RECORD,plant_environment:'warirak-pool-mission-v4r2-dev',source:'simulation',units:'normalized',control_enabled:false,physical_transport:false,control_sequence:issued.sequence,request_sequence:issued.request_sequence,issued_at_ms:issued.issued_at_ms,valid_until_ms:issued.valid_until_ms,left:issued.left,right:issued.right},{atMs:env.now()});
     const movedCommand=Math.abs(trace.applied.left)>0||Math.abs(trace.applied.right)>0;nonzero+=Number(movedCommand);
     if(movedCommand&&(o.sensors.manual_override||!o.sensors.armed||operatorStop||env.faults.range_packet_loss))integrityFailures++;
     if(issued.valid_until_ms-issued.issued_at_ms>400)ttlFailures++;
     recentProposals.push({at_ms:at,proposal,actual_original_request:request});if(recentProposals.length>12)recentProposals.shift();
     const declined=(proposal.base_reason??proposal.reason)==='no_original_evasive_request_permitted'&&allowed.includes(1)&&action===0;
     const event=!firstExtension&&proposal.corridor_extension_used?'first_corridor_extension':!firstDecline&&declined?'first_decline_with_forward_permitted':!firstNear&&near?'first_guard_near_STOP':!firstAssist&&assist.has(env.mode)?'first_assistance':!firstFault&&captured.stream_fault?'first_recorder_fault':null;
     if(event){if(event==='first_corridor_extension')firstExtension=true;if(event==='first_decline_with_forward_permitted')firstDecline=true;if(event==='first_guard_near_STOP')firstNear=true;if(event==='first_assistance')firstAssist=true;if(event==='first_recorder_fault')firstFault=true;if(windows.length<4)windows.push({event,at_ms:at,trigger_original_observation:o,records:recorder.records(),proposals:structuredClone(recentProposals)});}
     if(env.trace.length>1)env.trace.splice(0,env.trace.length-1);previous=action??0;
    }
    assert.equal(env.collected+env.collisions+Number(env.truncated),1);
    const result={schema:'warirak.corridor-development-case.v1',protocol_sha256:protocolHash,role,case_id:fixture.id,pair_id:fixture.pair_id,geometry:fixture.geometry,seed:fixture.seed,source:'simulation',development_fixture:true,profile:'stress',transport_delay_ms:env.delayTicks*100,outcome:env.collected?'collection':env.collisions?'collision':'timeout',collections:env.collected,collisions:env.collisions,timeouts:Number(env.truncated),steps:env.steps,near_guard_STOP_steps:nearSteps,nonzero_applied_steps:nonzero,integrity_failures:integrityFailures,mask_violations:maskFailures,ttl_violations:ttlFailures,reason_counts:reasons,corridor_extension_uses:reasons.supported_forward_corridor_request??0,first_event_windows:windows,final_recorder:recorder.snapshot(),all_fault_cases_retained:true,assistance_not_early_termination:true,trained:false,validation_opened:false,test_opened:false,physical_motor_transport:false};
    save(current,result);results.push(result);
    const bytes=fs.readdirSync(root).map(f=>fs.statSync(path.join(root,f)).size).reduce((a,b)=>a+b,0);assert(bytes<=config.output_limit_mib*1024*1024,'Output budget exceeded; inspect saved evidence before resuming');
   }
   assert.equal(results.length,40);
   const summary=Object.fromEntries(['reference','candidate'].map(role=>{const rows=results.filter(r=>r.role===role);return[role,{cases:rows.length,collections:rows.reduce((n,r)=>n+r.collections,0),collisions:rows.reduce((n,r)=>n+r.collisions,0),timeouts:rows.reduce((n,r)=>n+r.timeouts,0),integrity_failures:rows.reduce((n,r)=>n+r.integrity_failures,0),mask_violations:rows.reduce((n,r)=>n+r.mask_violations,0),ttl_violations:rows.reduce((n,r)=>n+r.ttl_violations,0)}];}));
   const paired=config.cases.map(f=>({fixture:f,candidate:results.find(r=>r.role==='candidate'&&r.case_id===f.id),reference:results.find(r=>r.role==='reference'&&r.case_id===f.id)}));
   const finitePairs=paired.filter(p=>p.fixture.geometry==='finite'),wallPairs=paired.filter(p=>p.fixture.geometry==='wall');
   const mechanics=Object.values(summary).every(r=>r.integrity_failures===0&&r.mask_violations===0&&r.ttl_violations===0)&&results.filter(r=>r.transport_delay_ms===600).every(r=>r.nonzero_applied_steps===0);
   const improved=finitePairs.filter(p=>p.candidate.collections>p.reference.collections&&p.candidate.collisions<=p.reference.collisions).map(p=>p.fixture.id);
   const regressions=finitePairs.filter(p=>p.candidate.collections<p.reference.collections||p.candidate.collisions>p.reference.collisions).map(p=>p.fixture.id);
   const wallExtensions=wallPairs.reduce((n,p)=>n+p.candidate.corridor_extension_uses,0);
   const gate={mechanics_passed:mechanics,no_finite_case_regression:regressions.length===0,no_wall_case_collision_increase:wallPairs.every(p=>p.candidate.collisions<=p.reference.collisions),at_least_one_finite_case_improves:improved.length>0,wall_corridor_extension_count_must_be_zero:wallExtensions===0};
   save('summary',{schema:'warirak.corridor-development-summary.v1',protocol_sha256:protocolHash,summary,gate,improved_finite_cases:improved,regressed_finite_cases:regressions,wall_extension_uses:wallExtensions,development_evidence_sufficient:Object.values(gate).every(Boolean),not_a_validation_or_field_benchmark:true,model_selected:false,training_started:false,test_opened:false,validation_opened:false,production_unchanged:true});
   save('status',{phase:'development_complete_needs_review',pid:process.pid,updated_at:new Date().toISOString(),completed_cases:40,review_pending:true,training_started:false,validation_opened:false,test_opened:false,physical_motor_transport:false});
   console.log(JSON.stringify({phase:'development_complete_needs_review',summary,gate}));
  }catch(error){save('status',{phase:'needs_repair',pid:process.pid,updated_at:new Date().toISOString(),failed_case:current,completed_cases:results.length,error:error.message,training_started:false,validation_opened:false,test_opened:false});throw error;}
  finally{if(fs.existsSync(lock)&&read(lock).pid===process.pid)fs.unlinkSync(lock);}
 }
}
