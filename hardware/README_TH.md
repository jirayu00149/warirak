# วารีรักษ์ • ชุดทดสอบ Raspberry Pi, ESP32 และ ESP8266

เริ่มจากบอร์ดที่มีอยู่กับสาย USB ส่งข้อมูลได้หนึ่งเส้น คอมพิวเตอร์ใช้ Arduino IDE ทดสอบได้เลย เมื่อมี Raspberry Pi ให้ใช้ Pi รันโมเดล NCNN `public-v4-2026-10-28` เพื่อตรวจจับขวดพลาสติกและฝาขวด แล้วส่งตำแหน่งซ้าย กลาง หรือขวาในภาพไปยังบอร์ดผ่าน USB

สเก็ตช์นี้ใช้ทดสอบการสื่อสารบนโต๊ะ เฟิร์มแวร์ตอบสถานะ `STOP` เสมอและแจ้ง `TIMEOUT STOP` เมื่อขาดข้อความประมาณ 400 มิลลิวินาที ไม่มีการกำหนดขามอเตอร์ สายพาน หรือเซนเซอร์ และไม่มีการนับยอดเก็บขยะจากกรอบตรวจจับ

## 1. ใช้บอร์ดอย่างเดียวได้ทันที

เปิด `hardware/esp32/Warirak_DevKit/Warirak_DevKit.ino` ด้วย Arduino IDE ใช้โฟลเดอร์ชื่อ `Warirak_DevKit` และถ้าคอมไพล์บน Windows ให้แตกชุดไฟล์ไว้ที่พาธภาษาอังกฤษ เช่น `C:\Arduino\Warirak_Board_Kit`

| บอร์ดที่ใช้ | Core ใน Boards Manager | ตัวเลือกบอร์ด |
| --- | --- | --- |
| ESP32 DevKit ชิป ESP32 รุ่นปกติ | `esp32` โดย Espressif Systems | `ESP32 Dev Module` หรือเลือกรุ่นตรงป้ายบอร์ด |
| NodeMCU ที่มีป้าย `ESP8266MOD` และพอร์ต USB | `esp8266` โดย ESP8266 Community | `NodeMCU 1.0 (ESP-12E Module)` ถ้าบอร์ดเป็น NodeMCU รุ่นนี้ |
| ESP8266MOD แบบโมดูลเปล่า | `esp8266` โดย ESP8266 Community | เลือกตามรุ่นโมดูลและความจุแฟลช ใช้ USB–UART 3.3 V และวงจรบูตตามโมดูล |

