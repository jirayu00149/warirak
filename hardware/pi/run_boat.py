"""Run Warirak detection and optionally send image hints over the bench link."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from usb_link import UsbLink, check_link, open_port
from detection_frame import attach_metadata, detection_metadata

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "frontend" / "assets" / "models"
NCNN_MODEL = MODELS / "warirak-yolo26n-public-v4_ncnn_model"
DEFAULT_URL = "https://warirak-monitor.kungmaxzaa.workers.dev"
MAX_HINT_AGE_SECONDS = 1.5
UPLOAD_INTERVAL_SECONDS = 5


def image_aim(detections, width):
    if not detections:
        return "NONE"
    box = max(detections, key=lambda item: item["confidence"])
    x1, _, x2, _ = box["xyxy"]
    center = (x1 + x2) / (2 * width)
    if center < 0.4:
        return "LEFT"
    if center > 0.6:
        return "RIGHT"
    return "CENTER"


def detect(model, frame, thresholds, classes):
    result = model.predict(
        frame, imgsz=800, rect=False, conf=min(thresholds.values()),
        device="cpu", verbose=False,
    )[0]
    detections = []
    for box in result.boxes:
        class_id = int(box.cls.item())
        class_name = classes[class_id]
        confidence = float(box.conf.item())
        if confidence >= thresholds[class_name]:
            detections.append({
                "class_id": class_id,
                "class_name": class_name,
                "confidence": confidence,
                "xyxy": box.xyxy[0].tolist(),
            })
    return detections


def draw_detections(cv2, frame, detections, aim):
    annotated = frame.copy()
    color = (40, 220, 100)
    for box in detections:
        x1, y1, x2, y2 = map(int, box["xyxy"])
        label = f"{box['class_name']} {box['confidence']:.2f}"
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated, label, (x1, max(16, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    cv2.putText(annotated, f"Image aim: {aim} | Bench STOP", (8, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    return annotated


def run_camera(args):
    sys.path.insert(0, str(ROOT / "ai"))
    from warirak_ai.camera import Camera
    from warirak_ai.camera_publish import publish_frame
    from warirak_ai.telemetry import validate_url

    if not all((NCNN_MODEL / name).is_file() for name in (
        "metadata.yaml", "model.ncnn.param", "model.ncnn.bin",
    )):
        raise ValueError(f"Unpack the included NCNN model into {MODELS}")

    live_camera = args.source == "picamera2" or args.source.isdigit()
    token = None
    if args.publish:
        if not live_camera:
            raise ValueError("Cloud publishing requires a live camera source")
        validate_url(args.url)
        token = os.environ.get("WARIRAK_DEVICE_TOKEN")
        if not token:
            raise ValueError("Set WARIRAK_DEVICE_TOKEN to your monitor device token")

    import cv2
    from ultralytics import YOLO
    from warirak_ai import CLASSES
    from warirak_ai.calibration import load_calibration
    from warirak_ai.infer import detection_event
    from warirak_ai.evaluate import model_classes

    thresholds = load_calibration(MODELS / "confidence-calibration-public-v4.json")["thresholds"]
    model = YOLO(str(NCNN_MODEL), task="detect")
    if model_classes(model) != CLASSES:
        raise ValueError("Unexpected classes in the Warirak model")

    next_upload = 0.0
    try:
        with ExitStack() as stack:
            link = None
            if args.port:
                port = stack.enter_context(open_port(args.port))
                time.sleep(2)
                port.reset_input_buffer()
                link = UsbLink(port)
                if not link.ping():
                    raise RuntimeError("No ESP STOP ACK. Run check-link first.")
            camera = stack.enter_context(Camera(args.source, width=640, height=480))
            count = 0
            while not args.frames or count < args.frames:
                frame = camera.read()
                if frame is None:
                    if live_camera or not count:
                        raise RuntimeError("Camera or video returned no frame")
                    break

                read_at = time.monotonic()
                captured = datetime.now(timezone.utc)
                frame_id = "frame-" + uuid4().hex
                height, width = frame.shape[:2]
                detections = detect(model, frame, thresholds, CLASSES)
                latency = time.monotonic() - read_at
                aim = image_aim(detections, width) if latency <= MAX_HINT_AGE_SECONDS else "NONE"
                event = detection_event(frame_id, width, height, detections, latency * 1000,
                                        captured.timestamp() * 1000)
                event["image_aim"] = aim
                event["usb_ack_stop"] = None
                if link:
                    try:
                        event["usb_ack_stop"] = link.ping(aim)
                    except OSError as error:
                        print(f"USB disconnected ({type(error).__name__}); restart to reconnect",
                              file=sys.stderr, flush=True)
                        event["usb_ack_stop"] = False
                        link = None
                print(json.dumps(event), flush=True)
                count += 1

                upload_due = token and time.monotonic() >= next_upload
                if args.show or upload_due:
                    annotated = draw_detections(cv2, frame, detections, aim)
                if upload_due:
                    try:
                        preview = cv2.resize(annotated, (640, 480))
                        ok, jpeg = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 60])
                        if not ok:
                            raise RuntimeError("JPEG encoding failed")
                        metadata = detection_metadata(detections, width, height, latency*1000, captured.isoformat())
                        response = publish_frame(args.url, token, attach_metadata(jpeg.tobytes(), metadata),
                                                 captured.isoformat(), frame_id)
                        print(f"Monitor upload accepted={response.get('accepted') is True}",
                              file=sys.stderr, flush=True)
                    except (OSError, ValueError, RuntimeError) as error:
                        detail = getattr(error, "code", type(error).__name__)
                        print(f"Monitor upload failed ({detail}); will try a fresh frame",
                              file=sys.stderr, flush=True)
                    next_upload = time.monotonic() + UPLOAD_INTERVAL_SECONDS
                if args.show:
                    cv2.imshow("Warirak bench", annotated)
                    if cv2.waitKey(1) & 0xff == ord("q"):
                        break
    finally:
        if args.show:
            cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-link", help="Check STOP acknowledgements and the ESP timeout")
    check.add_argument("--port", required=True)
    run = sub.add_parser("run", help="Detect bottles and caps using the included NCNN model")
    run.add_argument("--source", default="0", help="USB camera index, picamera2, or a video file")
    run.add_argument("--port", help="Optional ESP USB port, e.g. /dev/ttyUSB0 or COM6")
    run.add_argument("--frames", type=int, default=0, help="Frame limit, or 0 to keep running")
    run.add_argument("--show", action="store_true", help="Open a preview window on a desktop")
    run.add_argument("--publish", action="store_true", help="Send live JPEG snapshots to the monitor")
    run.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()
    if args.command == "run" and args.frames < 0:
        parser.error("--frames must be zero or greater")
    try:
        if args.command == "check-link":
            check_link(args.port)
        else:
            run_camera(args)
    except KeyboardInterrupt:
        return 0
    except (ImportError, OSError, ValueError, RuntimeError) as error:
        print(f"Warirak: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
