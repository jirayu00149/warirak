// Metadata lives inside the displayed JPEG, so results cannot drift to another frame.
const signature = new TextEncoder().encode('WARIRAK-YOLO\0');
const classes = ['plastic_bottle', 'bottle_cap'];
const labels = ['ขวดพลาสติก', 'ฝาขวด'];
const finite = v => typeof v === 'number' && Number.isFinite(v);

export function validDetections(m) {
  if (!m || m.schema !== 'warirak.yolo-frame.v1' || typeof m.model !== 'string' ||
      !/^[a-zA-Z0-9._-]{1,80}$/.test(m.model) || m.collection_confirmed !== false ||
      m.control_enabled !== false || !Array.isArray(m.image_size) || m.image_size.length !== 2 ||
      !m.image_size.every(v => Number.isInteger(v) && v >= 16 && v <= 16384) ||
      !finite(m.latency_ms) || m.latency_ms < 0 || m.latency_ms > 60000 ||
      typeof m.captured_at !== 'string' || m.captured_at.length > 40 ||
      !/Z$|[+-]\d\d:\d\d$/.test(m.captured_at) || !Number.isFinite(Date.parse(m.captured_at)) ||
      !Array.isArray(m.detections) || m.detections.length > 64 ||
      !Number.isInteger(m.total_detected) || m.total_detected < m.detections.length || m.total_detected > 300 ||
      m.detections.length !== Math.min(m.total_detected, 64)) return false;
  const [w,h] = m.image_size;
  return m.detections.every(d => d && Number.isInteger(d.class_id) && classes[d.class_id] === d.class_name &&
    d.class_id >= 0 && d.class_id < 2 && finite(d.confidence) && d.confidence >= 0 && d.confidence <= 1 &&
    Array.isArray(d.xyxy) && d.xyxy.length === 4 && d.xyxy.every(finite) &&
    d.xyxy[0] >= 0 && d.xyxy[1] >= 0 && d.xyxy[2] <= w && d.xyxy[3] <= h &&
    d.xyxy[0] < d.xyxy[2] && d.xyxy[1] < d.xyxy[3]);
}

export async function readDetections(blob) {
  if (blob.size > 262144) return null;
  const bytes = new Uint8Array(await blob.slice(0, 65536).arrayBuffer());
  if (bytes[0] !== 255 || bytes[1] !== 216) return null;
  let offset = 2;
  while (offset + 4 <= bytes.length) {
    if (bytes[offset] !== 255) return null;
    const marker = bytes[offset+1];
    if (marker === 218 || marker === 217) break;
    const size = bytes[offset+2] * 256 + bytes[offset+3];
    if (size < 2 || offset + 2 + size > bytes.length) return null;
    if (marker === 239 && signature.every((v,i) => bytes[offset+4+i] === v)) {
      if (size > 16386) return null;
      try {
        const m = JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(bytes.slice(offset+4+signature.length, offset+2+size)));
        return validDetections(m) ? m : null;
      } catch { return null; }
    }
    offset += size + 2;
  }
  return null;
}

export function detectionView(metadata, hasFrame, fresh) {
  if (!metadata) return {title:hasFrame?'ภาพเข้าระบบแล้ว · ยังไม่มีผล YOLO':'รอภาพพร้อมผลตรวจจับ', items:[], detail:'แยกขวดพลาสติกและฝาขวดจากภาพบน Pi', state:'waiting'};
  const items = classes.map((name,id) => {
    const rows = metadata.detections.filter(d => d.class_id === id);
    return rows.length ? {label:labels[id], count:rows.length, confidence:Math.round(Math.max(...rows.map(d=>d.confidence))*100)} : null;
  }).filter(Boolean);
  return {
    title:(fresh?'':'ภาพล่าสุด · ') + (metadata.total_detected?`ตรวจพบ ${metadata.total_detected} ชิ้นในภาพ`:'ไม่พบขยะเป้าหมายในภาพนี้'),
    items,
    detail:`YOLO · ${metadata.model} · ประมวลผล ${(metadata.latency_ms/1000).toFixed(2)} วินาที${metadata.total_detected>64?' · แสดงรายละเอียด 64 รายการแรก':''}`,
    state:fresh?'ready':'stale'
  };
}

export function renderDetections(element, metadata, hasFrame, fresh) {
  const view = detectionView(metadata, hasFrame, fresh);
  const key = JSON.stringify(view);
  if (element.dataset.view === key) return;
  element.dataset.view = key;
  element.dataset.state = view.state;
  element.querySelector('[data-yolo-title]').textContent = view.title;
  element.querySelector('[data-yolo-detail]').textContent = view.detail;
  const list = element.querySelector('[data-yolo-items]');
  list.replaceChildren(...view.items.map(item => {
    const entry = document.createElement('li');
    const name = document.createElement('strong');
    name.textContent = `${item.label} ${item.count} ชิ้น`;
    const score = document.createElement('span');
    score.textContent = `ความมั่นใจสูงสุด ${item.confidence}%`;
    entry.append(name, score);
    return entry;
  }));
}
