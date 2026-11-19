// Read-only snapshot evaluation and validation-only selection. No training or physical transport.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {MissionPoolEnvR2} from './navigation_mission_env_r2.mjs';
import {NavigationEpisodeBridge} from './navigation_episode_bridge.mjs';
import {navigationFeatures,navigationRule} from './navigation_action_interface.mjs';
import {navigationBaseline} from './navigation_only_learning.mjs';
import {selectProactiveRequest} from './proactive_request_selector.mjs';
import {selectCorridorRequest} from './corridor_request_selector.mjs';
import {missionResearchGate,assertMissionPartitions} from './navigation_mission_learning.mjs';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))),RPC='warirak.navigation-evaluation-rpc.v1';
const MODEL='warirak.navigation-history-duration-double-dqn.v1';
const python=process.env.WARIRAK_TRAINING_PYTHON??'C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350/work/warirak_training_runtime/Scripts/python.exe';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const sha=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const hashJSON=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const save=(p,v)=>{fs.mkdirSync(path.dirname(p),{recursive:true});const temp=p+'.pending';fs.writeFileSync(temp,JSON.stringify(v,null,2));fs.renameSync(temp,p);};
const saveReceipt=(p,v)=>save(p,{...v,payload_sha256:hashJSON(v)});
function receipt(p){const v=read(p),{payload_sha256,...body}=v;if(hashJSON(body)!==payload_sha256)throw Error('Completed receipt checksum changed');return v;}
let legacyController=null;
export const REFERENCE_ROLES=Object.freeze(['legacy_mapped','rules_with_hold','selector_v1','selector_v2']);
export function frozenResearchGates(){return read(path.join(root,'work/navigation-only-r3-experiment/protocol.json')).gates;}
function verifyProtocol(protocolPath){
 const p=read(protocolPath);for(const[f,h]of Object.entries(p.source_sha256)){const target=path.resolve(root,f);if(!target.startsWith(root+path.sep)||sha(target)!==h)throw Error('Frozen evaluation source changed:'+f);}
 if(!p.source_sha256['frontend/assets/navigation-policy.json']||!p.source_sha256['work/navigation-only-r3-experiment/protocol.json'])throw Error('Frozen reference policy/gate evidence required');
 assert.deepEqual(p.selection.gates,frozenResearchGates(),'Do not weaken original R2/R3 research/readiness gates');
 assert.deepEqual(p.evaluation.baselines,REFERENCE_ROLES);assert.equal(p.selection.test_used_for_selection,false);
 return p;
}
export function baselineAction(role,bridge){
 const allowed=bridge.allowed();let action;
 if(role==='rules_with_hold')action=navigationRule(navigationFeatures(bridge.current.observation,bridge.previousAction),allowed);
 else if(role==='legacy_mapped'){if(!legacyController)legacyController=navigationBaseline('legacy_mapped',read(path.join(root,'frontend/assets/navigation-policy.json')));action=legacyController(bridge.current.observation,bridge.previousAction);}
 else{
  const history=bridge.recorder.decisionWindow(),last=history.at(-1),request=bridge.request();
  const context=last?.stream.record_sequence===request.record_sequence?{features:last.features,evidence_new:last.stream.evidence_new,epoch:last.stream.epoch,record_sequence:last.stream.record_sequence}:null;
  if(role==='selector_v1')action=selectProactiveRequest(context,history,allowed,{nowMs:bridge.env.now()}).action;
  else if(role==='selector_v2')action=selectCorridorRequest(context,history,allowed,{nowMs:bridge.env.now()}).action;
  else throw Error('Unknown frozen reference role');
 }
 if(action!==null&&!allowed.includes(action))throw Error('Reference expanded original navigation mask');return action;
}

