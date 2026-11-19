import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hardware/pi'))
import phone_camera as phone


class PhoneCameraTests(unittest.TestCase):
    def test_source_rejects_file_pages_without_scheme_and_incomplete_ip(self):
        for value in ('/tmp/recording.mp4', 'file:///tmp/video', '192.168.1.135:8081',
                      'rtsp://192.1.135:8081/live', 'ftp://192.168.1.135/live', 'rtsp://host:99999/live'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                phone.validate_source(value)
        self.assertEqual(phone.validate_source('rtsp://192.168.1.135:8554/live'), 'rtsp://192.168.1.135:8554/live')

    def test_config_keeps_camera_and_device_credentials_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'phone.json'
            with patch('getpass.getpass', side_effect=['rtsp://192.168.1.135:8554/live', 'a:b@c']), patch('builtins.input', return_value='camera user'):
                phone.configure(path)
            value = json.loads(path.read_text())
            self.assertEqual(value, {'source': 'rtsp://camera%20user:a%3Ab%40c@192.168.1.135:8554/live'})

    def test_latest_frame_stream_and_disconnect_are_bounded(self):
        import cv2
        import numpy as np
        ok, encoded = cv2.imencode('.jpg', np.full((120, 160, 3), 100, dtype=np.uint8))
        self.assertTrue(ok)
        jpeg = encoded.tobytes()
        stop = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                self.end_headers()
                try:
                    while not stop.is_set():
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n')
                        self.wfile.flush()
                        time.sleep(.04)
                except (ConnectionError, OSError): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with phone.LatestStream(f'http://127.0.0.1:{server.server_port}/video') as stream:
                first = stream.next(timeout=15)
                time.sleep(.8)
                latest = stream.next()
                self.assertGreater(latest[0], first[0] + 2, 'Must drain old frames while main thread is occupied')
                self.assertLess(time.monotonic() - latest[1], 1)
                self.assertEqual(latest[3].shape, (120, 160, 3))
                self.assertIsNotNone(datetime.fromisoformat(latest[2]).tzinfo)
                stop.set()
                time.sleep(.5)
                # A final buffered frame may be delivered once; repeated images cannot persist forever.
                for _ in range(3):
                    try: stream.next(timeout=1)
                    except RuntimeError: break
                else: self.fail('Disconnected source should stop producing frames')
            self.assertFalse(stream.process.is_alive())
        finally:
            stop.set()
            server.shutdown(); server.server_close(); thread.join()

    def test_portrait_preview_is_bounded_and_not_stretched(self):
        import cv2
        import numpy as np
        jpeg = phone.preview_jpeg(cv2, np.zeros((900, 600, 3), dtype=np.uint8))
        decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape[:2], (480, 320))
        self.assertLess(len(jpeg), 262144)

    def test_publish_uses_frame_api_and_does_not_forward_credentials(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            redirect = False
            def log_message(self, *_): pass
            def do_POST(self):
                data = self.rfile.read(int(self.headers['Content-Length']))
                seen.append((self.path, dict(self.headers), data))
                self.send_response(302 if self.redirect else 200)
                if self.redirect: self.send_header('Location', '/leak')
                self.end_headers()
                if not self.redirect: self.wfile.write(b'{"accepted":true}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            config = {'url': f'http://127.0.0.1:{server.server_port}', 'token': 'fixture-private-token'}
            at = datetime.now(timezone.utc).isoformat()
            self.assertTrue(phone.publish_frame(config, b'fixture-jpeg', at))
            self.assertEqual(seen[0][0], '/api/device/frame')
            self.assertEqual(seen[0][1]['User-Agent'], 'Warirak-Phone-Camera/1.0.0')
            self.assertEqual(seen[0][1]['X-Captured-At'], at)
            self.assertEqual(seen[0][2], b'fixture-jpeg')
            Handler.redirect = True
            with self.assertRaises(urllib.error.HTTPError): phone.publish_frame(config, b'fixture-jpeg', at)
            self.assertEqual(len(seen), 2)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_non_pi_cannot_publish(self):
        with patch.object(phone.monitor_agent, 'is_raspberry_pi', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Raspberry Pi'):
                phone.run(argparse.Namespace(command='run'))

    def test_async_detector_never_blocks_and_keeps_metadata_on_its_own_frame(self):
        import cv2
        import numpy as np
        calls = []
        def slow_detector(image):
            calls.append(int(image[0, 0, 0]))
            time.sleep(.3)
            return image, [{'class_id': 0, 'class_name': 'plastic_bottle', 'confidence': .9, 'xyxy': [1, 1, 20, 20]}]
        first = np.full((120, 160, 3), 10, dtype=np.uint8)
        second = np.full((120, 160, 3), 200, dtype=np.uint8)
        with phone.AsyncDetector(cv2, slow_detector) as ai:
            started = time.monotonic()
            self.assertTrue(ai.offer(first, '2026-11-19T06:00:00+00:00', time.monotonic()))
            self.assertFalse(ai.offer(second, '2026-11-19T06:00:01+00:00', time.monotonic()), 'busy detector refuses new frames')
            self.assertLess(time.monotonic() - started, .1, 'offer must return immediately')
            self.assertIsNone(ai.take())
            deadline = time.monotonic() + 3
            result = None
            while result is None and time.monotonic() < deadline:
                time.sleep(.02)
                result = ai.take()
        self.assertEqual(calls, [10])
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hardware/pi'))
        jpeg = result[0]
        start = jpeg.index(b'WARIRAK-YOLO\x00') + len(b'WARIRAK-YOLO\x00')
        size = int.from_bytes(jpeg[4:6], 'big')
        metadata = json.loads(jpeg[start:4 + size])
        self.assertEqual(metadata['captured_at'], '2026-11-19T06:00:00+00:00')
        self.assertEqual(metadata['total_detected'], 1)
        self.assertFalse(metadata['collection_confirmed'])

    def test_live_stream_keeps_its_rate_while_yolo_is_slow(self):
        import cv2
        import numpy as np
        class Stream:
            n = 0
            def next(self, timeout=12):
                self.n += 1
                return self.n, time.monotonic(), datetime.now(timezone.utc).isoformat(), np.full((120, 160, 3), self.n % 255, dtype=np.uint8)
        sent = []
        class Socket:
            def send_binary(self, data): sent.append(data)
            def recv(self): return 'ok'
            def close(self, timeout=1): pass
        class FakeWebsocket:
            class WebSocketBadStatusException(Exception): pass
            class WebSocketException(Exception): pass
            class WebSocketConnectionClosedException(Exception): pass
            @staticmethod
            def create_connection(url, **kwargs):
                self.assertEqual(url, 'wss://boat.example/api/device/stream')
                self.assertEqual(kwargs['header']['Authorization'], 'Bearer fixture-token')
                return Socket()
        def slow_detector(image):
            time.sleep(.5)
            return image, []
        args = argparse.Namespace(duration=0, frames=12, fps=15)
        with patch.dict(sys.modules, {'websocket': FakeWebsocket}):
            started = time.monotonic()
            code = phone.send_live_frames(Stream(), {'url': 'https://boat.example', 'token': 'fixture-token'}, args, cv2, slow_detector)
            elapsed = time.monotonic() - started
        self.assertEqual(code, 0)
        plain = [x for x in sent if b'WARIRAK-YOLO' not in x]
        annotated = [x for x in sent if b'WARIRAK-YOLO' in x]
        self.assertEqual(len(plain), 12)
        self.assertLess(elapsed, 1.6, '12 frames at 15 FPS must not wait for 0.5 s inferences')
        self.assertGreaterEqual(len(annotated), 1, 'AI frames are sent beside the live frames')

    def test_local_preview_serves_mjpeg_and_never_repeats_an_old_frame(self):
        import socket as sock
        with phone.LocalPreview(0) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                server.update(b'\xff\xd8frame-one\xff\xd9', time.monotonic())
                client = sock.create_connection(('127.0.0.1', server.server_port), timeout=3)
                client.sendall(f'GET /stream.mjpg HTTP/1.1\r\nHost: 127.0.0.1:{server.server_port}\r\n\r\n'.encode())
                data = b''
                while b'frame-one' not in data:
                    data += client.recv(4096)
                self.assertIn(b'multipart/x-mixed-replace', data)
                server.update(b'\xff\xd8frame-two\xff\xd9', time.monotonic())
                while b'frame-two' not in data:
                    data += client.recv(4096)
                self.assertEqual(data.count(b'frame-one'), 1)
                client.close()
                self.assertEqual(urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/', timeout=3).status, 200)
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/detection.jpg', timeout=3)
                self.assertEqual(missing.exception.code, 503)
            finally:
                server.shutdown(); thread.join()


if __name__ == '__main__':
    unittest.main()
