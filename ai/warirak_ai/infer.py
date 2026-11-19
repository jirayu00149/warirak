"""Run a trained detector on Pi/PC. Writes detections only; never controls motors."""
import argparse,datetime,json,time,sys
from pathlib import Path
from . import CLASSES
from .camera import Camera
from .evaluate import model_classes
from .calibration import load_calibration

def detection_event(frame_id,width,height,detections,latency_ms,captured_at_ms=None):
    completed=time.time()*1000
    return{'schema':'warirak.detection.v1','source':'detector','frame_id':frame_id,'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'captured_at_ms':captured_at_ms,'inference_completed_at_ms':completed,'image_size':[width,height],'latency_ms':round(latency_ms,2),'detections':detections,'collection_confirmed':False,'control_enabled':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--weights',type=Path,required=True);p.add_argument('--source',default='0');p.add_argument('--conf',type=float,default=.5);p.add_argument('--imgsz',type=int,default=640);p.add_argument('--frames',type=int,default=300);p.add_argument('--out',type=Path,default=Path('runs/detections.jsonl'));p.add_argument('--thresholds',type=Path,help='Validation-selected confidence-calibration.json');a=p.parse_args()
    if not a.weights.exists():p.exit(2,'Trained model path not found.\n')
    if not 0<a.conf<1 or a.frames<1:p.error('conf must be 0..1 and frames positive')
    thresholds=load_calibration(a.thresholds)['thresholds']if a.thresholds else{c:a.conf for c in CLASSES}
    from ultralytics import YOLO
    model=YOLO(str(a.weights),task='detect')
    if model_classes(model)!=CLASSES:p.exit(2,'The model must be trained for plastic_bottle and bottle_cap.\n')
    a.out.parent.mkdir(parents=True,exist_ok=True)
    if a.out.exists():p.exit(2,'Output already exists; choose a new JSONL path to preserve previous measurements.\n')
    with Camera(a.source,width=640,height=480)as camera,a.out.open('x',encoding='utf-8')as output:
        for frame_id in range(a.frames):
            frame=camera.read()
            if frame is None:break
            captured_at=time.time()*1000;start=time.perf_counter();result=model.predict(frame,imgsz=a.imgsz,rect=False,conf=min(thresholds.values()),verbose=False)[0];latency=(time.perf_counter()-start)*1000;height,width=frame.shape[:2];detections=[]
            for box in result.boxes:
                k=int(box.cls.item());confidence=float(box.conf.item())
                if confidence<thresholds[CLASSES[k]]:continue
                xyxy=list(map(float,box.xyxy[0].tolist()));detections.append({'class_id':k,'class_name':CLASSES[k],'confidence':confidence,'xyxy':xyxy})
            event=detection_event(frame_id,width,height,detections,latency,captured_at);output.write(json.dumps(event)+'\n');output.flush();print(json.dumps(event),flush=True)
    print('Finished. Detection counts are not collection confirmations. No motor commands were sent.',file=sys.stderr)

if __name__=='__main__':main()
