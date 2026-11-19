# วารีรักษ์บน Coolify (ชื่อ `warirak`) + สำรองข้อมูล

เวอร์ชันนี้ใช้โค้ดเว็บชุดเดียวกับ Cloudflare (`worker/index.mjs`) แต่รันด้วย Node ใน Docker
- ฐานข้อมูลเปลี่ยนจาก D1 เป็นไฟล์ SQLite ใน volume `warirak-data` (`/data/warirak.db`)
- กล้องสดใช้ WebSocket relay ในเครื่องเดียวกัน ไม่ต้องใช้ Durable Object
- ไม่ต้องติดตั้ง npm package เพิ่ม และเว็บบน Cloudflare เดิมยังใช้ได้เหมือนเดิม

ไฟล์ที่เกี่ยวข้อง: `Dockerfile`, `docker-compose.yaml`, `.dockerignore`, `server/*.mjs`, `tests/node-server.test.mjs`

## 1) เตรียม
1. ต้องมีเซิร์ฟเวอร์ที่ติดตั้ง Coolify แล้ว และมีโดเมนชี้มาที่เซิร์ฟเวอร์ เช่น `warirak.example.com`
2. ทดสอบในเครื่องก่อน:
   ```powershell
   npm run build
   npm test
   $env:WARIRAK_DATA_DIR="data"; npm start     # เปิด http://127.0.0.1:3000
   ```
3. push โค้ดขึ้น GitHub (ควรเป็น repo แบบ private) ไฟล์ลับถูกกันไว้แล้วใน `.gitignore` / `.dockerignore`

## 2) สร้างแอปใน Coolify
1. **Projects → + Add** ตั้งชื่อ `warirak` แล้วเลือก environment `production`
2. **+ New Resource → Private Repository (GitHub App)** แล้วเลือก repo และ branch
3. **Build Pack: Docker Compose** และ Docker Compose Location: `/docker-compose.yaml`
4. ที่ service `warirak` ใส่ Domain เป็น `https://warirak.example.com` (พอร์ตในคอนเทนเนอร์คือ 3000) Coolify จะออก HTTPS ให้อัตโนมัติ
5. กด **Deploy** เสร็จแล้วเปิด `https://warirak.example.com/healthz` ต้องเห็นคำว่า `ok`

> รันได้ **1 instance เท่านั้น** เพราะ SQLite และกล้องสดเก็บสถานะในเครื่องเดียว ห้ามตั้ง replicas มากกว่า 1

## 3) ใส่ข้อมูล: เลือกวิธี A หรือ B
**A. เริ่มใหม่:** เปิด Coolify → แอป → **Terminal** แล้วรัน
```sh
node server/create-owner.mjs
```
ระบบจะแสดงรหัสเข้าใช้ **ครั้งเดียว** ให้เก็บไว้ในตัวจัดการรหัสผ่าน จากนั้นเข้า `/login` แล้วเพิ่มเรือในหน้า admin เพื่อรับ token ใหม่ให้ Pi

**B. ย้ายข้อมูลจาก Cloudflare D1 (บัญชี รายชื่อเรือ และ token เดิมยังใช้ได้)**
1. ที่เครื่องตัวเอง (คำสั่งนี้แค่อ่านข้อมูลจาก D1 ไม่แก้อะไร):
   ```powershell
   npx wrangler d1 export warirak-db --remote --output warirak-d1.sql
   ```
2. คัดลอกไฟล์ไปไว้ใน volume:
   ```sh
   scp warirak-d1.sql root@<เซิร์ฟเวอร์>:/tmp/
   ssh root@<เซิร์ฟเวอร์> 'docker cp /tmp/warirak-d1.sql $(docker ps -qf name=warirak):/data/import/ && rm /tmp/warirak-d1.sql'
   ```
3. กด **Restart** ใน Coolify ระบบจะนำเข้าไฟล์เอง (ถ้าฐานข้อมูลยังว่าง) แล้วเปลี่ยนชื่อไฟล์เป็น `.imported`

