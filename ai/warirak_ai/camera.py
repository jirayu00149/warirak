"""Explicit camera selection. Picamera2 RGB888 is BGR in its NumPy array."""
class Camera:
    def __init__(self,source='0',width=1280,height=720):self.source=source;self.width=width;self.height=height;self.camera=None;self.picamera=False
    def __enter__(self):
        if self.source=='picamera2':
            from picamera2 import Picamera2
            self.camera=Picamera2();self.camera.configure(self.camera.create_video_configuration(main={'size':(self.width,self.height),'format':'RGB888'}));self.camera.start();self.picamera=True
        else:
            import cv2
            source=int(self.source)if str(self.source).isdigit()else str(self.source);self.camera=cv2.VideoCapture(source)
            if not self.camera.isOpened():raise RuntimeError('Cannot open video source')
            if isinstance(source,int):self.camera.set(cv2.CAP_PROP_FRAME_WIDTH,self.width);self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT,self.height)
        return self
    def read(self):
        if self.picamera:return self.camera.capture_array() # uint8 HWC, BGR: matches Ultralytics/OpenCV.
        ok,frame=self.camera.read();return frame if ok else None
    def __exit__(self,*args):
        if self.camera:
            if self.picamera:self.camera.stop();self.camera.close()
            else:self.camera.release()
