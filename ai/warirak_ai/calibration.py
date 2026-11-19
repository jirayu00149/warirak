"""Choose confidence thresholds on validation only; read test curves at fixed thresholds."""
import numpy as np
import json,math
from pathlib import Path
from . import CLASSES

def load_calibration(path):
 value=json.loads(Path(path).read_text(encoding='utf-8'))
 if value.get('schema')!='warirak.confidence-calibration.v1'or value.get('selection_split')!='val':raise ValueError('Invalid confidence calibration schema or selection split')
 thresholds=value.get('thresholds',{})
 if set(thresholds)!=set(CLASSES)or any(type(v)not in(int,float)or not math.isfinite(v)or not .05<=v<=.95 for v in thresholds.values()):raise ValueError('Invalid per-class confidence thresholds')
 return value

def choose_thresholds(metrics):
 box=metrics.box;thresholds={}
 for row,class_id in enumerate(box.ap_class_index):
  class_id=int(class_id)
  if class_id not in range(len(CLASSES)):continue
  curve=np.asarray(box.f1_curve[row],dtype=float);grid=np.asarray(box.px,dtype=float)
  if len(curve)!=len(grid)or not len(grid)or not np.all(np.isfinite(curve)):raise ValueError('Invalid validation confidence curve')
  smooth=np.convolve(np.pad(curve,(15,15),mode='edge'),np.ones(31)/31,mode='valid')
  thresholds[CLASSES[class_id]]=float(np.clip(grid[int(smooth.argmax())],.05,.95))
 if set(thresholds)!=set(CLASSES):raise ValueError('Validation has no measured curve for a target class')
 return dict(schema='warirak.confidence-calibration.v1',selection_split='val',method='maximum smoothed per-class validation F1; confidence bounded to 0.05–0.95',thresholds=thresholds)

def fixed_precision_recall(metrics,calibration):
 if calibration.get('selection_split')!='val':raise ValueError('Confidence thresholds must be selected on validation')
 result={};box=metrics.box
 for row,class_id in enumerate(box.ap_class_index):
  class_id=int(class_id)
  if class_id not in range(len(CLASSES)):continue
  name=CLASSES[class_id];threshold=calibration['thresholds'][name]
  result[name]={'precision':float(np.interp(threshold,box.px,box.p_curve[row])),'recall':float(np.interp(threshold,box.px,box.r_curve[row])),'confidence_threshold':threshold}
 return result