ไฟล์ export นี้มีข้อมูลบัญชีอยู่ด้วย **ห้าม commit เข้า Git** และให้ลบทิ้งหลังนำเข้าเสร็จ

## 4) ให้ Pi ส่งข้อมูลมาที่ Coolify
แก้ค่า URL ของเซิร์ฟเวอร์ในไฟล์ตั้งค่าของ Pi (`~/.config/warirak/…`) ให้เป็นโดเมนใหม่ ถ้าใช้วิธี B ใช้ token เดิมได้เลย ถ้าใช้วิธี A ใช้ token ใหม่จากหน้า admin
กล้องสดยังใช้ `wss://<โดเมน>/api/device/stream` เหมือนเดิม Coolify (Traefik) รองรับ WebSocket อยู่แล้ว

## 5) สำรองข้อมูล
Coolify สำรองอัตโนมัติให้เฉพาะ database ที่สร้างผ่าน Coolify เอง แอปนี้จึงมีระบบสำรองในตัว:

| ทำอะไร | ค่าเริ่มต้น / คำสั่ง |
|---|---|
| สำรองอัตโนมัติ | ทุก 24 ชม. (ครั้งแรก 1 นาทีหลังเปิดแอป) → `/data/backups/warirak-YYYYMMDD-HHMMSS.db.gz` |
| เก็บย้อนหลัง | 14 ไฟล์ล่าสุด (`WARIRAK_BACKUP_KEEP`) |
| สำรองทันที | Terminal: `node server/backup.mjs` |
| ดูรายการ | `node server/backup.mjs --list` |
| กู้คืน | `node server/backup.mjs --restore warirak-….db.gz` แล้วกด **Restart** |

- ทุกไฟล์สำรองจะผ่าน `PRAGMA integrity_check` ก่อนเก็บ
- ตอนกู้คืน ระบบจะสลับไฟล์ฐานข้อมูลตอนเปิดแอปครั้งถัดไป ฐานข้อมูลที่กำลังใช้งานจึงไม่เสีย
- ถ้าอยากตั้งเวลาเองผ่าน Coolify ไปที่ **Scheduled Tasks → Add** ใส่ Command `node server/backup.mjs`, Frequency `0 20 * * *` (ตี 3 เวลาไทย = 20:00 UTC) และตั้ง `WARIRAK_BACKUP_INTERVAL_HOURS=0` เพื่อไม่ให้สำรองซ้ำ

**สำรองไว้นอกเซิร์ฟเวอร์ (แนะนำ):** ถ้าเซิร์ฟเวอร์เสีย ไฟล์ใน volume จะหายไปด้วย ให้ตั้ง Environment Variables ใน Coolify สำหรับที่เก็บแบบ S3 เช่น Cloudflare R2 (มีโควตาฟรี) หรือ Backblaze B2
```
WARIRAK_BACKUP_S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
WARIRAK_BACKUP_S3_REGION=auto
WARIRAK_BACKUP_S3_BUCKET=warirak-backup
WARIRAK_BACKUP_S3_ACCESS_KEY_ID=…        (ตั้งเป็น secret ใน Coolify)
WARIRAK_BACKUP_S3_SECRET_ACCESS_KEY=…    (ตั้งเป็น secret ใน Coolify)
```
คีย์ควรสิทธิ์แค่เขียน bucket นี้ bucket เดียว

ดึงไฟล์สำรองลงเครื่อง:
```sh
ssh root@<เซิร์ฟเวอร์> 'docker cp $(docker ps -qf name=warirak):/data/backups/ /tmp/warirak-backups'
scp -r root@<เซิร์ฟเวอร์>:/tmp/warirak-backups .
```

## สิ่งที่ยังไม่ได้ทดสอบ
- ยังไม่ได้ build Docker image จริง และยังไม่ได้ deploy บน Coolify (ทดสอบแค่ตัว Node server ในเครื่อง)
- ยังไม่ได้ทดสอบอัปโหลดไปที่เก็บ S3/R2 จริง (ทดสอบแค่รูปแบบลายเซ็น)
