export class MissionSimulator{
 constructor(){this.reset();}
 reset(scenario='normal'){this.scenario=scenario;this.elapsed=0;this.state='idle';this.phase='พร้อมเริ่มภารกิจจำลอง';this.detected=0;this.collected=0;this.battery=86;this.distance=0;this.events=[];this.route=[[.5,.6]];this.next=0;this.id=null;}
 start(scenario='normal'){this.reset(scenario);this.id='SIM-'+Date.now().toString(36).toUpperCase();this.started_at=new Date().toISOString();this.state='running';this.phase='ค้นหาขยะในสระจำลอง';this.log('เริ่มภารกิจจำลอง','start');return this.snapshot();}
 log(message,type,time=this.elapsed,class_id=null){this.events.push({id:`${this.id}:${this.events.length}`,time_s:Math.round(time),occurred_at:new Date(Date.now()-Math.max(0,this.elapsed-time)*1000).toISOString(),class_id,message,type,source:'simulation'});}
 pause(){if(this.state==='running'){this.state='paused';this.log('พักภารกิจจำลอง','pause');}else if(this.state==='paused'){this.state='running';this.log('จำลองต่อจากจุดเดิม','resume');}}
 stop(reason='ผู้ควบคุมหยุดภารกิจจำลอง'){if(['running','paused'].includes(this.state)){this.state='stopped';this.phase=reason;this.log(reason,'stop');}}
 tick(seconds){if(this.state!=='running')return this.snapshot();this.elapsed=Math.min(60,this.elapsed+Math.max(0,seconds));
  const schedule=[{t:4,type:'detection',msg:'ตรวจพบขวดพลาสติก · จำลอง'},{t:8,type:'approach',msg:'หันหัวเรือและเข้าหาเป้าหมาย'},{t:13,type:'collected',msg:'ยืนยันเก็บขวดสำเร็จ 1 ชิ้น · จำลอง'},{t:20,type:'detection',msg:'ตรวจพบฝาขวด · จำลอง'},{t:24,type:'approach',msg:'เข้าหาฝาขวดด้วยความเร็วต่ำ'},{t:30,type:'collected',msg:'ยืนยันเก็บฝาขวดสำเร็จ 1 ชิ้น · จำลอง'},{t:37,type:'detection',msg:'ตรวจพบขวดพลาสติกอีก 1 ชิ้น · จำลอง'},{t:42,type:'approach',msg:'จัดแนวขวดกับปากสายพาน'},{t:48,type:'collected',msg:'ยืนยันเก็บขวดสำเร็จ 1 ชิ้น · จำลอง'}];
  let stopping=null;
  if(this.scenario==='obstacle'&&this.elapsed>=23){this.elapsed=23;stopping=['หยุดเมื่อพบสิ่งกีดขวางจำลอง','obstacle'];}
  if(this.scenario==='low-battery'&&this.elapsed>=35){this.elapsed=35;this.battery=18;stopping=['หยุดเมื่อแบตเตอรี่จำลองต่ำ','low_battery'];}
  while(this.next<schedule.length&&schedule[this.next].t<=this.elapsed){const e=schedule[this.next++];this.log(e.msg,e.type,e.t,e.t===30?1:e.type==='collected'?0:null);if(e.type==='detection')this.detected++;if(e.type==='collected')this.collected++;this.phase=e.type==='detection'?'ค้นหาและยืนยันเป้าหมาย':e.type==='approach'?'เข้าหาเป้าหมายด้วยมอเตอร์คู่':'สายพานลำเลียงและยืนยันการเก็บ';}
  if(stopping){this.state='stopped';this.phase=stopping[0];this.log(...stopping);}
  if(this.battery!==18)this.battery=Math.max(20,86-Math.floor(this.elapsed*.18));this.distance=this.elapsed*.12;const t=this.elapsed/60;const x=.5+8.5*t,y=.6+2.1*Math.sin(t*Math.PI);const last=this.route.at(-1);if(Math.hypot(x-last[0],y-last[1])>.05)this.route.push([x,y]);
  if(this.elapsed>=60){this.state='completed';this.phase='สิ้นสุดภารกิจจำลอง';this.log(this.phase,'complete');}return this.snapshot();
 }
 snapshot(){return{id:this.id,source:'simulation',scenario:this.scenario,started_at:this.started_at||null,state:this.state,phase:this.phase,elapsed_s:Math.round(this.elapsed),detected_count:this.detected,confirmed_collected_count:this.collected,battery_percent:this.battery,distance_m:Math.round(this.distance*10)/10,route:this.route.map(p=>[...p]),events:this.events.map(e=>({...e}))};}
}