class ReadOnlyPeer{
 static async open(options){const peer=new ReadOnlyPeer(options);try{peer.initialVerification=await peer.rpc('verify',{});return peer;}catch(e){await peer.close();throw e;}}
 constructor({protocolPath,snapshotPath,expectedSnapshotSha256,partition,authorizationPath}){
  const args=['-X','utf8','-m','warirak_ai.navigation_evaluator','--protocol',path.resolve(protocolPath),'--snapshot',path.resolve(snapshotPath),'--expected-snapshot-sha256',expectedSnapshotSha256,'--partition',partition];
  if(authorizationPath)args.push('--authorization',path.resolve(authorizationPath));
  this.child=spawn(python,args,{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'ai')},stdio:['pipe','pipe','pipe'],windowsHide:true});
  this.counter=0;this.pending=null;this.buffer='';this.stderr='';this.closed=false;
  this.exit=new Promise(resolve=>this.child.on('close',code=>{this.closed=true;this.fail(Error('Read-only evaluator exited '+code+':'+this.stderr.slice(-1500)));resolve(code);}));
  this.child.on('error',e=>this.fail(e));this.child.stdin.on('error',e=>this.fail(e));this.child.stdout.setEncoding('utf8');this.child.stderr.setEncoding('utf8');
  this.child.stderr.on('data',s=>this.stderr=(this.stderr+s).slice(-65536));
  this.child.stdout.on('data',s=>{this.buffer+=s;if(Buffer.byteLength(this.buffer)>1048576){this.fail(Error('Evaluation output bound'));this.child.kill();return;}
   let i;while((i=this.buffer.indexOf('\n'))>=0){const line=this.buffer.slice(0,i);this.buffer=this.buffer.slice(i+1);try{const r=JSON.parse(line),p=this.pending;if(!p||r.schema!==RPC||r.id!==p.id||typeof r.ok!=='boolean')throw Error('Evaluation RPC ordering/identity');this.pending=null;clearTimeout(p.timer);r.ok?p.resolve(r.result):p.reject(Error(r.error));}catch(e){this.fail(e);this.child.kill();}}
  });
 }
 fail(e){if(this.pending){clearTimeout(this.pending.timer);this.pending.reject(e);this.pending=null;}}
 rpc(method,params){if(this.closed||this.pending)return Promise.reject(Error('One live read-only RPC required'));const id=this.counter+1,body=JSON.stringify({schema:RPC,id,method,params})+'\n';if(Buffer.byteLength(body)>65536)return Promise.reject(Error('Evaluation input bound'));this.counter=id;
  return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{this.fail(Error('Evaluation RPC timeout'));this.child.kill();},30000);this.pending={id,resolve,reject,timer};this.child.stdin.write(body,e=>{if(e)this.fail(e);});});
 }
 async close(){if(this.closed)return this.exit;try{if(!this.pending)await this.rpc('shutdown',{});}catch{}this.child.stdin.end();const timer=setTimeout(()=>this.child.kill(),3000);const code=await this.exit;clearTimeout(timer);return code;}
}

function softwareEnvironment(seed,profile){
 const p=new MissionPoolEnvR2(seed,{profile}),d=p.drift,xAxis=Math.abs(d.x)>=Math.abs(d.y),speed=Math.abs(xAxis?d.x:d.y);
 if(!speed)throw Error('Software current fixture needs nonzero generated drift');
 const fixture={x:5,y:3,heading:0,target:{x:9,y:3,class_id:0},obstacles:[]};
 if(xAxis)fixture.x=d.x>0?p.width-p.radius-speed*.35:p.radius+speed*.35;
 else fixture.y=d.y>0?p.height-p.radius-speed*.35:p.radius+speed*.35;
 return new MissionPoolEnvR2(seed,{profile,record:true,fixture});
}
export function evaluationMetrics(rows,profile,seed,count){
 if(rows.length!==count||rows.some((r,i)=>r.seed!==seed+i||r.profile!==profile||r.source!=='simulation'||r.physical_motor_transport!==false||r.done!==true||!r.all_physical_steps_accounted||!r.assistance_not_early_termination||!Number.isInteger(r.steps)||r.steps<1||r.steps>960||!['collections','collisions','timeouts'].every(k=>Number.isInteger(r[k])&&r[k]>=0&&r[k]<=1)||r.collections+r.collisions+r.timeouts!==1||r.pending_credit_steps!==0||r.credited_steps+r.passive_prefix_steps!==r.steps||!Number.isFinite(r.reward_conservation_error)||Math.abs(r.reward_conservation_error)>1e-7))throw Error('Incomplete/censored evaluation population');
 const sum=k=>rows.reduce((n,r)=>n+r[k],0),steps=sum('steps'),collections=sum('collections'),collisions=sum('collisions'),timeouts=sum('timeouts');
 return{schema:'warirak.mission-evaluation.v1',environment:'warirak-pool-mission-v4r2-dev',source:'simulation',profile,seed,episodes:count,collections,collisions,timeouts,steps,range_wait_steps:sum('range_wait_steps'),assistance_episodes:rows.filter(r=>r.assistance).length,hard_unavailable_episodes:rows.filter(r=>r.hard_unavailable).length,transport_latency_over_ttl_episodes:rows.filter(r=>r.transport_delay_ms>=400).length,success_rate:collections/count,collision_rate:collisions/count,timeout_rate:timeouts/count,assistance_rate:rows.filter(r=>r.assistance).length/count,hard_unavailable_rate:rows.filter(r=>r.hard_unavailable).length/count,mean_steps:steps/count,range_wait_observation_fraction:sum('range_wait_steps')/(2*steps),all_fault_cases_in_denominator:true,continues_physics_after_assistance:true,real_world_validated:false,control_enabled:false};
}
function validateTestReview(p,hash,snapshotSha,authorizationPath){
 if(!authorizationPath)throw Error('Test remains closed until reviewed validation selection');
 const review=read(authorizationPath);
 if(!path.resolve(review.selection_path??'').startsWith(root+path.sep)||review.schema!=='warirak.navigation-test-authorization.v1'||review.protocol_sha256!==hash||review.snapshot_sha256!==snapshotSha||review.engineering_review_complete!==true||review.open_test!==true||review.test_used_for_selection!==false||sha(review.selection_path)!==review.selection_sha256)throw Error('Changed test review/selection hash');
 const selection=read(review.selection_path);
 if(selection.schema!=='warirak.navigation-snapshot-selection.v1'||selection.partition!=='validation'||selection.protocol_sha256!==hash||selection.status!=='candidate_ready_for_review'||selection.test_opened!==false||selection.selected?.snapshot_sha256!==snapshotSha)throw Error('Test cannot choose or replace a model');
}

