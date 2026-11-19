import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {NavigationLearningPeer,runNavigationLearning,runtimeEnvironment,runtimeEpisodeIdentity} from '../ai/navigation_learning_runtime.mjs';
import {NavigationEpisodeBridge} from '../ai/navigation_episode_bridge.mjs';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))),work=fs.realpathSync(path.join(root,'work'));
const protocolPath=path.join(work,'navigation-runtime-preflight/protocol.json');
const protocol=JSON.parse(fs.readFileSync(protocolPath)),hash=createHash('sha256').update(fs.readFileSync(protocolPath)).digest('hex');
const scratch=()=>fs.mkdtempSync(path.join(work,'navigation-runtime-unit-'));
function cleanup(dir){const resolved=fs.realpathSync(dir);assert.equal(path.dirname(resolved),work);assert(path.basename(resolved).startsWith('navigation-runtime-unit-'));fs.rmSync(resolved,{recursive:true,force:false});}
function receipts(run){return fs.readdirSync(path.join(run,'checkpoints/outcomes')).filter(f=>/^episode-\d{8}\.json$/.test(f)).sort().map(f=>JSON.parse(fs.readFileSync(path.join(run,'checkpoints/outcomes',f))));}
test('Full Node/Python runtime commits two natural unit episodes with wait credit and protected snapshots',async()=>{
 const dir=scratch();try{
  const run=path.join(dir,'complete'),r=await runNavigationLearning({protocolPath,runRoot:run,operation:'initialize'});
  assert.equal(r.phase,'software_integration_complete');assert.equal(r.state.cursor.next_episode_index,2);assert.equal(r.state.cursor.environment_steps,8);assert.equal(r.state.actual_training,false);assert.equal(r.state.updates,0);
  const rows=receipts(run);assert.equal(rows.length,2);assert.equal(rows[0].result.duration_credits,1);assert.equal(rows[0].result.null_request_steps,1);
  assert(rows.every(x=>x.result.done&&x.result.all_physical_steps_accounted&&Math.abs(x.result.reward_conservation_error)<1e-7));
  for(const i of [1,2]){const folder=path.join(run,'snapshots','episode-'+String(i).padStart(6,'0')),m=JSON.parse(fs.readFileSync(path.join(folder,'snapshot.json')));assert.equal(m.episode,i);assert.equal(m.actual_training,false);assert.equal(createHash('sha256').update(fs.readFileSync(path.join(folder,'checkpoint.pt'))).digest('hex'),m.checkpoint_sha256);}
  assert.equal(fs.existsSync(path.join(run,'checkpoints.runtime.lock')),false);
 }finally{cleanup(dir);}
});
test('A new Python process restarts the same uncommitted seed and matches an uninterrupted full state',async()=>{
 const dir=scratch();try{
  const clean=path.join(dir,'clean'),interrupted=path.join(dir,'interrupted');
  const expected=await runNavigationLearning({protocolPath,runRoot:clean,operation:'initialize'});
  const first=await runNavigationLearning({protocolPath,runRoot:interrupted,operation:'initialize',stopAfterPhysicalSteps:6});
  assert.equal(first.phase,'interrupted_for_software_preflight');assert.equal(first.state.cursor.next_episode_index,1);assert.equal(first.uncommitted_seed,11501);
  const resumed=await runNavigationLearning({protocolPath,runRoot:interrupted,operation:'resume'});
  assert.equal(resumed.state_fingerprint,expected.state_fingerprint);assert.deepEqual(resumed.state,expected.state);
  assert.deepEqual(receipts(interrupted).map(x=>x.result),receipts(clean).map(x=>x.result));
 }finally{cleanup(dir);}
});
test('Malformed step fails closed without committing the partially advanced software episode',async()=>{
 const dir=scratch();let peer;
 try{
  peer=await NavigationLearningPeer.open({protocolPath,storePath:path.join(dir,'checkpoints'),operation:'initialize'});
  const env=runtimeEnvironment(protocol,0),bridge=new NavigationEpisodeBridge(env,runtimeEpisodeIdentity(hash,0));
  await peer.rpc('begin',{seed:env.seed,profile:env.profile,fixture_used:true,first_request:bridge.request()});
  const request=bridge.request(),p=await peer.rpc('act',{request,now_ms:request.encoded_at_ms});
  const ledger=bridge.advanceFromReply(p.reply,{expectedModelSchema:'warirak.navigation-history-duration-double-dqn.v1'});ledger.reward+=1;
  await assert.rejects(peer.rpc('step',ledger),/Changed R2 reward terms/);
  await peer.close({abortUncommitted:true});peer=null;
  const pointer=JSON.parse(fs.readFileSync(path.join(dir,'checkpoints/CURRENT.json'))),manifest=JSON.parse(fs.readFileSync(path.join(dir,'checkpoints',pointer.head.directory,'manifest.json')));
  assert.equal(manifest.cursor.next_episode_index,0);assert.equal(receipts(dir).length,0);
 }finally{if(peer)await peer.close({abortUncommitted:true});cleanup(dir);}
});
test('A healthy Python owner prevents a duplicate runtime from loading the same checkpoint store',async()=>{
 const dir=scratch();let peer;
 try{
  const storePath=path.join(dir,'checkpoints');peer=await NavigationLearningPeer.open({protocolPath,storePath,operation:'initialize'});
  await assert.rejects(NavigationLearningPeer.open({protocolPath,storePath,operation:'resume'}),/runtime.lock|FileExistsError/);
  const state=await peer.rpc('status',{});assert.equal(state.cursor.next_episode_index,0);
 }finally{if(peer)await peer.close({abortUncommitted:true});cleanup(dir);}
});
