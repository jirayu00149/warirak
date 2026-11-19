import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {acceptInferenceReply,NavigationInferenceClient,VALIDATION_MODEL_SCHEMA} from '../ai/navigation_inference_wire.mjs';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const fixtures=JSON.parse(fs.readFileSync(new URL('./fixtures/navigation-dqn-vectors.json',import.meta.url)));
const python=process.env.WARIRAK_TRAINING_PYTHON??'C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350/work/warirak_training_runtime/Scripts/python.exe';
const wrap=r=>({request:r,now_ms:r.encoded_at_ms+1});
const opts=nowMs=>({nowMs,expectedModelSchema:VALIDATION_MODEL_SCHEMA,allowValidationFixture:true});
function runStream(messages){return new Promise((resolve,reject)=>{
 const child=spawn(python,['-X','utf8','-m','warirak_ai.navigation_dqn_stream','--preflight-stream'],{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'ai')},stdio:['pipe','pipe','pipe']});
 let stdout='',stderr='';
 const timer=setTimeout(()=>{child.kill();reject(Error('Bounded software stream timed out'));},30000);
 child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
 child.stdout.on('data',s=>{stdout+=s;if(stdout.length>1024*1024)child.kill();});
 child.stderr.on('data',s=>{stderr+=s;});
 child.on('error',e=>{clearTimeout(timer);reject(e);});
 child.stdin.on('error',()=>{});
 child.on('close',code=>{clearTimeout(timer);resolve({code,stdout,stderr,rows:stdout.trim()?stdout.trim().split('\n').map(s=>JSON.parse(s)):[]});});
 child.stdin.end(messages.map(m=>JSON.stringify(m)+'\n').join(''));
});}
test('Persistent Node→Python CPU forward stream preserves original request bindings and masks',async()=>{
 const requests=fixtures.requests.slice(0,3),r=await runStream(requests.map(wrap));
 assert.equal(r.code,0,r.stderr);assert.equal(r.rows.length,3);
 for(let i=0;i<3;i++){
  const item=r.rows[i];assert.equal(item.ok,true);assert.equal(item.fixture_only,true);assert.equal(item.trained_model_loaded,false);assert.equal(item.optimizer_steps,0);
  assert.throws(()=>acceptInferenceReply(item.reply,requests[i],{nowMs:requests[i].encoded_at_ms+2,expectedModelSchema:VALIDATION_MODEL_SCHEMA}));
  const p=acceptInferenceReply(item.reply,requests[i],opts(requests[i].encoded_at_ms+2));
  assert.equal(requests[i].allowed_mask[p.action],true);assert.equal(p.physical_motor_transport,false);
 }
});
test('A valid Python response arriving after cancellation or original deadline stays unusable',async()=>{
 const base=fixtures.requests[0],client=new NavigationInferenceClient('stream-cancel');
 const encoded={...base,schema:'warirak.navigation-history-vector.v1',command_authorization:false};
 const request=client.issue(encoded);client.cancel(request.encoded_at_ms+2);
 const r=await runStream([wrap(request)]);assert.equal(r.code,0,r.stderr);
 assert.throws(()=>client.receive(r.rows[0].reply,opts(request.encoded_at_ms+3)));
 assert.throws(()=>acceptInferenceReply(r.rows[0].reply,request,opts(request.valid_until_ms)));
 assert.equal(client.snapshot().commands_generated,0);
});
test('Duplicate stream identity fails closed and produces no later proposal',async()=>{
 const r=await runStream([wrap(fixtures.requests[0]),wrap(fixtures.requests[0]),wrap(fixtures.requests[1])]);
 assert.equal(r.code,2);assert.equal(r.rows.length,2);assert.equal(r.rows[0].ok,true);assert.equal(r.rows[1].ok,false);
 assert.equal(Object.hasOwn(r.rows[1],'reply'),false);
});
test('Expired simulation frames are rejected before a model reply',async()=>{
 const request=fixtures.requests[0],r=await runStream([{request,now_ms:request.valid_until_ms}]);
 assert.equal(r.code,2);assert.equal(r.rows.length,1);assert.equal(r.rows[0].ok,false);assert.equal(Object.hasOwn(r.rows[0],'reply'),false);
});
