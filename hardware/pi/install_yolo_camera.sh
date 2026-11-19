#!/usr/bin/env bash
set -eu
base='https://warirak-monitor.kungmaxzaa.workers.dev/assets/pi'
target="$HOME/warirak-monitor"
python="$HOME/Warirak_Pi5_Kit/.venv/bin/python"
if [ ! -x "$python" ]; then
  echo 'Missing Warirak_Pi5_Kit Python environment. Install the existing Pi kit first.' >&2
  exit 1
fi
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
for name in phone_camera.py detection_frame.py monitor_agent.py; do
  curl --fail --location --retry 2 "$base/$name?release=yolo-frame-v1" -o "$stage/$name"
done
"$python" -m py_compile "$stage/phone_camera.py" "$stage/detection_frame.py" "$stage/monitor_agent.py"
"$python" -c 'import cv2, ncnn, ultralytics; print("Camera dependencies OK")'
mkdir -p "$target"
stamp=$(date +%Y%m%d-%H%M%S)
for name in phone_camera.py detection_frame.py monitor_agent.py; do
  if [ -f "$target/$name" ]; then cp "$target/$name" "$target/$name.backup-$stamp"; fi
  cp "$stage/$name" "$target/$name"
done
echo 'YOLO camera sender installed. Camera and device credentials preserved.'
echo 'Stop the previous camera sender with Ctrl+C, then run:'
echo 'cd ~/warirak-monitor'
echo '~/Warirak_Pi5_Kit/.venv/bin/python phone_camera.py run --detect'
