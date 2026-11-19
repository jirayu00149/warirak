"""Measure the exported NCNN detector; this is a PC compatibility check, not Pi FPS."""
import argparse,json,os
from pathlib import Path
from .dataset import validate,training_yaml
from .evaluate import report_from_metrics,model_classes
from .calibration import fixed_precision_recall
from . import CLASSES

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path('runs/public-yolo26n-v2'));p.add_argument('--ncnn',type=Path);a=p.parse_args();root=a.root.resolve();report=json.loads((root/'evaluation.json').read_text());ncnn=a.ncnn or root/'warirak-yolo26n-public-v2_ncnn_model'
 os.environ['YOLO_CONFIG_DIR']=str(Path('data/runtime-config').resolve());os.environ['OMP_NUM_THREADS']='4'
 import torch,cv2
 from ultralytics import YOLO
 torch.set_num_threads(4);cv2.setNumThreads(1)
 selected=report['model_selection']['selected']['model'];data=Path('data/public-v2'if selected=='cap_refinement_best'else'data/public-v1');dataset=validate(data)
 if not dataset['valid']:raise ValueError('Dataset validation failed')
 config=training_yaml(data,root/'export-evaluation-data.yaml');model=YOLO(str(ncnn),task='detect')
 if model_classes(model)!=CLASSES:raise ValueError('NCNN classes differ from PyTorch')
 metrics=model.val(data=str(config),split='test',imgsz=report['imgsz'],batch=1,rect=False,device='cpu',workers=0,plots=False,project=str(root),name='ncnn-held-out-test',verbose=False)
 result=report_from_metrics(metrics,ncnn.name,dataset,report['imgsz']);fixed=fixed_precision_recall(metrics,report['confidence_calibration'])
 for name,values in fixed.items():result['classes'][name].update(values)
 result['overall']['precision']=sum(m['precision']for m in fixed.values())/len(fixed);result['overall']['recall']=sum(m['recall']for m in fixed.values())/len(fixed)
 differences={key:result['overall'][key]-report['overall'][key]for key in ['map50','map50_95']};consistent=max(abs(v)for v in differences.values())<=.02
 result.update(metric_definition=report['metric_definition'],backend='NCNN',test_hardware='AMD Ryzen 7 6800HS CPU on Windows; not Raspberry Pi',pi_fps_measured=False,real_world_validated=False,export_consistent=consistent,pytorch_metric_difference=differences,confidence_calibration=report['confidence_calibration'])
 (root/'export-evaluation.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps({'export_consistent':consistent,'overall':result['overall'],'pytorch_metric_difference':differences,'pi_fps_measured':False}),flush=True)
 if not consistent:raise RuntimeError('NCNN differs materially from the selected detector; inspect before deployment')
if __name__=='__main__':main()
