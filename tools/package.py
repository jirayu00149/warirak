"""Create distributable source archives without data, credentials, or build caches."""
from pathlib import Path
import json, zipfile

root = Path(__file__).resolve().parents[1]
output = root / 'outputs'
output.mkdir(exist_ok=True)
folders = ['worker', 'backend', 'frontend', 'migrations', 'tools', 'tests', 'ai']
files = [root / name for name in ['README.md', 'CHANGELOG.md', 'RELEASE_V1_2_GUIDE_TH.md', 'RELEASE_V1_2_PLAN.md', 'UX_DESIGN_NOTES.md', 'DATABASE.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'package.json', 'package-lock.json', 'wrangler.jsonc', '.gitignore']]
for folder in folders:
    files.extend(p for p in (root / folder).rglob('*') if p.is_file()
                 and not any(part in {'__pycache__', 'node_modules', 'data', 'runs'} for part in p.relative_to(root / folder).parts)
                 and p.suffix.lower() not in {'.zip', '.pyc', '.sqlite', '.db'}
                 and not (folder == 'ai' and p.name == 'yolo26n.pt')
                 and '.env' not in p.name and 'credentials' not in p.name.lower())
files = sorted(set(files))
for file in files:
    content = file.read_bytes()
    if any(marker in content for marker in [b'OAI_SITES_TOKEN', b'OAI-Sites-Authorization', b'chatgpt.site']):
        # Tests intentionally verify that spoofed provider identity cannot sign in.
        if 'tests' not in file.relative_to(root).parts and file != Path(__file__).resolve():
            raise RuntimeError('Legacy runtime dependency in ' + str(file.relative_to(root)))
target = output / 'Warirak_Cloudflare_Independent.zip'
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
    for file in files:
        archive.write(file, 'warirak-cloudflare/' + file.relative_to(root).as_posix())
    archive.writestr('warirak-cloudflare/SOURCE_MANIFEST.json', json.dumps({'version': json.loads((root/'package.json').read_text(encoding='utf-8'))['version'], 'files': [p.relative_to(root).as_posix() for p in files]}, indent=2))
assets = root / 'frontend' / 'assets'
(assets / 'warirak-source.zip').write_bytes(target.read_bytes())
with zipfile.ZipFile(assets / 'warirak-training-kit.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for file in files:
        rel = file.relative_to(root)
        if rel.parts[0] == 'ai' or file.name in {'LICENSE', 'THIRD_PARTY_NOTICES.md', 'AI_GUIDE_TH.md', 'INTEGRATION_TH.md', 'AUTONOMY_TH.md', 'USER_ADMIN_CAMERA_TH.md'}:
            archive.write(file, rel.as_posix())
print(json.dumps({'archive': str(target), 'source_files': len(files), 'bytes': target.stat().st_size}))