เพิ่ม URL ที่ตรงบอร์ดใน **File → Preferences → Additional boards manager URLs** แล้วค้นหา core ใน Boards Manager [คู่มือติดตั้ง ESP32](https://docs.espressif.com/projects/arduino-esp32/en/latest/installing.html) · [คู่มือติดตั้ง ESP8266](https://arduino-esp8266.readthedocs.io/en/3.1.2/installing.html) · [การต่อ UART สำหรับ ESP8266 แบบโมดูล](https://docs.espressif.com/projects/esptool/en/latest/esp8266/esptool/serial-connection.html)

```text
https://espressif.github.io/arduino-esp32/package_esp32_index.json
https://arduino.esp8266.com/stable/package_esp8266com_index.json
```

ใน **Library Manager** ติดตั้ง **Adafruit SSD1306** แล้วเลือก **Install all** เพื่อติดตั้ง **Adafruit GFX Library** และไลบรารีที่เกี่ยวข้องด้วย

ต่อปุ่มกดหนึ่งตัวและจอ **SSD1306 I2C 128×64 แบบ 4 ขา** ตามตาราง สเก็ตช์ตรวจที่อยู่จอ `0x3C` และ `0x3D` อัตโนมัติ

| การต่อสาย | ESP32 DevKit | NodeMCU ESP8266 |
| --- | --- | --- |
| ปุ่มกด | `GPIO27` ↔ `GND` | `D5` ↔ `GND` |
| OLED `SDA` | `GPIO21` | `D2` (`GPIO4`) |
| OLED `SCL` | `GPIO22` | `D1` (`GPIO5`) |
| OLED `VCC` | `3V3` | `3V3` |
| OLED `GND` | `GND` | `GND` |

เมื่อเปิดบอร์ด จอจะแสดง `MANUAL` กดปุ่มหนึ่งครั้งเพื่อเข้า `AUTO` แล้วกดอีกครั้งเพื่อกลับ `MANUAL` ดูโหมดได้ที่ **Serial Monitor** ด้วย หากไม่ได้ต่อจอ ให้ดูสถานะโหมดจาก **Serial Monitor** ได้ตามปกติ

1. เสียบ USB เลือก **Tools → Port** เป็นพอร์ตที่เพิ่งปรากฏ แล้วกด **Upload**
2. เปิด **Serial Monitor** เลือก **115200 baud** และ **Newline** แล้วส่งบรรทัดนี้

   ```text
   WR1 PING 1234abcd CENTER
   ```

3. ดูข้อความตอบกลับ `WR1 ACK 1234abcd CENTER STOP` เมื่อเว้นไว้จะเห็น `WR1 TIMEOUT STOP` ส่งข้อความเดิมอีกครั้งเพื่อทดสอบว่าลิงก์กลับมาได้

ทดสอบซ้ำอัตโนมัติจากคอม Windows ที่มี Python ได้โดยติดตั้ง `pyserial` อย่างเดียว ปิด Serial Monitor ก่อนเปิดพอร์ตจาก Python แล้วเปลี่ยน `COM6` ให้ตรงกับบอร์ด

```powershell
py -m pip install pyserial==3.5
py hardware/pi/run_boat.py check-link --port COM6
```

## 2. เตรียม Raspberry Pi เมื่อมีเครื่อง

สำหรับ Raspberry Pi 5 ที่มีอยู่ ให้ใช้ Raspberry Pi OS 64-bit (Bookworm หรือ Trixie) และอะแดปเตอร์ USB-C PD 27 W ที่รองรับ 5.1 V / 5 A เมื่อลองบนโต๊ะ เริ่มด้วยกล้อง USB UVC และต่อ ESP32 หรือ ESP8266 ทีละตัวผ่าน USB เปิดเทอร์มินัลที่โฟลเดอร์ `Warirak_Board_Kit` หลังแตก ZIP โมเดล NCNN และเกณฑ์ความเชื่อมั่นอยู่ในชุดแล้ว [คู่มือไฟเลี้ยง Pi 5](https://www.raspberrypi.com/documentation/computers/getting-started.html#recommended-power-supply) · [คู่มือ NCNN บน Raspberry Pi](https://docs.ultralytics.com/guides/raspberry-pi)

```bash
uname -m  # ควรได้ aarch64
sudo apt update
sudo apt install -y python3-venv libgl1 libglib2.0-0  # Trixie ใช้ libglib2.0-0t64
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r hardware/pi/requirements.txt
```

ถ้าคัดลอกมาจากซอร์สโครงการแทน ZIP ให้แตก `frontend/assets/models/warirak-yolo26n-public-v4-ncnn.zip` ใน `frontend/assets/models/` เพื่อให้ได้โฟลเดอร์ `warirak-yolo26n-public-v4_ncnn_model`

ดูชื่อพอร์ต USB ก่อนใช้คำสั่ง ตัวอย่างใช้ `/dev/ttyUSB0` บอร์ดที่เป็น USB CDC อาจขึ้น `/dev/ttyACM0` ถ้าพอร์ตแจ้ง `Permission denied` ให้เพิ่มผู้ใช้ในกลุ่ม `dialout` ด้วย `sudo usermod -aG dialout "$USER"` แล้วออกจากระบบและเข้าใหม่

```bash
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
python hardware/pi/run_boat.py check-link --port /dev/ttyUSB0
python hardware/pi/run_boat.py run --source 0 --port /dev/ttyUSB0 --frames 30
```

ดู `detections`, `latency_ms`, `image_aim` และ `usb_ack_stop` ในผล JSON ถ้าใช้ Pi Desktop เพิ่ม `--show` เพื่อเปิดหน้าต่างภาพและกด `q` เพื่อจบ เมื่อทดสอบกล้องอย่างเดียวให้ละ `--port`

ถ้าใช้กล้อง CSI หัว Standard 15-pin กับ Pi 5 ให้ใช้สายกล้อง Standard-Mini ขนาด 15-pin ฝั่งกล้องไป 22-pin ฝั่ง Pi 5 ตรวจว่ากล้องขึ้นใน `rpicam-hello --list-cameras` แล้วติดตั้ง `python3-picamera2` จาก apt และสร้าง venv ด้วย `--system-site-packages` ก่อนใช้ `--source picamera2` [คู่มือต่อกล้อง Raspberry Pi](https://www.raspberrypi.com/documentation/accessories/camera-software.html)

ค่า `image_aim` ระบุด้านของวัตถุที่ได้คะแนนสูงสุดในภาพ เมื่อไม่พบวัตถุหรือประมวลผลภาพเกิน 1.5 วินาที จะส่ง `NONE` บอร์ดอาจแจ้งหมดเวลาระหว่างเฟรมบน Pi ที่ประมวลผลช้า แล้วกลับมารับได้เมื่อมีข้อความใหม่

## 3. ดูภาพบนเว็บวารีรักษ์ (เลือกใช้)

สร้างอุปกรณ์ในหน้า **ระบบและอุปกรณ์** แล้วใช้โทเค็นของอุปกรณ์กับคำสั่งด้านล่าง โปรแกรมส่ง JPEG จากกล้องจริงพร้อมกรอบตรวจจับประมาณทุก 5 วินาที เปิดหน้าติดตามด้วยบัญชีที่เข้าถึงเรือลำนั้นได้ [หน้าติดตามวารีรักษ์](https://warirak-monitor.kungmaxzaa.workers.dev/monitor)

```bash
read -rsp 'Device token: ' WARIRAK_DEVICE_TOKEN
echo
export WARIRAK_DEVICE_TOKEN
python hardware/pi/run_boat.py run --source 0 --port /dev/ttyUSB0 --publish
unset WARIRAK_DEVICE_TOKEN
```

การเลือกขา GPIO การขับมอเตอร์และสายพาน รวมถึงการยืนยันว่าเก็บขยะลงถังแล้ว ต้องอ้างอิงบอร์ดขับมอเตอร์ เซนเซอร์ และการสอบเทียบของชุดจริงก่อนใช้งาน
