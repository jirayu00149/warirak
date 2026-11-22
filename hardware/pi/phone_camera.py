#!/usr/bin/env python3
"""Read an iPhone IP-camera stream on Pi and publish JPEG previews. No motor commands."""
import argparse
from datetime import datetime, timezone
import getpass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

import monitor_agent
from detection_frame import attach_metadata, detection_metadata

PHONE_CONFIG = Path.home() / '.config/warirak/phone-camera.json'
KIT = Path.home() / 'Warirak_Pi5_Kit'
MAX_FRAME_AGE = 10.0
USER_AGENT = 'Warirak-Phone-Camera/1.0.0'
LIVE_FPS = 10
MAX_LIVE_FPS = 15
LIVE_FRAME_INTERVAL = 1 / LIVE_FPS
MJPEG_BOUNDARY = b'warirak-frame'
LOCAL_PAGE = b"""<!doctype html>
<html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Warirak camera on Pi</title>
<style>
body{background:#f7f8f6;color:#1d2522;font:15px/1.5 system-ui,"Noto Sans Thai",sans-serif;margin:0}
main{max-width:1100px;margin:auto;padding:20px;display:grid;gap:16px;grid-template-columns:minmax(0,2fr) minmax(240px,1fr)}
h1{font-size:18px;margin:0;grid-column:1/-1}section{background:#fff;border:1px solid #e3e7e4;border-radius:12px;padding:12px}
img{display:block;width:100%;border-radius:8px;background:#e9edeb;aspect-ratio:4/3;object-fit:contain}
p{margin:8px 0 0;color:#5b6863;font-size:13px}[hidden]{display:none}
@media(max-width:760px){main{grid-template-columns:1fr}}
</style>
<main><h1>Warirak camera on Pi (LAN)</h1>
<section><img id="live" src="/stream.mjpg" alt="Live camera"><p id="status" role="status">Live stream from Pi. Motors disabled.</p></section>
<section><img id="ai" alt="Latest AI frame" hidden><p id="ai-status" role="status">Waiting for AI result (requires --detect)</p></section></main>
<script>
const live=document.querySelector('#live'),status=document.querySelector('#status');
live.onerror=()=>{status.textContent='Camera stream interrupted; retrying';setTimeout(()=>{live.src='/stream.mjpg?'+Date.now()},1000)};
let aiUrl;
async function ai(){
  const box=document.querySelector('#ai'),text=document.querySelector('#ai-status');
  try{
    const r=await fetch('/detection.jpg',{cache:'no-store',signal:AbortSignal.timeout(3000)});
    if(r.ok){const url=URL.createObjectURL(await r.blob());box.src=url;box.hidden=false;if(aiUrl)URL.revokeObjectURL(aiUrl);aiUrl=url;
      const age=Number(r.headers.get('X-Frame-Age'));text.textContent='AI frame, captured '+(Number.isFinite(age)?age.toFixed(1)+' s ago':'recently')+'. Detection is not a confirmed collection.';}
    else text.textContent=box.hidden?'Waiting for AI result (requires --detect)':'No new AI result; showing last AI frame';
  }catch{text.textContent='Waiting for AI result';}
  setTimeout(ai,700);
}
ai();
</script></html>
"""


PICAMERA_PREFIX = 'picamera'


def is_picamera(value):
    return isinstance(value, str) and (value == PICAMERA_PREFIX or value.startswith(PICAMERA_PREFIX + ':'))


USB_PREFIX = 'usb'


def is_usbcam(value):
    return isinstance(value, str) and (value == USB_PREFIX or value.startswith(USB_PREFIX + ':'))


def usb_device(source):
    """usb -> first USB webcam (/dev/v4l/by-id/*usb*-video-index0); usb:N -> /dev/videoN."""
    index = source.partition(':')[2]
    if index:
        return f'/dev/video{int(index)}'
    import glob
    found = sorted(glob.glob('/dev/v4l/by-id/*usb*-video-index0')) or sorted(glob.glob('/dev/v4l/by-id/*-video-index0'))
    return os.path.realpath(found[0]) if found else '/dev/video0'


