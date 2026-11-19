"""Train the project's two-class detector after validating independent image groups."""
import argparse,json,datetime,uuid,shutil
from pathlib import Path
from .dataset import validate,training_yaml

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);p.add_argument('--epochs',type=int,default=100);p.add_argument('--imgsz',type=int,default=640);p.add_argument('--batch',type=int,default=8);p.add_argument('--device',default='cpu');p.add_argument('--project',type=Path,default=Path('runs'));p.add_argument('--name',default='warirak');p.add_argument('--model',choices=['yolo26n','yolo11n'],default='yolo26n');p.add_argument('--from-scratch',action='store_true');p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    if a.epochs<1 or a.imgsz<320 or a.imgsz%32 or a.batch<1:p.error('epochs/batch must be positive; imgsz must be >=320 and divisible by 32')
    report=validate(a.data)
    if not report['valid']:p.exit(2,json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    provenance=a.project/'provenance'/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    config=training_yaml(a.data,provenance/'data.yaml')
    shutil.copy2(a.data/'manifest.json',provenance/'manifest.json')
    (provenance/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    settings=dict(data=str(config),epochs=a.epochs,imgsz=a.imgsz,batch=a.batch,device=a.device,workers=0,seed=42,deterministic=True,project=str(a.project),name=a.name,patience=30,close_mosaic=10,fliplr=.5,flipud=0.,degrees=10.,mixup=0.,copy_paste=0.,exist_ok=False)
    print(json.dumps({'dataset':report,'weights':a.model+('.yaml'if a.from_scratch else'.pt'),'training':settings},ensure_ascii=False,indent=2))
    (provenance/'training_config.json').write_text(json.dumps(settings,indent=2),encoding='utf-8')
    if a.dry_run:return
    try:from ultralytics import YOLO
    except ImportError:p.exit(2,'Install ai/requirements.txt before training\n')
    model=YOLO(a.model+('.yaml'if a.from_scratch else'.pt'))
    model.train(**settings)
    savedir=Path(model.trainer.save_dir)
    shutil.copytree(provenance,savedir/'provenance',dirs_exist_ok=True)
    print('Custom weights:',savedir/'weights/best.pt')
    print('Evaluate best.pt on the held-out test split. No field accuracy has been established yet.')

if __name__=='__main__':main()
