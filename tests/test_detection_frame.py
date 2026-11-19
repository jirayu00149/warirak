import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'hardware/pi'))
from detection_frame import attach_metadata, detection_metadata, SIGNATURE
import phone_camera


class DetectionFrameTests(unittest.TestCase):
    def test_real_preview_decodes_and_metadata_matches_same_image(self):
        import cv2
        import numpy as np
        boxes = [dict(class_id=0,class_name='plastic_bottle',confidence=.812345,xyxy=[50,60,150,260])]
        frame = np.zeros((480,640,3), dtype=np.uint8)
        captured = '2026-11-14T07:00:00+00:00'
        def detector(image):
            cv2.rectangle(image,(50,60),(150,260),(0,255,0),2)
            return image,boxes
        jpeg = phone_camera.preview_jpeg(cv2, frame, detector, captured)
        size = int.from_bytes(jpeg[4:6], 'big')
        data = json.loads(jpeg[6+len(SIGNATURE):4+size])
        self.assertEqual(data['captured_at'],captured)
        self.assertEqual(data['detections'][0]['confidence'],.8123)
        self.assertFalse(data['collection_confirmed'])
        result=cv2.imdecode(np.frombuffer(jpeg,dtype=np.uint8),cv2.IMREAD_COLOR)
        self.assertEqual(result.shape,frame.shape)
        self.assertGreater(int(result[100,50,1]),100)

    def test_bounded_metadata_and_invalid_values(self):
        box=dict(class_id=1,class_name='bottle_cap',confidence=.8,xyxy=[0,0,10,10])
        m=detection_metadata([box]*100,640,480,100,'2026-11-14T00:00:00Z')
        self.assertEqual(len(m['detections']),64)
        self.assertEqual(m['total_detected'],100)
        self.assertLess(len(attach_metadata(b'\xff\xd8\xff\xd9',m)),16384)
        for bad in [dict(box,confidence=float('nan')),dict(box,class_id=2),dict(box,xyxy=[3,3,1,1])]:
            with self.assertRaises(ValueError):
                detection_metadata([bad],640,480,100,'2026-11-14T00:00:00Z')
        with self.assertRaises(ValueError):attach_metadata(b'not-jpeg',m)


if __name__=='__main__':unittest.main()
