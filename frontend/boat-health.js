// Receipt times are server timestamps. Old telemetry must never imply a boat is online.
export const HEARTBEAT_FRESH_MS=60000;
export const FRAME_FRESH_MS=15000;
export function boatHealth(device,now=Date.now()){
 const receipt=device.heartbeat_received_at_ms??device.received_at_ms;
 const age=value=>typeof value==='number'&&Number.isFinite(value)&&value>0&&value<=now+5000?Math.max(0,now-value):null;
 const heartbeatAge=age(receipt),frameAge=age(device.frame_received_at_ms),online=heartbeatAge!==null&&heartbeatAge<HEARTBEAT_FRESH_MS;
 const battery=typeof device.battery_percent==='number'&&Number.isFinite(device.battery_percent)&&device.battery_percent>=0&&device.battery_percent<=100?device.battery_percent:null;
 const alerts=[];
 if(heartbeatAge!==null&&!online)alerts.push({code:'offline',severity:'warning',title:'ไม่ได้รับสถานะล่าสุด',action:'ตรวจไฟและการเชื่อมต่อของเรือ'});
 if(online&&battery!==null&&battery<=25)alerts.push({code:'low_battery',severity:battery<=15?'critical':'warning',title:'แบตเตอรี่เหลือน้อย',action:'ตรวจแบตเตอรี่ก่อนเริ่มภารกิจ'});
 if(online&&device.state==='error')alerts.push({code:'device_error',severity:'critical',title:'เรือแจ้งข้อผิดพลาด',action:'ตรวจอุปกรณ์และหยุดการใช้งานจนแก้ไขแล้ว'});
 if(online&&frameAge!==null&&frameAge>=FRAME_FRESH_MS)alerts.push({code:'stale_camera',severity:'warning',title:'ภาพกล้องยังไม่อัปเดต',action:'ตรวจกล้องและโปรแกรมส่งภาพ'});
 return{id:device.id,name:device.name,online,has_telemetry:heartbeatAge!==null,heartbeat_age_ms:heartbeatAge,frame_age_ms:frameAge,camera_fresh:frameAge!==null&&frameAge<FRAME_FRESH_MS,battery_percent:battery,status:online?'online':heartbeatAge===null?'not_connected':'offline',alerts};
}
export function fleetHealth(devices,now=Date.now()){
 const boats=devices.filter(d=>d.revoked_at_ms==null).map(d=>boatHealth(d,now));return{total:boats.length,online:boats.filter(b=>b.online).length,offline:boats.filter(b=>b.status==='offline').length,not_connected:boats.filter(b=>b.status==='not_connected').length,alerts:boats.flatMap(b=>b.alerts.map(a=>({...a,device_id:b.id,device_name:b.name}))),boats};
}
