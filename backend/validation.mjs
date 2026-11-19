export class ApiError extends Error{constructor(status,code,message){super(message);this.status=status;this.code=code;}}
export function fail(status,code,message){throw new ApiError(status,code,message);}
export function text(value,name,max=120){if(typeof value!=='string'||!value.trim()||value.length>max)fail(400,'invalid_input',`${name} ไม่ถูกต้อง`);return value.trim();}
export function id(value,name='id'){const v=text(value,name,180);if(!/^[\w:.-]+$/.test(v))fail(400,'invalid_id',`${name} ใช้ได้เฉพาะตัวอักษรอังกฤษ ตัวเลข : . - _`);return v;}
export function integer(value,name,min=0,max=1e9){if(!Number.isSafeInteger(value)||value<min||value>max)fail(400,'invalid_input',`${name} ไม่ถูกต้อง`);return value;}
export function timestamp(value,name='occurred_at'){const n=typeof value==='number'?value:Date.parse(value);if(!Number.isFinite(n)||n<Date.UTC(2020,0,1)||n>Date.now()+300000)fail(400,'invalid_timestamp',`${name} ไม่ถูกต้องหรืออยู่ในอนาคต`);return Math.floor(n);}
export function reportDays(value=7){const days=typeof value==='string'&&/^(7|30|90)$/.test(value)?Number(value):value;if(![7,30,90].includes(days))fail(400,'invalid_period','เลือกช่วงรายงาน 7, 30 หรือ 90 วัน');return days;}
export function bangkokRange(date,days=7){reportDays(days);if(typeof date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(date))fail(400,'invalid_date','วันที่ต้องเป็น YYYY-MM-DD');const midnight=Date.parse(date+'T00:00:00+07:00');if(!Number.isFinite(midnight)||new Date(midnight+7*3600000).toISOString().slice(0,10)!==date)fail(400,'invalid_date','วันที่ไม่มีอยู่จริง');return{start:midnight-(days-1)*86400000,end:midnight+86400000};}
export function source(value){if(!['simulation','hardware'].includes(value))fail(400,'invalid_source','ต้องระบุ simulation หรือ hardware');return value;}
export function collection(input,missionId,sourceValue='simulation',deviceId=null){
 if(!input||typeof input!=='object'||input.type&&input.type!=='collected'||input.collection_confirmed===false)fail(400,'not_confirmed','รับเฉพาะเหตุการณ์ยืนยันเก็บแล้ว');
 const classId=input.class_id==null?null:integer(input.class_id,'class_id',0,1);
 return{id:id(input.id,'event_id'),mission_id:id(missionId,'mission_id'),source:sourceValue,device_id:deviceId,class_id:classId,occurred_at_ms:timestamp(input.occurred_at??input.occurred_at_ms),estimated:input.time_estimated===true?1:0};
}
export function simulationMission(input){
 if(!input||input.source!=='simulation')fail(400,'simulation_only','ช่องทางนี้รับเฉพาะข้อมูลจำลอง');
 const missionId=id(input.id,'mission_id');if(missionId.startsWith('HW:'))fail(400,'reserved_id','HW: สงวนสำหรับอุปกรณ์จริง');const states=['idle','running','paused','completed','stopped','interrupted','collision','timeout'];if(!states.includes(input.state))fail(400,'invalid_state','สถานะภารกิจไม่ถูกต้อง');
 const elapsed=integer(Math.round(input.elapsed_s||0),'elapsed_s',0,86400),started=timestamp(input.started_at,'started_at');
 if(!Array.isArray(input.events)||input.events.length>1000)fail(400,'invalid_events','จำนวนเหตุการณ์ไม่ถูกต้อง');
 const events=input.events.flatMap((event,index)=>event.type==='collected'?[collection({...event,id:event.id||`${missionId}:${index}`,occurred_at:event.occurred_at||new Date(started+(event.time_s||0)*1000).toISOString(),time_estimated:!event.occurred_at},missionId)]:[]);
 const revision=timestamp(input.client_updated_at||input.ended_at||Math.max(started,...events.map(e=>e.occurred_at_ms)),'client_updated_at');
 return{id:missionId,source:'simulation',device_id:null,started_at_ms:started,updated_at_ms:revision,scenario:text(input.scenario||'imported','scenario',40),state:input.state,elapsed_s:elapsed,detected_count:integer(input.detected_count||0,'detected_count',0,1000000),events};
}
export async function digest(value){const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value));return[...new Uint8Array(bytes)].map(x=>x.toString(16).padStart(2,'0')).join('');}
export function token(){return'wr_'+[...crypto.getRandomValues(new Uint8Array(32))].map(x=>x.toString(16).padStart(2,'0')).join('');}
