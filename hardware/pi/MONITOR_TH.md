# เชื่อม Raspberry Pi กับ Dashboard วารีรักษ์

ชุดนี้ส่งสถานะจริงของ Pi ขึ้นเว็บทุกประมาณ 15 วินาที: อุณหภูมิ CPU, หน่วยความจำที่ใช้, พื้นที่เก็บข้อมูลว่าง และระยะเวลาตั้งแต่เปิดเครื่อง ใช้ Python 3 ที่มากับ Raspberry Pi OS ไม่มีไลบรารีเพิ่ม ไม่ต้องติดตั้ง YOLO ซ้ำ และไม่สั่ง GPIO หรือมอเตอร์

เว็บไซต์: https://warirak-monitor.kungmaxzaa.workers.dev/monitor
ผู้ดูแล: https://warirak-monitor.kungmaxzaa.workers.dev/admin#system

## 1. รับรหัสอุปกรณ์จากเว็บ

เข้าสู่ระบบผู้ดูแลด้วยบัญชีเดิม ไปที่ “ระบบและอุปกรณ์” ตั้งชื่อ เช่น “วารีรักษ์ Pi 5” และกดสร้างอุปกรณ์ คัดลอก Device token ที่ขึ้นครั้งเดียว รหัสนี้ต่างจากรหัสผ่านผู้ดูแล เก็บไว้ส่วนตัว ไม่ใส่ในภาพหน้าจอหรือ Git

ถ้ารหัสเดิมสูญหาย ให้สร้างอุปกรณ์ใหม่และเพิกถอนรายการเดิมที่เลิกใช้ ห้ามเดารหัสหรือใช้รหัสผ่านผู้ดูแลแทน

## 2. ดาวน์โหลดบน Pi

เปิด PowerShell บน Windows แล้วเข้า Pi ด้วย `ssh warirak@172.20.10.3` (เปลี่ยน IP หากเครือข่ายเปลี่ยน) หลังเข้าสำเร็จ prompt ต้องขึ้น `warirak@warirakpi` ก่อนรันคำสั่ง Linux ต่อไปนี้ ห้ามรันใน prompt `PS C:\...`

```bash
mkdir -p ~/warirak-monitor && cd ~/warirak-monitor && curl --fail --show-error --location https://warirak-monitor.kungmaxzaa.workers.dev/assets/pi/monitor_agent.py -o monitor_agent.py
python3 monitor_agent.py configure
```

วาง Device token เมื่อขึ้น `Paste device token (input hidden)` แล้วกด Enter ตัวอักษรจะไม่แสดงขณะพิมพ์ โปรแกรมเก็บรหัสใน `~/.config/warirak/device.json` สิทธิ์อ่านเฉพาะผู้ใช้ ไม่ต้องกรอกรหัสผ่านเว็บ

หากดาวน์โหลด ZIP ให้แตก ZIP แล้วเข้าโฟลเดอร์ `Warirak_Pi_Monitor` ก่อนรันคำสั่ง configure

## 3. ทดสอบและส่งต่อเนื่อง

```bash
python3 monitor_agent.py run --once
python3 monitor_agent.py run
```

เมื่อขึ้น `Connected` เปิดหน้าติดตามและเลือกเรือที่ลงทะเบียน เว็บรีเฟรชประมาณทุก 5 วินาที สถานะ Pi ส่งทุก 15 วินาที ถ้าไม่ได้รับสถานะ 60 วินาที เว็บจะแจ้งออฟไลน์และระบุว่าค่าเป็นข้อมูลล่าสุดที่เคยรับ

กด Ctrl+C เพื่อหยุด ไม่ต้องให้ Pi อยู่เครือข่ายเดียวกับผู้เปิดเว็บ แต่ Pi ต้องออกอินเทอร์เน็ต HTTPS ได้ การ SSH จากคอมยังต้องมีเครือข่ายที่เข้าถึง Pi

## 4. เริ่มส่งอัตโนมัติหลังเปิด Pi (เลือกใช้)

หยุดคำสั่ง run ด้วย Ctrl+C แล้วรัน:

```bash
python3 monitor_agent.py install-service
sudo loginctl enable-linger "$USER"
systemctl --user status warirak-monitor
```

โปรแกรมคัดลอกตัวเองไป `~/.local/share/warirak/monitor_agent.py` และสร้าง user service ชื่อ `warirak-monitor` ไม่แก้บริการ AI เดิม ดู log และหยุดบริการได้ดังนี้:

```bash
journalctl --user -u warirak-monitor -n 20
systemctl --user stop warirak-monitor
systemctl --user disable warirak-monitor
```

หลังเปลี่ยน Device token ให้รัน configure แล้ว `systemctl --user restart warirak-monitor` บริการหยุด retry เมื่อรหัสถูกปฏิเสธ ส่วนอินเทอร์เน็ตขัดข้องจะลองใหม่พร้อมข้อมูลที่อ่านใหม่ภายใน 60 วินาที ไม่ส่งสถานะเก่าค้างให้ดูเหมือนเครื่องออนไลน์

## ข้อมูลที่ยังไม่มีอุปกรณ์วัด

- แบตเตอรี่ส่ง `null` และแสดง “ยังไม่มีข้อมูลจากเซนเซอร์” ไม่ประมาณจากไฟเลี้ยง USB หรือเวลาที่เปิดเครื่อง
- ภาพกล้องยังว่างจนกว่าจะต่อกล้องและเปิดโปรแกรม `run_boat.py ... --publish` ในชุด Pi เดิม
- ชุดสถานะนี้ไม่จับพอร์ต USB ของ ESP จึงใช้คู่กับโปรแกรมเดิมได้
- ยอดเก็บจริงนับจากเหตุการณ์ยืนยันเก็บเท่านั้น การออนไลน์ ตรวจจับวัตถุ หรือดูภาพไม่เพิ่มยอด
- ทุกการส่งระบุ `control_enabled: false` การออนไลน์ไม่ได้หมายความว่าเรือพร้อมขับอัตโนมัติ

## แก้ปัญหา

- `401/403`: ตรวจ Device token ในหน้าอุปกรณ์ ไม่ใช้รหัสผ่านผู้ดูแล
- `Not connected`: ตรวจอินเทอร์เน็ตและเวลา Pi ด้วย `timedatectl` แล้วลอง `run --once` ใหม่
- ข้อมูลไม่ขึ้น: ตรวจว่าเลือกเรือถูกลำและไม่มีบริการเก่าค้างส่ง token อีกตัว
- ยังรอเชื่อม: เปิด log บริการ ต้องเห็น `Connected` จริง ไม่ใช่เพียงติดตั้งไฟล์แล้ว
- Pi ไม่มีหน้าจอก็ใช้ได้ ใช้ SSH ตั้งค่าครั้งแรก

ระบบนี้ทดสอบการรับข้อมูลและแสดงผลได้ในเครื่องพัฒนา ผลการเชื่อม Pi จริงต้องยืนยันจากข้อมูลที่ส่งมาจาก Pi ของผู้ใช้ ไม่ถือว่าทดสอบเสร็จเพียงเพราะหน้าเว็บเปิดได้
