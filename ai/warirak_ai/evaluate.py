"""Write measured, held-out evaluation results for Dashboard import."""
import argparse,json,datetime
from pathlib import Path
from . import CLASSES
from .dataset import training_yaml,validate,digest
from .calibration import load_calibration,fixed_precision_recall

def model_classes(model):
    names=model.names
    return[names[i]for i in range(len(names))]if isinstance(names,dict)else list(names)

def report_from_metrics(metrics,model_name,dataset_report,imgsz):
    classes={name:None for name in CLASSES}
    for row,class_id in enumerate(metrics.box.ap_class_index):
        class_id=int(class_id)
        if class_id not in range(len(CLASSES)):continue
        p,r,ap50,ap=metrics.box.class_result(row)
        classes[CLASSES[class_id]]=dict(zip(['precision','recall','map50','map50_95'],map(float,[p,r,ap50,ap])))
    return{'schema':'warirak.evaluation.v1','source':'measured_evaluation','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'model':str(model_name),'split':'test','imgsz':imgsz,'metric_definition':'Ultralytics detection validation: P/R from its PR evaluation; mAP IoU 0.5 and 0.5:0.95. Not a collection-success rate.','overall':{'precision':float(metrics.box.mp),'recall':float(metrics.box.mr),'map50':float(metrics.box.map50),'map50_95':float(metrics.box.map)},'classes':classes,'evaluated_class_ids':list(map(int,metrics.box.ap_class_index)),'dataset':dataset_report,'complete':all(v is not None for v in classes.values())}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);p.add_argument('--weights',type=Path,required=True);p.add_argument('--imgsz',type=int,default=640);p.add_argument('--device',default='cpu');p.add_argument('--out',type=Path,default=Path('runs/evaluation.json'));p.add_argument('--thresholds',type=Path,help='Validation-selected confidence-calibration.json');a=p.parse_args()
    if not a.weights.exists():p.exit(2,'Trained model path does not exist. Train your custom detector first.\n')
    report=validate(a.data)
    if not report['valid']:p.exit(2,json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    data=training_yaml(a.data,a.out.parent/'evaluation-data.yaml')
    from ultralytics import YOLO
    calibration=load_calibration(a.thresholds)if a.thresholds else None
    model=YOLO(str(a.weights),task='detect')
    if model_classes(model)!=CLASSES:p.exit(2,'Weights must contain the project classes in order: plastic_bottle, bottle_cap\n')
    metrics=model.val(data=str(data),split='test',imgsz=a.imgsz,batch=1,rect=False,device=a.device,workers=0,plots=True,project=str(a.out.parent),name='test-evaluation',exist_ok=False)
    result=report_from_metrics(metrics,a.weights,report,a.imgsz)
    if calibration:
        fixed=fixed_precision_recall(metrics,calibration)
        for name,values in fixed.items():result['classes'][name].update(values)
        if fixed:
            for key in ['precision','recall']:result['overall'][key]=sum(m[key]for m in fixed.values())/len(fixed)
        result['confidence_calibration']=calibration
        result['metric_definition']='mAP follows Ultralytics detection evaluation. Precision and recall are fixed-validation-threshold IoU-0.5 PR curves, not a field collection success rate.'
    result['dataset_manifest_sha256']=digest(a.data/'manifest.json');a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print('Report:',a.out)
    if not result['complete']:p.exit(2,'Some target classes have no measured metrics; report marks them unavailable, not as the overall mAP.\n')

if __name__=='__main__':main()