def validate_source(value):
    if is_usbcam(value):
        index = value.partition(':')[2]
        if index and (not index.isdigit() or int(index) > 63):
            raise ValueError('Use usb or usb:0 / usb:1 for a USB webcam.')
        return value
    if is_picamera(value):
        index = value.partition(':')[2] or '0'
        if not index.isdigit() or int(index) > 3:
            raise ValueError('Use picamera or picamera:0 / picamera:1 for the Raspberry Pi camera.')
        return value
    if not isinstance(value, str) or any(ord(c) < 33 for c in value):
        raise ValueError('Camera URL must not contain spaces or control characters.')
    u = urllib.parse.urlsplit(value)
    if u.scheme not in ('rtsp', 'rtsps', 'http', 'https') or not u.hostname or u.fragment:
        raise ValueError('Use the RTSP or direct MJPEG stream URL displayed by the camera app.')
    if all(c in '0123456789.' for c in u.hostname):
        ipaddress.IPv4Address(u.hostname)  # Reject incomplete IPs such as 192.1.135.
    if u.port is not None and not 1 <= u.port <= 65535:
        raise ValueError('Invalid camera port.')
    return value


def configure(path):
    source = validate_source(getpass.getpass('Paste camera RTSP/MJPEG URL, or type usb / picamera (input hidden): ').strip())
    u = urllib.parse.urlsplit(source)
    if not (is_picamera(source) or is_usbcam(source)) and u.username is None:
        username = input('Camera username (Enter if authentication is disabled): ').strip()
        if username:
            password = getpass.getpass('Camera password (input hidden): ')
            auth = urllib.parse.quote(username, safe='') + ':' + urllib.parse.quote(password, safe='') + '@'
            source = urllib.parse.urlunsplit(u._replace(netloc=auth + u.netloc))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.phone-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as out:
            json.dump({'source': source}, out)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Camera settings saved privately. Next: check')


def put_latest(channel, item):
    try:
        channel.put_nowait(item)
    except queue.Full:
        try:
            channel.get_nowait()
        except queue.Empty:
            pass
        try:
            channel.put_nowait(item)
        except queue.Full:
            pass


PICAMERA_SIZE = (int(os.environ.get('WARIRAK_PICAM_WIDTH', '1280')), int(os.environ.get('WARIRAK_PICAM_HEIGHT', '720')))
PICAMERA_FPS = int(os.environ.get('WARIRAK_PICAM_FPS', '15'))


def picamera_command(source):
    import shutil
    exe = shutil.which('rpicam-vid') or shutil.which('libcamera-vid')
    if not exe:
        raise RuntimeError('rpicam-vid not found: sudo apt install rpicam-apps')
    index = source.partition(':')[2] or '0'
    w, h = PICAMERA_SIZE
    return [exe, '--camera', index, '-t', '0', '-n', '--codec', 'mjpeg', '--quality', '80',
            '--width', str(w), '--height', str(h), '--framerate', str(PICAMERA_FPS), '--flush', '-o', '-']


