"""Package measured detector/navigation artifacts only after final selection and export."""
from pathlib import Path
import argparse,csv,hashlib,json,shutil,zipfile

root=Path(__file__).resolve().parents[1]
def digest(file):return hashlib.sha256(file.read_bytes()).hexdigest()
def write(file,text):file.parent.mkdir(parents=True,exist_ok=True);file.write_text(text,encoding='utf-8')
def archive(folder,target):
 with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED)as z:
  for file in sorted(folder.rglob('*')):
   if file.is_file():z.write(file,folder.name+'/'+file.relative_to(folder).as_posix())
def epochs(file):
 if not file.exists():return None
 rows=list(csv.DictReader(file.open(encoding='utf-8')));return int(float(rows[-1]['epoch']))if rows else 0
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ncnn',type=Path);p.add_argument('--skip-dataset-zip',action='store_true');a=p.parse_args()
 run=root/'ai/runs/public-yolo26n-v2';status=json.loads((run/'finalization-status.json').read_text(encoding='utf-8'));assert status['phase']=='complete','Final model selection is not complete'
 evaluation=json.loads((run/'evaluation.json').read_text(encoding='utf-8'));calibration=json.loads((run/'confidence-calibration.json').read_text(encoding='utf-8'));selection=json.loads((run/'final-selection.json').read_text(encoding='utf-8'));weights=run/'warirak-yolo26n-public-v2.pt';assert digest(weights)==evaluation['weights_sha256']
 export_evaluation=json.loads((run/'export-evaluation.json').read_text(encoding='utf-8'));assert export_evaluation['export_consistent']is True,'NCNN compatibility check did not pass'
 ncnn=a.ncnn or run/'warirak-yolo26n-public-v2_ncnn_model';assert ncnn.is_dir()and list(ncnn.glob('*.param'))and list(ncnn.glob('*.bin')),'NCNN export missing'
 data=root/('ai/data/public-v2'if status['selected_model']=='cap_refinement_best'else'ai/data/public-v1');manifest=json.loads((data/'manifest.json').read_text(encoding='utf-8'));assert digest(data/'manifest.json')==evaluation['dataset_manifest_sha256']
 out=root.parent/'outputs';out.mkdir(exist_ok=True);pack=out/'Warirak_AI_Trained_Models_2026-10-27';pack.mkdir(exist_ok=True)
 model_name=weights.name;shutil.copy2(weights,pack/model_name)
 portable_ncnn=pack/'warirak-yolo26n-public-v2_ncnn_model';portable_ncnn.mkdir(exist_ok=True)
 for file in ncnn.iterdir():
  if file.is_file()and file.suffix in{'.param','.bin','.yaml','.json'}:shutil.copy2(file,portable_ncnn/file.name)
 for name in ['evaluation.json','confidence-calibration.json','final-selection.json','dataset-manifest.json','export-evaluation.json']:
  shutil.copy2(run/name,pack/name)
 for name in ['navigation-policy.json','navigation-selection-report.json']:
  shutil.copy2(root/'frontend/assets'/name,pack/name)
 for name in ['LICENSE','THIRD_PARTY_NOTICES.md']:shutil.copy2(root/name,pack/name)
 shutil.copy2(root/'ai/evaluation-protocol.json',pack/'evaluation-protocol.json')
 for label,folder in [('warmup',root/'ai/runs/public-yolo26n-v1/training'),('refinement',run/'refinement')]:
  history=pack/'training-history'/label;history.mkdir(parents=True,exist_ok=True)
  for name in ['args.yaml','results.csv']:
   if(folder/name).is_file():shutil.copy2(folder/name,history/name)
 nav=json.loads((pack/'navigation-policy.json').read_text(encoding='utf-8'));learned=nav['evaluation']['results'][0];counts=evaluation['dataset']['counts'];metrics=evaluation['overall'];size=evaluation['imgsz']
 table='\n'.join('| '+label+' | '+' | '.join(f"{evaluation['classes'][name][key]*100:.1f}%"for key in['precision','recall','map50','map50_95'])+' |'for name,label in [('plastic_bottle','ขวดพลาสติก'),('bottle_cap','ฝาขวด')])
 thresholds=' / '.join(f"{label} {calibration['thresholds'][name]:.4f}"for name,label in [('plastic_bottle','ขวด'),('bottle_cap','ฝาขวด')])
 card=f'''# วารีรักษ์: โมเดลตรวจจับขยะและนโยบายขับเรือจำลอง

จัดทำเพื่อโครงงาน คณะวิศวกรรมศาสตร์ มหาวิทยาลัยทักษิณ วันที่ 27 ตุลาคม 2569

## โมเดลตรวจจับภาพ

ใช้ YOLO26n ที่เริ่มจากน้ำหนัก COCO ของ Ultralytics แล้วปรับฝึกกับข้อมูลขยะสองคลาส การฝึกเกิดบนคอมพิวเตอร์ NVIDIA GeForce RTX 2050 ไม่ใช่การฝึกบนเว็บไซต์หรือ Raspberry Pi

- น้ำหนักที่เผยแพร่: `{model_name}`
- ขนาดภาพที่ใช้ประเมิน: {size} × {size} พิกเซล
- ชุดข้อมูลที่โมเดลที่เลือกใช้: {evaluation['dataset']['images']:,} ภาพ; train {counts['train']}, validation {counts['val']}, test {counts['test']}
- ฝาขวดในชุด test: 37 ชิ้น; ขวดพลาสติก 98 ชิ้น
- รอบอุ่นเครื่องที่ทำจริง: {epochs(root/'ai/runs/public-yolo26n-v1/training/results.csv')} รอบ; รอบปรับละเอียดที่ทำจริง: {epochs(run/'refinement/results.csv')} รอบ
- เลือกโมเดลและขนาดภาพจาก validation ตาม protocol ที่กำหนดก่อนประเมิน test ไม่เลือกจากคะแนน test
- เกณฑ์ความเชื่อมั่นเลือกจาก validation: {thresholds}

| คลาส | Precision | Recall | mAP50 | mAP50–95 |
|---|---:|---:|---:|---:|
{table}

ค่า mAP50 รวมเท่ากับ {metrics['map50']*100:.1f}% และ mAP50–95 รวมเท่ากับ {metrics['map50_95']*100:.1f}% ค่า Precision และ Recall ใช้ IoU 0.5 และเกณฑ์ความเชื่อมั่นรายคลาสที่เลือกจาก validation ก่อนทดสอบ ส่วน mAP ประเมินตลอดเส้นโค้งตามวิธีของ Ultralytics ตัวเลขเหล่านี้ไม่ใช่อัตราเก็บขยะสำเร็จ

## ขอบเขตของผล

ผลมาจากข้อมูลสาธารณะ มีฝาขวดในชุดทดสอบเพียง 37 ชิ้น จึงยังมีความไม่แน่นอน ไม่ใช่ผลทดสอบกล้องบนเรือในบ่อมหาวิทยาลัย แหล่งภาพบางส่วนไม่มีข้อมูลรอบถ่ายจริง การกรองภาพคล้ายช่วยลดความเสี่ยงแต่ไม่สามารถยืนยันความเป็นอิสระของทุกฉากได้ ต้องเก็บภาพจากกล้องที่จะใช้จริงและประเมินกับแสง เงาสะท้อน และระยะตรวจจับจริงเพิ่มเติม

## นโยบายขับเรือ

ฝึก Q-learning จากตารางว่าง เปรียบเทียบ 8,000 / 16,000 / 20,000 รอบด้วย validation แยก และเลือกนโยบาย 20,000 รอบ ชุดทดสอบใหม่ {learned['episodes']:,} สนามให้ผลเก็บสำเร็จ {learned['collections']}, ชน {learned['collisions']} และหมดเวลา {learned['timeouts']} หรือสำเร็จ {learned['success_rate']*100:.1f}%

เป็นผลในสระจำลอง 10 × 6 เมตร มีเป้าหมายหนึ่งชิ้นต่อสนามและสิ่งกีดขวางคงที่ ไม่ใช่ผลขับเรือจริง โค้ด navigation บน Pi ให้เพียงคำสั่งเสนอแบบ shadow ไม่มีการส่งคำสั่งมอเตอร์ และต้องมีค่าระยะกับเซนเซอร์ที่สอบเทียบแล้ว

รายละเอียดที่ตรวจสอบซ้ำได้อยู่ใน `evaluation.json`, `final-selection.json`, `dataset-manifest.json`, `navigation-selection-report.json` และ `checksums.json`
'''
 write(pack/'MODEL_CARD_TH.md',card)
 guide=f'''# เริ่มใช้โมเดลกับ Raspberry Pi

ใช้ Raspberry Pi OS แบบ 64 บิต ติดตั้งโครงการวารีรักษ์และ dependencies ตามคู่มือทางการ Ultralytics สำหรับ Raspberry Pi: https://docs.ultralytics.com/guides/raspberry-pi/

แตกชุดโมเดลไว้ในโฟลเดอร์ที่คุณเลือก จากโฟลเดอร์ `ai` ของโครงการใช้คำสั่งต่อไปนี้ โดยแก้เส้นทางให้ตรงกับไฟล์ที่แตกไว้:

```sh
python -m warirak_ai.infer --weights /path/to/warirak-yolo26n-public-v2_ncnn_model --thresholds /path/to/confidence-calibration.json --imgsz {size} --source 0 --frames 300 --out runs/boat-detections.jsonl
```

NCNN ที่ให้ส่งออกตามขนาดภาพ {size} พิกเซล ผลความแม่นยำในรายงานใช้ขนาดเดียวกัน ยังไม่มีผล FPS อุณหภูมิ หรือการใช้ไฟที่วัดบน Pi 4 ของคุณ การตรวจพบในภาพไม่นับเป็นการเก็บขยะสำเร็จ

ถ้าต้องการทดลองนโยบายขับ ให้เตรียม observations JSONL จากกล้องและเซนเซอร์ที่สอบเทียบแล้ว และใช้:

```sh
python -m warirak_ai.navigation --policy /path/to/navigation-policy.json --observations /path/to/observations.jsonl
```

โหมดนี้พิมพ์คำสั่งเสนอเท่านั้น ไม่ส่งคำสั่งไป ESP32 หรือมอเตอร์ ตัวอย่างข้อมูลเข้ามี timestamp_unix_ms, battery_percent, clearance_m สามทิศ, armed, manual_override, target_visible และเมื่อเห็นเป้าหมายต้องมี target_bearing_rad กับ target_distance_m ที่ได้จากการสอบเทียบ หากข้อมูลขาดหรือเก่า ระบบเสนอให้หยุด

ประเมินซ้ำด้วยชุดข้อมูลที่แตกไว้ โดยใช้ขนาดภาพและเกณฑ์ความเชื่อมั่นเดียวกับรายงาน:

```sh
python -m warirak_ai.dataset validate --data /path/to/dataset
python -m warirak_ai.evaluate --data /path/to/dataset --weights /path/to/warirak-yolo26n-public-v2_ncnn_model --thresholds /path/to/confidence-calibration.json --imgsz {size} --device cpu --out runs/reproduced-evaluation.json
```

คำสั่งประเมินใช้ภาพสี่เหลี่ยมจัตุรัสแบบ rect=False ตรงกับ NCNN ที่ส่งออกไว้ หากเปลี่ยนกล้องหรือสภาพแวดล้อม ควรสร้างชุดทดสอบของเรือจริงก่อนใช้ผลเพื่อนำเสนอประสิทธิภาพภาคสนาม
'''
 write(pack/'PI_START_TH.md',guide)
 credits='''# Data and model credits

- TACO: Pedro F. Proença and Pedro Simões, TACO: Trash Annotations in Context for Litter Detection (2020), https://github.com/pedropro/TACO , https://doi.org/10.5281/zenodo.3587843 . Annotations CC BY 4.0. Images follow their individual source licences, default CC BY 4.0 where unspecified by the source.
- TACO image mirror: Pictograph, https://huggingface.co/datasets/pictograph/taco . Target annotations were checked against primary TACO annotations; six conflicting cases were excluded.
- SC-FloatWaste: https://huggingface.co/datasets/OliviaWuYJ/sc-floatwaste , CC BY 4.0. Only plastic beverage/other bottle categories were mapped to plastic_bottle; ambiguous DH_lid-containing frames were excluded rather than relabelled as caps.
- Reviewed ExtendedTACO: RoboticsLab URJC, https://huggingface.co/datasets/roboticslaburjc/ExtendedTACO-reviewed . Detection rectangles from darknet-labels/. Annotations CC BY 4.0; individual image licences prevail. Known/held-out visually similar images were excluded before train-only additions.
- Ultralytics YOLO26: https://github.com/ultralytics/ultralytics , AGPL-3.0 / applicable commercial licence. This project uses AGPL-3.0 and provides its source separately.

Image changes: verified dimensions, resized longest edge to at most 1280 preserving aspect ratio, stripped EXIF consistently with the annotation coordinate system, JPEG quality 93. Categories were merged into plastic_bottle and bottle_cap; boxes were clipped at image boundaries. Further augmentation during training is recorded in the training configuration. Source revisions, image checksums and source filenames are in dataset-manifest.json.

The navigation environment, observations and trajectories are synthetic; their simulation results are not field measurements.
'''
 write(pack/'DATA_CREDITS.md',credits)
 checks={file.relative_to(pack).as_posix():digest(file)for file in sorted(pack.rglob('*'))if file.is_file()and file.name!='checksums.json'};write(pack/'checksums.json',json.dumps(checks,indent=2))
 model_zip=out/'Warirak_AI_Trained_Models_2026-10-27.zip';archive(pack,model_zip);ncnn_zip=out/'warirak-yolo26n-public-v2-ncnn.zip';archive(portable_ncnn,ncnn_zip)
 assets=root/'frontend/assets/models';assets.mkdir(parents=True,exist_ok=True)
 for src,name in [(pack/model_name,model_name),(model_zip,model_zip.name),(ncnn_zip,ncnn_zip.name),(pack/'evaluation.json','evaluation-public-v2.json'),(pack/'confidence-calibration.json','confidence-calibration.json'),(pack/'MODEL_CARD_TH.md','MODEL_CARD_TH.md'),(pack/'DATA_CREDITS.md','DATA_CREDITS.md')]:
  assert src.stat().st_size<24*1024*1024,'Model asset too large for the static hosting target';shutil.copy2(src,assets/name)
 release=dict(schema='warirak.model-release.v1',version='public-v2-2026-10-27',pytorch='/assets/models/'+model_name,ncnn='/assets/models/'+ncnn_zip.name,package='/assets/models/'+model_zip.name,evaluation='/assets/models/evaluation-public-v2.json',calibration='/assets/models/confidence-calibration.json',weights_sha256=evaluation['weights_sha256'],field_validated=False)
 write(assets/'release.json',json.dumps(release,indent=2))
 if not a.skip_dataset_zip:
  with zipfile.ZipFile(out/'Warirak_YOLO_Public_Dataset.zip','w',zipfile.ZIP_DEFLATED)as z:
   for r in manifest['images']:
    z.write(data/r['file'],r['file']);label=Path('labels')/r['split']/(Path(r['file']).stem+'.txt');z.write(data/label,label.as_posix())
   z.write(data/'manifest.json','manifest.json');z.write(data/'data.yaml','data.yaml');z.writestr('DATA_CREDITS.md',credits)
 print(json.dumps({'model_pack':str(model_zip),'ncnn_zip':str(ncnn_zip),'published_assets':str(assets),'weights_sha256':evaluation['weights_sha256'],'dataset_images':len(manifest['images'])}))
if __name__=='__main__':main()
