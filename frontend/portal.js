import{piStatus,renderPiStatus}from'./pi-status.js';
import{dayKey}from'./analytics.js';
import{periodSummary,reportFilters,reportLink,reportCsv,validReportDate}from'./reporting.js';
import{watchCamera}from'./live-camera.js';
import{readDetections,renderDetections}from'./yolo-frame.js';
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const initial=reportFilters(location.search,dayKey());
let session=null,data=null,selectedId=initial.boat,reportDeviceId=initial.boat,image=null,imageUrl=null,busy=false,queued=false,failed=false,serverOffset=0,lastPoll=0,detailDate=initial.date,appliedKey='';
let stopCamera=null,streamDeviceId=null,ai=null,aiUrl=null,frameTimes=[];
const now=()=>Date.now()+serverOffset,isReports=()=>location.hash==='#reports';
const canView=()=>!!session&&(session.public_monitor_enabled||['admin','viewer'].includes(session.role));
function frameAgeText(seconds){
 if(seconds===null)return '—';
 if(seconds<60)return seconds+' วินาที';
 if(seconds<3600)return Math.floor(seconds/60)+' นาที';
 if(seconds<86400)return Math.floor(seconds/3600)+' ชม. '+Math.floor(seconds%3600/60)+' นาที';
 return Math.floor(seconds/86400)+' วัน '+Math.floor(seconds%86400/3600)+' ชม.';
}
const dateText=value=>new Date(value+'T12:00:00+07:00').toLocaleDateString('th-TH',{timeZone:'Asia/Bangkok',day:'numeric',month:'short',year:'numeric'});
function clock(value){return value?new Date(Number(value)).toLocaleString('th-TH',{timeZone:'Asia/Bangkok',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—';}
function feedback(message,databaseOkay=!message){$('#portal-error').textContent=message||'';$('#portal-error').hidden=!message;$('#portal-error-retry').hidden=!message;$('#public-database-state').textContent=databaseOkay?'เชื่อมต่อฐานข้อมูลแล้ว':'เชื่อมต่อข้อมูลขัดข้อง';$('#public-database-state').dataset.state=databaseOkay?'ready':'error';}
async function request(path){const response=await fetch(path,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000)});if(!response.ok){let message='เชื่อมต่อระบบไม่สำเร็จ',code='request_failed';try{const error=(await response.json()).error;message=error?.message||message;code=error?.code||code;}catch{}const e=Error(message);e.status=response.status;e.code=code;throw e;}return response;}
const json=async path=>(await request(path)).json();
function clearFrame(){if(imageUrl)URL.revokeObjectURL(imageUrl);imageUrl=null;image=null;$('#boat-camera').removeAttribute('src');$('#boat-camera').hidden=true;$('#camera-placeholder').hidden=false;$('#camera-stale-overlay').hidden=true;$('#expand-camera').disabled=true;$('#camera-full-image').removeAttribute('src');$('#camera-full-dialog').close();clearAi();frameTimes=[];renderDetections($('#yolo-results'),null,false,false);}
function clearAi(){if(aiUrl)URL.revokeObjectURL(aiUrl);aiUrl=null;ai=null;$('#yolo-image').removeAttribute('src');$('#yolo-figure').hidden=true;}
const device=()=>data?.devices.find(d=>d.id===selectedId)||null;
function filters(){return{date:isReports()?$('#report-date').value:dayKey(),days:isReports()?Number($('#report-period').value):7,boat:isReports()?reportDeviceId:selectedId};}
const queryKey=()=>JSON.stringify(filters());
function rememberReport(){const url=reportLink({date:$('#report-date').value,days:Number($('#report-period').value),boat:reportDeviceId},location.origin);history.replaceState(null,'',url);}
function showPage(){const reports=isReports();$('#user-monitor').hidden=reports;$('#user-reports').hidden=!reports;document.querySelectorAll('[data-user-nav]').forEach(a=>{const active=a.dataset.userNav===(reports?'reports':'monitor');a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});$('#report-next').disabled=$('#report-date').value>=dayKey();document.title=(reports?'รายงานการเก็บขยะ':'ติดตามเรือ')+' · วารีรักษ์';$('#portal-current-page').textContent=reports?'รายงานการเก็บขยะ':'ติดตามวารีรักษ์';syncCamera();if(canView())refresh();}
function renderAges(){renderPiStatus($('#pi-health'),device(),now());const d=device(),heartbeat=d?.heartbeat_received_at_ms,online=typeof heartbeat==='number'&&now()-heartbeat>=-5000&&now()-heartbeat<60000,age=image?Math.max(0,Math.floor((now()-image.received_at_ms)/1000)):null;
 $('#boat-state').textContent=online?'เรือส่งสถานะล่าสุด':heartbeat?'เรือออฟไลน์':'ยังไม่ได้รับสถานะเรือ';$('#boat-state').classList.toggle('online',!!online);$('#live-heartbeat').textContent=clock(heartbeat);$('#frame-age').textContent=frameAgeText(age);
 renderCamera(age);
}
function liveFps(){const t=performance.now();frameTimes=frameTimes.filter(x=>t-x<3000);return frameTimes.length>2?Math.round((frameTimes.length-1)/((t-frameTimes[0])/1000)):0;}
function renderCamera(age=image?Math.max(0,Math.floor((now()-image.received_at_ms)/1000)):null){
 const live=image?.live&&age<3,fresh=live||age!==null&&age<15&&!failed,fps=live?liveFps():0;
 $('#camera-dot').className='status-dot'+(fresh?' fresh':image?' stale':'');
 $('#camera-state').textContent=!image?'ยังไม่เชื่อมกล้อง':live?'ภาพสด':fresh?'ได้รับภาพล่าสุด':failed?'การเชื่อมต่อขาด · ภาพล่าสุด':'ภาพล่าช้า · รอภาพใหม่';
 $('#camera-clock').textContent=image?(live&&fps?`≈${fps} ภาพ/วินาที · `:'')+(image.live?'รับภาพเมื่อ ':'ภาพถ่ายเมื่อ ')+clock(image.captured_at_ms):'ไม่มีภาพ';
 $('#camera-stale-overlay').hidden=!image||fresh;
 // AI results are shown on their own frame, with that frame's own capture time.
 const meta=ai?.metadata,aiAge=meta?now()-Date.parse(meta.captured_at):Infinity,aiFresh=fresh&&aiAge>=-5000&&aiAge<15000;
 renderDetections($('#yolo-results'),meta,!!image,aiFresh);
 // AI boxes are drawn on the live view; the separate AI frame panel stays hidden.
 $('#yolo-figure').hidden=true;
 drawAiOverlay(fresh?meta:null,aiAge);
}
const AI_COLORS={plastic_bottle:'#22c55e',bottle_cap:'#f59e0b'},AI_NAMES={plastic_bottle:'ขวด',bottle_cap:'ฝาขวด'};
function drawAiOverlay(meta,ageMs){
 const canvas=$('#ai-overlay'),img=$('#boat-camera'),badge=$('#ai-badge');if(!canvas||!img)return;
 const box=canvas.parentElement.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
 canvas.width=Math.round(box.width*dpr);canvas.height=Math.round(box.height*dpr);
 const g=canvas.getContext('2d');g.clearRect(0,0,canvas.width,canvas.height);
 const show=meta&&!img.hidden&&img.naturalWidth&&ageMs>=-5000&&ageMs<3000;
 badge.hidden=!show;if(!show)return;
 // Map the AI frame's coordinates onto the live image drawn with object-fit: contain.
 const scale=Math.min(box.width/img.naturalWidth,box.height/img.naturalHeight),w=img.naturalWidth*scale,h=img.naturalHeight*scale,ox=(box.width-w)/2,oy=(box.height-h)/2;
 const [iw,ih]=meta.image_size||[img.naturalWidth,img.naturalHeight],sx=w/iw,sy=h/ih,alpha=ageMs<1500?1:Math.max(.25,1-(ageMs-1500)/1500);
 g.save();g.scale(dpr,dpr);g.globalAlpha=alpha;g.lineWidth=2;g.font='600 11px Noto,Tahoma,sans-serif';g.textBaseline='bottom';
 for(const d of meta.detections||[]){const[x1,y1,x2,y2]=d.xyxy,c=AI_COLORS[d.class_name]||'#22c55e',x=ox+x1*sx,y=oy+y1*sy,bw=(x2-x1)*sx,bh=(y2-y1)*sy,label=`${AI_NAMES[d.class_name]||d.class_name} ${Math.round(d.confidence*100)}%`;
  g.strokeStyle=c;g.strokeRect(x,y,bw,bh);const tw=g.measureText(label).width+8,ty=y>16?y:y+bh+16;g.fillStyle=c;g.fillRect(x-1,ty-16,tw,16);g.fillStyle='#0b1a14';g.fillText(label,x+3,ty-2);}
 g.restore();
 const counts={};for(const d of meta.detections||[])counts[d.class_name]=(counts[d.class_name]||0)+1;
 const parts=Object.entries(counts).map(([k,v])=>`${AI_NAMES[k]||k} ${v}`);
 badge.textContent=`AI · ${parts.length?parts.join(' · '):'ไม่พบขยะ'} · ${ageMs<1000?'ล่าสุด':(ageMs/1000).toFixed(1)+' วิที่แล้ว'}`;
}
addEventListener('resize',()=>renderCamera());
function renderDay(){if(!data)return;const row=data.daily.find(d=>d.date===detailDate)||data.daily.at(-1);if(!row)return;detailDate=row.date;$('#report-day-title').textContent=dateText(row.date);$('#report-day-values').textContent=`ยืนยันเก็บ ${row.total} ชิ้น · ขวด ${row.bottles} · ฝาขวด ${row.caps} · ไม่ระบุชนิด ${row.unknown}`;$('#user-daily-chart').querySelectorAll('button').forEach(b=>{const active=b.dataset.date===row.date;b.classList.toggle('selected',active);b.setAttribute('aria-pressed',String(active));});}
function render(){if(!data)return;const options=data.devices.map(d=>`<option value="${esc(d.id)}">${esc(d.name)}</option>`).join('');$('#boat-select').innerHTML=options||'<option value="">ยังไม่มีเรือในระบบ</option>';$('#boat-select').value=selectedId;$('#report-boat-select').innerHTML='<option value="">ทุกลำ</option>'+options;$('#report-boat-select').value=reportDeviceId;
 const d=device();$('#selected-boat-name').textContent=d?.name||'ยังไม่มีเรือ';$('#live-battery').textContent=piStatus(d,now()).battery;$('#live-state').textContent=({monitoring:'ส่งสถานะ Pi · ยังไม่ควบคุมเรือ',idle:'รอเริ่มงาน',standby:'พร้อมทำงาน',collecting:'กำลังเก็บขยะ',searching:'กำลังค้นหา',returning:'กำลังกลับ',paused:'หยุดพัก',stopped:'หยุดทำงาน',error:'พบปัญหา'})[d?.state]||(d?.state?'ไม่ระบุสถานะ':'—');
 const today=data.daily.find(x=>x.date===dayKey())||{total:0,bottles:0,caps:0};$('#live-collected').innerHTML=today.total+'<small>ชิ้น</small>';$('#overview-total').textContent=today.total;$('#overview-bottles').textContent=today.bottles;$('#overview-caps').textContent=today.caps;$('#live-collection-scope').textContent=d?'เฉพาะ '+d.name:'ยอดรวมทุกลำ';
 if(!image){$('#camera-empty-title').textContent=piStatus(d,now()).online?'Pi ออนไลน์แล้ว · รอเชื่อมกล้อง':d?'ยังไม่ได้รับภาพจากกล้องเรือ':'ยังไม่มีเรือในระบบ';$('#camera-empty-text').textContent=piStatus(d,now()).online?'สถานะเครื่องแสดงด้านล่าง เมื่อต่อกล้องและเปิดโปรแกรมส่งภาพ ภาพจะแสดงที่นี่':d?'เมื่อเรือส่งภาพเข้าระบบ ภาพจะแสดงที่นี่โดยอัตโนมัติ':'ผู้ดูแลสามารถเชื่อมอุปกรณ์ได้ หรือทดลองโหมดสาธิตระหว่างเตรียมเรือ';}
 const totals=periodSummary(data.daily),reportBoat=data.devices.find(b=>b.id===reportDeviceId);$('#report-date-title').textContent=`${dateText(data.daily[0].date)} – ${dateText(data.daily.at(-1).date)}`;$('#report-total').innerHTML=totals.total+'<small>ชิ้น</small>';$('#report-bottles').textContent=totals.bottles;$('#report-caps').textContent=totals.caps;$('#report-unknown').textContent=totals.unknown;$('#report-scope').textContent=(reportBoat?'เฉพาะ '+reportBoat.name:'ยอดรวมทุกลำ')+` · ${data.daily.length} วัน · ยืนยันเก็บแล้วเท่านั้น`;$('#report-period-summary').textContent=`${totals.missions} ภารกิจที่มีการเก็บสำเร็จ${totals.estimated?' · '+totals.estimated+' รายการใช้เวลาประมาณ':''}`;
 $('#report-next').disabled=$('#report-date').value>=dayKey();const chart=$('#user-daily-chart'),max=Math.max(1,...data.daily.map(x=>x.total));chart.style.setProperty('--chart-days',String(data.daily.length));chart.setAttribute('aria-label',`จำนวนขยะรายวัน ${data.daily.length} วัน`);chart.innerHTML=data.daily.map(x=>`<button type="button" data-date="${x.date}" aria-label="${x.date} ยืนยันเก็บ ${x.total} ชิ้น"><strong>${x.total}</strong><span style="height:${Math.max(3,x.total/max*110)}px"></span><small>${x.date.slice(8)}/${x.date.slice(5,7)}</small></button>`).join('');chart.querySelectorAll('button').forEach(b=>b.onclick=()=>{detailDate=b.dataset.date;renderDay();});renderDay();
 $('#user-history').innerHTML=data.missions.map(m=>`<tr><td>${esc(m.id)}</td><td>${clock(Date.parse(m.started_at))}</td><td>${m.confirmed_collected_count} ชิ้น</td><td>${esc(({running:'กำลังทำงาน',completed:'เสร็จสิ้น',stopped:'หยุดแล้ว'})[m.state]||m.state)}</td></tr>`).join('');$('#user-history-empty').hidden=data.missions.length>0;$('#report-mission-limit').textContent=`แสดงภารกิจที่อยู่ในช่วงเวลาที่เลือก ล่าสุดไม่เกิน ${data.missions_limit||100} รายการ · ยอดรวมด้านบนครอบคลุมเหตุการณ์ยืนยันเก็บทั้งหมดในช่วง`;$('#last-refreshed').textContent='อัปเดตข้อมูล '+clock(Date.parse(data.server_time));renderAges();
}
async function displayCameraFrame(blob, frame, active=()=>true){
 if(!blob.type.startsWith('image/jpeg'))throw Error('ข้อมูลภาพไม่ถูกต้อง');
 const nextUrl=URL.createObjectURL(blob),preview=new Image();
 preview.src=nextUrl;
 try{await preview.decode();}catch{URL.revokeObjectURL(nextUrl);throw Error('ไม่สามารถเปิดภาพจากกล้องได้');}
 frame.detections=await readDetections(blob);
 if(!active()||selectedId!==frame.device_id||isReports()||document.hidden){URL.revokeObjectURL(nextUrl);return;}
 if(frame.detections&&!(ai?.device_id===frame.device_id&&ai.received_at_ms>=frame.received_at_ms)){
   if(aiUrl)URL.revokeObjectURL(aiUrl);
   aiUrl=URL.createObjectURL(blob);ai={device_id:frame.device_id,received_at_ms:frame.received_at_ms,metadata:frame.detections};
   $('#yolo-image').src=aiUrl;
 }
 // While plain live frames are flowing, an AI frame (slower, older capture) stays in its
 // own panel so the live view never jumps back in time.
 const plainLive=image?.live&&!image.detections&&image.device_id===frame.device_id&&frame.received_at_ms-image.received_at_ms<1500;
 if(image?.device_id===frame.device_id&&image.received_at_ms>=frame.received_at_ms||frame.detections&&frame.live&&plainLive){
   URL.revokeObjectURL(nextUrl);return;
 }
 const previous=imageUrl;
 imageUrl=nextUrl;image=frame;
 if(frame.live)frameTimes.push(performance.now());
 $('#boat-camera').src=imageUrl;$('#boat-camera').hidden=false;$('#camera-placeholder').hidden=true;
 $('#expand-camera').disabled=false;
 if($('#camera-full-dialog').open)$('#camera-full-image').src=imageUrl;
 if(previous)URL.revokeObjectURL(previous);
}
function syncCamera(){
 const target=canView()&&!isReports()&&!document.hidden?device()?.id:null;
 if(target===streamDeviceId)return;
 stopCamera?.();stopCamera=null;streamDeviceId=target;
 if(target)stopCamera=watchCamera(target,async(blob,time,active)=>{
   await displayCameraFrame(blob,{device_id:target,live:true,captured_at_ms:time,received_at_ms:time},active);
   if(active())renderCamera();
 });
}
async function loadFrame(){
 const d=device();
 if(!d?.frame_id||image?.device_id===d.id&&(image.frame_id===d.frame_id||image.live&&now()-image.received_at_ms<3000))return;
 const response=await request('/api/live/devices/'+encodeURIComponent(d.id)+'/frame.jpg?t='+Date.now());
 await displayCameraFrame(await response.blob(),{device_id:d.id,frame_id:response.headers.get('x-frame-id'),captured_at_ms:Number(response.headers.get('x-captured-at')),received_at_ms:Number(response.headers.get('x-received-at'))});
}
async function refresh(){if(!canView()||document.hidden)return;if(busy){queued=true;return;}busy=true;lastPoll=Date.now();$('#refresh-monitor').disabled=true;$('#download-user-csv').disabled=true;$('#refresh-monitor').textContent='กำลังอัปเดต…';$('#user-reports').setAttribute('aria-busy',String(isReports()));const key=queryKey(),selected=filters();
 try{const url=()=>'/api/monitor?'+new URLSearchParams({date:selected.date,days:String(selected.days),...(selected.boat?{device_id:selected.boat}:{})});let next=await json(url());if(key!==queryKey()){queued=true;return;}
  if(!isReports()&&!selectedId&&next.devices.length){selectedId=next.devices[0].id;queued=true;return;}
  data=next;appliedKey=key;serverOffset=Date.parse(data.server_time)-Date.now();failed=false;render();syncCamera();feedback('');if(!isReports())try{await loadFrame();renderAges();}catch(cameraError){failed=true;if(cameraError.status===404&&!image?.live)clearFrame();$('#camera-empty-text').textContent='ยังโหลดภาพไม่ได้ กดรีเฟรชเพื่อลองอีกครั้ง ข้อมูลยอดเก็บขยะยังอัปเดตได้';feedback('ข้อมูลยอดเก็บขยะอัปเดตแล้ว แต่ยังโหลดภาพกล้องไม่ได้',true);renderAges();}
 }catch(e){failed=true;feedback(e.message);if([401,403].includes(e.status)){session=null;syncCamera();clearFrame();await boot();}else if(e.code==='device_not_found'){if(isReports()){reportDeviceId='';rememberReport();}else selectedId='';syncCamera();clearFrame();queued=true;}renderAges();}
 finally{busy=false;$('#refresh-monitor').disabled=false;$('#download-user-csv').disabled=!data||appliedKey!==queryKey();$('#user-reports').setAttribute('aria-busy','false');$('#refresh-monitor').textContent='รีเฟรช';if(queued){queued=false;queueMicrotask(refresh);}}
}
async function boot(){try{session=await json('/api/session');$('#user-name').textContent=session.display_name||'';$('#user-role').textContent=session.role==='admin'?'ผู้ดูแลระบบ':session.public_monitor_enabled?'ผู้เข้าชม':'ผู้ใช้ระบบ';$('#admin-entry').hidden=!session.can_admin;$('#admin-login').hidden=session.can_admin||!session.public_monitor_enabled;const member=canView();$('#access-panel').hidden=member;$('#user-workspace').hidden=!member;$('#portal-signin').hidden=session.authenticated;$('#redeem-invitation').hidden=!session.authenticated||session.blocked;$('#access-message').textContent=session.blocked?'บัญชีถูกระงับ กรุณาติดต่อผู้ดูแล':session.authenticated?'ใส่รหัสเชิญเพื่อเข้าถึงข้อมูลเรือ':'เข้าสู่ระบบเพื่อดูภาพและรายงาน';if(member)await refresh();}catch(e){$('#access-panel').hidden=false;$('#user-workspace').hidden=true;$('#access-message').textContent='ยังเชื่อมต่อระบบไม่ได้ กรุณาลองใหม่';feedback(e.message);}}
$('#report-date').value=initial.date;$('#report-date').max=dayKey();$('#report-period').value=String(initial.days);
function updateReports(){if(!validReportDate($('#report-date').value,dayKey())){$('#report-date').value=data?.end_date||initial.date;$('#report-share-status').textContent='เลือกวันที่ที่ถูกต้องและไม่เกินวันนี้';}else $('#report-share-status').textContent='';detailDate=$('#report-date').value;$('#report-next').disabled=$('#report-date').value>=dayKey();rememberReport();refresh();}
$('#report-date').onchange=updateReports;$('#report-period').onchange=updateReports;$('#report-boat-select').onchange=()=>{reportDeviceId=$('#report-boat-select').value;updateReports();};$('#report-today').onclick=()=>{$('#report-date').value=dayKey();updateReports();};
function shiftDate(delta){if(!validReportDate($('#report-date').value,dayKey())){updateReports();return;}const date=new Date($('#report-date').value+'T12:00:00+07:00');date.setUTCDate(date.getUTCDate()+delta);const next=dayKey(date);if(next>dayKey())return;$('#report-date').value=next;updateReports();}$('#report-prev').onclick=()=>shiftDate(-1);$('#report-next').onclick=()=>shiftDate(1);
$('#boat-select').onchange=()=>{selectedId=$('#boat-select').value;syncCamera();clearFrame();refresh();};$('#refresh-monitor').onclick=refresh;$('#portal-retry').onclick=boot;$('#portal-error-retry').onclick=()=>canView()?refresh():boot();
$('#expand-camera').onclick=()=>{if(imageUrl){$('#camera-full-image').src=imageUrl;$('#camera-full-dialog').showModal();}};$('#close-camera-dialog').onclick=()=>$('#camera-full-dialog').close();
$('#redeem-invitation').onsubmit=async event=>{event.preventDefault();try{const response=await fetch('/api/access/redeem',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Warirak-Client':'dashboard'},body:JSON.stringify({code:$('#invitation-code').value.trim()})});const result=await response.json();if(!response.ok)throw Error(result.error?.message||'ใช้รหัสเชิญไม่ได้');$('#invitation-code').value='';$('#access-error').textContent='';await boot();}catch(e){$('#access-error').textContent=e.message;}};
$('#download-user-csv').onclick=()=>{if(!data||!isReports()||appliedKey!==queryKey())return;const blob=new Blob([reportCsv(data.daily,reportDeviceId)],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`warirak-report-${data.start_date}-${data.end_date}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);};
$('#report-share').onclick=async()=>{const link=reportLink({date:$('#report-date').value,days:Number($('#report-period').value),boat:reportDeviceId},location.origin);try{await navigator.clipboard.writeText(link);$('#report-share-status').textContent='คัดลอกลิงก์แล้ว เปิดที่อื่นจะได้ช่วงเวลาและเรือเดียวกัน';$('#report-share-fallback').hidden=true;}catch{$('#report-share-fallback').hidden=false;$('#report-share-fallback').value=link;$('#report-share-fallback').select();$('#report-share-status').textContent='เลือกลิงก์ไว้แล้ว คัดลอกจากช่องนี้ได้เลย';}};
window.addEventListener('hashchange',showPage);document.addEventListener('visibilitychange',()=>{syncCamera();if(!document.hidden)refresh();});window.addEventListener('pagehide',()=>{stopCamera?.();stopCamera=null;streamDeviceId=null;clearFrame();});window.addEventListener('pageshow',syncCamera);showPage();await boot();setInterval(()=>{if(!document.hidden&&Date.now()-lastPoll>=(isReports()?30000:5000))refresh();renderAges();},1000);
window.__warirakPortal={refresh,get session(){return session;},get data(){return data;},get image(){return image;},get filters(){return filters();}};
