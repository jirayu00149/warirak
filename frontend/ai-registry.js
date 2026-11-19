const $=s=>document.querySelector(s);let pending=null,last=null,lastAt=0;
export function loadAiRegistry(force=false){
 if(!force&&last&&Date.now()-lastAt<15000)return Promise.resolve(last);
 if(pending)return pending;
 pending=fetch('/api/ai/registry',{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(10000)}).then(async r=>{if(!r.ok)throw Error('ยังโหลดทะเบียน AI จากฐานข้อมูลไม่ได้');const value=await r.json();if(value.schema!=='warirak.ai-registry.v1'||!Array.isArray(value.runs)||!Array.isArray(value.datasets))throw Error('ข้อมูลทะเบียน AI ไม่ถูกต้อง');last=value;lastAt=Date.now();return value;}).finally(()=>pending=null);return pending;
}
const labels={preparing:'กำลังเตรียมข้อมูล',training:'กำลังฝึกบน GPU',validating:'กำลังประเมินด้วย validation',exporting:'กำลังตรวจชุด NCNN',completed:'ฝึกเสร็จแล้ว',retained_baseline:'คงโมเดลเดิมตามผล validation',failed:'ต้องตรวจสอบงานฝึก'};
function time(ms){return new Date(ms).toLocaleString('th-TH',{timeZone:'Asia/Bangkok',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});}
export function initAiRegistry(){
 if(!$('#ai-registry-panel'))return;let busy=false;
 async function refresh(){if(busy||document.hidden)return;busy=true;$('#ai-registry-refresh').disabled=true;
  try{const data=await loadAiRegistry(true),run=data.runs[0];$('#ai-database-state').textContent='เชื่อมต่อ Cloudflare D1 แล้ว';$('#ai-database-state').dataset.state='ready';$('#ai-registry-note').textContent='ประวัติการฝึกและรุ่นโมเดลบันทึกในฐานข้อมูล · ภาพฝึกเก็บแยกจาก D1';
   $('#ai-current-release').textContent=data.current_release?.id||'ยังไม่มีรุ่นที่เผยแพร่';$('#ai-training-title').textContent=run?labels[run.status]||run.status:'ยังไม่มีงานฝึก';
   const finished=!!run&&['completed','retained_baseline'].includes(run.status),terminal=finished||run?.status==='failed';$('#ai-training-progress').max=run?.total_epochs||1;$('#ai-training-progress').value=finished?run.total_epochs:run?.epoch||0;$('#ai-training-progress').setAttribute('aria-valuetext',run?`${finished?'งานเสร็จแล้ว ':''}ฝึก ${run.epoch} จากสูงสุด ${run.total_epochs} รอบ`:'ยังไม่มีงานฝึก');$('#ai-training-count').textContent=run?`${run.id} · ${finished?'จบแล้ว ':''}${run.epoch} รอบ / สูงสุด ${run.total_epochs} รอบ`:'รอเริ่มงานฝึก';
   $('#ai-training-updated').textContent=run?`อัปเดต ${time(run.updated_at_ms)}${!terminal&&Date.now()-run.updated_at_ms>20*60000?' · สถานะยังไม่ได้อัปเดตล่าสุด':''}`:'';
   $('#ai-training-review').hidden=!run?.details?.pending_review;
   let outcome=$('#ai-training-outcome');if(!outcome){outcome=document.createElement('p');outcome.id='ai-training-outcome';$('#ai-training-review').after(outcome);}const comparison=run?.details?.validation_comparison;outcome.hidden=!comparison;outcome.textContent=comparison?`validation mAP50–95: รุ่นเดิม ${(comparison.baseline_map50_95*100).toFixed(2)}% · รุ่นทดลอง ${(comparison.candidate_map50_95*100).toFixed(2)}%${run.status==='retained_baseline'?' · คงรุ่นเดิมเพื่อรักษาผลทั้งสองคลาส':''}`:'';
   let reportLink=$('#ai-training-report');if(!reportLink){reportLink=document.createElement('a');reportLink.id='ai-training-report';reportLink.className='text-button';reportLink.textContent='ดาวน์โหลดผลการทดลอง (JSON) ↓';reportLink.download='training-outcome.json';reportLink.style.display='inline-block';reportLink.style.marginTop='10px';outcome.after(reportLink);}const reportPath=run?.details?.outcome_report;reportLink.hidden=typeof reportPath!=='string'||!/^\/assets\/models\/[a-zA-Z0-9._-]+$/.test(reportPath);if(!reportLink.hidden)reportLink.href=reportPath;
   const body=$('#ai-datasets-body');body.replaceChildren();for(const d of data.datasets){const row=document.createElement('tr');for(const value of[d.name,d.status==='ready'?d.image_count.toLocaleString('th-TH'):'กำลังเตรียม',`${d.train_count} / ${d.val_count} / ${d.test_count}`]){const td=document.createElement('td');td.textContent=value;row.append(td);}body.append(row);}
  }catch(error){$('#ai-database-state').textContent='ยังโหลดทะเบียน AI ไม่ได้';$('#ai-database-state').dataset.state='error';$('#ai-registry-note').textContent='กดรีเฟรชเพื่อลองเชื่อมต่ออีกครั้ง โมเดลที่เผยแพร่แล้วยังดาวน์โหลดได้ตามเดิม';}
  finally{busy=false;$('#ai-registry-refresh').disabled=false;}
 }
 $('#ai-registry-refresh').addEventListener('click',refresh);window.addEventListener('hashchange',()=>{if(location.hash==='#training')refresh();});document.addEventListener('visibilitychange',()=>{if(!document.hidden&&location.hash==='#training')refresh();});setInterval(()=>{if(location.hash==='#training')refresh();},30000);refresh();
}
