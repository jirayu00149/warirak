#!/usr/bin/env python3
"""Publish Raspberry Pi health only. No camera, AI, GPIO or motor commands."""
import argparse
from datetime import datetime, timezone
import getpass
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

VERSION = '1.0.0'
DEFAULT_URL = 'https://warirak-monitor.kungmaxzaa.workers.dev'
CONFIG = Path.home() / '.config/warirak/device.json'
STOP = threading.Event()


def validate_origin(value):
    parsed = urllib.parse.urlsplit(value)
    loopback = parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')
    if (not parsed.hostname or (parsed.scheme != 'https' and not loopback)
            or parsed.username or parsed.password or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment):
        raise ValueError('Use an HTTPS website origin, or HTTP localhost for development.')
    return value.rstrip('/')


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError('Invalid configuration. Run configure again.')
    token = config.get('token', '')
    if not isinstance(token, str) or not re.fullmatch(r'wr_[a-f0-9]{64}', token):
        raise ValueError('Use the device token from Admin > System, not the admin password.')
    return {'url': validate_origin(config.get('url', DEFAULT_URL)), 'token': token}


def save_config(path, config):
    config = validate_config(config)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.device-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as out:
            json.dump(config, out)
            out.write('\n')
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_text(path):
    try:
        return Path(path).read_text(encoding='utf8').strip().strip('\x00')
    except (OSError, UnicodeError):
        return ''


def number(value, lower, upper):
    try:
        result = float(value)
        return result if math.isfinite(result) and lower <= result <= upper else None
    except (ValueError, TypeError):
        return None


def is_raspberry_pi():
    return any('Raspberry Pi' in read_text(p) for p in
               ('/proc/device-tree/model', '/sys/firmware/devicetree/base/model'))


def collect_health():
    temperature = number(read_text('/sys/class/thermal/thermal_zone0/temp'), -40000, 125000)
    memory = {}
    for line in read_text('/proc/meminfo').splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ('MemTotal:', 'MemAvailable:'):
            memory[parts[0][:-1]] = number(parts[1], 0, 1e12)
    total, available = memory.get('MemTotal'), memory.get('MemAvailable')
    used = round((total - available) / total * 100, 1) if total and available is not None and available <= total else None
    uptime = number(read_text('/proc/uptime').split(' ')[0], 0, 315576000)
    try:
        disk_free = round(shutil.disk_usage(Path.home()).free / (1024**3), 2)
    except OSError:
        disk_free = None
    return {
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'state': 'monitoring',
        'battery_percent': None,
        'cpu_temperature_c': round(temperature / 1000, 1) if temperature is not None else None,
        'memory_used_percent': used,
        'disk_free_gb': disk_free,
        'uptime_s': int(uptime) if uptime is not None else None,
        'agent_version': VERSION,
        'control_enabled': False,
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward a device token to a redirect target.
        return None


def publish(config, payload):
    req = urllib.request.Request(config['url'] + '/api/device/telemetry',
        data=json.dumps(payload, allow_nan=False).encode('utf8'), method='POST',
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + config['token'],
                 'User-Agent': 'Warirak-Pi-Monitor/' + VERSION})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=10) as response:
        raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError('Server response is too large.')
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get('accepted') is not True:
            raise ValueError('Observation was not accepted. Check the Pi clock and device configuration.')
        return result


def run(config_path, once=False):
    if not is_raspberry_pi():
        raise ValueError('Run this sender on the Raspberry Pi. Use --dry-run on another computer.')
    if not config_path.is_file():
        raise ValueError('Device configuration is missing. Run: python3 monitor_agent.py configure')
    config = validate_config(json.loads(config_path.read_text(encoding='utf8')))
    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, lambda *_: STOP.set())
    delay = 15
    while not STOP.is_set():
        try:
            result = publish(config, collect_health())
            print(datetime.now().isoformat(timespec='seconds') + ' Connected: Pi health received; motors disabled.', flush=True)
            if result.get('device_id'):
                print(config['url'] + '/monitor?boat=' + urllib.parse.quote(result['device_id']), flush=True)
            delay = 15
            if once:
                return 0
        except urllib.error.HTTPError as error:
            # Never log request headers, the token, or an untrusted response body.
            print(f'Upload HTTP {error.code}. Check website/device configuration.', file=sys.stderr, flush=True)
            if error.code in (401, 403):
                print('Token invalid/revoked. Run configure with a current device token.', file=sys.stderr)
                return 3
            if once:
                return 1
            delay = min(delay * 2, 60)
        except (OSError, ValueError, urllib.error.URLError):
            print('Not connected: check Internet, Pi date/time, and backend. Retrying with a fresh observation.', file=sys.stderr, flush=True)
            if once:
                return 1
            delay = min(delay * 2, 60)
        STOP.wait(delay)
    return 0


def install_service(config_path):
    if not is_raspberry_pi():
        raise ValueError('Install the service on the Raspberry Pi only.')
    validate_config(json.loads(config_path.read_text(encoding='utf8')))
    # Use a private copy so moving a downloaded ZIP does not break the service.
    install = Path.home() / '.local/share/warirak'
    install.mkdir(parents=True, exist_ok=True)
    agent = install / 'monitor_agent.py'
    if Path(__file__).resolve() != agent.resolve():
        shutil.copyfile(__file__, agent)
    units = Path.home() / '.config/systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    unit = ('[Unit]\nDescription=Warirak Pi health monitor (no motors)\n'
            '[Service]\nType=simple\nExecStart=/usr/bin/python3 ' + quote(agent) +
            ' --config ' + quote(config_path.resolve()) + ' run\nRestart=on-failure\nRestartSec=30\n'
            'RestartPreventExitStatus=2 3\nUMask=0077\nNoNewPrivileges=true\n'
            '[Install]\nWantedBy=default.target\n')
    (units / 'warirak-monitor.service').write_text(unit, encoding='utf8')
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'warirak-monitor.service'], check=True)
    print('Service installed. Logs: journalctl --user -u warirak-monitor -n 20')
    print('To start at boot without SSH login: sudo loginctl enable-linger "$USER"')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG)
    sub = parser.add_subparsers(dest='command', required=True)
    configure = sub.add_parser('configure', help='Save device token privately; no token in shell history')
    configure.add_argument('--url', default=DEFAULT_URL)
    runner = sub.add_parser('run', help='Publish health every 15 seconds')
    runner.add_argument('--once', action='store_true')
    runner.add_argument('--dry-run', action='store_true', help='Print local readings without publishing')
    sub.add_parser('install-service', help='Install and start a user service; no sudo required')
    args = parser.parse_args()
    try:
        if args.command == 'configure':
            validate_origin(args.url)
            token = getpass.getpass('Paste device token (input hidden): ').strip()
            save_config(args.config, {'url': args.url, 'token': token})
            print('Saved privately. Next: python3 monitor_agent.py run --once')
        elif args.command == 'install-service':
            install_service(args.config)
        elif args.dry_run:
            print(json.dumps({'dry_run': True, 'raspberry_pi': is_raspberry_pi(), 'observation': collect_health()}, indent=2))
        else:
            return run(args.config, args.once)
    except (OSError, ValueError, subprocess.CalledProcessError):
        print('Setup failed. Check the file path, device token format, HTTPS URL, and Pi user service. No credentials were printed.', file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