def picamera_worker(source, channel, stop):
    """Read MJPEG from rpicam-vid (Pi 5 / libcamera) and keep only the newest frame."""
    import subprocess
    import cv2
    import numpy as np
    proc = subprocess.Popen(picamera_command(source), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    buffer, sequence = bytearray(), 0
    try:
        while not stop.is_set():
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            buffer += chunk
            latest = None
            while True:
                start = buffer.find(b'\xff\xd8')
                end = buffer.find(b'\xff\xd9', start + 2) if start >= 0 else -1
                if start < 0 or end < 0:
                    if start > 0:
                        del buffer[:start]
                    elif start < 0 and len(buffer) > 1:
                        del buffer[:-1]
                    break
                latest = bytes(buffer[start:end + 2])
                del buffer[:end + 2]
                sequence += 1
            if latest is None or not channel.empty():
                continue
            frame = cv2.imdecode(np.frombuffer(latest, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            put_latest(channel, (sequence, time.monotonic(), datetime.now(timezone.utc).isoformat(), frame))
            if len(buffer) > 8 * 1024 * 1024:
                buffer.clear()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def capture_worker(source, channel, stop):
    # Native decoder diagnostics can include a URL/password. Keep them off logs.
    with open(os.devnull, 'w') as null:
        os.dup2(null.fileno(), 2)
    if is_picamera(source):
        try:
            picamera_worker(source, channel, stop)
        except Exception:
            pass
        finally:
            channel.cancel_join_thread()
        return
    camera = None
    try:
        import cv2
        if hasattr(cv2, 'setLogLevel'):
            cv2.setLogLevel(0)
        if is_usbcam(source):
            camera = cv2.VideoCapture(usb_device(source), cv2.CAP_V4L2)
            camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, PICAMERA_SIZE[0])
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, PICAMERA_SIZE[1])
            camera.set(cv2.CAP_PROP_FPS, PICAMERA_FPS)
        else:
            camera = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000,
            ])
        if not camera.isOpened():
            return
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        sequence = 0
        while not stop.is_set():
            # Keep reading so the network buffer never lags; only decode/copy a frame
            # when the consumer has taken the previous one.
            if not camera.grab():
                break
            sequence += 1
            if not channel.empty():
                continue
            ok, frame = camera.retrieve()
            if not ok or frame is None:
                break
            received_mono = time.monotonic()
            received_at = datetime.now(timezone.utc).isoformat()
            h, w = frame.shape[:2]
            if max(h, w) > 1280:
                factor = 1280 / max(h, w)
                frame = cv2.resize(frame, (max(1, round(w * factor)), max(1, round(h * factor))))
            put_latest(channel, (sequence, received_mono, received_at, frame))
    except Exception:
        pass  # Parent reports a credential-free diagnostic on missing frames.
    finally:
        if camera is not None:
            camera.release()
        # Do not wait forever for the parent to drain a large frame at shutdown.
        channel.cancel_join_thread()


class LatestStream:
    def __init__(self, source):
        context = mp.get_context('spawn')
        self.channel, self.stop = context.Queue(maxsize=1), context.Event()
        self.process = context.Process(target=capture_worker, args=(validate_source(source), self.channel, self.stop), daemon=True)

    def __enter__(self):
        self.process.start()
        return self

    def next(self, timeout=12):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                item = self.channel.get(timeout=min(.3, max(.01, end - time.monotonic())))
                if time.monotonic() - item[1] <= MAX_FRAME_AGE:
                    return item
            except queue.Empty:
                if not self.process.is_alive():
                    break
        raise RuntimeError('No fresh frame. USB camera: check ls /dev/v4l/by-id and that no other program uses it. Pi camera: check the ribbon cable and run rpicam-hello --list-cameras. Phone camera: keep the app open; check its URL, credentials and local network.')

    def __exit__(self, *args):
        self.stop.set()
        self.process.join(timeout=1)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)
        self.channel.close()


def preview_jpeg(cv2, frame, detector=None, captured_at=None, quality=65):
    image = frame.copy()
    metadata = None
    if detector:
        started = time.monotonic()
        image, detections = detector(image)
        h, w = frame.shape[:2]
        metadata = detection_metadata(detections, w, h, (time.monotonic()-started)*1000,
                                      captured_at or datetime.now(timezone.utc).isoformat())
    h, w = image.shape[:2]
    factor = min(640 / w, 480 / h)
    image = cv2.resize(image, (max(16, round(w * factor)), max(16, round(h * factor))))
    cv2.putText(image, 'iPhone test | received by Pi | motors disabled', (6, 18),
                cv2.FONT_HERSHEY_SIMPLEX, .35, (20, 230, 110), 1, cv2.LINE_AA)
    ok, jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok or len(jpeg) > 262144:
        raise ValueError('Preview encoding failed or exceeded 256 KiB.')
    return attach_metadata(jpeg.tobytes(), metadata) if metadata else jpeg.tobytes()


