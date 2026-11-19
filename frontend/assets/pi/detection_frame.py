"""Attach bounded detection metadata to its exact JPEG, for HTTP and WebSocket."""
import json
import math

SIGNATURE = b'WARIRAK-YOLO\x00'
CLASSES = ('plastic_bottle', 'bottle_cap')
MAX_DETECTIONS = 64


def detection_metadata(detections, width, height, latency_ms, captured_at, model='public-v4-2026-10-28'):
    if not 16 <= width <= 16384 or not 16 <= height <= 16384:
        raise ValueError('Invalid detection image size')
    if not math.isfinite(latency_ms) or latency_ms < 0:
        raise ValueError('Invalid inference duration')
    rows = []
    for box in detections[:MAX_DETECTIONS]:
        class_id = box['class_id']
        confidence = box['confidence']
        if type(class_id) is not int or class_id not in (0, 1) or box['class_name'] != CLASSES[class_id]:
            raise ValueError('Unknown detector class')
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError('Invalid detector confidence')
        coords = box['xyxy']
        if len(coords) != 4 or not all(math.isfinite(x) for x in coords):
            raise ValueError('Invalid detection box')
        x1, y1, x2, y2 = [round(max(0., min(float(x), width if i % 2 == 0 else height)), 2) for i,x in enumerate(coords)]
        if x1 >= x2 or y1 >= y2:
            raise ValueError('Empty detection box')
        rows.append(dict(class_id=class_id, class_name=CLASSES[class_id], confidence=round(confidence, 4), xyxy=[x1,y1,x2,y2]))
    return dict(schema='warirak.yolo-frame.v1', model=model, image_size=[width,height],
                captured_at=captured_at, latency_ms=round(latency_ms, 2), detections=rows,
                total_detected=len(detections), collection_confirmed=False, control_enabled=False)


def attach_metadata(jpeg, metadata):
    if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
        raise ValueError('Expected complete JPEG')
    payload = SIGNATURE + json.dumps(metadata, separators=(',', ':'), allow_nan=False).encode('utf8')
    if len(payload) > 16384:
        raise ValueError('Detection metadata exceeds 16 KiB')
    result = jpeg[:2] + b'\xff\xef' + (len(payload)+2).to_bytes(2, 'big') + payload + jpeg[2:]
    if len(result) > 262144:
        raise ValueError('Preview and metadata exceed 256 KiB')
    return result
