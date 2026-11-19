export const CLASSES=['plastic_bottle','bottle_cap'];
export const CLASS_NAMES_TH=['ขวดพลาสติก','ฝาขวด'];
export const MAX_FILE_SIZE=20*1024*1024;
const TYPES={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'};
export function validBox(b){return Number.isInteger(b.class_id)&&b.class_id>=0&&b.class_id<2&&[b.x,b.y,b.w,b.h].every(Number.isFinite)&&b.x>=0&&b.y>=0&&b.w>0&&b.h>0&&b.x+b.w<=1.000001&&b.y+b.h<=1.000001;}
export function yoloLine(b){if(!validBox(b))throw Error('กรอบวัตถุอยู่นอกภาพหรือชนิดขยะไม่ถูกต้อง');return[b.class_id,b.x+b.w/2,b.y+b.h/2,b.w,b.h].map((x,i)=>i?x.toFixed(6):String(x)).join(' ');}
export async function hashBytes(bytes){return[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');}
export async function assignSplits(records,seed=42){
 const groups=[...new Set(records.map(r=>r.session_id.trim()))];if(groups.length<3)throw Error('ต้องมีอย่างน้อย 3 กลุ่มถ่ายภาพ จึงแยก train / val / test ได้');
 const sorted=await Promise.all(groups.map(async g=>[g,await hashBytes(new TextEncoder().encode(`${seed}:${g}`))]));sorted.sort((a,b)=>a[1].localeCompare(b[1]));
 const n=sorted.length,nVal=Math.max(1,Math.floor(n*.15+.5)),nTest=Math.max(1,Math.floor(n*.15+.5));
 const map={};sorted.forEach(([g],i)=>map[g]=i<nTest?'test':i<nTest+nVal?'val':'train');
 return map;
}
export async function datasetHealth(records){
 const reviewed=records.filter(r=>r.reviewed),groups=new Set(records.map(r=>r.session_id)).size,instances=[0,0],errors=[],warnings=[];
 const splitCounts={train:0,val:0,test:0},splitClasses={train:[0,0],val:[0,0],test:[0,0]};let splits=null;
 for(const r of records){for(const b of r.boxes||[])if(validBox(b))instances[b.class_id]++;}
 if(!records.length)errors.push('ยังไม่มีภาพจริง เริ่มนำเข้าภาพหรือเปิดกล้องได้เลย');
 if(records.length!==reviewed.length)errors.push(`ยังไม่ตรวจทาน ${records.length-reviewed.length} ภาพ`);
 if(groups<3)errors.push('ต้องมีอย่างน้อย 3 กลุ่มถ่ายภาพ และมีทั้งขวดกับฝาขวดในแต่ละชุดที่แยกได้');
 const hashes=new Set();for(const r of records){
  if(hashes.has(r.sha256))errors.push('พบไฟล์ภาพซ้ำ ต้องลบภาพซ้ำก่อนส่งออก');hashes.add(r.sha256);
  if(!r.session_id?.trim())errors.push('ทุกภาพต้องระบุกลุ่มถ่ายภาพ');
  if((r.boxes||[]).some(b=>!validBox(b)))errors.push(`กรอบไม่ถูกต้องในภาพ ${r.filename}`);
  if(r.reviewed&&!r.boxes.length&&!r.negative)errors.push(`ภาพ ${r.filename} ไม่มีกรอบและยังไม่ยืนยันว่าไม่มีขยะ`);
  if(r.negative&&r.boxes.length)errors.push(`ภาพ ${r.filename} ระบุว่าไม่มีขยะแต่มีกรอบ`);
 }
 if(groups>=3&&records.every(r=>r.session_id?.trim())){
  splits=await assignSplits(records);for(const r of records){const s=splits[r.session_id];splitCounts[s]++;for(const b of r.boxes||[])if(validBox(b))splitClasses[s][b.class_id]++;}
  for(const s of['train','val','test'])for(let k=0;k<2;k++)if(!splitClasses[s][k])errors.push(`ชุด ${s} ยังไม่มีตัวอย่าง ${CLASS_NAMES_TH[k]} ให้เพิ่มหรือจัดกลุ่มภาพให้ครอบคลุม`);
 }
 if(records.length&&records.length<1000)warnings.push('จำนวนภาพยังน้อยสำหรับงานภาคสนาม ควรเพิ่มภาพจากหลายวันและสภาพแสง');
 const tiny=records.reduce((n,r)=>n+r.boxes.filter(b=>Math.min(b.w*r.width,b.h*r.height)<8).length,0);if(tiny)warnings.push(`มีกรอบวัตถุเล็กกว่า 8 พิกเซล ${tiny} กรอบ ควรทบทวนระยะกล้องและความละเอียด`);
 const negatives=records.filter(r=>r.negative&&r.reviewed).length;if(records.length&&negatives/records.length<.15)warnings.push('ควรเพิ่มภาพไม่มีขยะ เช่น คลื่น ใบไม้ และเงาสะท้อน เพื่อลดการตรวจผิด');
 return{total:records.length,reviewed:reviewed.length,groups,instances,negatives,errors:[...new Set(errors)],warnings,splits,splitCounts,splitClasses};
}
export class DatasetStore{
 async open(){this.db=await new Promise((resolve,reject)=>{const r=indexedDB.open('warirak-dataset-v1',1);r.onupgradeneeded=()=>{const s=r.result.createObjectStore('images',{keyPath:'id'});s.createIndex('sha256','sha256',{unique:true});};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});return this;}
 async list(){return this.request('readonly',s=>s.getAll()).then(a=>a.sort((x,y)=>y.created_at.localeCompare(x.created_at)));}
 request(mode,fn){return new Promise((resolve,reject)=>{const tx=this.db.transaction('images',mode),r=fn(tx.objectStore('images'));tx.oncomplete=()=>resolve(r.result);tx.onerror=()=>reject(tx.error||r.error);tx.onabort=()=>reject(tx.error||Error('บันทึกไม่สำเร็จ'));});}
 async put(record){return this.request('readwrite',s=>s.put(record));}
 async remove(id){return this.request('readwrite',s=>s.delete(id));}
 async add(file,sessionId){
  if(!TYPES[file.type])throw Error('รองรับ JPG, PNG และ WebP เท่านั้น');if(file.size>MAX_FILE_SIZE)throw Error('ภาพใหญ่เกิน 20 MB กรุณาเลือกไฟล์ขนาดเล็กลง');
  if(!sessionId.trim())throw Error('ระบุชื่อกลุ่มถ่ายภาพก่อนนำเข้า');
  const sha256=await hashBytes(await file.arrayBuffer());if(await this.request('readonly',s=>s.index('sha256').get(sha256)))return{duplicate:true};
  const bitmap=await createImageBitmap(file,{imageOrientation:'from-image'}),width=bitmap.width,height=bitmap.height;bitmap.close();
  if(width*height>25_000_000)throw Error('ภาพเกิน 25 ล้านพิกเซล กรุณาลดขนาดภาพก่อนนำเข้า');
  const record={id:crypto.randomUUID(),filename:file.name||'capture.jpg',extension:TYPES[file.type],mime:file.type,blob:file,sha256,width,height,session_id:sessionId.trim(),boxes:[],negative:false,reviewed:false,created_at:new Date().toISOString()};
  await this.put(record);return{record,duplicate:false};
 }
}
function metadata(r){const{blob,...rest}=r;return rest;}
function zipLibrary(){if(!globalThis.JSZip)throw Error('โหลดเครื่องมือ ZIP ไม่สำเร็จ กรุณารีเฟรชหน้า');return new JSZip();}
export async function projectZip(records){
 const z=zipLibrary();z.file('annotations.json',JSON.stringify({schema:'warirak.project.v1',classes:CLASSES,images:records.map(r=>({...metadata(r),file:`images/${r.id}.${r.extension}`}))},null,2));
 for(const r of records)z.file(`images/${r.id}.${r.extension}`,r.blob);
 return z.generateAsync({type:'blob',compression:'STORE',streamFiles:true});
}
export async function yoloZip(records){
 const health=await datasetHealth(records);if(health.errors.length)throw Error(health.errors[0]);const z=zipLibrary(),images=[];
 for(const r of records){const split=health.splits[r.session_id],filename=`${r.id}.${r.extension}`,file=`images/${split}/${filename}`;
  z.file(file,r.blob);z.file(`labels/${split}/${r.id}.txt`,r.boxes.map(yoloLine).join('\n')+(r.boxes.length?'\n':''));images.push({...metadata(r),file,split});
 }
 z.file('data.yaml','path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: plastic_bottle\n  1: bottle_cap\n');
 z.file('manifest.json',JSON.stringify({schema:'warirak.dataset.v1',classes:CLASSES,split_strategy:'capture_session_sha256_seed42',seed:42,group_splits:health.splits,images},null,2));
 z.file('README_TH.txt','ชุดข้อมูลภาพจริงของผู้จัดทำ แยกกลุ่มถ่ายภาพก่อนแบ่ง train/val/test\nไม่ใช่โมเดลที่ฝึกแล้ว ตรวจด้วย python -m warirak_ai.dataset validate --data <โฟลเดอร์นี้> ก่อนฝึก\nสคริปต์ฝึกจะปรับ path ใน data.yaml ให้เป็น absolute ตามเครื่องโดยอัตโนมัติ\n');
 return z.generateAsync({type:'blob',compression:'STORE',streamFiles:true});
}
export async function importProject(file,store){
 if(file.size>250*1024*1024)throw Error('โปรเจกต์ใหญ่เกิน 250 MB ให้แยกนำเข้าเป็นชุดย่อย');
 const z=await JSZip.loadAsync(file),a=z.file('annotations.json');if(!a)throw Error('ไม่พบ annotations.json ในไฟล์โปรเจกต์');
 const raw=await a.async('string');if(raw.length>5_000_000)throw Error('ไฟล์ป้ายกำกับใหญ่เกินกำหนด');const meta=JSON.parse(raw);
 if(meta.schema!=='warirak.project.v1'||JSON.stringify(meta.classes)!==JSON.stringify(CLASSES)||!Array.isArray(meta.images)||meta.images.length>2000)throw Error('รูปแบบโปรเจกต์หรือรายการคลาสไม่ถูกต้อง');
 let added=0,duplicates=0;
 for(const r of meta.images){
  if(typeof r.id!=='string'||!r.id.match(/^[a-zA-Z0-9-]{1,80}$/)||!['jpg','png','webp'].includes(r.extension)||r.file!==`images/${r.id}.${r.extension}`||!r.session_id?.trim()||!Array.isArray(r.boxes)||r.boxes.some(b=>!validBox(b)))throw Error('ข้อมูลภาพหรือป้ายกำกับไม่ถูกต้อง');
  const entry=z.file(r.file);if(!entry||entry._data?.uncompressedSize>MAX_FILE_SIZE)throw Error('ไฟล์ภาพหายหรือใหญ่เกินกำหนด');const blob=await entry.async('blob');if(blob.size>MAX_FILE_SIZE)throw Error('ภาพใหญ่เกิน 20 MB');
  const mime={'jpg':'image/jpeg','png':'image/png','webp':'image/webp'}[r.extension],typed=new File([blob],r.filename||r.id,{type:mime});const result=await store.add(typed,r.session_id);
  if(result.duplicate){duplicates++;continue;}const clean=result.record;
  if(clean.sha256!==r.sha256||clean.width!==r.width||clean.height!==r.height){await store.remove(clean.id);throw Error('ภาพไม่ตรงกับ hash หรือขนาดที่บันทึกไว้');}
  clean.boxes=r.boxes.map(b=>({id:crypto.randomUUID(),class_id:b.class_id,x:b.x,y:b.y,w:b.w,h:b.h}));clean.negative=!!r.negative;clean.reviewed=!!r.reviewed;
  if(clean.negative&&clean.boxes.length||clean.reviewed&&!clean.negative&&!clean.boxes.length){await store.remove(clean.id);throw Error('สถานะตรวจทานไม่สอดคล้องกับป้ายกำกับ');}
  await store.put(clean);added++;
 }
 return{added,duplicates};
}
