"""Freeze detector/resolution using validation; evaluate the selected artifact on test."""
import argparse,datetime,gc,json,os,shutil,time
from pathlib import Path
from .dataset import validate,training_yaml,digest
from .evaluate import report_from_metrics,model_classes
from .calibration import choose_thresholds,fixed_precision_recall
from . import CLASSES

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path('runs/public-yolo26n-v2'));p.add_argument('--candidate',type=Path);a=p.parse_args()
 os.environ['YOLO_CONFIG_DIR']=str(Path('data/runtime-config').resolve());os.environ['OMP_NUM_THREADS']='4'
 import torch,cv2
 from ultralytics import YOLO
 from ultralytics.utils.torch_utils import strip_optimizer
 torch.set_num_threads(4);cv2.setNumThreads(1)
 root=a.root.resolve();protocol_path=Path('evaluation-protocol.json');protocol=json.loads(protocol_path.read_text());assert protocol['selection_split']=='val'and protocol['test_results_used_for_selection']is False
 candidate=a.candidate or root/'refinement/weights/best.pt';choices=[('warmup_best',root/'baseline.pt',Path('data/public-v1')),('cap_refinement_best',candidate,Path('data/public-v2'))]
 status=root/'finalization-status.json';start=time.time()
 def state(phase,**fields):
  result=dict(phase=phase,elapsed_seconds=round(time.time()-start,1),updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),**fields);status.write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
 rows=[];calibrations={};reports={};configs={}
 for name,weights,data in choices:
  report=validate(data)
  if not report['valid']:raise ValueError('Dataset did not pass the frozen manifest checks')
  reports[name]=report;configs[name]=training_yaml(data,root/(name+'-finalization-data.yaml'))
  for size in protocol['candidate_resolutions']:
   state('validation_comparison',model=name,imgsz=size)
   model=YOLO(str(weights))
   if model_classes(model)!=CLASSES:raise ValueError('Unexpected model classes')
   metrics=model.val(data=str(configs[name]),split='val',imgsz=size,batch=2,rect=False,device=0,workers=0,plots=False,project=str(root/'validation-grid'),name=name+'-'+str(size),exist_ok=False,verbose=False)
   row=dict(model=name,weights=str(weights),imgsz=size,map50=float(metrics.box.map50),map50_95=float(metrics.box.map));rows.append(row);calibrations[(name,size)]=choose_thresholds(metrics)
   del model,metrics;gc.collect();torch.cuda.empty_cache()
 rows.sort(key=lambda r:(-r['map50_95'],r['imgsz']));chosen=rows[0];name=chosen['model'];size=chosen['imgsz'];data=next(data for model,_,data in choices if model==name);calibration=calibrations[(name,size)]
 selection=dict(schema='warirak.detector-selection.v1',protocol=protocol,protocol_sha256=digest(protocol_path),validation_results=rows,selected={k:v for k,v in chosen.items()if k!='weights'},test_results_used_for_selection=False)
 (root/'final-selection.json').write_text(json.dumps(selection,indent=2));state('selection_frozen',selection=selection)
 weights=root/'warirak-yolo26n-public-v2.pt';strip_optimizer(chosen['weights'],s=str(weights))
 (root/'confidence-calibration.json').write_text(json.dumps(calibration,indent=2))
 # The training driver's fixed-resolution diagnostic is retained but never read for selection.
 previous=root/'evaluation.json'
 if previous.exists():shutil.copy2(previous,root/'preliminary-960-diagnostic.json')
 state('final_held_out_test',model=name,imgsz=size)
 model=YOLO(str(weights));metrics=model.val(data=str(configs[name]),split='test',imgsz=size,batch=2,rect=False,device=0,workers=0,plots=True,project=str(root),name='final-held-out-test',exist_ok=False,verbose=False)
 report=report_from_metrics(metrics,weights.name,reports[name],size);fixed=fixed_precision_recall(metrics,calibration)
 for key,values in fixed.items():report['classes'][key].update(values)
 report['overall']['precision']=sum(v['precision']for v in fixed.values())/len(fixed);report['overall']['recall']=sum(v['recall']for v in fixed.values())/len(fixed)
 report.update(metric_definition='mAP follows Ultralytics detection evaluation. Precision and recall are fixed-validation-threshold IoU-0.5 PR curves, not a field collection success rate.',confidence_calibration=calibration,model_selection=selection,weights_sha256=digest(weights),dataset_manifest_sha256=digest(data/'manifest.json'),training_source='public_litter_datasets',boat_camera_validated=False,real_world_validated=False,limitations=['Public data only; not a university-pond field test','Source capture groups are inferred and image similarity filtering cannot prove all scene independence','Test has 37 cap instances, so cap estimates have considerable uncertainty'])
 (root/'evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');shutil.copy2(data/'manifest.json',root/'dataset-manifest.json')
 state('complete',weights=str(weights),imgsz=size,selected_model=name,evaluation=report)
if __name__=='__main__':main()
