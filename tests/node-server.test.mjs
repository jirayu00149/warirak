// Self-hosted (Coolify/Docker) build: real server process, SQLite file, WebSocket relay, backups.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { jpeg } from './jpeg-fixture.mjs';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const node = ['--disable-warning=ExperimentalWarning'];

function start(dataDir, port) {
  const child = spawn(process.execPath, [...node, '--import', './server/register.mjs', 'server/node.mjs'], {
    cwd: root, env: { ...process.env, PORT: String(port), WARIRAK_DATA_DIR: dataDir, WARIRAK_BACKUP_INTERVAL_HOURS: '0' }, stdio: ['ignore', 'pipe', 'pipe']
  });
  return new Promise((resolve, reject) => {
    let log = '';
    const timer = setTimeout(() => reject(new Error('server did not start\n' + log)), 15000);
    const on = chunk => { log += chunk; if (log.includes('listening')) { clearTimeout(timer); resolve(child); } };
    child.stdout.on('data', on);
    child.stderr.on('data', on);
  });
}

const stop = child => new Promise(r => { child.once('exit', r); child.kill('SIGTERM'); });
const message = ws => new Promise((resolve, reject) => {
  ws.addEventListener('message', e => resolve(e.data), { once: true });
  ws.addEventListener('close', e => reject(new Error('closed ' + e.code)), { once: true });
});
const opened = ws => new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = () => reject(new Error('ws error')); });

test('self-hosted server: login, devices, live camera relay, backup and restore', { timeout: 60000 }, async () => {
  if (!fs.existsSync(path.join(root, 'build/templates.mjs'))) execFileSync(process.execPath, ['tools/build.mjs'], { cwd: root });
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'warirak-node-'));
  const port = 4300 + Math.floor(Math.random() * 500);
  const base = `http://127.0.0.1:${port}`;
  const env = { ...process.env, WARIRAK_DATA_DIR: dataDir };
  let server = await start(dataDir, port);
  try {
    const out = execFileSync(process.execPath, [...node, 'server/create-owner.mjs'], { cwd: root, env, encoding: 'utf8' });
    const key = out.match(/wa_[a-f0-9]{64}/)[0];
    const headers = { Origin: base, 'X-Warirak-Client': 'dashboard', 'Content-Type': 'application/json' };
    const login = await fetch(base + '/api/auth/login', { method: 'POST', headers, body: JSON.stringify({ username: 'admin', access_key: key }) });
    assert.equal(login.status, 200);
    const cookie = login.headers.getSetCookie()[0].split(';')[0];
    assert.match(cookie, /^warirak_session_local=ws_/);
    const created = await fetch(base + '/api/devices', { method: 'POST', headers: { ...headers, Cookie: cookie }, body: JSON.stringify({ name: 'วารีรักษ์ 1' }) });
    assert.equal(created.status, 201);
    const device = await created.json();
    const deviceId = device.device?.id || device.id;
    assert.ok(device.token && deviceId);

    assert.equal((await fetch(base + `/api/live/devices/${deviceId}/stream`)).status, 426);
    const viewer = new WebSocket(`ws://127.0.0.1:${port}/api/live/devices/${deviceId}/stream`);
    viewer.binaryType = 'arraybuffer';
    await opened(viewer);
    const publisher = new WebSocket(`ws://127.0.0.1:${port}/api/device/stream`, { headers: { Authorization: 'Bearer ' + device.token } });
    await opened(publisher);
    const wanted = message(viewer);
    viewer.send('next');
    await new Promise(r => setTimeout(r, 50));
    const ack = message(publisher);
    publisher.send(jpeg);
    assert.equal(await ack, 'ok');
    const packet = new Uint8Array(await wanted);
    assert.deepEqual(packet.slice(8), jpeg);
    assert.ok(new DataView(packet.buffer).getFloat64(0) > 0);
    publisher.close(); viewer.close();

    const bad = new WebSocket(`ws://127.0.0.1:${port}/api/device/stream`, { headers: { Authorization: 'Bearer wr_' + '0'.repeat(64) } });
    await assert.rejects(opened(bad));

    const backup = execFileSync(process.execPath, [...node, 'server/backup.mjs'], { cwd: root, env, encoding: 'utf8' });
    assert.match(backup, /warirak-\d{8}-\d{6}\.db\.gz/);
    const file = backup.match(/warirak-\d{8}-\d{6}\.db\.gz/)[0];
    await fetch(base + '/api/devices', { method: 'POST', headers: { ...headers, Cookie: cookie }, body: JSON.stringify({ name: 'หลังสำรอง' }) });
    const count = async () => (await (await fetch(base + '/api/devices', { headers: { ...headers, Cookie: cookie } })).json()).devices.length;
    assert.equal(await count(), 2);

    execFileSync(process.execPath, [...node, 'server/backup.mjs', '--restore', file], { cwd: root, env });
    await stop(server);
    server = await start(dataDir, port);
    assert.equal(await count(), 1, 'restart applies the staged restore');
  } finally {
    await stop(server);
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test('s3 upload signs requests (AWS SigV4 shape)', async () => {
  const { s3Put } = await import('../server/backup.mjs');
  const original = globalThis.fetch;
  let seen;
  globalThis.fetch = async (url, init) => { seen = { url: String(url), init }; return new Response(null, { status: 200 }); };
  try {
    await s3Put({ WARIRAK_BACKUP_S3_ENDPOINT: 'https://acc.r2.cloudflarestorage.com', WARIRAK_BACKUP_S3_BUCKET: 'boat', WARIRAK_BACKUP_S3_ACCESS_KEY_ID: 'AKID', WARIRAK_BACKUP_S3_SECRET_ACCESS_KEY: 'secret' }, 'warirak/x.db.gz', Buffer.from('x'), new Date('2026-11-19T00:00:00Z'));
  } finally { globalThis.fetch = original; }
  assert.equal(seen.url, 'https://acc.r2.cloudflarestorage.com/boat/warirak/x.db.gz');
  assert.match(seen.init.headers.authorization, /^AWS4-HMAC-SHA256 Credential=AKID\/20261119\/auto\/s3\/aws4_request, SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature=[a-f0-9]{64}$/);
});
