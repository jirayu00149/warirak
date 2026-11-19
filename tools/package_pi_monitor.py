"""Publish an allowlisted, credential-free Pi monitor kit."""
from pathlib import Path
import hashlib
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
target = root / 'frontend/assets/pi'
target.mkdir(parents=True, exist_ok=True)
for source, name in [('hardware/pi/monitor_agent.py', 'monitor_agent.py'), ('hardware/pi/MONITOR_TH.md', 'README_TH.md')]:
    shutil.copyfile(root / source, target / name)
with zipfile.ZipFile(target / 'Warirak_Pi_Monitor.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in ('monitor_agent.py', 'README_TH.md'):
        archive.write(target / name, 'Warirak_Pi_Monitor/' + name)
checksum = hashlib.sha256((target / 'Warirak_Pi_Monitor.zip').read_bytes()).hexdigest()
(target / 'SHA256SUMS.txt').write_text(checksum + '  Warirak_Pi_Monitor.zip\n', encoding='utf8')
output = root / 'output'
output.mkdir(exist_ok=True)
shutil.copyfile(target / 'Warirak_Pi_Monitor.zip', output / 'Warirak_Pi_Monitor.zip')
print('Packaged Pi monitor: script + Thai guide, no credentials or models.')