def load_detector(kit):
    if not (kit / 'hardware/pi/run_boat.py').is_file():
        raise ValueError('Warirak_Pi5_Kit not found; use --kit with the existing kit folder.')
    sys.path.insert(0, str(kit / 'hardware/pi'))
    sys.path.insert(0, str(kit / 'ai'))
    from run_boat import detect, draw_detections
    from warirak_ai import CLASSES
    from warirak_ai.calibration import load_calibration
    from warirak_ai.evaluate import model_classes
    from ultralytics import YOLO
    import cv2
    models = kit / 'frontend/assets/models'
    model = YOLO(str(models / 'warirak-yolo26n-public-v4_ncnn_model'), task='detect')
    if model_classes(model) != CLASSES:
        raise ValueError('Unexpected model classes.')
    thresholds = load_calibration(models / 'confidence-calibration-public-v4.json')['thresholds']
    def annotate(frame):
        detections = detect(model, frame, thresholds, CLASSES)
        print(json.dumps({'source': 'iphone_test', 'detections': len(detections),
                          'control_enabled': False, 'collection_confirmed': False}), flush=True)
        return draw_detections(cv2, frame, detections, 'NONE'), detections
    return annotate


class AsyncDetector:
    """Run YOLO beside the live stream so slow inference never stalls live frames.

    Each result is the annotated JPEG of the exact frame that was analysed, with its
    own captured_at; results are never drawn onto newer frames.
    """

    def __init__(self, cv2, detector, quality=70):
        self.cv2, self.detector, self.quality = cv2, detector, quality
        self.lock = threading.Condition()
        self.job = None
        self.result = None
        self.busy = False
        self.stopped = False
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        with self.lock:
            self.stopped = True
            self.lock.notify_all()
        self.thread.join(timeout=5)

    def offer(self, frame, captured_at, received_mono):
        """Give the detector a frame only when it is idle; returns True if accepted."""
        with self.lock:
            if self.busy or self.job is not None or self.stopped:
                return False
            self.job = (frame.copy(), captured_at, received_mono)
            self.lock.notify()
            return True

    def take(self):
        """Return the newest (jpeg, received_mono) once, or None."""
        with self.lock:
            result, self.result = self.result, None
            return result

    def _loop(self):
        while True:
            with self.lock:
                while self.job is None and not self.stopped:
                    self.lock.wait()
                if self.stopped:
                    return
                frame, captured_at, received_mono = self.job
                self.job, self.busy = None, True
            try:
                jpeg = preview_jpeg(self.cv2, frame, self.detector, captured_at, self.quality)
            except Exception:
                jpeg = None  # A failed inference must not stop the live stream.
            with self.lock:
                self.busy = False
                if jpeg is not None and time.monotonic() - received_mono <= MAX_FRAME_AGE:
                    self.result = (jpeg, received_mono)


class LocalPreview(ThreadingHTTPServer):
    def __init__(self, port):
        super().__init__(('127.0.0.1', port), LocalPreviewHandler)
        self.frame = None
        self.detection = None
        self.changed = threading.Condition()
        self.closing = False

    def update(self, jpeg, received_at):
        with self.changed:
            self.frame = (jpeg, received_at)
            self.changed.notify_all()

    def update_detection(self, jpeg, received_at):
        self.detection = (jpeg, received_at)

    def shutdown(self):
        with self.changed:
            self.closing = True
            self.changed.notify_all()
        super().shutdown()


class LocalPreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        port = self.server.server_port
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            return self.send_error(400)
        if self.path == '/':
            return self.send_body(LOCAL_PAGE, 'text/html; charset=utf-8')
        if self.path == '/frame.jpg':
            frame = self.server.frame
            if frame is None or time.monotonic() - frame[1] > MAX_FRAME_AGE:
                return self.send_error(503, 'Waiting for a fresh frame')
            return self.send_body(frame[0], 'image/jpeg')
        if self.path == '/detection.jpg':
            frame = self.server.detection
            if frame is None or time.monotonic() - frame[1] > 60:
                return self.send_error(503, 'No AI result yet')
            return self.send_body(frame[0], 'image/jpeg', {'X-Frame-Age': f'{time.monotonic() - frame[1]:.2f}'})
        if self.path.split('?', 1)[0] == '/stream.mjpg':
            return self.send_stream()
        self.send_error(404)

    def send_stream(self):
        """Multipart MJPEG: the browser shows each new frame as soon as it exists."""
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=' + MJPEG_BOUNDARY.decode())
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        server, last = self.server, None
        try:
            while True:
                with server.changed:
                    server.changed.wait_for(lambda: server.closing or (server.frame is not None and server.frame is not last), timeout=MAX_FRAME_AGE)
                    if server.closing:
                        return
                    frame = server.frame
                if frame is None or frame is last or time.monotonic() - frame[1] > MAX_FRAME_AGE:
                    continue  # No fresh frame: never repeat an old frame as if it were live.
                last = frame
                self.wfile.write(b'--' + MJPEG_BOUNDARY + b'\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                                 str(len(frame[0])).encode() + b'\r\n\r\n' + frame[0] + b'\r\n')
                self.wfile.flush()
        except (ConnectionError, OSError):
            pass

    def send_body(self, body, content_type, extra=None):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionError:
            pass


def run_local(stream, args, cv2, detector):
    deadline = time.monotonic() + args.duration if args.duration else float('inf')
    interval = 1 / getattr(args, 'fps', LIVE_FPS)
    with LocalPreview(args.local_port) as server, (AsyncDetector(cv2, detector) if detector else _NoDetector()) as ai:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f'Local preview: http://127.0.0.1:{server.server_port}/', flush=True)
        sent = 0
        try:
            while time.monotonic() < deadline:
                started = time.monotonic()
                _, received_at, captured_at, frame = stream.next()
                ai.offer(frame, captured_at, received_at)
                result = ai.take()
                if result:
                    server.update_detection(*result)
                jpeg = preview_jpeg(cv2, frame)
                if time.monotonic() - received_at <= MAX_FRAME_AGE:
                    server.update(jpeg, received_at)
                    sent += 1
                    if args.frames and sent >= args.frames:
                        break
                time.sleep(max(0, interval - (time.monotonic() - started)))
        finally:
            server.shutdown()
            thread.join()
    return 0


class _NoDetector:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def offer(self, *args):
        return False

    def take(self):
        return None


def publish_frame(config, jpeg, received_at):
    request = urllib.request.Request(config['url'] + '/api/device/frame', data=jpeg, method='POST', headers={
        'Content-Type': 'image/jpeg', 'Authorization': 'Bearer ' + config['token'],
        'User-Agent': USER_AGENT,
        'X-Frame-Id': 'frame-' + uuid4().hex, 'X-Captured-At': received_at,
    })
    with urllib.request.build_opener(monitor_agent.NoRedirect()).open(request, timeout=10) as response:
        data = response.read(16385)
        if len(data) > 16384:
            raise ValueError('Unexpected server response.')
        return json.loads(data).get('accepted') is True


def send_live_frames(stream, config, args, cv2, detector):
    try:
        import websocket
    except ImportError as error:
        raise RuntimeError('Install websocket-client in the Pi kit Python environment.') from error
    origin = urllib.parse.urlsplit(config['url'])
    scheme = 'wss' if origin.scheme == 'https' else 'ws'
    url = urllib.parse.urlunsplit((scheme, origin.netloc, '/api/device/stream', '', ''))
    deadline = time.monotonic() + args.duration if args.duration else float('inf')
    interval = 1 / getattr(args, 'fps', LIVE_FPS)
    with (AsyncDetector(cv2, detector) if detector else _NoDetector()) as ai:
        return _live_loop(stream, url, config, args, cv2, websocket, ai, deadline, interval)


