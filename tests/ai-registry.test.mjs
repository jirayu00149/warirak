import test from'node:test';import assert from'node:assert/strict';import fs from'node:fs';import{SQLiteDatabase}from'../backend/sqlite.mjs';import{handleApi}from'../backend/api.mjs';
function setup(){const db=new SQLiteDatabase();const dir=new URL('../migrations/',import.meta.url);for(const name of fs.readdirSync(dir).filter(x=>x.endsWith('.sql')).sort())db.sqlite.exec(fs.readFileSync(new URL(name,dir),'utf8'));return db;}
const request=(db,userId)=>handleApi(new Request('https://test.invalid/api/ai/registry'),{db,userId,ownerUserId:'owner',publicMonitorEnabled:true});
test('AI registry is administrator-only and cannot expose a different workspace',async()=>{const db=setup();try{
 assert.equal((await request(db,null)).status,401);assert.equal((await request(db,'stranger')).status,403);
 for(const owner of ['owner','other'])db.sqlite.prepare('INSERT INTO ai_datasets(owner_id,id,name,status,image_count,train_count,val_count,test_count,created_at_ms,updated_at_ms) VALUES(?,?,?,\'ready\',3,1,1,1,1,1)').run(owner,'dataset-'+owner,'Dataset '+owner);
 const response=await request(db,'owner');assert.equal(response.status,200);const data=await response.json();assert.equal(data.storage,'Cloudflare D1');assert.deepEqual(data.datasets.map(x=>x.id),['dataset-owner']);assert.equal(data.current_release,null);assert.deepEqual(data.runs,[]);
 }finally{db.close();}});
test('AI database rejects inconsistent counts, orphan runs and multiple active releases',()=>{const db=setup();try{
 assert.throws(()=>db.sqlite.prepare('INSERT INTO ai_datasets(owner_id,id,name,status,image_count,created_at_ms,updated_at_ms) VALUES(\'owner\',\'bad\',\'Bad\',\'ready\',4,1,1)').run());
 assert.throws(()=>db.sqlite.prepare('INSERT INTO ai_training_runs(owner_id,id,dataset_id,status,total_epochs,started_at_ms,updated_at_ms) VALUES(\'owner\',\'orphan\',\'missing\',\'training\',10,1,1)').run());
 db.sqlite.exec("INSERT INTO ai_datasets(owner_id,id,name,status,created_at_ms,updated_at_ms) VALUES('owner','data','Data','ready',1,1); INSERT INTO ai_training_runs(owner_id,id,dataset_id,status,total_epochs,started_at_ms,updated_at_ms) VALUES('owner','run','data','training',10,1,1)");
 const insert=db.sqlite.prepare("INSERT INTO ai_model_releases(owner_id,id,run_id,weights_sha256,input_size,release_json,evaluation_json,active,published_at_ms) VALUES('owner',?,'run',?,800,'{}','{}',1,1)");insert.run('one','a'.repeat(64));assert.throws(()=>insert.run('two','b'.repeat(64)));
 }finally{db.close();}});
