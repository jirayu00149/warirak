import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error

spec = importlib.util.spec_from_file_location('monitor_agent', Path(__file__).resolve().parents[1] / 'hardware/pi/monitor_agent.py')
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class MonitorAgentTests(unittest.TestCase):
    def test_reads_measurements_and_leaves_unmeasured_values_unknown(self):
        readings = {'/proc/meminfo': 'MemTotal: 1000 kB\nMemAvailable: 750 kB', '/proc/uptime': '7200.5 0', '/sys/class/thermal/thermal_zone0/temp': '49200'}
        with patch.object(agent, 'read_text', side_effect=lambda path: readings.get(path, '')):
            data = agent.collect_health()
        self.assertEqual(data['cpu_temperature_c'], 49.2)
        self.assertEqual(data['memory_used_percent'], 25)
        self.assertEqual(data['uptime_s'], 7200)
        self.assertIsNone(data['battery_percent'])
        self.assertFalse(data['control_enabled'])
        with patch.object(agent, 'read_text', return_value=''), patch.object(agent.shutil, 'disk_usage', side_effect=OSError):
            missing = agent.collect_health()
        for field in ('cpu_temperature_c', 'memory_used_percent', 'uptime_s', 'disk_free_gb'):
            self.assertIsNone(missing[field])

    def test_config_rejects_passwords_and_insecure_origins(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'private/device.json'
            config = {'url': agent.DEFAULT_URL, 'token': 'wr_' + 'a' * 64}
            agent.save_config(path, config)
            self.assertEqual(json.loads(path.read_text()), config)
        for url in ('http://example.com', 'https://user:pass@example.com', 'https://example.com/?token=x', 'https://example.com/api'):
            with self.assertRaises(ValueError):
                agent.validate_origin(url)
        with self.assertRaises(ValueError):
            agent.validate_config({'token': 'admin-password'})

    def test_sender_posts_only_health_and_does_not_follow_redirects(self):
        captured = []
        class Handler(BaseHTTPRequestHandler):
            redirect = False
            def log_message(self, *_):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                captured.append((self.path, self.headers.get('Authorization'), body))
                if self.redirect:
                    self.send_response(302)
                    self.send_header('Location', '/credential-leak')
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"accepted":true,"device_id":"boat-test"}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = agent.validate_config({'url': f'http://127.0.0.1:{server.server_port}', 'token': 'wr_' + 'b' * 64})
            self.assertTrue(agent.publish(config, agent.collect_health())['accepted'])
            self.assertEqual(captured[0][0], '/api/device/telemetry')
            self.assertEqual(captured[0][1], 'Bearer ' + config['token'])
            self.assertIsNone(captured[0][2]['battery_percent'])
            Handler.redirect = True
            with self.assertRaises(urllib.error.HTTPError):
                agent.publish(config, agent.collect_health())
            self.assertEqual(len(captured), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_non_pi_cannot_publish_as_pi(self):
        with patch.object(agent, 'is_raspberry_pi', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Raspberry Pi'):
                agent.run(Path('unused'), once=True)


if __name__ == '__main__':
    unittest.main()