def exchange(socket, jpeg, websocket):
    """Send one frame and wait for the server; stop-and-wait keeps latency bounded."""
    socket.send_binary(jpeg)
    reply = socket.recv()
    if reply not in ('ok', 'skip'):
        raise websocket.WebSocketConnectionClosedException()
    return reply


MAX_IN_FLIGHT = int(os.environ.get('WARIRAK_LIVE_INFLIGHT', '3'))


class PipelinedSender:
    """Send frames without waiting for each reply; at most MAX_IN_FLIGHT unanswered frames.

    Stop-and-wait limited the frame rate to 1/(upload + round trip) on a phone hotspot.
    A small window keeps latency bounded while letting the link stay busy.
    """

    def __init__(self, socket, websocket, window=MAX_IN_FLIGHT):
        self.socket, self.websocket = socket, websocket
        self.slots = threading.Semaphore(max(1, window))
        self.lock = threading.Lock()
        self.failed = threading.Event()
        self.accepted = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while not self.failed.is_set():
                reply = self.socket.recv()
                if reply not in ('ok', 'skip'):
                    break
                if reply == 'ok':
                    self.accepted += 1
                self.slots.release()
        except Exception:
            pass
        self.failed.set()
        self.slots.release()

    def send(self, jpeg, timeout=8):
        if self.failed.is_set() or not self.slots.acquire(timeout=timeout) or self.failed.is_set():
            raise self.websocket.WebSocketConnectionClosedException()
        with self.lock:
            self.socket.send_binary(jpeg)


def _live_loop(stream, url, config, args, cv2, websocket, ai, deadline, interval):
    delay = 1
    while time.monotonic() < deadline:
        socket = None
        try:
            socket = websocket.create_connection(url, timeout=8, redirect_limit=0, header={
                'Authorization': 'Bearer ' + config['token'],
                'User-Agent': USER_AGENT
            })
            socket.settimeout(None)
            sender, announced = PipelinedSender(socket, websocket), False
            while time.monotonic() < deadline:
                started = time.monotonic()
                _, received, captured_at, frame = stream.next()
                ai.offer(frame, captured_at, received)
                result = ai.take()
                if result and time.monotonic() - result[1] <= MAX_FRAME_AGE:
                    # The annotated frame carries its own metadata and capture time.
                    sender.send(result[0])
                jpeg = preview_jpeg(cv2, frame)
                if time.monotonic() - received > MAX_FRAME_AGE:
                    continue
                sender.send(jpeg)
                if sender.accepted:
                    delay = 1
                    if not announced:
                        announced = True
                        print('Live camera connected. Open the Dashboard to watch.', flush=True)
                    if args.frames and sender.accepted >= args.frames:
                        return 0
                time.sleep(max(0, interval - (time.monotonic() - started)))
        except websocket.WebSocketBadStatusException as error:
            print(f'Live camera handshake HTTP {error.status_code}.', file=sys.stderr, flush=True)
            if error.status_code in (401, 403, 404):
                return 3
        except (OSError, websocket.WebSocketException):
            print('Live connection lost. Reconnecting.', file=sys.stderr, flush=True)
        finally:
            if socket is not None:
                socket.close(timeout=1)
        time.sleep(max(0, min(delay, deadline - time.monotonic())))
        delay = min(15, delay * 2)
    return 0


