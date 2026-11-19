# ทดสอบให้ Raspberry Pi สั่ง LED บน ESP8266

เฟิร์มแวร์ `Warirak_LED/Warirak_LED.ino` รับคำสั่งเปิดและปิด LED ผ่าน USB ที่ 115200 baud บอร์ดเริ่มต้นโดยดับ LED และดับเองประมาณ 1 วินาทีหลังขาดคำสั่งเปิดจาก Pi

## ต่อ LED ภายนอก

ถอด USB ก่อนต่อสาย ใช้ LED สีแดง 1 ดวงกับตัวต้านทาน 330 Ω ต่ออนุกรมดังนี้

```text
ESP8266 D6 (GPIO12) ── 330 Ω ── ขายาว LED (+)
ESP8266 GND ─────────────────── ขาสั้น LED (−)
```

ถ้าต้องอัปโหลดใหม่ เปิด `Warirak_LED.ino` ใน Arduino IDE เลือก **NodeMCU 1.0 (ESP-12E Module)** สำหรับบอร์ด NodeMCU แล้วเลือกพอร์ตของบอร์ดและกด **Upload** ใช้ core ESP8266 Community 3.1.2 [คู่มือ ESP8266 Arduino](https://arduino-esp8266.readthedocs.io/en/3.1.2/installing.html)

## คัดลอกตัวสั่งไป Pi

ใน PowerShell บน Windows เข้าโฟลเดอร์โปรเจกต์ แล้วคัดลอกไฟล์ทั้งสองไปโฟลเดอร์บ้านของผู้ใช้บน Pi ใช้ IP เดียวกับที่เข้า SSH ได้

```powershell
scp .\hardware\pi\led_test.py .\hardware\pi\usb_link.py warirak@172.20.10.3:
```

ถอด USB ของ ESP8266 จาก Windows แล้วเสียบสาย USB ส่งข้อมูลเข้าที่ Pi จากนั้นรันในหน้าต่าง SSH ของ Pi

```bash
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
~/Warirak_Pi5_Kit/.venv/bin/python ~/led_test.py blink --port /dev/ttyUSB0
```

เปลี่ยน `/dev/ttyUSB0` ตามผลจากคำสั่งแรก LED ควรกะพริบ 5 ครั้งและจบด้วย `Test complete. ACK OFF` หากมี `No module named 'serial'` ติดตั้งด้วย `~/Warirak_Pi5_Kit/.venv/bin/python -m pip install pyserial==3.5`

หากพอร์ตขึ้น `Permission denied` ให้รัน `sudo usermod -aG dialout "$USER"` แล้วออกจาก SSH เข้าใหม่ ปิด Serial Monitor ก่อนเปิดพอร์ตจาก Python

ใช้ `on --seconds 3` แทน `blink` เพื่อให้ LED ติด 3 วินาที หรือใช้ `off` เพื่อสั่งดับ
