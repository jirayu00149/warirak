"""Verify and package a completed balanced detector without running training/evaluation again."""
import argparse,csv,datetime,hashlib,json,shutil,zipfile
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def make_zip(folder,target):
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for file in sorted(folder.rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts:z.write(file,folder.name+'/'+file.relative_to(folder).as_posix())

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ['run','data','out']:p.add_argument('--'+arg,type=Path,required=True)
    p.add_argument('--activate-static',action='store_true',help='Only after staged assets and active D1 release are verified')
    a=p.parse_args();run=a.run.resolve();data=a.data.resolve();out=a.out.resolve();assets=PROJECT/'frontend/assets/models'
    if a.activate_static:
        release=read(assets/'release-public-v4.json');audit=read(out/'Warirak_Public_v4_Package_Audit.json')
        assert release==audit['release'] and sha(assets/'warirak-yolo26n-public-v4.pt')==audit['weights_sha256']
        assert sha(assets/'Warirak_AI_Public_v4_Models_2026-10-28.zip')==audit['model_zip_sha256']
        assert sha(assets/'warirak-yolo26n-public-v4-ncnn.zip')==audit['ncnn_zip_sha256']
        write(assets/'release.json',release);shutil.copy2(assets/'MODEL_CARD_PUBLIC_V4_TH.md',assets/'MODEL_CARD_TH.md');shutil.copy2(assets/'confidence-calibration-public-v4.json',assets/'confidence-calibration.json')
        audit['static_active']=True;write(out/'Warirak_Public_v4_Package_Audit.json',audit)
        print(json.dumps({'activated_static':True,'release':release['version'],'existing_archive_hashes_preserved':True}));return
    status=read(run/'status.json');selection=read(run/'selection.json');protocol=read(run/'protocol.json');evaluation=read(run/'evaluation.json');export=read(run/'export-evaluation.json');calibration=read(run/'confidence-calibration.json');manifest=read(data/'manifest.json')
    assert status['phase']=='artifacts_ready' and selection['promote'] is True
    assert protocol==selection['protocol'] and protocol['frozen_before_training'] and not selection['test_used_for_selection']
    assert selection['candidate_map50_95']>=selection['baseline_map50_95']+protocol['min_macro_gain']
    assert all(selection['candidate_classes'][c]>=v-protocol['max_class_drop'] for c,v in selection['baseline_classes'].items())
    weights=run/'warirak-yolo26n-public-v4.pt';weights_sha=sha(weights)
    assert weights_sha==evaluation['weights_sha256']==export['weights_sha256']
    manifest_sha=sha(data/'manifest.json');assert manifest_sha==protocol['dataset_manifest_sha256']==evaluation['dataset_manifest_sha256']==export['dataset_manifest_sha256']
    assert calibration['selection_split']=='val' and calibration==evaluation['confidence_calibration']==export['confidence_calibration']
    for report in [evaluation,export]:
        assert report['test_is_historical'] and report['validation_previously_exposed']
        assert not report['fresh_independent_test_available'] and not report['boat_camera_validated'] and not report['real_world_validated']
    assert export['export_consistent'] and max(abs(export['overall'][k]-evaluation['overall'][k]) for k in ['map50','map50_95'])<=.02
    assert all(abs(export['overall'][k]-evaluation['overall'][k]-export['pytorch_metric_difference'][k])<1e-10 for k in ['map50','map50_95'])
    assert evaluation['dataset']['counts']=={s:sum(r['split']==s for r in manifest['images']) for s in ['train','val','test']}
    history=list(csv.DictReader((run/'refinement/results.csv').open(encoding='utf-8')));actual=int(float(history[-1]['epoch']));assert actual==len(history)==status['epoch']
    best=int(float(max(history,key=lambda r:float(r['metrics/mAP50-95(B)']))['epoch']))
    pack=out/'Warirak_AI_Public_v4_Models_2026-10-28';pack.mkdir(parents=True,exist_ok=True)
    # Keep the already published v2 calibration/card addressable after switching the generic pointers.
    old=read(assets/'release.json')
    if old['version']=='public-v2-2026-10-27':
        preserved={**old,'calibration':'/assets/models/confidence-calibration-public-v2.json'}
        old_path=assets/'release-public-v2.json'
        if not old_path.exists():
            write(old_path,preserved);shutil.copy2(assets/'confidence-calibration.json',assets/'confidence-calibration-public-v2.json');shutil.copy2(assets/'MODEL_CARD_TH.md',assets/'MODEL_CARD_PUBLIC_V2_TH.md')
    shutil.copy2(weights,pack/weights.name)
    ncnn=run/'warirak-yolo26n-public-v4_ncnn_model';portable=pack/ncnn.name;portable.mkdir(exist_ok=True)
    for f in ncnn.iterdir():
        if f.is_file() and f.suffix in ['.bin','.param','.yaml','.py']:shutil.copy2(f,portable/f.name)
    assert (portable/'model.ncnn.bin').stat().st_size>1000000 and (portable/'model.ncnn.param').exists()
    for name in ['protocol.json','selection.json','baseline-validation.json','confidence-calibration.json']:shutil.copy2(run/name,pack/name)
    definition='mAP follows Ultralytics across confidence thresholds. Precision/recall are macro means of per-class IoU0.5 P/R at validation-selected fixed confidence thresholds. Historical previously exposed test; not a fresh independent or boat-camera field result.'
    for report,name in [(evaluation,'evaluation.json'),(export,'export-evaluation.json')]:
        report={**report,'metric_definition':definition};write(pack/name,report)
    shutil.copy2(data/'manifest.json',pack/'dataset-manifest.json')
    for name in ['args.yaml','results.csv']:shutil.copy2(run/'refinement'/name,pack/name)
    for name in ['LICENSE','THIRD_PARTY_NOTICES.md']:shutil.copy2(PROJECT/name,pack/name)
    shutil.copy2(assets/'DATA_CREDITS.md',pack/'DATA_CREDITS.md')
    for name in ['navigation-policy.json','navigation-selection-report.json']:shutil.copy2(PROJECT/'frontend/assets'/name,pack/name)
    nav_sha=sha(PROJECT/'frontend/assets/navigation-policy.json')
    release=dict(schema='warirak.model-release.v1',version='public-v4-2026-10-28',pytorch='/assets/models/'+weights.name,ncnn='/assets/models/warirak-yolo26n-public-v4-ncnn.zip',package='/assets/models/Warirak_AI_Public_v4_Models_2026-10-28.zip',evaluation='/assets/models/evaluation-public-v4.json',calibration='/assets/models/confidence-calibration-public-v4.json',model_card='/assets/models/MODEL_CARD_PUBLIC_V4_TH.md',weights_sha256=weights_sha,field_validated=False,test_is_historical=True,validation_previously_exposed=True)
    report=dict(schema='warirak.training-outcome.v1',created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),outcome='promoted',published_release=release['version'],previous_release='public-v2-2026-10-27',actual_epochs_completed=actual,epochs_planned=status['total_epochs'],early_stopping_patience=12,best_training_checkpoint_epoch=best,dataset_images=len(manifest['images']),dataset_counts=evaluation['dataset']['counts'],additional_images=0,selection=selection,selection_split='val',test_used_for_selection=False,historical_test_evaluated_in_this_run=True,test_is_historical=True,validation_previously_exposed=True,fresh_independent_test_available=False,boat_camera_validated=False,real_world_validated=False,ncnn_export_verified=True,ncnn_metric_difference=export['pytorch_metric_difference'],weights_sha256=weights_sha,dataset_manifest_sha256=manifest_sha,dataset_delivery='Warirak_YOLO_Public_Dataset_v3.zip (same1715images; no duplicate dataset archive)',navigation_policy_changed=False,navigation_policy_sha256=nav_sha,limitations=['Repeatedly used validation; existing historical test already exposed','No boat-camera dataset or field results','No measured Raspberry Pi FPS','234negative images under15%;49tinyboxes; inferred capture groups'])
    write(pack/'training-public-v4-report.json',report)
    table='\n'.join('| '+label+' | '+ ' | '.join(f"{evaluation['classes'][c][k]*100:.2f}%" for k in ['precision','recall','map50','map50_95'])+' |' for c,label in [('plastic_bottle','ขวดพลาสติก'),('bottle_cap','ฝาขวด')])
    card=f'''# วารีรักษ์: โมเดลตรวจจับ public-v4

คณะวิศวกรรมศาสตร์ มหาวิทยาลัยทักษิณ — 28 ตุลาคม 2569

## การเลือกโมเดล

เริ่มจาก public-v2 และปรับ YOLO26n บน NVIDIA RTX2050 โดยถ่วงน้ำหนักคลาส cls_pw=0.5 และ AdamW lr0=0.00008 ภาพ800px batch8 seed61 ฝึกจริง {actual} จากสูงสุด45รอบ ก่อน early stopping12รอบ checkpointดีที่สุดในประวัติอยู่รอบ{best}

| validation mAP50–95 ที่800px | รุ่นเดิม | รุ่นใหม่ |
|---|---:|---:|
| เฉลี่ยสองคลาส | {selection['baseline_map50_95']*100:.2f}% | {selection['candidate_map50_95']*100:.2f}% |
| ขวดพลาสติก | {selection['baseline_classes']['plastic_bottle']*100:.2f}% | {selection['candidate_classes']['plastic_bottle']*100:.2f}% |
| ฝาขวด | {selection['baseline_classes']['bottle_cap']*100:.2f}% | {selection['candidate_classes']['bottle_cap']*100:.2f}% |

ค่าเฉลี่ยเพิ่ม {(selection['candidate_map50_95']-selection['baseline_map50_95'])*100:.2f} จุดเปอร์เซ็นต์ ขวดดีขึ้น แต่ฝาขวดลดลง {(selection['baseline_classes']['bottle_cap']-selection['candidate_classes']['bottle_cap'])*100:.2f} จุดเปอร์เซ็นต์ ยังอยู่ในเกณฑ์ที่กำหนดก่อนฝึก: ค่าเฉลี่ยเพิ่มอย่างน้อย0.30จุด และแต่ละคลาสลดไม่เกิน2.00จุด เลือกจาก validation เท่านั้น ไม่ใช้คะแนน test เลือกโมเดล

## ผลเชิงพรรณนาบนชุด test เดิม

**ชุด test นี้เคยเปิดผลแล้ว ไม่ใช่ชุดทดสอบอิสระใหม่ และ validation ถูกใช้หลายรอบ ผลต่อไปนี้ไม่ใช่ความแม่นยำภาคสนาม**

ชุดข้อมูล public-v3 เดิมมี1,715ภาพ: train1,426 / validation147 / test142 ไม่ได้เพิ่มภาพหรือสร้างชุดภาพใหม่ในรอบนี้ test มีขวด98ชิ้นและฝาขวด37ชิ้น

| คลาส | Precision | Recall | mAP50 | mAP50–95 |
|---|---:|---:|---:|---:|
{table}

mAP50 รวม {evaluation['overall']['map50']*100:.2f}% และ mAP50–95 รวม {evaluation['overall']['map50_95']*100:.2f}% Precision/Recall ใช้IoU0.5ที่เกณฑ์รายคลาสซึ่งเลือกจากvalidation: ขวด {calibration['thresholds']['plastic_bottle']:.4f}, ฝาขวด {calibration['thresholds']['bottle_cap']:.4f} ส่วนmAPวัดตลอดช่วงความเชื่อมั่น ไม่ใช่อัตราเก็บขยะสำเร็จ

NCNNวัดบนCPUคอมพิวเตอร์ได้mAP50–95 {export['overall']['map50_95']*100:.2f}% ต่างจากPyTorch {export['pytorch_metric_difference']['map50_95']*100:.4f} จุดเปอร์เซ็นต์ ผ่านเกณฑ์ความสอดคล้องไม่เกิน2จุด ยังไม่ได้วัดFPSบนRaspberry Pi

## ใช้บน Pi/PC และข้อจำกัด

ติดตั้ง dependencies ในซอร์ส แล้วแตกแพ็ก NCNN หรือใช้น้ำหนักPyTorch พร้อม calibration ของรุ่นเดียวกัน:

```sh
cd ai
python -m warirak_ai.infer --weights /path/to/warirak-yolo26n-public-v4_ncnn_model --source 0 --imgsz 800 --thresholds /path/to/confidence-calibration.json --frames 300 --out runs/detections-v4.jsonl
```

เครื่องมืออ่านภาพและออกผลตรวจจับ ไม่ส่งมอเตอร์ ภาพบนกล้องเรือ แสงสะท้อน ความสูงกล้อง ระยะจริง และความหน่วงบนPi4ต้องวัดหลังประกอบ มีภาพไม่มีเป้าหมาย234ภาพและกรอบเล็กมาก49กรอบ แหล่งภาพบางส่วนไม่มีข้อมูลรอบถ่ายครบ การแยกกลุ่มและกรองภาพคล้ายลดความเสี่ยงแต่ไม่พิสูจน์ความเป็นอิสระทั้งหมด

นโยบายเดินเรือที่แนบยังเป็นรุ่นเดิม การฝึกstress-v2ไม่ผ่านเกณฑ์จึงไม่เปลี่ยนนโยบาย ผลขับในตัวจำลองไม่ใช่ผลเรือจริง โค้ดvisual_pilot/shadow_controlให้ข้อเสนอและการหยุดแบบshadow-only ไม่มีserial/GPIO/motor transport

ข้อมูลภาพเต็มใช้ Warirak_YOLO_Public_Dataset_v3.zip เดิม แพ็กนี้มีmanifest แหล่งข้อมูล ใบอนุญาต protocol ประวัติฝึก calibration และผลNCNNครบ

SHA256น้ำหนัก: `{weights_sha}`
SHA256datasetmanifest: `{manifest_sha}`
'''
    (pack/'MODEL_CARD_TH.md').write_text(card,encoding='utf-8');(pack/'TRAINING_V4_REPORT_TH.md').write_text(card,encoding='utf-8')
    write(pack/'release.json',release);write(pack/'checksums.json',{f.relative_to(pack).as_posix():sha(f) for f in pack.rglob('*') if f.is_file() and f.name!='checksums.json'})
    model_zip=out/'Warirak_AI_Public_v4_Models_2026-10-28.zip';ncnn_zip=out/'warirak-yolo26n-public-v4-ncnn.zip';make_zip(pack,model_zip);make_zip(portable,ncnn_zip)
    for src,name in [(weights,weights.name),(model_zip,model_zip.name),(ncnn_zip,ncnn_zip.name),(pack/'evaluation.json','evaluation-public-v4.json'),(pack/'export-evaluation.json','export-evaluation-public-v4.json'),(pack/'confidence-calibration.json','confidence-calibration-public-v4.json'),(pack/'training-public-v4-report.json','training-public-v4-report.json'),(pack/'MODEL_CARD_TH.md','MODEL_CARD_PUBLIC_V4_TH.md'),(pack/'TRAINING_V4_REPORT_TH.md','TRAINING_V4_REPORT_TH.md')]:
        assert src.stat().st_size<24*1024*1024;shutil.copy2(src,assets/name)
    write(assets/'release-public-v4.json',release)
    # Verify each archived file and binary against its manifest; no inference is repeated.
    with zipfile.ZipFile(model_zip) as z:
        checks=read(pack/'checksums.json')
        for name,digest in checks.items():assert hashlib.sha256(z.read(pack.name+'/'+name)).hexdigest()==digest,name
    dataset_zip=out/'Warirak_YOLO_Public_Dataset_v3.zip'
    assert dataset_zip.exists(),'Existing dataset delivery is required; do not create a duplicate blindly'
    with zipfile.ZipFile(dataset_zip) as z:assert hashlib.sha256(z.read('manifest.json')).hexdigest()==manifest_sha
    if a.activate_static:
        write(assets/'release.json',release);shutil.copy2(pack/'MODEL_CARD_TH.md',assets/'MODEL_CARD_TH.md');shutil.copy2(pack/'confidence-calibration.json',assets/'confidence-calibration.json')
    write(out/'Warirak_Public_v4_Package_Audit.json',dict(verified_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),release=release,weights_sha256=weights_sha,model_zip_sha256=sha(model_zip),ncnn_zip_sha256=sha(ncnn_zip),dataset_manifest_sha256=manifest_sha,actual_epochs=actual,best_epoch=best,selection=selection,export_difference=export['pytorch_metric_difference'],archived_hashes_verified=len(checks),static_active=a.activate_static))
    print(json.dumps({'verified':True,'release':release['version'],'model_zip':str(model_zip),'model_zip_bytes':model_zip.stat().st_size,'ncnn_zip_bytes':ncnn_zip.stat().st_size,'weights_sha256':weights_sha,'actual_epochs':actual,'static_active':a.activate_static}))

if __name__=='__main__':main()
