#!/bin/bash
# Installs warirak-camera.service: starts the USB/Pi camera live stream + AI at boot,
# restarts it if it stops. Run on the Pi:  curl -fsSL <raw url> | bash   (asks for sudo password)
set -eu
USER_NAME=$(id -un)
DIR="$HOME/warirak-monitor"
PY="$HOME/Warirak_Pi5_Kit/.venv/bin/python"
[ -f "$DIR/phone_camera.py" ] || { echo "ERROR: $DIR/phone_camera.py not found"; exit 1; }
[ -x "$PY" ] || PY=$(command -v python3)
grep -q '"source"' "$HOME/.config/warirak/phone-camera.json" 2>/dev/null || { echo "ERROR: run the camera setup first (no camera source configured)"; exit 1; }
echo "== stop camera processes started by hand"
pkill -f "phone_camera.py run" 2>/dev/null || true; sleep 2; pkill -f "multiprocessing.spawn" 2>/dev/null || true
echo "== install /etc/systemd/system/warirak-camera.service (sudo password may be asked)"
sudo tee /etc/systemd/system/warirak-camera.service >/dev/null <<UNIT
[Unit]
Description=Warirak boat camera live stream + AI
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$DIR
Environment=PYTHONUNBUFFERED=1
Environment=WARIRAK_LIVE_INFLIGHT=1
Environment=WARIRAK_LIVE_SIZE=480x360
Environment=WARIRAK_LIVE_QUALITY=55
Environment=WARIRAK_CAMERA_LABEL=USB camera
ExecStart=$PY $DIR/phone_camera.py run --live --detect --fps 12
Restart=always
RestartSec=5
KillMode=control-group
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now warirak-camera.service
sleep 20
systemctl --no-pager --lines=5 status warirak-camera.service | sed -n '1,12p'
systemctl is-active --quiet warirak-camera.service && echo "OK: camera service is running and will start at every boot." || echo "ERROR: service not running; see: journalctl -u warirak-camera -n 30"
