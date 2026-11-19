"""Train and evaluate a public-data YOLO baseline locally; never upload training images."""
import argparse,datetime,json,os,time,shutil
from pathlib import Path
from .dataset import validate,training_yaml,digest
from .evaluate import report_from_metrics,model_classes
from . import CLASSES
from .calibration import choose_thresholds,fixed_precision_recall

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,default=Path('data/public-v1'));p.add_argument('--epochs',type=int,default=120);p.add_argument('--imgsz',type=int,default=800);p.add_argument('--batch',type=int,default=4);p.add_argument('--resume',type=Path);a=p.parse_args()
 os.environ['YOLO_CONFIG_DIR']=str(Path('data/runtime-config').resolve())
 os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
 os.environ['OMP_NUM_THREADS']='4'
 import torch,cv2
 from ultralytics import YOLO,settings
 torch.set_num_threads(4);cv2.setNumThreads(1)
 settings.update({k:False for k in ['sync','hub','wandb','mlflow','tensorboard','comet','clearml','neptune','raytune']if k in settings})
 if not torch.cuda.is_available():raise RuntimeError('CUDA is not available; refusing a silent CPU fallback')
 report=validate(a.data)
 if not report['valid']:raise ValueError(json.dumps(report))
 root=Path('runs/public-yolo26n-v1').resolve();root.mkdir(parents=True,exist_ok=True)
 config=training_yaml(a.data,root/'data.yaml');status=root/'status.json';start=time.time()
 def state(phase,**fields):
  value={'phase':phase,'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_seconds':round(time.time()-start,1),**fields}
  status.write_text(json.dumps(value,indent=2),encoding='utf-8');print('WARIRAK_STATUS '+json.dumps(value),flush=True)
 state('initializing',gpu=torch.cuda.get_device_name(0),dataset=report)
 model=YOLO(str(a.resume)if a.resume else'yolo26n.pt')
 def progress(trainer):
  metrics={k:float(v)for k,v in trainer.metrics.items()if isinstance(v,(int,float))}
  state('training',epoch=trainer.epoch+1,total_epochs=trainer.epochs,metrics=metrics,best_fitness=float(trainer.best_fitness),gpu_memory_reserved_mb=round(torch.cuda.memory_reserved()/1024**2),run_directory=str(trainer.save_dir))
 model.add_callback('on_fit_epoch_end',progress)
 if a.resume:model.train(resume=True,workers=0,cache=False)
 else:model.train(data=str(config),model='yolo26n.pt',epochs=a.epochs,imgsz=a.imgsz,batch=a.batch,device=0,workers=0,cache=False,optimizer='AdamW',lr0=.001,cos_lr=True,patience=25,close_mosaic=15,seed=42,deterministic=True,fliplr=.5,flipud=0.,degrees=10.,scale=.4,mixup=0.,copy_paste=0.,project=str(root),name='training',exist_ok=False,save_period=10,plots=True,verbose=False,amp=True)
 run=Path(model.trainer.save_dir);best=run/'weights/best.pt'
 if not best.is_file():raise RuntimeError('Training did not produce best.pt')
 state('calibrating_on_validation',weights=str(best),selection='best validation fitness only')
 detector=YOLO(str(best))
 if model_classes(detector)!=CLASSES:raise ValueError('Model classes do not match the project')
 validation_metrics=detector.val(data=str(config),split='val',imgsz=a.imgsz,batch=4,device=0,workers=0,plots=False,project=str(root),name='confidence-calibration',exist_ok=False,verbose=False)
 calibration=choose_thresholds(validation_metrics)
 (root/'confidence-calibration.json').write_text(json.dumps(calibration,indent=2),encoding='utf-8')
 state('evaluating_held_out_test',weights=str(best),selection='best validation fitness only')
 metrics=detector.val(data=str(config),split='test',imgsz=a.imgsz,batch=4,device=0,workers=0,plots=True,project=str(root),name='held-out-test',exist_ok=False,verbose=False)
 result=report_from_metrics(metrics,'warirak-yolo26n-public-v1.pt',report,a.imgsz)
 fixed=fixed_precision_recall(metrics,calibration)
 for name,values in fixed.items():result['classes'][name].update(values)
 result['overall']['precision']=sum(m['precision']for m in fixed.values())/len(fixed)
 result['overall']['recall']=sum(m['recall']for m in fixed.values())/len(fixed)
 result['confidence_calibration']=calibration
 result['metric_definition']='mAP follows standard Ultralytics detection evaluation. Precision/recall are interpolated IoU-0.5 PR curves at per-class confidence thresholds chosen on validation only, fixed before test evaluation. Not a collection-success rate.'
 result.update(dataset_manifest_sha256=digest(a.data/'manifest.json'),weights_sha256=digest(best),training_source='public_litter_datasets',real_world_validated=False,boat_camera_validated=False,selection='best validation fitness; test evaluated after training',limitations=['No local boat-camera data was used','Public-dataset results do not establish accuracy on the university pond','Bottle caps have limited labelled examples and are often very small'])
 (root/'evaluation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 shutil.copy2(best,root/'warirak-yolo26n-public-v1.pt')
 shutil.copy2(a.data/'manifest.json',root/'dataset-manifest.json')
 (root/'provenance.json').write_text(json.dumps({'torch':torch.__version__,'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(0),'data_manifest_sha256':result['dataset_manifest_sha256'],'weights_sha256':result['weights_sha256'],'config':vars(a)|{'data':str(a.data),'resume':str(a.resume)if a.resume else None},'real_world_validated':False},indent=2),encoding='utf-8')
 state('complete',evaluation=result,weights=str(root/'warirak-yolo26n-public-v1.pt'))
if __name__=='__main__':main()
