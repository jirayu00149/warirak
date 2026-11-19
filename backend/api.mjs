import{Repository}from'./repository.mjs';
import{Access}from'./access.mjs';
import{Camera}from'./camera.mjs';
import{aiRegistry}from'./ai-registry.mjs';
import{overview}from'./overview.mjs';
import{telemetryObservation}from'./telemetry.mjs';
import{dayKey}from'../frontend/analytics.js';
import{APP_VERSION}from'../frontend/release.js';
import{ApiError,fail,text,id,timestamp,integer,source,reportDays,collection,simulationMission}from'./validation.mjs';
const headers={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
function json(value,status=200){return new Response(JSON.stringify(value),{status,headers});}
async function body(request){if(!request.headers.get('content-type')?.startsWith('application/json'))fail(415,'json_required','ต้องส่ง application/json');if(Number(request.headers.get('content-length')||0)>524288)fail(413,'too_large','ข้อมูลใหญ่เกิน 512 KB');const reader=request.body?.getReader();if(!reader)fail(400,'invalid_json','JSON ว่าง');let size=0,raw='';const decoder=new TextDecoder();while(true){const{value,done}=await reader.read();if(done)break;size+=value.byteLength;if(size>524288){await reader.cancel();fail(413,'too_large','ข้อมูลใหญ่เกิน 512 KB');}raw+=decoder.decode(value,{stream:true});}raw+=decoder.decode();try{return JSON.parse(raw);}catch{fail(400,'invalid_json','JSON ไม่ถูกต้อง');}}
function browserWrite(request){const origin=request.headers.get('origin');if(origin!==new URL(request.url).origin||request.headers.get('x-warirak-client')!=='dashboard'||['cross-site','same-site'].includes(request.headers.get('sec-fetch-site')))fail(403,'csrf_rejected','ไม่อนุญาตคำขอข้ามเว็บไซต์');}
export async function handleApi(request,{db,userId=null,storage='D1',ownerUserId=null,displayName='',publicMonitorEnabled=false}){
 try{
  const url=new URL(request.url),path=url.pathname,method=request.method;
  if(path==='/api/health'&&method==='GET'){if(!db)fail(503,'database_unavailable','ฐานข้อมูลยังไม่พร้อม');await db.prepare('SELECT 1').first();return json({ok:true,version:APP_VERSION,storage,authenticated:!!userId,configured:!!ownerUserId,public_monitor_enabled:publicMonitorEnabled,time_zone:'Asia/Bangkok',control_enabled:false});}
  if(!db)fail(503,'database_unavailable','ฐานข้อมูลยังไม่พร้อม');if(!ownerUserId)fail(503,'owner_not_configured','ยังไม่ได้กำหนดบัญชีผู้ดูแลระบบ');const repo=new Repository(db),access=new Access(db,ownerUserId),camera=new Camera(db);
  if(path==='/api/session'&&method==='GET')return json({...await access.session(userId,displayName),public_monitor_enabled:publicMonitorEnabled});
  if(path.startsWith('/api/device/')){
   if(method!=='POST')fail(405,'method_not_allowed','ต้องใช้ POST');const bearer=request.headers.get('authorization')?.match(/^Bearer (wr_[a-f0-9]{64})$/)?.[1];if(!bearer)fail(401,'device_token_required','ต้องระบุ Device bearer token');const device=await repo.authenticateDevice(bearer);if(device.owner_id!==ownerUserId)fail(403,'device_workspace_mismatch','อุปกรณ์นี้ไม่ได้อยู่ในระบบนี้');
   if(path==='/api/device/frame')return json(await camera.upload(device,request));
   const input=await body(request);
   if(path==='/api/device/telemetry'){
    return json(await repo.telemetry(device,telemetryObservation(input)));
   }
   if(path==='/api/device/collections'){
    if(input.collection_confirmed!==true||input.source&&input.source!=='hardware')fail(400,'confirmation_required','ต้องมี collection_confirmed=true จากเหตุยืนยันเก็บจริง');
    const missionId=`HW:${device.id}:${id(input.mission_id,'mission_id')}`,event=collection({...input,id:`HW:${device.id}:${id(input.event_id,'event_id')}`},missionId,'hardware',device.id);
    const m={id:missionId,source:'hardware',device_id:device.id,scenario:'hardware',state:'running',started_at_ms:event.occurred_at_ms,updated_at_ms:event.occurred_at_ms,elapsed_s:0,detected_count:0,events:[event]};return json(await repo.upsertMissions(device.owner_id,[m]),201);
   }
   fail(404,'not_found','ไม่พบ API นี้');
  }
  const session=await access.session(userId,displayName);
  if(path==='/api/monitor'&&method==='GET'){if(!publicMonitorEnabled)await access.member(session);const deviceId=url.searchParams.get('device_id')||null,devices=await camera.devices(ownerUserId),days=reportDays(url.searchParams.get('days')??7);if(deviceId&&!devices.some(d=>d.id===deviceId))fail(404,'device_not_found','ไม่พบเรือลำนี้');const data=await repo.dashboard(ownerUserId,url.searchParams.get('date')||dayKey(),'hardware',deviceId,days,true);return json({...data,devices,refresh_interval_ms:5000,selected_device_id:deviceId});}
  const frameMatch=path.match(/^\/api\/live\/devices\/([^/]+)\/frame\.jpg$/);if(frameMatch&&method==='GET'){if(!publicMonitorEnabled)await access.member(session);return await camera.frame(ownerUserId,id(decodeURIComponent(frameMatch[1])));}
  if(!userId)fail(401,'sign_in_required','กรุณาเข้าสู่ระบบก่อนใช้งานฐานข้อมูล');
  if(!['GET','HEAD'].includes(method))browserWrite(request);
  if(path==='/api/access/redeem'&&method==='POST'){const input=await body(request);return json(await access.redeem(userId,displayName,input.code));}
  await access.member(session);
  await access.member(session,true);
  if(path==='/api/overview'&&method==='GET')return json(await overview(db,ownerUserId));
  if(path==='/api/ai/registry'&&method==='GET')return json(await aiRegistry(db,ownerUserId));
  if(path==='/api/admin/members'&&method==='GET')return json({members:await access.members()});
  if(path==='/api/admin/invitations'&&method==='POST')return json(await access.invitation(),201);
  if(path.startsWith('/api/admin/members/')&&method==='PATCH')return json(await access.update(userId,id(decodeURIComponent(path.slice('/api/admin/members/'.length))),await body(request)));
  if(path==='/api/dashboard'&&method==='GET')return json(await repo.dashboard(ownerUserId,url.searchParams.get('date'),source(url.searchParams.get('source')||'simulation')));
  if(path==='/api/simulation/sync'&&method==='POST'){
   const input=await body(request);if(!Array.isArray(input.missions)||input.missions.length>50||!Array.isArray(input.collections||[])||(input.collections||[]).length>300)fail(400,'invalid_batch','ส่งภารกิจไม่เกิน 50 และเหตุการณ์ไม่เกิน 300 ต่อครั้ง');
   const missions=input.missions.map(simulationMission),extra=(input.collections||[]).map(e=>{if(e.source!=='simulation')fail(400,'simulation_only','ห้ามส่งข้อมูลจริงผ่านช่องทางจำลอง');return collection(e,e.mission_id);});return json(await repo.upsertMissions(ownerUserId,missions,extra));
  }
  if(path==='/api/devices'&&method==='GET')return json({devices:await repo.devices(ownerUserId)});
  if(path==='/api/devices'&&method==='POST'){const input=await body(request);return json(await repo.createDevice(ownerUserId,text(input.name,'name',80)),201);}
  if(path.startsWith('/api/devices/')&&method==='DELETE')return json(await repo.revoke(ownerUserId,id(decodeURIComponent(path.slice('/api/devices/'.length)))));
  fail(404,'not_found','ไม่พบ API นี้');
 }catch(error){if(error instanceof ApiError)return json({error:{code:error.code,message:error.message}},error.status);console.error('API failure',error?.message);return json({error:{code:'server_error',message:'บันทึกข้อมูลไม่สำเร็จ กรุณาลองใหม่'}},500);}
}
