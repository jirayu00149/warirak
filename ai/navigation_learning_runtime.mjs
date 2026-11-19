// Full local simulation runtime. Explicit frozen protocol required; never physical transport.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {MissionPoolEnvR2} from './navigation_mission_env_r2.mjs';
import {NavigationEpisodeBridge} from './navigation_episode_bridge.mjs';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const RPC='warirak.navigation-learning-rpc.v1',MODEL='warirak.navigation-history-duration-double-dqn.v1';
const python=process.env.WARIRAK_TRAINING_PYTHON??'C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350/work/warirak_training_runtime/Scripts/python.exe';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const sha=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const save=(p,value)=>{const temp=p+'.pending';fs.writeFileSync(temp,JSON.stringify(value,null,2));fs.renameSync(temp,p);};

export class NavigationLearningPeer{
 static async open({protocolPath,storePath,operation}){
  const peer=new NavigationLearningPeer(protocolPath,storePath,operation);
  try{await peer.rpc('status',{});return peer;}catch(e){await peer.close({abortUncommitted:true});throw e;}
 }
 constructor(protocolPath,storePath,operation){
  if(!['initialize','resume'].includes(operation))throw Error('Explicit initialize/resume operation required');
  this.counter=0;this.pending=null;this.buffer='';this.stderr='';this.closed=false;
  this.child=spawn(python,['-X','utf8','-m','warirak_ai.navigation_runtime','--protocol',path.resolve(protocolPath),'--store',path.resolve(storePath),'--operation',operation],{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'ai')},stdio:['pipe','pipe','pipe'],windowsHide:true});
  this.exit=new Promise(resolve=>this.child.on('close',code=>{this.closed=true;this._fail(Error('Runtime exited '+code+': '+this.stderr.slice(-1500)));resolve(code);}));
  this.child.on('error',e=>this._fail(e));this.child.stdin.on('error',e=>this._fail(e));
  this.child.stdout.setEncoding('utf8');this.child.stderr.setEncoding('utf8');
  this.child.stderr.on('data',s=>{this.stderr=(this.stderr+s).slice(-65536);});
  this.child.stdout.on('data',s=>{
   this.buffer+=s;if(Buffer.byteLength(this.buffer,'utf8')>1048576){this._fail(Error('Bounded RPC output exceeded'));this.child.kill();return;}
   let at;while((at=this.buffer.indexOf('\n'))>=0){const line=this.buffer.slice(0,at);this.buffer=this.buffer.slice(at+1);
    try{const r=JSON.parse(line),p=this.pending;if(!p||r.schema!==RPC||r.id!==p.id||typeof r.ok!=='boolean')throw Error('RPC response identity/ordering mismatch');this.pending=null;clearTimeout(p.timer);r.ok?p.resolve(r.result):p.reject(Error('Runtime rejected '+p.method+': '+r.error));}
    catch(error){this._fail(error);this.child.kill();}
   }
  });
 }
 _fail(error){if(this.pending){clearTimeout(this.pending.timer);this.pending.reject(error);this.pending=null;}}
 rpc(method,params){
  if(this.closed||this.pending)return Promise.reject(Error('One live sequential runtime RPC required'));
  const id=this.counter+1,body=JSON.stringify({schema:RPC,id,method,params})+'\n';
  if(Buffer.byteLength(body,'utf8')>65536)return Promise.reject(Error('Bounded RPC input exceeded'));
  this.counter=id;
  return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{this._fail(Error('Runtime RPC timed out; inspect owner lock/checkpoint'));this.child.kill();},30000);this.pending={id,method,resolve,reject,timer};this.child.stdin.write(body,error=>{if(error)this._fail(error);});});
 }
 async close({abortUncommitted=false}={}){
  if(this.closed)return this.exit;
  try{if(!this.pending)await this.rpc('shutdown',{abort_uncommitted:abortUncommitted});}catch{}
  this.child.stdin.end();const timer=setTimeout(()=>this.child.kill(),3000);
  const result=await this.exit;clearTimeout(timer);return result;
 }
}

export function runtimeEpisodeIdentity(protocolHash,index){
 if(!/^[0-9a-f]{64}$/.test(protocolHash)||!Number.isInteger(index)||index<0||index>100000)throw Error('Bounded protocol/episode identity required');
 return{episodeId:'duration-'+protocolHash.slice(0,12)+'-'+String(index).padStart(6,'0'),sessionId:'dn-'+protocolHash.slice(0,12)+'-'+String(index).padStart(6,'0')};
}
export function runtimeEnvironment(protocol,index){
 const c=protocol.runtime_config,seed=c.scene_seed+index,profile=c.profiles[index%c.profiles.length];
 if(c.fixture_policy==='generated_unmodified')return new MissionPoolEnvR2(seed,{profile,record:true});
 if(protocol.execution_scope!=='software_preflight'||c.fixture_policy!=='analytic_bank_four_steps')throw Error('Development fixture forbidden for actual training');
 const p=new MissionPoolEnvR2(seed,{profile}),d=p.drift,xAxis=Math.abs(d.x)>=Math.abs(d.y),speed=Math.abs(xAxis?d.x:d.y);
 if(speed===0)throw Error('Four-step current fixture needs generated nonzero current');
 const fixture={x:5,y:3,heading:0,target:{x:9,y:3,class_id:0},obstacles:[]};
 if(xAxis)fixture.x=d.x>0?p.width-p.radius-speed*.35:p.radius+speed*.35;
 else fixture.y=d.y>0?p.height-p.radius-speed*.35:p.radius+speed*.35;
 // Preserve generated actuator delay as well as current/noise/dropout/gains.
 return new MissionPoolEnvR2(seed,{profile,record:true,fixture});
}

