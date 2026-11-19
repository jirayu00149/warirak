"""Send fresh low-rate JPEG snapshots to the private boat-monitoring API. No motor control."""
import argparse,datetime,json,os,time,urllib.request,uuid
from .camera import Camera
from .telemetry import validate_url,NoRedirect
def publish_frame(url,device_token,jpeg,captured_at,frame_id):
    url=validate_url(url)
    if not device_token:raise ValueError('WARIRAK_DEVICE_TOKEN is missing')
    if len(jpeg)>262144:raise ValueError('JPEG exceeds 256 KiB')
    headers={'Content-Type':'image/jpeg','Authorization':'Bearer '+device_token,'X-Frame-Id':frame_id,'X-Captured-At':captured_at}
    request=urllib.request.Request(url+'/api/device/frame',data=jpeg,headers=headers,method='POST')
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=10) as response:return json.loads(response.read(1048576))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',required=True);p.add_argument('--source',default='0');p.add_argument('--interval',type=float,default=5);p.add_argument('--frames',type=int,default=0,help='0 keeps publishing until Ctrl+C');a=p.parse_args();validate_url(a.url)
    if a.interval<1 or a.frames<0:p.error('interval >=1 and frames >=0 required')
    device_token=os.environ.get('WARIRAK_DEVICE_TOKEN')
    if not device_token:p.error('Set WARIRAK_DEVICE_TOKEN before opening the camera')
    import cv2
    sent=0;next_send=time.monotonic()
    try:
        with Camera(a.source,width=640,height=360) as camera:
            while a.frames==0 or sent<a.frames:
                frame=camera.read()
                if frame is None:break
                if time.monotonic()<next_send:time.sleep(.03);continue
                frame=cv2.resize(frame,(640,360));ok,encoded=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,60])
                if not ok:raise RuntimeError('Cannot encode frame')
                try:
                    result=publish_frame(a.url,device_token,encoded.tobytes(),datetime.datetime.now(datetime.timezone.utc).isoformat(),'frame-'+str(uuid.uuid4()));sent+=1;print(json.dumps({'sent_frames':sent,'accepted':result.get('accepted')},ensure_ascii=False),flush=True)
                except Exception as error:print('Frame not delivered; capture a fresh frame on next interval. '+type(error).__name__,flush=True)
                next_send=time.monotonic()+a.interval
    except KeyboardInterrupt:pass
if __name__=='__main__':main()
