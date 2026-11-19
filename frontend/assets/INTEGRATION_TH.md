# การเชื่อมอุปกรณ์กับ Backend

ใช้ URL หลักที่ได้จากการ deploy Worker โดยตรง ทุกคำขออุปกรณ์ใช้ `Authorization: Bearer <DEVICE_TOKEN>` ไม่ต้องล็อกอินผู้ดูแลบน Pi และไม่ต้องเชื่อมบริการยืนยันตัวตนอื่น

- `POST /api/device/frame` ส่ง JPEG ไม่เกิน 256 KiB พร้อม `X-Frame-Id` ที่ไม่ซ้ำและ `X-Captured-At` รูปแบบ ISO 8601 UTC
- `POST /api/device/telemetry` ส่ง JSON `{ "observed_at": "2026-10-27T08:00:00Z", "battery_percent": 80, "state": "searching" }` เวลาแต่ละครั้งต้องใหม่กว่าข้อมูลก่อนหน้า
- `POST /api/device/collections` ส่ง JSON พร้อม `mission_id`, `event_id`, `occurred_at`, `class_id` (0 ขวด, 1 ฝาขวด หรือ null เมื่อไม่ทราบ) และ `collection_confirmed: true`

ใช้ `event_id` เดิมเมื่อส่งเหตุการณ์เดิมซ้ำ Backend ไม่นับเหตุการณ์นั้นเพิ่มอีก ห้ามตั้ง `collection_confirmed` จากการตรวจพบในภาพอย่างเดียว ต้องยืนยันจากเซนเซอร์ที่ปากตะกร้าหรือผู้ควบคุม และส่งเวลาที่เกิดเหตุการณ์จริง

อ่านรายงานสาธารณะด้วย `GET /api/monitor?date=YYYY-MM-DD` และภาพล่าสุดด้วย `GET /api/live/devices/DEVICE_ID/frame.jpg` การเพิ่มและเพิกถอน Device token ต้องใช้เซสชันผู้ดูแล

คำสั่งบน ESP32 สำหรับขับมอเตอร์และระบบหยุดฉุกเฉินยังต้องพัฒนาและทดสอบกับฮาร์ดแวร์ รุ่นนี้ให้เครื่องมือข้อมูล กล้อง และการจำลอง ไม่ได้เปิดควบคุมมอเตอร์จากคลาวด์
