# ใช้ iPhone เป็นกล้องทดลองให้ Raspberry Pi 5

เส้นทางภาพ: iPhone → สตรีมในเครือข่าย → Pi → ภาพ JPEG ล่าสุดบน Dashboard

แอปที่รองรับ: [IP Camera Lite บน App Store ประเทศไทย](https://apps.apple.com/th/app/ip-camera-lite/id1013455241) ผู้พัฒนาระบุว่ารุ่นฟรีส่ง RTSP/HTTP ได้และมีลายน้ำ รุ่นนี้เพียงพอสำหรับเริ่มทดสอบการเชื่อมภาพ ไม่จำเป็นต้องซื้อรุ่นเต็มก่อน

## ตั้งค่า iPhone

1. ให้ iPhone กับ Pi อยู่เครือข่ายเดียวกันที่อุปกรณ์ติดต่อกันได้ เช่นเราเตอร์ส่วนตัว หลีกเลี่ยง Wi-Fi หอที่แยกอุปกรณ์ หากใช้ iPhone ปล่อยฮอตสปอตเองต้องทดสอบว่าแอปเปิดเซิร์ฟเวอร์บนเครือข่ายนั้นได้จริง
2. เปิดแอป อนุญาตกล้องและการเข้าถึงเครือข่ายภายใน เปิดโหมด IP Camera Server ใช้กล้องหลัง ทดลอง 640 × 480 หรือ 720p ประมาณ 10–15 fps หากมีตัวเลือก codec ให้เริ่ม H.264/AVC
3. เปิดหน้าแอปค้างไว้ขณะทดสอบ อย่าล็อกจอหรือสลับออกจากแอป หากภาพหยุดให้ตรวจหน้าแอปก่อน
4. คัดลอก **RTSP URL เต็ม** จากแอป รวมพอร์ตและเส้นทาง ห้ามเดาว่า HTTP port 8081 คือ RTSP port และที่อยู่หน้าดูกล้อง HTML ไม่ใช่ URL วิดีโอโดยตรง
5. ใช้ชื่อผู้ใช้/รหัสผ่านกล้องตามที่ตั้งในแอป โปรแกรมจะถามแยกบน Pi รหัสนี้ไม่ใช่รหัสเว็บหรือ Device token ไม่ต้องส่งรหัสผ่านในแชต

## ดาวน์โหลดบน Pi

รันใน SSH ที่ขึ้น `warirak@warirakpi` เท่านั้น ชุด AI เดิมอยู่ `~/Warirak_Pi5_Kit` และมี OpenCV/NCNN ติดตั้งแล้ว ใช้ Python ในชุดนั้น ไม่ติดตั้ง PyTorch ใหม่

```bash
mkdir -p ~/warirak-monitor && cd ~/warirak-monitor
curl --fail --show-error --location https://warirak-monitor.kungmaxzaa.workers.dev/assets/pi/phone_camera.py -o phone_camera.py
```

โฟลเดอร์นี้ต้องมี `monitor_agent.py` จากขั้นเชื่อมสถานะ Pi เดิม หากไม่มี ให้ดาวน์โหลดไฟล์จาก `/assets/pi/monitor_agent.py` มาไว้ข้างกัน หรือใช้ ZIP ชุดกล้อง

## ตั้งค่าแล้วตรวจภาพก่อนเผยแพร่

```bash
python3 phone_camera.py configure
```

วาง URL สตรีมเมื่อถาม (ตัวอักษรซ่อน) กรอก username และ password ของกล้องหากแอปเปิด authentication ถ้าไม่ได้เปิดให้กด Enter ข้าม username โปรแกรมเก็บไว้ส่วนตัวที่ `~/.config/warirak/phone-camera.json`

```bash
~/Warirak_Pi5_Kit/.venv/bin/python phone_camera.py check
```

ต้องเห็น `Camera OK: ...` จึงถือว่า Pi รับภาพจริงได้ คำสั่ง check ไม่ส่งภาพขึ้นเว็บ หากไม่ผ่าน ให้ตรวจ URL เต็ม เครือข่ายและรหัสกล้อง ไม่เปลี่ยนรหัสผู้ดูแลเว็บ

## ดูภาพเมื่อไม่มีอินเทอร์เน็ต

ให้ Pi คอม และ iPhone อยู่บน Wi-Fi วงเดียวกัน เราเตอร์ใช้กระจาย Wi-Fi ภายในได้แม้สายอินเทอร์เน็ตหลุด เปิด IP Camera Server บน iPhone ค้างไว้ หากเปลี่ยนเครือข่าย ให้ใช้ IP ใหม่ของ Pi และ RTSP URL ใหม่จากแอปกล้อง

รันใน **PowerShell บน Windows** ใช้ `exit` หากยังอยู่ในหน้าต่าง SSH แล้วแก้ IP ให้ตรงกับ Pi ในเครือข่ายปัจจุบัน

```powershell
cd "C:\Users\Administrator\OneDrive\เอกสาร\ChatGPT\boat_TSU"
scp .\hardware\pi\phone_camera.py .\hardware\pi\monitor_agent.py warirak@172.20.10.3:warirak-monitor/
ssh -L 8765:127.0.0.1:8765 warirak@172.20.10.3
```

เมื่อเห็นพรอมต์ **`warirak@warirakpi`** ให้รันบน Pi

```bash
cd ~/warirak-monitor
~/Warirak_Pi5_Kit/.venv/bin/python phone_camera.py local --detect
```

เปิด `http://127.0.0.1:8765/` ในเบราว์เซอร์บน **คอมที่เปิด SSH** ค้างหน้าต่าง SSH และแอปกล้องไว้ โหมดนี้ใช้ OpenCV และ NCNN ที่ติดตั้งไว้ในชุด Pi เดิม ภาพจะดูได้ในเครื่องผ่าน SSH หากต้องการเช็กภาพอย่างเดียวให้ใช้ `local` เมื่อ IP ของกล้องเปลี่ยน ให้รัน `python3 phone_camera.py configure` แล้วใส่ RTSP URL ที่แอปแสดงล่าสุด

ถ้าไม่มีเราเตอร์เลย ใช้ Wi-Fi hotspot ของ Pi หรือเราเตอร์พกพาเพื่อให้ทั้งสามเครื่องอยู่ในวงเดียวกัน การเปลี่ยน Wi-Fi ของ Pi อาจทำให้ SSH ตัด ให้ตั้ง hotspot จากจอและคีย์บอร์ดที่ต่อ Pi แล้วเชื่อมคอมและ iPhone เข้ากับชื่อ Wi-Fi ใหม่ [คู่มือตั้ง hotspot ของ Raspberry Pi](https://www.raspberrypi.com/tutorials/host-a-hotel-wifi-hotspot/)

## ส่งภาพขึ้น Dashboard

คำสั่งต่อไปนี้ส่งภาพไป **หน้าติดตามสาธารณะของโครงงาน** จัดมุมกล้องให้เห็นเฉพาะพื้นที่ทดสอบที่ต้องการเผยแพร่ ใช้ Device token เดิมจาก `~/.config/warirak/device.json` โดยไม่ต้องวาง token ใหม่

```bash
~/Warirak_Pi5_Kit/.venv/bin/python phone_camera.py run
```

เมื่อขึ้น `Dashboard image accepted` เปิด https://warirak-monitor.kungmaxzaa.workers.dev/monitor ภาพจะเปลี่ยนประมาณทุก 5 วินาที ไม่ใช่วิดีโอเต็มเฟรมเรต กด Ctrl+C หยุดส่งภาพได้ บริการสถานะ Pi ยังทำงานต่อ

## เปิดภาพสด

หยุดตัวส่งภาพเดิมด้วย Ctrl+C แล้วรันบน Pi

```bash
cd ~/warirak-monitor &&
curl -fL 'https://warirak-monitor.kungmaxzaa.workers.dev/assets/pi/phone_camera.py?v=live' -o phone_camera.py &&
curl -fL 'https://warirak-monitor.kungmaxzaa.workers.dev/assets/pi/detection_frame.py?v=yolo-frame-v1' -o detection_frame.py &&
~/Warirak_Pi5_Kit/.venv/bin/python -m pip install websocket-client==1.9.0 &&
~/Warirak_Pi5_Kit/.venv/bin/python phone_camera.py run --live
```

เปิดแอปกล้องค้างไว้ เมื่อขึ้น `Live camera connected` หน้าติดตามจะแสดงป้าย **ภาพสด** ภาพอัปเดตได้สูงสุดประมาณ 5 เฟรมต่อวินาที ขึ้นกับสัญญาณและความเร็วของ Pi ถ้าสตรีมสะดุด เว็บจะคงภาพล่าสุดพร้อมแสดงสถานะความสดของภาพ ตัวส่งจะเชื่อมต่อใหม่เมื่อการเชื่อมต่อกับเว็บขาด

## แสดงกรอบและชนิดขยะบน Dashboard

อัปเดตบน **เทอร์มินัลของ Pi** ที่ขึ้น `warirak@warirakpi` หยุดตัวส่งภาพเดิมด้วย Ctrl+C ก่อน ไม่ใช้คำสั่งนี้ใน Windows PowerShell

```bash
cd ~/warirak-monitor
curl -fL 'https://warirak-monitor.kungmaxzaa.workers.dev/assets/pi/install_yolo_camera.sh' -o install_yolo_camera.sh
bash install_yolo_camera.sh
~/Warirak_Pi5_Kit/.venv/bin/python phone_camera.py run --detect
```

ตัวติดตั้งสำรองไฟล์สคริปต์เดิม เก็บการตั้งค่ากล้องและ device token เดิมไว้ และตรวจโปรแกรมที่ต้องใช้ก่อนติดตั้ง

เปิดหน้า `/monitor` จะเห็นกรอบ ชื่อชนิดขวดพลาสติก/ฝาขวด จำนวนในภาพ และความมั่นใจสูงสุดของแต่ละชนิด ผลแนบมากับ JPEG เดียวกัน จึงไม่จับคู่ผลของคนละภาพ ถ้ากล้องหรือโปรแกรมหยุด เว็บระบุว่าเป็นภาพล่าสุด ไม่ทำให้ดูเหมือนตรวจจับต่ออยู่ จำนวนที่ตรวจพบไม่เพิ่มยอดเก็บสำเร็จ ต้องมีเหตุการณ์ยืนยันการเก็บจากระบบจริงก่อน

ใช้ `--live --detect` ร่วมกันได้ แต่อัตราภาพจะขึ้นกับเวลาประมวลผล YOLO บน Pi ไม่รับประกัน 5 FPS ขณะตรวจจับ ซอฟต์แวร์นี้ไม่สั่งมอเตอร์

## ทดลองตรวจจับแบบส่งภาพทุก 5 วินาที

หยุดคำสั่ง run เดิมก่อน แล้วรัน:

```bash
~/Warirak_Pi5_Kit/.venv/bin/python phone_camera.py run --detect
```

ใช้โมเดล NCNN public-v4 และค่า confidence calibration เดิม ไม่ฝึกหรือดาวน์โหลดโมเดลใหม่ มีกรอบขวด/ฝาขวดเมื่อโมเดลตรวจพบ การตรวจจับไม่เพิ่มยอดเก็บจริง ไม่สั่ง ESP, GPIO หรือมอเตอร์ และไม่ได้ยืนยันว่าระบบขับเรือใช้งานจริงได้

## ข้อจำกัดและการตรวจสอบ

- เวลาในภาพ/ส่วนหัว API คือเวลาที่ Pi อ่านเฟรมได้หลังถอดรหัส ไม่ใช่เวลาถ่ายจริงของเซนเซอร์ iPhone ความหน่วงในมือถือ/เครือข่ายยังไม่ได้สอบเทียบ
- มีตัวอ่านแยกที่เก็บเฟรมล่าสุด ไม่สะสมคิวภาพรอ AI หรืออัปโหลด ภาพที่ค้างหลังอ่านเกิน 10 วินาทีจะไม่ส่ง และไม่ส่งเฟรมเดิมซ้ำเมื่อกล้องหลุด
- แอปปิดหรือเครือข่ายหลุดจะหยุดตัวส่งกล้องและแจ้งให้ตรวจการเชื่อม ไม่มีการทำให้ภาพเก่าดูสดด้วยเวลาใหม่ ให้เปิดแอปแล้วรันใหม่ หน้าเว็บจะแสดงภาพล่าสุดเป็นภาพเก่าตามเวลา
- กล้องมือถือมีมุมมอง ลายน้ำ และการบีบอัดต่างจากกล้องเรือ การทดสอบนี้ไม่ใช่ผลความแม่นยำภาคสนาม
- ซอฟต์แวร์ทดสอบด้วยสตรีม MJPEG ในเครื่องพัฒนา ไม่ถือว่าเชื่อม iPhone ของผู้ใช้สำเร็จจนกว่า check และการรับภาพจริงจะผ่าน

อ้างอิงเทคนิค: [OpenCV VideoCapture flags](https://docs.opencv.org/4.x/d4/d15/group__videoio__flags__base.html)
