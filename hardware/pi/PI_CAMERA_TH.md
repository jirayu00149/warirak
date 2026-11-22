# ใช้กล้อง Raspberry Pi (สายแพ CSI) ขึ้นเว็บวารีรักษ์

`phone_camera.py` รองรับกล้อง Pi โดยตรง ใช้ `rpicam-vid` ส่งภาพ MJPEG แล้วส่งต่อเข้าภาพสด/AI ตัวเดิม (token เดิม, ไม่แก้เว็บ)

บน Pi (เทอร์มินัลหรือ SSH):
```bash
cd ~/warirak-monitor
curl -fL https://raw.githubusercontent.com/jirayu00149/warirak/main/hardware/pi/phone_camera.py -o phone_camera.py
rpicam-hello --list-cameras          # ต้องเห็นกล้อง 1 ตัว ถ้าไม่เห็น เช็กสายแพ/ด้านสายแล้วรีบูต
python3 phone_camera.py configure    # ตอนถามให้พิมพ์: picamera   (กล้องช่องที่ 2 = picamera:1)
~/Warirak_Pi5_Kit/.venv/bin/python phone_camera.py check
~/Warirak_Pi5_Kit/.venv/bin/python phone_camera.py run --live --detect --fps 10
```
ปรับขนาด/เฟรมได้ด้วย env: `WARIRAK_PICAM_WIDTH=1280 WARIRAK_PICAM_HEIGHT=720 WARIRAK_PICAM_FPS=15`
