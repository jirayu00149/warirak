"""Refine cap detection and choose between baseline/refinement on validation only."""
import argparse,datetime,gc,json,os,shutil,time
from pathlib import Path
from . import CLASSES
from .dataset import validate,training_yaml,digest
from .evaluate import report_from_metrics,model_classes
from .calibration import choose_thresholds,fixed_precision_recall

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-model',type=Path,required=True);p.add_argument('--base-data',type=Path,default=Path('data/public-v1'));p.add_argument('--data',type=Path,default=Path('data/public-v2'));p.add_argument('--epochs',type=int,default=60);p.add_argument('--imgsz',type=int,default=960);p.add_argument('--batch',type=int,default=8);p.add_argument('--resume',type=Path);a=p.parse_args()
 os.environ['YOLO_CONFIG_DIR']=str(Path('data/runtime-config').resolve());os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8';os.environ['OMP_NUM_THREADS']='4'
 import torch,cv2
 from ultralytics import YOLO,settings
 torch.set_num_threads(4);cv2.setNumThreads(1);settings.update({k:False for k in ['sync','hub','wandb','mlflow','tensorboard','comet','clearml','neptune','raytune']if k in settings})
 report=validate(a.data)
 if not report['valid']:raise ValueError(json.dumps(report))
 base_report=validate(a.base_data)
 if not base_report['valid']:raise ValueError('Baseline dataset is invalid')
 base_manifest=json.loads((a.base_data/'manifest.json').read_text());candidate_manifest=json.loads((a.data/'manifest.json').read_text())
 for split in ['val','test']:
  def rows(manifest):return sorted((r['id'],r['sha256'],json.dumps(r['boxes'],sort_keys=True))for r in manifest['images']if r['split']==split)
  if rows(base_manifest)!=rows(candidate_manifest):raise ValueError('Refinement changed the held-out cohorts')
 root=Path('runs/public-yolo26n-v2').resolve();root.mkdir(parents=True,exist_ok=True);config=training_yaml(a.data,root/'data.yaml');start=time.time()
 def state(phase,**fields):
  value=dict(phase=phase,updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),elapsed_seconds=round(time.time()-start,1),**fields);(root/'status.json').write_text(json.dumps(value,indent=2),encoding='utf-8');print('WARIRAK_STATUS '+json.dumps(value),flush=True)
 state('baseline_validation',dataset=report)
 baseline=YOLO(str(a.base_model))
 if model_classes(baseline)!=CLASSES:raise ValueError('Unexpected baseline classes')
 baseline_metrics=baseline.val(data=str(config),split='val',imgsz=a.imgsz,batch=4,device=0,workers=0,plots=False,project=str(root),name='baseline-validation',verbose=False)
 baseline_score=float(baseline_metrics.box.map);baseline_calibration=choose_thresholds(baseline_metrics)
 base_copy=root/'baseline.pt';shutil.copy2(a.base_model,base_copy)
 del baseline,baseline_metrics;gc.collect();torch.cuda.empty_cache()
 model=YOLO(str(a.resume)if a.resume else str(base_copy))
 def progress(trainer):state('refinement_training',epoch=trainer.epoch+1,total_epochs=trainer.epochs,best_fitness=float(trainer.best_fitness),baseline_validation_map50_95=baseline_score,metrics={k:float(v)for k,v in trainer.metrics.items()if isinstance(v,(int,float))},gpu_memory_reserved_mb=round(torch.cuda.memory_reserved()/1024**2))
 model.add_callback('on_fit_epoch_end',progress)
 if a.resume:model.train(resume=True,workers=0,cache=False)
 else:model.train(data=str(config),epochs=a.epochs,imgsz=a.imgsz,batch=a.batch,device=0,workers=0,cache=False,optimizer='AdamW',lr0=.00025,cos_lr=True,patience=20,close_mosaic=15,mosaic=.25,scale=.25,fliplr=.5,flipud=0.,degrees=5.,mixup=0.,copy_paste=0.,seed=43,deterministic=True,project=str(root),name='refinement',exist_ok=False,save_period=10,plots=True,verbose=False,amp=True)
 candidate_path=Path(model.trainer.save_dir)/'weights/best.pt';candidate=YOLO(str(candidate_path));state('selecting_on_validation')
 candidate_metrics=candidate.val(data=str(config),split='val',imgsz=a.imgsz,batch=4,device=0,workers=0,plots=False,project=str(root),name='refinement-validation',verbose=False)
 candidate_score=float(candidate_metrics.box.map);use_candidate=candidate_score>baseline_score;calibration=choose_thresholds(candidate_metrics)if use_candidate else baseline_calibration
 selected=candidate_path if use_candidate else base_copy;weights=root/'warirak-yolo26n-public-v2.pt';shutil.copy2(selected,weights)
 selection=dict(criterion='maximum validation mAP50–95 at the same deployment resolution; test not used',baseline_map50_95=baseline_score,refinement_map50_95=candidate_score,selected='refinement'if use_candidate else'baseline',imgsz=a.imgsz,baseline_sha256=digest(base_copy),refinement_sha256=digest(candidate_path))
 (root/'selection.json').write_text(json.dumps(selection,indent=2));(root/'confidence-calibration.json').write_text(json.dumps(calibration,indent=2));del model,candidate,candidate_metrics;gc.collect();torch.cuda.empty_cache()
 state('evaluating_held_out_test',selection=selection)
 selected_data=a.data if use_candidate else a.base_data;selected_report=report if use_candidate else base_report;test_config=training_yaml(selected_data,root/'evaluation-data.yaml')
 detector=YOLO(str(weights));metrics=detector.val(data=str(test_config),split='test',imgsz=a.imgsz,batch=4,device=0,workers=0,plots=True,project=str(root),name='held-out-test',verbose=False)
 result=report_from_metrics(metrics,weights.name,selected_report,a.imgsz);fixed=fixed_precision_recall(metrics,calibration)
 for name,values in fixed.items():result['classes'][name].update(values)
 result['overall']['precision']=sum(m['precision']for m in fixed.values())/len(fixed);result['overall']['recall']=sum(m['recall']for m in fixed.values())/len(fixed)
 result.update(metric_definition='mAP follows Ultralytics detection evaluation; precision/recall are IoU-0.5 PR curves at per-class confidence selected on validation before test. Not collection success.',confidence_calibration=calibration,model_selection=selection,dataset_manifest_sha256=digest(selected_data/'manifest.json'),weights_sha256=digest(weights),training_source='public_litter_datasets',real_world_validated=False,boat_camera_validated=False,limitations=['No boat-camera field evaluation','External cap source lacks capture-session metadata; conservative similarity checks cannot prove all scenes independent','Only 37 caps in the held-out test; no claim of maximum or guaranteed accuracy'])
 (root/'evaluation.json').write_text(json.dumps(result,indent=2),encoding='utf-8');shutil.copy2(selected_data/'manifest.json',root/'dataset-manifest.json')
 (root/'provenance.json').write_text(json.dumps(dict(torch=torch.__version__,cuda=torch.version.cuda,gpu=torch.cuda.get_device_name(0),imgsz=a.imgsz,epochs_requested=a.epochs,batch=a.batch,weights_sha256=result['weights_sha256'],dataset_manifest_sha256=result['dataset_manifest_sha256'],model_selection=selection,real_world_validated=False),indent=2))
 state('complete',weights=str(weights),evaluation=result)
if __name__=='__main__':main()
