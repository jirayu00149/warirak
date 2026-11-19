"""Capture real frames into a Studio-importable project ZIP (no automatic labels)."""
import argparse,datetime,hashlib,json,time,uuid,zipfile
from pathlib import Path
from . import CLASSES
from .camera import Camera

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',default='0',help='0 for USB camera, picamera2 for Pi CSI, or a video path');p.add_argument('--session',required=True,help='Keep adjacent frames and related scenes in one group');p.add_argument('--out',type=Path,required=True);p.add_argument('--frames',type=int,default=60);p.add_argument('--interval',type=float,default=1.0);a=p.parse_args()
    if not a.session.strip()or a.frames<1 or a.interval<=0:p.error('session, positive frames and interval are required')
    archive=Path(str(a.out)+'.zip')
    if a.out.exists()or archive.exists():p.exit(2,'Output directory or ZIP already exists; choose a new destination.\n')
    import cv2
    (a.out/'images').mkdir(parents=True);records=[]
    try:
        with Camera(a.source)as camera:
            next_frame=time.monotonic()
            for _ in range(a.frames):
                if not(a.source.isdigit()or a.source=='picamera2'):
                    # Video files should sample by presentation timestamp, not decoding/wall-clock speed.
                    camera.camera.set(cv2.CAP_PROP_POS_MSEC,len(records)*a.interval*1000)
                    frame=camera.read()
                    if frame is None:break
                else:
                    frame=camera.read()
                    if frame is None:break
                    now=time.monotonic()
                    while now<next_frame:
                        time.sleep(min(.02,next_frame-now));frame=camera.read()
                        if frame is None:break
                        now=time.monotonic()
                    if frame is None:break
                id=str(uuid.uuid4());path=a.out/'images'/(id+'.jpg')
                if not cv2.imwrite(str(path),frame,[cv2.IMWRITE_JPEG_QUALITY,92]):raise RuntimeError('Cannot write captured image')
                height,width=frame.shape[:2];records.append({'id':id,'filename':path.name,'file':'images/'+path.name,'extension':'jpg','mime':'image/jpeg','width':width,'height':height,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'session_id':a.session.strip(),'boxes':[],'negative':False,'reviewed':False,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
                next_frame=time.monotonic()+a.interval
                print(f'Captured {len(records)}/{a.frames}',flush=True)
    except KeyboardInterrupt:print('Capture stopped; saving the collected real frames.')
    meta={'schema':'warirak.project.v1','classes':CLASSES,'images':records};(a.out/'annotations.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_STORED)as z:
        z.write(a.out/'annotations.json','annotations.json')
        for r in records:z.write(a.out/r['file'],r['file'])
    print('Import this project ZIP in Dataset Studio and annotate/review every frame:',archive)

if __name__=='__main__':main()
