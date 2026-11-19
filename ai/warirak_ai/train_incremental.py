"""Continue public-data training; choose on validation and retain the old release until review."""
import argparse,csv,datetime,gc,json,os,shutil,subprocess,sys,time
from pathlib import Path
from .dataset import validate,training_yaml,digest
from .evaluate import report_from_metrics,model_classes
from .calibration import choose_thresholds,fixed_precision_recall
from . import CLASSES

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--data',type=Path,required=True);p.add_argument('--base-data',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--prepare-pid',type=int,required=True);p.add_argument('--epochs',type=int,default=35);a=p.parse_args()
 import psutil
 root=a.out.resolve();root.mkdir(parents=True,exist_ok=True);lock=root/'training-lock.json'
 if lock.exists()and psutil.pid_exists(json.loads(lock.read_text())['pid']):raise RuntimeError('Incremental training is already running')
 lock.write_text(json.dumps({'pid':os.getpid()}));start_ms=int(time.time()*1000);epoch=0;phase='waiting_for_data';project=Path(__file__).resolve().parents[2];last_sync=0
 def sync():
  try:subprocess.run([sys.executable,str(project/'tools/sync_ai_registry.py'),'--run',str(root)],cwd=project,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=100)
  except Exception as error:(root/'database-sync-error.txt').write_text(str(error),encoding='utf-8')
 def state(value,update_db=True,**fields):
  nonlocal phase,last_sync
  phase=value;v=dict(phase=value,pid=os.getpid(),data=str(a.data.resolve()),started_at_ms=start_ms,updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),epoch=epoch,total_epochs=a.epochs,**fields)
  (root/'status.json').write_text(json.dumps(v,indent=2),encoding='utf-8');print('WARIRAK_STATUS '+json.dumps(v),flush=True)
  if update_db:sync();last_sync=time.time()
 try:
  state('waiting_for_data')
  while not(a.data/'validation.json').exists():
   if not psutil.pid_exists(a.prepare_pid):raise RuntimeError('Data preparation exited before validation; inspect public-v3-preparation.log')
   time.sleep(15)
  dataset=validate(a.data)
  if not dataset['valid']:raise ValueError('Prepared data failed validation')
  base_manifest=json.loads((a.base_data/'manifest.json').read_text(encoding='utf-8'));new_manifest=json.loads((a.data/'manifest.json').read_text(encoding='utf-8'))
  for split in ['val','test']:
   rows=lambda m:sorted((r['id'],r['sha256'],json.dumps(r['boxes'],sort_keys=True))for r in m['images']if r['split']==split)
   if rows(base_manifest)!=rows(new_manifest):raise ValueError('Held-out images or labels changed')
  protocol=dict(schema='warirak.incremental-protocol.v1',frozen_before_training=True,base_weights_sha256=digest(a.base),dataset_manifest_sha256=digest(a.data/'manifest.json'),imgsz=800,rect=False,candidate='best validation checkpoint from one fixed refinement recipe',selection_split='val',selection_criterion='mAP50-95 improves by at least0.003; neither class falls by more than0.02 mAP50-95',test_used_for_selection=False,test_is_historical=True,fresh_independent_test_available=False,field_validated=False)
  (root/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
  os.environ['YOLO_CONFIG_DIR']=str(root/'runtime-config');os.environ['OMP_NUM_THREADS']='4';os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
  import torch,cv2
  from ultralytics import YOLO,settings
  torch.set_num_threads(4);cv2.setNumThreads(1);settings.update({k:False for k in ['sync','hub','wandb','mlflow','tensorboard','comet','clearml','neptune','raytune']if k in settings})
  config=training_yaml(a.data,root/'data.yaml');model=YOLO(str(a.base),task='detect')
  if model_classes(model)!=CLASSES:raise ValueError('Unexpected detector classes')
  state('baseline_validation');baseline=model.val(data=str(config),split='val',imgsz=800,rect=False,batch=4,device=0,workers=0,plots=False,project=str(root),name='baseline-validation',verbose=False)
  baseline_scores={CLASSES[int(k)]:float(baseline.box.ap[i])for i,k in enumerate(baseline.box.ap_class_index)};baseline_map=float(baseline.box.map);del baseline;gc.collect();torch.cuda.empty_cache()
  def progress(trainer):
   nonlocal epoch
   epoch=trainer.epoch+1;metrics={k:float(v)for k,v in trainer.metrics.items()if isinstance(v,(int,float))};state('training',update_db=epoch%5==0 or time.time()-last_sync>300,metrics=metrics)
  model.add_callback('on_fit_epoch_end',progress)
  model.train(data=str(config),epochs=a.epochs,imgsz=800,batch=8,device=0,workers=0,cache=False,optimizer='AdamW',lr0=.00015,cos_lr=True,patience=12,close_mosaic=10,mosaic=.15,scale=.4,hsv_s=.45,hsv_v=.3,fliplr=.5,flipud=0.,degrees=5.,mixup=0.,seed=47,deterministic=True,project=str(root),name='refinement',exist_ok=False,save_period=10,plots=True,verbose=False,amp=True)
  # Final Ultralytics validation can emit one extra fit callback. The CSV records actual epochs.
  history=list(csv.DictReader((Path(model.trainer.save_dir)/'results.csv').open(encoding='utf-8')))
  epoch=int(float(history[-1]['epoch']))if history else epoch
  candidate_path=Path(model.trainer.save_dir)/'weights/best.pt';del model;gc.collect();torch.cuda.empty_cache();candidate=YOLO(str(candidate_path),task='detect');state('validation_selection')
  measured=candidate.val(data=str(config),split='val',imgsz=800,rect=False,batch=4,device=0,workers=0,plots=True,project=str(root),name='candidate-validation',verbose=False)
  scores={CLASSES[int(k)]:float(measured.box.ap[i])for i,k in enumerate(measured.box.ap_class_index)};score=float(measured.box.map);promote=score>=baseline_map+.003 and all(scores.get(c,0)>=baseline_scores[c]-.02 for c in CLASSES)
  selection=dict(protocol=protocol,baseline_map50_95=baseline_map,candidate_map50_95=score,baseline_classes=baseline_scores,candidate_classes=scores,promote=promote,test_used_for_selection=False)
  (root/'selection.json').write_text(json.dumps(selection,indent=2),encoding='utf-8')
  if not promote:state('retained_baseline',metrics={'map50_95':score},reason='Candidate did not pass validation improvement gates');return
  calibration=choose_thresholds(measured);(root/'confidence-calibration.json').write_text(json.dumps(calibration,indent=2),encoding='utf-8');weights=root/'warirak-yolo26n-public-v3.pt';shutil.copy2(candidate_path,weights)
  from ultralytics.utils.torch_utils import strip_optimizer
  strip_optimizer(str(weights));del candidate,measured;gc.collect();torch.cuda.empty_cache();state('historical_test')
  detector=YOLO(str(weights),task='detect');metrics=detector.val(data=str(config),split='test',imgsz=800,rect=False,batch=1,device=0,workers=0,plots=True,project=str(root),name='historical-test',verbose=False)
  def report(m,name):
   result=report_from_metrics(m,name,dataset,800);fixed=fixed_precision_recall(m,calibration)
   for c,v in fixed.items():result['classes'][c].update(v)
   for key in ['precision','recall']:result['overall'][key]=sum(v[key]for v in fixed.values())/len(fixed)
   result.update(metric_definition='mAP follows Ultralytics; precision/recall at validation-selected per-class IoU0.5 thresholds. Test is historical, previously exposed; not fresh independent validation.',confidence_calibration=calibration,model_selection=selection,weights_sha256=digest(weights),dataset_manifest_sha256=digest(a.data/'manifest.json'),training_source='public_litter_datasets',test_is_historical=True,fresh_independent_test_available=False,boat_camera_validated=False,real_world_validated=False,limitations=['Previously exposed historical test; no new independent accuracy claim','Public source capture groups are inferred','No boat-camera field evaluation or measured Pi FPS'])
   return result
  evaluation=report(metrics,weights.name);(root/'evaluation.json').write_text(json.dumps(evaluation,indent=2),encoding='utf-8');shutil.copy2(a.data/'manifest.json',root/'dataset-manifest.json');state('ncnn_export');ncnn=Path(detector.export(format='ncnn',imgsz=800,batch=1,device='cpu'));del detector,metrics;gc.collect();torch.cuda.empty_cache();state('ncnn_check')
  exported=YOLO(str(ncnn),task='detect');m=exported.val(data=str(config),split='test',imgsz=800,rect=False,batch=1,device='cpu',workers=0,plots=False,project=str(root),name='ncnn-historical-test',verbose=False);result=report(m,ncnn.name);diff={k:result['overall'][k]-evaluation['overall'][k]for k in ['map50','map50_95']};consistent=max(abs(v)for v in diff.values())<=.02
  result.update(backend='NCNN',test_hardware='AMD Ryzen7 6800HS CPU on Windows, not Raspberry Pi',pi_fps_measured=False,export_consistent=consistent,pytorch_metric_difference=diff);(root/'export-evaluation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
  if not consistent:raise RuntimeError('NCNN compatibility gate failed')
  state('artifacts_ready',metrics={'map50_95':score},needs_review_and_publication=True)
 except Exception as error:state('needs_repair',error=type(error).__name__+': '+str(error));raise
 finally:lock.unlink(missing_ok=True)
if __name__=='__main__':main()