def run(args):
    if args.command == 'run' and not monitor_agent.is_raspberry_pi():
        raise ValueError('Publish on Raspberry Pi only. Use check on another computer.')
    source = validate_source(json.loads(args.camera_config.read_text(encoding='utf8'))['source'])
    import cv2
    config = detector = None
    if args.command == 'local':
        os.environ['YOLO_AUTOINSTALL'] = 'false'
        detector = load_detector(args.kit) if args.detect else None
    if args.command == 'run':
        config = monitor_agent.validate_config(json.loads(args.device_config.read_text(encoding='utf8')))
        detector = load_detector(args.kit) if args.detect else None
        print('Sending camera images to the public Dashboard. Ctrl+C stops this sender.', flush=True)
    with LatestStream(source) as stream:
        if args.command == 'local':
            return run_local(stream, args, cv2, detector)
        if args.command == 'run' and args.live:
            return send_live_frames(stream, config, args, cv2, detector)
        sent, deadline = 0, time.monotonic() + args.duration if args.duration else float('inf')
        while time.monotonic() < deadline:
            _, received_mono, received_at, frame = stream.next()
            if args.command == 'check':
                print(f'Camera OK: {frame.shape[1]} x {frame.shape[0]}. No image uploaded.', flush=True)
                return 0
            jpeg = preview_jpeg(cv2, frame, detector, received_at)
            if time.monotonic() - received_mono > MAX_FRAME_AGE:
                print('Skipped delayed frame; waiting for a fresh frame.', flush=True)
                continue
            try:
                if publish_frame(config, jpeg, received_at):
                    sent += 1
                    print(f'Dashboard image accepted ({sent}); motors disabled.', flush=True)
                    if args.frames and sent >= args.frames:
                        return 0
                else:
                    print('Frame not accepted; a new frame will be used.', flush=True)
            except urllib.error.HTTPError as error:
                print(f'Upload HTTP {error.code}; check device token/backend.', file=sys.stderr, flush=True)
                if error.code in (401, 403):
                    return 3
            except (OSError, ValueError):
                print('Upload failed; waiting for a new frame.', file=sys.stderr, flush=True)
            time.sleep(5)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['configure', 'check', 'run', 'local'])
    parser.add_argument('--camera-config', type=Path, default=PHONE_CONFIG)
    parser.add_argument('--device-config', type=Path, default=monitor_agent.CONFIG)
    parser.add_argument('--kit', type=Path, default=KIT)
    parser.add_argument('--detect', action='store_true', help='Use the existing NCNN model; requires kit venv')
    parser.add_argument('--live', action='store_true', help='Stream live images over WebSocket (see --fps)')
    parser.add_argument('--fps', type=float, default=LIVE_FPS, help=f'Live/local frame rate limit, 1-{MAX_LIVE_FPS} (default {LIVE_FPS})')
    parser.add_argument('--local-port', type=int, default=8765, help='Local preview HTTP port on Pi')
    parser.add_argument('--frames', type=int, default=0, help='Stop after this many accepted images; 0 is unlimited')
    parser.add_argument('--duration', type=float, default=0, help='Maximum run duration in seconds; 0 is unlimited')
    args = parser.parse_args()
    if args.frames < 0 or not math.isfinite(args.duration) or args.duration < 0:
        parser.error('frames/duration must be nonnegative')
    if not math.isfinite(args.fps) or not 1 <= args.fps <= MAX_LIVE_FPS:
        parser.error(f'--fps must be between 1 and {MAX_LIVE_FPS}')
    if not 1024 <= args.local_port <= 65535:
        parser.error('--local-port must be between 1024 and 65535')
    try:
        if args.command == 'configure':
            configure(args.camera_config)
            return 0
        return run(args)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, KeyError) as error:
        if args.command == 'local' and isinstance(error, OSError) and getattr(error, 'errno', None) in (98, 10048):
            print(f'Local preview port {args.local_port} is already in use.', file=sys.stderr)
            return 2
        print('Camera setup failed: check app stream URL/password, same network, config and kit Python environment. No credentials printed.', file=sys.stderr)
        import re
        detail = re.sub(r'(?i)([a-z][a-z0-9+.-]*://)[^/@\s]*@', r'\1***@', str(error))
        detail = re.sub(r'(?i)(token|password|bearer|key)[=: ]+\S+', r'\1=***', detail)
        print(f'Reason: {type(error).__name__}: {detail[:300]}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    mp.freeze_support()
    sys.exit(main())
