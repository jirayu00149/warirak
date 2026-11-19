// Run against LOCAL Wrangler only. Fixtures never go to production.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import assert from 'node:assert/strict';
import {hashPassword} from '../backend/password.mjs';
const require=createRequire('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1112-737-0_26.1112.737.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright/package.json');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:4176',dir='tmp/yolo-camera-qa';
const token='wr_'+crypto.randomBytes(32).toString('hex'),password='qa-'+crypto.randomUUID();
const device='qa-yolo-camera',other='qa-yolo-empty',digest=crypto.createHash('sha256').update(token).digest('hex');
function sql(text){const file=path.resolve(dir,'local.sql');fs.writeFileSync(file,text);const r=spawnSync(process.execPath,['node_modules/wrangler/bin/wrangler.js','d1','execute','DB','--local','--config','wrangler.jsonc','--persist-to','tmp/live-camera-state','--file',file],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);fs.unlinkSync(file);}
sql(`INSERT OR REPLACE INTO devices VALUES('owner','${device}','เรือทดสอบ YOLO · ข้อมูลจำลอง QA','${digest}',${Date.now()},NULL);
INSERT OR REPLACE INTO devices VALUES('owner','${other}','เรือทดสอบไม่มีภาพ','qa-no-token',${Date.now()-1},NULL);
UPDATE auth_users SET username='qa-camera',access_key_hash='${await hashPassword(password)}' WHERE id='owner';`);
const raw=fs.readFileSync(dir+'/frame.jpg');
const makeMetadata=()=>({schema:'warirak.yolo-frame.v1',model:'public-v4-2026-10-28',image_size:[640,480],
  captured_at:new Date().toISOString(),latency_ms:190,detections:[
    {class_id:0,class_name:'plastic_bottle',confidence:.88,xyxy:[185,90,295,355]},
    {class_id:1,class_name:'bottle_cap',confidence:.72,xyxy:[395,295,435,335]}],total_detected:2,collection_confirmed:false,control_enabled:false});
function jpeg(meta){if(!meta)return raw;const payload=Buffer.from('WARIRAK-YOLO\0'+JSON.stringify(meta));return Buffer.concat([raw.subarray(0,2),Buffer.from([255,239,(payload.length+2)>>8,(payload.length+2)&255]),payload,raw.subarray(2)]);}
const browser=await chromium.launch({headless:true,channel:'chrome'});
let page,errors=[];
try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});page=await context.newPage();
 page.on('pageerror',e=>errors.push(e.message));
 const snapshot=await context.request.post(origin+'/api/device/frame',{headers:{Authorization:'Bearer '+token,'Content-Type':'image/jpeg','X-Frame-Id':'qa-'+Date.now(),'X-Captured-At':new Date().toISOString()},data:jpeg(makeMetadata())});assert.equal(snapshot.status(),200);
 await page.goto(origin+'/monitor?boat='+device);await page.waitForFunction(()=>document.querySelector('[data-yolo-title]')?.textContent==='ตรวจพบ 2 ชิ้นในภาพ');
 assert.match(await page.locator('[data-yolo-items]').innerText(),/ขวดพลาสติก 1 ชิ้น/);
 const collected=await page.locator('#live-collected').innerText();
 await page.locator('.camera-card').screenshot({path:dir+'/desktop.png'});
 await page.setViewportSize({width:390,height:844});
 await page.locator('.camera-card').screenshot({path:dir+'/mobile.png'});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.waitForFunction(()=>document.querySelector('#yolo-results')?.dataset.state==='stale',{},{timeout:25000});
 assert.match(await page.locator('[data-yolo-title]').innerText(),/ภาพล่าสุด/);
 // A newer empty prediction clears the previous detections.
 const empty={...makeMetadata(),detections:[],total_detected:0};
 const upload=await context.request.post(origin+'/api/device/frame',{headers:{Authorization:'Bearer '+token,'Content-Type':'image/jpeg','X-Frame-Id':'qa-empty-'+Date.now(),'X-Captured-At':new Date().toISOString()},data:jpeg(empty)});assert.equal(upload.status(),200);
 await page.evaluate(()=>window.__warirakPortal.refresh());
 await page.waitForFunction(()=>document.querySelector('[data-yolo-title]')?.textContent==='ไม่พบขยะเป้าหมายในภาพนี้');
 assert.equal(await page.locator('[data-yolo-items] li').count(),0);
 assert.equal(await page.locator('#live-collected').innerText(),collected);
 await page.locator('#boat-select').selectOption(other);
 await page.waitForFunction(()=>document.querySelector('[data-yolo-title]')?.textContent==='รอภาพพร้อมผลตรวจจับ');
 await page.goto(origin+'/login');await page.locator('#login-username').fill('qa-camera');await page.locator('#login-key').fill(password);await page.locator('#login-submit').click();await page.waitForURL('**/admin**');
 await page.goto(origin+'/admin#system');await page.locator('#iphone-camera-setup summary').click();
 assert.equal(await page.locator('a[href="#users"]').count(),0);
 assert.match(await page.locator('#iphone-camera-setup').innerText(),/YOLO/);
 for(const file of ['phone_camera.py','detection_frame.py','install_yolo_camera.sh']){
   const r=await context.request.get(origin+'/assets/pi/'+file);assert.equal(r.status(),200);
   assert.ok((await r.body()).equals(fs.readFileSync('frontend/assets/pi/'+file)));
 }
 assert.deepEqual(errors,[]);
 fs.writeFileSync(dir+'/result.json',JSON.stringify({passed:true,localOnly:true,checks:['HTTP snapshot metadata','Thai class names/confidence','desktop/mobile layout','stale frame warning','no-target reset','device switch reset','collection count unchanged','admin guide','published Pi downloads'],pageErrors:errors},null,2));
 console.log('YOLO camera integration passed: HTTP, stale/empty/device switch, collection isolation, mobile/admin/downloads.');
}catch(error){
 console.error(JSON.stringify({errors,page:page?await page.evaluate(()=>({image:window.__warirakPortal?.image,state:document.querySelector('#camera-state')?.textContent,visible:!document.hidden})):null}));
 if(page)await page.screenshot({path:dir+'/failure.png'});
 throw error;
}finally{await browser.close();sql(`DELETE FROM camera_frames WHERE device_id IN ('${device}','${other}'); DELETE FROM devices WHERE id IN ('${device}','${other}');`);}
