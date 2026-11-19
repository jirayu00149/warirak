"""A resumable class-balanced public-data experiment. Promotion uses validation only."""
import argparse,csv,datetime,gc,json,os,shutil,subprocess,sys,time
from pathlib import Path
from .dataset import validate,training_yaml,digest
from . import CLASSES

def promotion_gate(baseline,candidate,min_gain=.003,max_class_drop=.02):
    return candidate['map50_95']>=baseline['map50_95']+min_gain and all(candidate['classes'].get(c,0)>=baseline['classes'][c]-max_class_drop for c in CLASSES)

def atomic_json(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2),encoding='utf-8');tmp.replace(path)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ['base','data','out']:p.add_argument('--'+flag,type=Path,required=True)
    p.add_argument('--epochs',type=int,default=45);p.add_argument('--resume',action='store_true');a=p.parse_args()
    import psutil
    root=a.out.resolve();root.mkdir(parents=True,exist_ok=True);status_path=root/'status.json';lock=root/'training-lock.json';project=Path(__file__).resolve().parents[2]
    if lock.exists():
        old=json.loads(lock.read_text())
        if psutil.pid_exists(old['pid']):
            process=psutil.Process(old['pid'])
            if abs(process.create_time()-old.get('created_at_s',0))<1:raise RuntimeError('This training process is still running')
    if status_path.exists() and not a.resume:raise RuntimeError('Run already exists; inspect it and use --resume instead of overwriting')
    previous=json.loads(status_path.read_text()) if status_path.exists() else {}
    start_ms=previous.get('started_at_ms',int(time.time()*1000));epoch=previous.get('epoch',0);last_sync=0;phase=previous.get('failed_phase',previous.get('phase'))
    recipe=dict(imgsz=800,batch=8,epochs=a.epochs,optimizer='AdamW',lr0=.00008,cls_pw=.5,seed=61,patience=12,cos_lr=True,close_mosaic=10,mosaic=.15,scale=.4,hsv_s=.45,hsv_v=.3,fliplr=.5,flipud=0.,degrees=5.,mixup=0.,workers=0,cache=False,deterministic=True,save_period=-1,amp=True)
    atomic_json(lock,{'pid':os.getpid(),'created_at_s':psutil.Process().create_time()})
    def sync():
        nonlocal last_sync
        try:
            subprocess.run([sys.executable,str(project/'tools/sync_ai_registry.py'),'--run',str(root)],cwd=project,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=100)
            (root/'database-sync-error.txt').unlink(missing_ok=True)
        except Exception as error:(root/'database-sync-error.txt').write_text(str(error),encoding='utf-8')
        last_sync=time.time()
    def state(phase,update_db=True,**fields):
        nonlocal current_phase
        current_phase=phase
        value=dict(phase=phase,pid=os.getpid(),process_created_at_s=psutil.Process().create_time(),run_id=root.name,dataset_id=a.data.name,data=str(a.data.resolve()),started_at_ms=start_ms,updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),epoch=epoch,total_epochs=a.epochs,recipe=recipe,**fields)
        atomic_json(status_path,value);print('WARIRAK_STATUS '+json.dumps(value),flush=True)
        if update_db:sync()
    current_phase=phase
    try:
        os.environ['YOLO_CONFIG_DIR']=str(root/'runtime-config');os.environ['OMP_NUM_THREADS']='4';os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
        dataset=validate(a.data)
        if not dataset['valid']:raise ValueError('Dataset validation failed')
        protocol=dict(schema='warirak.balanced-protocol.v1',frozen_before_training=True,base_weights_sha256=digest(a.base),dataset_manifest_sha256=digest(a.data/'manifest.json'),recipe=recipe,evaluation_imgsz=800,rect=False,selection_split='val',min_macro_gain=.003,max_class_drop=.02,test_used_for_selection=False,test_is_historical=True,validation_previously_exposed=True,fresh_independent_test_available=False,field_validated=False,hypothesis='Inverse-frequency class weighting and lower learning rate can recover cap performance lost in v3 without inventing additional images',reference='https://docs.ultralytics.com/modes/train/#train-settings')
        if(root/'protocol.json').exists():
            if json.loads((root/'protocol.json').read_text())!=protocol:raise ValueError('Frozen protocol or dataset changed; do not resume this run')
        else:atomic_json(root/'protocol.json',protocol)
        import torch,cv2
        from ultralytics import YOLO,settings
        from .evaluate import model_classes,report_from_metrics
        from .calibration import choose_thresholds,fixed_precision_recall
        torch.set_num_threads(4);cv2.setNumThreads(1);settings.update({k:False for k in ['sync','hub','wandb','mlflow','tensorboard','comet','clearml','neptune','raytune'] if k in settings})
        if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable; do not silently switch to prolonged CPU training')
        config=training_yaml(a.data,root/'data.yaml')
        def scores(m):return dict(map50_95=float(m.box.map),classes={CLASSES[int(k)]:float(m.box.ap[i]) for i,k in enumerate(m.box.ap_class_index)})
        baseline_file=root/'baseline-validation.json'
        if baseline_file.exists():baseline=json.loads(baseline_file.read_text())
        else:
            state('baseline_validation');model=YOLO(str(a.base),task='detect')
            if model_classes(model)!=CLASSES:raise ValueError('Class mapping differs from the published detector')
            measured=model.val(data=str(config),split='val',imgsz=800,rect=False,batch=4,device=0,workers=0,plots=False,project=str(root),name='baseline-validation',verbose=False)
            baseline=scores(measured);atomic_json(baseline_file,baseline);del model,measured;gc.collect();torch.cuda.empty_cache()
        last=root/'refinement/weights/last.pt';candidate_path=root/'refinement/weights/best.pt';history_file=root/'refinement/results.csv'
        history=list(csv.DictReader(history_file.open(encoding='utf-8'))) if history_file.exists() else []
        finished_before=phase in ['validation_selection','historical_test','ncnn_export','ncnn_check','artifacts_ready','retained_baseline']
        if not finished_before:
            if a.resume and (root/'refinement').exists() and not last.exists():raise RuntimeError('Interrupted training has no last checkpoint; inspect before starting another run')
            model=YOLO(str(last if a.resume and last.exists() else a.base),task='detect')
            def progress(trainer):
                nonlocal epoch
                epoch=trainer.epoch+1
                metrics={k:float(v) for k,v in trainer.metrics.items() if isinstance(v,(int,float))}
                state('training',update_db=epoch%5==0 or time.time()-last_sync>300,metrics=metrics)
            model.add_callback('on_fit_epoch_end',progress);state('training')
            if a.resume and last.exists():model.train(resume=True)
            else:model.train(data=str(config),device=0,project=str(root),name='refinement',exist_ok=False,plots=True,verbose=False,**recipe)
            history=list(csv.DictReader(history_file.open(encoding='utf-8')));epoch=int(float(history[-1]['epoch']));del model;gc.collect();torch.cuda.empty_cache()
        elif history:epoch=int(float(history[-1]['epoch']))
        state('validation_selection');candidate=YOLO(str(candidate_path),task='detect')
        measured=candidate.val(data=str(config),split='val',imgsz=800,rect=False,batch=4,device=0,workers=0,plots=True,project=str(root),name='candidate-validation',exist_ok=True,verbose=False)
        candidate_score=scores(measured);promote=promotion_gate(baseline,candidate_score)
        selection=dict(protocol=protocol,baseline_map50_95=baseline['map50_95'],candidate_map50_95=candidate_score['map50_95'],baseline_classes=baseline['classes'],candidate_classes=candidate_score['classes'],promote=promote,test_used_for_selection=False)
        atomic_json(root/'selection.json',selection)
        if not promote:state('retained_baseline',metrics={'map50_95':candidate_score['map50_95']},reason='Class-balanced candidate failed the frozen validation gate');return
        calibration=choose_thresholds(measured);atomic_json(root/'confidence-calibration.json',calibration)
        weights=root/'warirak-yolo26n-public-v4.pt';shutil.copy2(candidate_path,weights)
        from ultralytics.utils.torch_utils import strip_optimizer
        strip_optimizer(str(weights));del candidate,measured;gc.collect();torch.cuda.empty_cache()
        # Historical test is descriptive only, after freezing the validation decision.
        def report(m,name):
            result=report_from_metrics(m,name,dataset,800);fixed=fixed_precision_recall(m,calibration)
            for c,v in fixed.items():result['classes'][c].update(v)
            for key in ['precision','recall']:result['overall'][key]=sum(v[key] for v in fixed.values())/len(fixed)
            result.update(confidence_calibration=calibration,model_selection=selection,weights_sha256=digest(weights),dataset_manifest_sha256=digest(a.data/'manifest.json'),training_source='public_litter_datasets',test_is_historical=True,validation_previously_exposed=True,fresh_independent_test_available=False,boat_camera_validated=False,real_world_validated=False,limitations=['Historical exposed test and repeatedly used validation; no fresh independent accuracy claim','No boat-camera data or Raspberry Pi FPS measurement'])
            return result
        detector=YOLO(str(weights),task='detect');state('historical_test')
        metrics=detector.val(data=str(config),split='test',imgsz=800,rect=False,batch=1,device=0,workers=0,plots=True,project=str(root),name='historical-test',exist_ok=True,verbose=False)
        evaluation=report(metrics,weights.name);atomic_json(root/'evaluation.json',evaluation)
        state('ncnn_export');ncnn=Path(detector.export(format='ncnn',imgsz=800,batch=1,device='cpu'));del detector,metrics;gc.collect();torch.cuda.empty_cache();state('ncnn_check')
        exported=YOLO(str(ncnn),task='detect');m=exported.val(data=str(config),split='test',imgsz=800,rect=False,batch=1,device='cpu',workers=0,plots=False,project=str(root),name='ncnn-historical-test',exist_ok=True,verbose=False)
        result=report(m,ncnn.name);diff={k:result['overall'][k]-evaluation['overall'][k] for k in ['map50','map50_95']};consistent=max(abs(v) for v in diff.values())<=.02
        result.update(backend='NCNN',test_hardware='Windows PC CPU, not Raspberry Pi',pi_fps_measured=False,export_consistent=consistent,pytorch_metric_difference=diff);atomic_json(root/'export-evaluation.json',result)
        if not consistent:raise RuntimeError('NCNN export gate failed')
        state('artifacts_ready',metrics={'map50_95':candidate_score['map50_95']},needs_review_and_publication=True)
    except Exception as error:state('needs_repair',failed_phase=current_phase,error=type(error).__name__+': '+str(error));raise
    finally:lock.unlink(missing_ok=True)

if __name__=='__main__':main()