export async function runNavigationLearning({protocolPath,runRoot,operation,stopAfterPhysicalSteps=null}){
 const protocol=read(protocolPath),hash=sha(protocolPath),c=protocol.runtime_config,software=protocol.execution_scope==='software_preflight';
 if(stopAfterPhysicalSteps!==null&&(!software||!Number.isInteger(stopAfterPhysicalSteps)||stopAfterPhysicalSteps<1))throw Error('Controlled interruption only in declared software preflight');
 runRoot=path.resolve(runRoot);fs.mkdirSync(runRoot,{recursive:true});
 const identity={schema:'warirak.navigation-runtime-run.v1',protocol_sha256:hash,scope:protocol.execution_scope};
 const identityFile=path.join(runRoot,'run-identity.json');
 if(operation==='initialize'){if(fs.existsSync(identityFile))throw Error('Existing run: inspect and explicitly resume');fs.writeFileSync(identityFile,JSON.stringify(identity),{flag:'wx'});}
 else if(JSON.stringify(read(identityFile))!==JSON.stringify(identity))throw Error('Run protocol identity changed');
 const statusFile=path.join(runRoot,'status.json');let peer=null,bridge=null,lastLedger=null,physicalThisProcess=0;
 const status=data=>save(statusFile,{updated_at:new Date().toISOString(),pid:process.pid,actual_training_started:!software,physical_motor_transport:false,...data});
 try{
  status({phase:'starting_python_runtime',operation});
  peer=await NavigationLearningPeer.open({protocolPath,storePath:path.join(runRoot,'checkpoints'),operation});
  let state=await peer.rpc('status',{});
  while(state.cursor.next_episode_index<c.episodes){
   const index=state.cursor.next_episode_index,env=runtimeEnvironment(protocol,index),id=runtimeEpisodeIdentity(hash,index);
   const schedule=software?(c.software_faults??[]).filter(x=>x.episode_index===index).map(({episode_index,...event})=>event):[];
   bridge=new NavigationEpisodeBridge(env,{...id,faultSchedule:schedule});
   await peer.rpc('begin',{seed:env.seed,profile:env.profile,fixture_used:env.fixtureUsed,first_request:bridge.request()});
   status({phase:software?'running_software_integration':'running_training',episode_index:index,seed:env.seed,committed_episodes:index});
   while(!env.done){
    const wait=software&&(c.software_waits??[]).some(x=>x.episode_index===index&&x.step===env.steps);
    if(wait)lastLedger=bridge.advance(null,{decisionSource:'declared_software_inference_wait'});
    else{const request=bridge.request(),proposal=await peer.rpc('act',{request,now_ms:request.encoded_at_ms});lastLedger=bridge.advanceFromReply(proposal.reply,{expectedModelSchema:MODEL});}
    await peer.rpc('step',lastLedger);physicalThisProcess++;
    if(stopAfterPhysicalSteps!==null&&physicalThisProcess>=stopAfterPhysicalSteps&&!env.done){
     save(path.join(runRoot,'partial-episode.json'),{software_preflight:true,summary:bridge.summary(),last_ledger:lastLedger,uncommitted_seed:env.seed});
     const partial=await peer.rpc('status',{});status({phase:'interrupted_for_software_preflight',committed_episodes:partial.cursor.next_episode_index,uncommitted_seed:env.seed});
     return{phase:'interrupted_for_software_preflight',state:partial,uncommitted_seed:env.seed};
    }
   }
   const result=bridge.summary();await peer.rpc('commit',result);state=await peer.rpc('status',{});
   status({phase:'episode_committed',committed_episodes:state.cursor.next_episode_index,last_seed:env.seed,last_result:result,updates:state.updates,replay_records:state.replay_records});
  }
  const final=await peer.rpc('fingerprint',{});
  const phase=software?'software_integration_complete':'training_complete_needs_validation_review';status({phase,committed_episodes:state.cursor.next_episode_index,updates:state.updates,replay_records:state.replay_records,state_fingerprint:final.state_sha256});
  return{phase,state:final.status,state_fingerprint:final.state_sha256};
 }catch(error){
  if(bridge&&lastLedger)save(path.join(runRoot,'partial-episode.json'),{summary:bridge.summary(),last_ledger:lastLedger,uncommitted_seed:bridge.env.seed});
  status({phase:'needs_repair',failed_phase:'runtime_episode_or_commit',error:String(error.message).slice(0,1500)});throw error;
 }finally{
  if(peer){await peer.close({abortUncommitted:true});fs.writeFileSync(path.join(runRoot,'python-stderr.log'),peer.stderr);}
 }
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const [operation,protocolPath,runRoot,...extra]=process.argv.slice(2);
 if(!['initialize','resume'].includes(operation)||!protocolPath||!runRoot||extra.length)throw Error('Use initialize|resume <frozen-protocol.json> <dedicated-run-root>');
 console.log(JSON.stringify(await runNavigationLearning({protocolPath,runRoot,operation})));
}
