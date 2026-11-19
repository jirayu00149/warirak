"""Package only the phone receiver, shared config helper and guide; no credentials."""
from pathlib import Path
import hashlib
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
target = root / 'frontend/assets/pi'
target.mkdir(parents=True, exist_ok=True)
files = ('phone_camera.py', 'monitor_agent.py', 'detection_frame.py', 'install_yolo_camera.sh', 'IPHONE_CAMERA_TH.md')
for name in files:
    shutil.copyfile(root / 'hardware/pi' / name, target / name)
archive = target / 'Warirak_iPhone_Camera.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
    for name in files:
        output.write(target / name, 'Warirak_iPhone_Camera/' + name)
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(target / 'IPHONE_SHA256SUMS.txt').write_text(digest + '  Warirak_iPhone_Camera.zip\n', encoding='utf8')
(root / 'output').mkdir(exist_ok=True)
shutil.copyfile(archive, root / 'output' / archive.name)
print('Packaged iPhone receiver, helper, and guide; no credentials/models.')
