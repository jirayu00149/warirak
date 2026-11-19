import {boatHealth} from './boat-health.js';

export function piStatus(device, now=Date.now()) {
  const health = boatHealth(device || {}, now);
  const present = typeof device?.agent_version === 'string' && !!device.agent_version;
  const measured = value => typeof value === 'number' && Number.isFinite(value);
  const uptime = device?.uptime_s;
  return {
    present,
    online: present && health.online,
    status: !present ? 'รอเชื่อม Raspberry Pi' : health.online ? 'Pi เชื่อมต่ออยู่' : 'Pi ออฟไลน์ · ค่าล่าสุด',
    temperature: measured(device?.cpu_temperature_c) ? device.cpu_temperature_c.toFixed(1) + ' °C' : 'ยังไม่มีข้อมูล',
    memory: measured(device?.memory_used_percent) ? Math.round(device.memory_used_percent) + '%' : 'ยังไม่มีข้อมูล',
    disk: measured(device?.disk_free_gb) ? device.disk_free_gb.toFixed(1) + ' GB' : 'ยังไม่มีข้อมูล',
    uptime: measured(uptime) ? uptime >= 86400 ? Math.floor(uptime / 86400) + ' วัน ' + Math.floor(uptime % 86400 / 3600) + ' ชม.' : uptime >= 3600 ? Math.floor(uptime / 3600) + ' ชม. ' + Math.floor(uptime % 3600 / 60) + ' นาที' : Math.floor(uptime / 60) + ' นาที' : 'ยังไม่มีข้อมูล',
    note: !present ? 'มี Pi แล้ว เริ่มส่งสถานะเครื่องได้แม้ยังไม่มีกล้องหรือมอเตอร์' : !health.online ? 'ค่าด้านล่างเป็นข้อมูลครั้งล่าสุด ตรวจไฟเลี้ยงและอินเทอร์เน็ตของ Pi' : 'รับสถานะเครื่องทุกประมาณ 15 วินาที · การเชื่อมต่อยังไม่ได้เปิดใช้งานมอเตอร์',
    battery: measured(device?.battery_percent) ? Math.round(device.battery_percent) + '%' : 'ยังไม่มีข้อมูลจากเซนเซอร์',
  };
}

export function renderPiStatus(root, device, now=Date.now()) {
  if (!root) return;
  const view = piStatus(device, now);
  root.dataset.state = view.online ? 'online' : view.present ? 'offline' : 'waiting';
  for (const key of ['status', 'temperature', 'memory', 'disk', 'uptime', 'note']) {
    const target = root.querySelector('[data-pi="' + key + '"]');
    if (target) target.textContent = view[key];
  }
}
