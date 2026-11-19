"""Join actual detection messages and sensor messages into shadow-only steering proposals.

Image size is never treated as a metric distance. No serial, GPIO or motor transport exists here.
"""
import argparse,json,math,sys,time

def finite(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

class VisualPilot:
    def __init__(self,thresholds=None,stable_frames=3,max_frame_age_ms=1500):
        if not isinstance(stable_frames,int) or stable_frames<2 or not 100<=max_frame_age_ms<=2000:raise ValueError('Invalid temporal limits')
        self.thresholds=thresholds or {0:.5,1:.5}
        if set(self.thresholds)!={0,1} or not all(finite(v) and 0<v<1 for v in self.thresholds.values()):raise ValueError('Both class confidence thresholds are required')
        self.stable_frames=stable_frames;self.max_age=max_frame_age_ms;self.track=None;self.last_frame=None;self.last_capture=None
    def propose(self,detection,sensors,now_ms=None):
        now=time.time()*1000 if now_ms is None else now_ms
        result=dict(schema='warirak.visual-pilot.v1',source='shadow_only',controller='visual_servo_v1',generated_at_ms=now,control_enabled=False,collection_confirmed=False,conveyor_enabled=False,left=0.,right=0.,reason='invalid_observation',requires_hardware_calibration=True)
        def stop(reason):self.track=None;result['reason']=reason;return result
        if not isinstance(sensors,dict) or not isinstance(detection,dict):return stop('missing_observation')
        stamp=sensors.get('timestamp_unix_ms')
        if not finite(stamp) or not -100<=now-stamp<=500:return stop('stale_sensor')
        if sensors.get('armed') is not True or sensors.get('manual_override') is not False:return stop('disarmed_or_manual')
        battery=sensors.get('battery_percent');clearance=sensors.get('clearance_m')
        if not finite(battery) or not 25<=battery<=100:return stop('low_or_invalid_battery')
        if not isinstance(clearance,list) or len(clearance)!=3 or not all(finite(x) and 0<=x<=20 for x in clearance):return stop('invalid_clearance')
        if min(clearance)<.35:return stop('obstacle_stop')
        captured=detection.get('captured_at_ms')
        if detection.get('schema')!='warirak.detection.v1' or detection.get('source')!='detector' or not finite(captured) or not -100<=now-captured<=self.max_age:return stop('stale_or_invalid_frame')
        frame=detection.get('frame_id')
        if not isinstance(frame,(str,int)) or isinstance(frame,bool) or not str(frame):return stop('invalid_frame_id')
        if frame==self.last_frame or self.last_capture is not None and captured<=self.last_capture:return stop('repeated_or_out_of_order_frame')
        if self.last_capture is not None and captured-self.last_capture>self.max_age:self.track=None
        self.last_frame=frame;self.last_capture=captured
        size=detection.get('image_size')
        if not isinstance(size,list) or len(size)!=2 or not all(finite(x) and x>0 for x in size):return stop('invalid_image_size')
        rows=detection.get('detections')
        if not isinstance(rows,list) or len(rows)>1000:return stop('invalid_detections')
        width,height=size;targets=[]
        for box in rows:
            if not isinstance(box,dict):continue
            k=box.get('class_id');confidence=box.get('confidence');xyxy=box.get('xyxy')
            if type(k) is not int or k not in [0,1] or not finite(confidence) or not max(.35,self.thresholds[k])<=confidence<=1:continue
            if not isinstance(xyxy,list) or len(xyxy)!=4 or not all(finite(x) for x in xyxy):continue
            x1,y1,x2,y2=xyxy
            if not 0<=x1<x2<=width or not 0<=y1<y2<=height:continue
            center=(x1+x2)/2/width;area=(x2-x1)*(y2-y1)/(width*height)
            targets.append(dict(class_id=k,center=center,area_fraction=area,confidence=confidence,xyxy=xyxy))
        if not targets:return stop('target_not_confirmed')
        # Prefer the current track; switching class or jumping across the frame requires reconfirmation.
        matched=[t for t in targets if self.track and t['class_id']==self.track['class_id'] and abs(t['center']-self.track['center'])<.15]
        target=min(matched or targets,key=lambda t:abs(t['center']-(self.track['center'] if matched else .5)))
        count=self.track['count']+1 if matched else 1;self.track={**target,'count':count}
        result.update(target=target,confirmed_frames=count,target_distance_m=None)
        if count<self.stable_frames:result['reason']='confirming_target';return result
        error=(target['center']-.5)*2
        # Positive image error proposes a right turn for the declared forward-positive differential layout.
        # The physical adapter must verify orientation and enforce its own independent watchdog.
        turn=max(-.16,min(.16,error*.24));forward=.18*(1-min(1,abs(error)))
        if clearance[1]<.65:forward=0.
        if turn>0 and clearance[2]<.65 or turn<0 and clearance[0]<.65:return stop('turn_clearance_stop')
        result.update(left=max(-.25,min(.25,forward+turn)),right=max(-.25,min(.25,forward-turn)),reason='approach_proposal')
        return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--observations',help='JSONL containing paired detection and sensors, otherwise stdin');parser.add_argument('--thresholds',help='Published validation-selected confidence-calibration.json');args=parser.parse_args()
    thresholds=None
    if args.thresholds:
        from .calibration import load_calibration
        from pathlib import Path
        from . import CLASSES
        selected=load_calibration(Path(args.thresholds))['thresholds'];thresholds={i:selected[c] for i,c in enumerate(CLASSES)}
    pilot=VisualPilot(thresholds);stream=open(args.observations,encoding='utf-8') if args.observations else sys.stdin
    try:
        for line in stream:
            try:
                pair=json.loads(line);result=pilot.propose(pair.get('detection'),pair.get('sensors'))
            except (ValueError,AttributeError):result=pilot.propose(None,None)
            print(json.dumps(result,ensure_ascii=False),flush=True)
    finally:
        if stream is not sys.stdin:stream.close()
        print(json.dumps(pilot.propose(None,None)),flush=True)

if __name__=='__main__':main()