export async function evaluateSnapshotPartition({protocolPath,snapshotPath,expectedSnapshotSha256,partition,outputRoot,authorizationPath}){
 const p=verifyProtocol(protocolPath),protocolHash=sha(protocolPath),software=p.execution_scope==='software_preflight';
 if(sha(path.join(snapshotPath,'snapshot.json'))!==expectedSnapshotSha256)throw Error('Snapshot manifest changed');
 const snapshotMetadata=read(path.join(snapshotPath,'snapshot.json'));
 if(snapshotMetadata.protocol_sha256!==protocolHash||snapshotMetadata.model_schema!==MODEL||sha(path.join(snapshotPath,'checkpoint.pt'))!==snapshotMetadata.checkpoint_sha256)throw Error('Snapshot checkpoint identity/hash changed');
 if(software&&partition!=='software'||!software&&!['validation','test'].includes(partition))throw Error('Explicit allowed partition required');
 if(!software)assertMissionPartitions(p);
 if(partition==='test')validateTestReview(p,protocolHash,expectedSnapshotSha256,authorizationPath);
 const spec=software?p.software_evaluation:p[partition],roles=partition==='test'?['candidate']:[...REFERENCE_ROLES,'candidate'];
 outputRoot=path.resolve(outputRoot);fs.mkdirSync(outputRoot,{recursive:true});const identity={schema:'warirak.navigation-evaluation-run.v1',protocol_sha256:protocolHash,partition};
 const identityFile=path.join(outputRoot,'run-identity.json');if(fs.existsSync(identityFile))assert.deepEqual(read(identityFile),identity);else fs.writeFileSync(identityFile,JSON.stringify(identity),{flag:'wx'});
 const reportFile=path.join(outputRoot,'candidates',expectedSnapshotSha256,'report.json');
 if(fs.existsSync(reportFile)){const old=receipt(reportFile);if(old.protocol_sha256!==protocolHash||old.snapshot_sha256!==expectedSnapshotSha256||!old.complete||!old.read_only.read_only_verified)throw Error('Changed closed evaluation receipt');return{...old,from_cache:true};}
 const lock=path.join(outputRoot,'evaluation.lock');fs.writeFileSync(lock,JSON.stringify({pid:process.pid,protocol_sha256:protocolHash,snapshot_sha256:expectedSnapshotSha256,started_at:new Date().toISOString()}),{flag:'wx'});
 let peer=null,completedCases=0;const status=data=>save(path.join(outputRoot,'status.json'),{updated_at:new Date().toISOString(),pid:process.pid,protocol_sha256:protocolHash,partition,snapshot_sha256:expectedSnapshotSha256,actual_model_evaluation:!software,physical_motor_transport:false,...data});
 try{
  status({phase:'loading_read_only_snapshot'});
  peer=await ReadOnlyPeer.open({protocolPath,snapshotPath,expectedSnapshotSha256,partition,authorizationPath});
  const byRole={};
  for(const role of roles){byRole[role]={};for(const profile of ['nominal','stress']){
   const seed=spec[profile+'_seed'],count=spec.episodes_per_profile,rows=[];
   for(let i=0;i<count;i++){
    const file=role==='candidate'?path.join(outputRoot,'candidates',expectedSnapshotSha256,profile,i+'.json'):path.join(outputRoot,'baselines',role,profile,i+'.json');
    if(fs.existsSync(file)){const saved=receipt(file);if(saved.protocol_sha256!==protocolHash||saved.partition!==partition||saved.role!==role||saved.seed!==seed+i||saved.snapshot_sha256!==(role==='candidate'?expectedSnapshotSha256:null)||role==='candidate'&&(!saved.read_only?.read_only_verified||saved.read_only.before_state_sha256!==peer.initialVerification.before_state_sha256||saved.read_only.after_state_sha256!==peer.initialVerification.before_state_sha256))throw Error('Changed/unverified prior completed case');rows.push(saved.result);completedCases++;continue;}
    status({phase:'evaluating',role,profile,seed:seed+i,completed_cases:completedCases,total_cases:roles.length*2*count});
    const env=software?softwareEnvironment(seed+i,profile):new MissionPoolEnvR2(seed+i,{profile,record:true});
    if(!software&&env.fixtureUsed)throw Error('Development fixtures forbidden in actual evaluation');
    const id=role+'-'+profile+'-'+i,bridge=new NavigationEpisodeBridge(env,{episodeId:id,sessionId:'eval-'+id});
    while(!env.done){if(role==='candidate'){const request=bridge.request(),r=await peer.rpc('predict',{request,now_ms:request.encoded_at_ms});bridge.advanceFromReply(r.reply,{expectedModelSchema:MODEL});}else bridge.advance(baselineAction(role,bridge),{decisionSource:'frozen_reference_'+role});}
    const result=bridge.summary(),verifiedCase=role==='candidate'?await peer.rpc('verify_case',{}):null;
    saveReceipt(file,{schema:'warirak.navigation-snapshot-case.v1',protocol_sha256:protocolHash,partition,role,seed:seed+i,snapshot_sha256:role==='candidate'?expectedSnapshotSha256:null,read_only:verifiedCase,result});rows.push(result);completedCases++;
   }
   byRole[role][profile]=evaluationMetrics(rows,profile,seed,count);
  }}
  const verified=await peer.rpc('verify',{}),metadata=read(path.join(snapshotPath,'snapshot.json'));
  const report={schema:'warirak.navigation-snapshot-evaluation.v1',protocol_sha256:protocolHash,partition,snapshot_sha256:expectedSnapshotSha256,checkpoint_sha256:metadata.checkpoint_sha256,snapshot_episode:metadata.episode,complete:true,software_preflight:software,not_a_performance_benchmark:software,read_only:verified,baselines:Object.fromEntries(REFERENCE_ROLES.filter(r=>byRole[r]).map(r=>[r,byRole[r]])),candidate:byRole.candidate,test_used_for_selection:false,physical_motor_transport:false};
  saveReceipt(reportFile,report);status({phase:'evaluation_complete',completed_cases:completedCases,report_path:reportFile,test_opened:partition==='test'});return report;
 }catch(error){status({phase:'needs_repair',completed_cases:completedCases,error:String(error.message).slice(0,1500)});throw error;}
 finally{if(peer){await peer.close();fs.writeFileSync(path.join(outputRoot,'python-stderr.log'),peer.stderr);}fs.unlinkSync(lock);}
}

