#!/bin/bash
# Run on the Pi (sent over SSH by PI_CAMERA_START.bat). Sets the USB or Pi camera as the Warirak live source.
set -u
fail() { echo "ERROR: $*"; exit 0; }
cd ~/warirak-monitor 2>/dev/null || fail "~/warirak-monitor not found"
echo "== 1/5 download phone_camera.py"
curl -fsSL https://raw.githubusercontent.com/jirayu00149/warirak/main/hardware/pi/phone_camera.py -o phone_camera.py.new && mv phone_camera.py.new phone_camera.py || echo "WARN: download failed, using existing file"
grep -q "def usb_device" phone_camera.py || fail "phone_camera.py has no USB camera support"
echo "== 2/5 find camera"
SOURCE=""
USB=$(ls /dev/v4l/by-id/*-video-index0 2>/dev/null | head -1)
if [ -n "$USB" ]; then
  echo "USB camera: $(basename "$USB") -> $(readlink -f "$USB")"; SOURCE="usb"
elif (rpicam-hello --list-cameras 2>&1 || true) | grep -qE "^[0-9] :"; then
  echo "Pi ribbon camera found"; SOURCE="picamera"
else
  ls /dev/video* 2>/dev/null | head -5
  fail "no camera found. Unplug/replug the USB camera (use a USB port directly on the Pi), then run again."
fi
echo "== 3/5 set source = $SOURCE (old setting kept as .bak)"
CFG=~/.config/warirak/phone-camera.json
mkdir -p ~/.config/warirak && chmod 700 ~/.config/warirak
[ -f "$CFG" ] && cp -p "$CFG" "$CFG.bak"
( umask 077; printf '{"source": "%s"}' "$SOURCE" > "$CFG" )
PY=~/Warirak_Pi5_Kit/.venv/bin/python; [ -x "$PY" ] || PY=python3
echo "== 4/5 stop old camera process, check"
pkill -f "phone_camera.py run" 2>/dev/null; sleep 1
timeout 60 "$PY" phone_camera.py check 2>&1 | tail -5
echo "== 5/5 start live + AI in background (log: ~/warirak-monitor/picam.log)"
nohup "$PY" phone_camera.py run --live --detect --fps 10 > ~/warirak-monitor/picam.log 2>&1 < /dev/null &
sleep 20
tail -n 8 ~/warirak-monitor/picam.log
pgrep -f "phone_camera.py run" >/dev/null && echo "OK: camera is running. Open the monitor page." || echo "ERROR: camera process stopped; see log above"
exit 0