export function rankValidationMetrics(records,baselines,gates){
 assert.deepEqual(gates,frozenResearchGates(),'Original research/readiness gates required');
 const rows=records.map(r=>({...r,gate:missionResearchGate(baselines,r.metrics,gates)}));
 const score=r=>r.metrics.stress.success_rate-2*r.metrics.stress.collision_rate-.25*r.metrics.stress.hard_unavailable_rate;
 rows.sort((a,b)=>Number(b.gate.eligible)-Number(a.gate.eligible)||score(b)-score(a)||b.metrics.nominal.success_rate-a.metrics.nominal.success_rate||a.metrics.nominal.mean_steps-b.metrics.nominal.mean_steps||a.episode-b.episode);
 return{ranking:rows,selected:rows.find(r=>r.gate.eligible)??null,test_used_for_selection:false,production_ready:false};
}
export function selectValidationSnapshots({protocolPath,reportPaths,outputPath}){
 const reports=reportPaths.map(receipt);if(reports.some(r=>r.partition!=='validation'))throw Error('Validation only; never select using test/software results');
 const p=verifyProtocol(protocolPath),hash=sha(protocolPath);if(p.execution_scope!=='research_training')throw Error('Actual research validation selection required');
 assert.deepEqual(reports.map(r=>r.snapshot_episode).sort((a,b)=>a-b),p.runtime_config.snapshot_episodes,'All frozen candidate snapshots must be reviewed');
 for(const r of reports){if(r.protocol_sha256!==hash||!r.complete||r.software_preflight||!r.read_only?.read_only_verified||r.read_only.before_state_sha256!==r.read_only.after_state_sha256||r.read_only.snapshot_sha256!==r.snapshot_sha256||r.read_only.checkpoint_sha256!==r.checkpoint_sha256||r.test_used_for_selection!==false)throw Error('Incomplete or changed validation artifact');for(const profile of ['nominal','stress'])for(const m of [r.candidate[profile],...REFERENCE_ROLES.map(role=>r.baselines[role][profile])]){if(m.seed!==p.validation[profile+'_seed']||m.episodes!==p.validation.episodes_per_profile||!m.all_fault_cases_in_denominator||!m.continues_physics_after_assistance||m.collections+m.collisions+m.timeouts!==m.episodes||Math.abs(m.success_rate-m.collections/m.episodes)>1e-12||Math.abs(m.collision_rate-m.collisions/m.episodes)>1e-12)throw Error('Validation population/ratios changed');}assert.deepEqual(Object.keys(r.baselines).sort(),[...REFERENCE_ROLES].sort());assert.deepEqual(r.baselines,reports[0].baselines,'Same frozen baseline population required');}
 const result=rankValidationMetrics(reports.map(r=>({episode:r.snapshot_episode,snapshot_sha256:r.snapshot_sha256,checkpoint_sha256:r.checkpoint_sha256,metrics:r.candidate})),reports[0].baselines,p.selection.gates);
 const selected=result.selected,report={schema:'warirak.navigation-snapshot-selection.v1',protocol_sha256:hash,partition:'validation',status:selected?'candidate_ready_for_review':'retained_baseline',selected:selected?{episode:selected.episode,snapshot_sha256:selected.snapshot_sha256,checkpoint_sha256:selected.checkpoint_sha256}:null,ranking:result.ranking,validation_report_sha256:reportPaths.map(sha),test_opened:false,test_used_for_selection:false,production_ready:false,physical_motor_transport:false};
 if(fs.existsSync(outputPath))throw Error('Preserve closed selection decision');saveReceipt(outputPath,report);return report;
}

export async function runValidationSnapshots({protocolPath,trainingRoot,outputRoot}){
 const p=verifyProtocol(protocolPath),hash=sha(protocolPath);if(p.execution_scope!=='research_training')throw Error('Actual validation pipeline needs a complete research protocol');
 outputRoot=path.resolve(outputRoot);fs.mkdirSync(outputRoot,{recursive:true});const selectionFile=path.join(outputRoot,'selection.json');
 if(fs.existsSync(selectionFile)){const old=receipt(selectionFile);if(old.protocol_sha256!==hash||old.partition!=='validation'||old.test_used_for_selection!==false)throw Error('Changed closed selection');return old;}
 const lock=path.join(outputRoot,'validation-pipeline.lock');fs.writeFileSync(lock,JSON.stringify({pid:process.pid,protocol_sha256:hash}),{flag:'wx'});
 try{
  const reports=[];
  for(const episode of p.runtime_config.snapshot_episodes){const snapshotPath=path.join(trainingRoot,'snapshots','episode-'+String(episode).padStart(6,'0')),digest=sha(path.join(snapshotPath,'snapshot.json'));
   await evaluateSnapshotPartition({protocolPath,snapshotPath,expectedSnapshotSha256:digest,partition:'validation',outputRoot:path.join(outputRoot,'validation')});
   reports.push(path.join(outputRoot,'validation','candidates',digest,'report.json'));
  }
  return selectValidationSnapshots({protocolPath,reportPaths:reports,outputPath:selectionFile});
 }finally{fs.unlinkSync(lock);}
}
