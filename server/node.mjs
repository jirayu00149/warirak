// Self-hosted entry point (Docker / Coolify). Runs the same worker/index.mjs used on
// Cloudflare, with Node stand-ins for D1 (SQLite file), static assets and the LiveCamera
// Durable Object. Start with: node --import ./server/register.mjs server/node.mjs
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import worker, { LiveCamera } from '../worker/index.mjs';
import { ROOT, dataPaths, openDatabase } from './database.mjs';
import { scheduleBackups } from './backup.mjs';
import { WebSocketPair, acceptKey } from './websocket.mjs';

const PORT = Number(process.env.PORT || 3000);
const MAX_BODY = 4 * 1024 * 1024;
const PUBLIC = path.join(ROOT, 'public');
const TRUST_PROXY = process.env.WARIRAK_TRUST_PROXY !== 'false';
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.ico': 'image/x-icon', '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8', '.zip': 'application/zip', '.pdf': 'application/pdf', '.webmanifest': 'application/manifest+json'
};

const paths = dataPaths();
const db = openDatabase(paths);
scheduleBackups(db.sqlite);

// ---- LiveCamera Durable Object stand-in -------------------------------------------------
class CameraContext {
  sockets = new Set();
  acceptWebSocket(ws, tags = []) { ws.tags = tags; this.sockets.add(ws); }
  getWebSockets(tag) { return [...this.sockets].filter(ws => ws.readyState <= 1 && (!tag || ws.tags.includes(tag))); }
  waitUntil(promise) { Promise.resolve(promise).catch(() => {}); }
}
const cameras = new Map();
const NativeResponse = globalThis.Response;
const UpgradeAwareResponse = class extends NativeResponse {
  constructor(body, init) {
    if (init?.status === 101) return { status: 101, webSocket: init.webSocket, upgrade: true };
    super(body, init);
  }
};
const LIVE_CAMERAS = {
  getByName(name) {
    if (!cameras.has(name)) {
      const ctx = new CameraContext();
      cameras.set(name, { ctx, object: new LiveCamera(ctx, env) });
    }
    const { ctx, object } = cameras.get(name);
    return {
      async fetch(request) {
        // LiveCamera.fetch is synchronous, so swapping the globals cannot interleave.
        const previousPair = globalThis.WebSocketPair;
        globalThis.WebSocketPair = WebSocketPair;
        globalThis.Response = UpgradeAwareResponse;
        try {
          const result = object.fetch(request);
          if (result?.upgrade) result.attach = ws => {
            ws.onmessage = message => { try { object.webSocketMessage(ws, message); } catch (e) { console.error('[camera] message failed', e.message); } };
            ws.onclose = () => ctx.sockets.delete(ws);
          };
          return result;
        } finally {
          globalThis.Response = NativeResponse;
          globalThis.WebSocketPair = previousPair;
        }
      }
    };
  }
};

// ---- Static assets (Cloudflare ASSETS binding stand-in) ---------------------------------
const ASSETS = {
  async fetch(request) {
    const url = new URL(request.url);
    let pathname;
    try { pathname = decodeURIComponent(url.pathname); } catch { return new Response('Bad request', { status: 400 }); }
    let file = path.join(PUBLIC, pathname);
    if (!file.startsWith(PUBLIC + path.sep) && file !== PUBLIC) return new Response('Not found', { status: 404 });
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
    if (!fs.existsSync(file) && fs.existsSync(file + '.html')) file += '.html';
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) return new Response('Not found', { status: 404 });
    const stat = fs.statSync(file);
    const etag = '"' + createHash('sha1').update(`${stat.size}-${stat.mtimeMs}`).digest('base64url') + '"';
    const headers = {
      'Content-Type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream',
      'Cache-Control': 'public, max-age=0, must-revalidate',
      'ETag': etag,
      'X-Content-Type-Options': 'nosniff'
    };
    if (request.headers.get('if-none-match') === etag) return new Response(null, { status: 304, headers });
    return new Response(request.method === 'HEAD' ? null : fs.readFileSync(file), { headers });
  }
};

const env = {
  DB: db,
  ASSETS,
  LIVE_CAMERAS,
  WARIRAK_OWNER_USER_ID: process.env.WARIRAK_OWNER_USER_ID || 'owner',
  WARIRAK_PUBLIC_MONITOR: process.env.WARIRAK_PUBLIC_MONITOR ?? 'true'
};

// ---- Node <-> Fetch API bridging ---------------------------------------------------------
function clientIp(req) {
  const forwarded = TRUST_PROXY && String(req.headers['x-forwarded-for'] || '').split(',')[0].trim();
  return forwarded || req.socket.remoteAddress || 'local';
}

function toRequest(req, body) {
  const proto = TRUST_PROXY && req.headers['x-forwarded-proto'] ? String(req.headers['x-forwarded-proto']).split(',')[0].trim() : 'http';
  const host = (TRUST_PROXY && req.headers['x-forwarded-host']) || req.headers.host || `127.0.0.1:${PORT}`;
  const headers = new Headers();
  for (const [key, value] of Object.entries(req.headers)) {
    if (key === 'cf-connecting-ip') continue; // never trust a client-supplied value
    headers.set(key, Array.isArray(value) ? value.join(', ') : value);
  }
  headers.set('cf-connecting-ip', clientIp(req));
  return new Request(`${proto}://${host}${req.url}`, { method: req.method, headers, body: body?.length ? body : undefined });
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    if (['GET', 'HEAD'].includes(req.method)) return resolve(null);
    const chunks = []; let size = 0;
    req.on('data', chunk => {
      size += chunk.length;
      if (size > MAX_BODY) { reject(Object.assign(new Error('Payload too large'), { status: 413 })); req.destroy(); return; }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

async function send(res, response) {
  const headers = {};
  response.headers.forEach((value, key) => { if (key !== 'set-cookie') headers[key] = value; });
  const cookies = response.headers.getSetCookie?.() || [];
  if (cookies.length) headers['set-cookie'] = cookies;
  res.writeHead(response.status, headers);
  res.end(response.body ? Buffer.from(await response.arrayBuffer()) : undefined);
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.url === '/healthz') {
      db.sqlite.prepare('SELECT 1').get();
      res.writeHead(200, { 'content-type': 'text/plain', 'cache-control': 'no-store' });
      return res.end('ok');
    }
    const body = await readBody(req);
    await send(res, await worker.fetch(toRequest(req, body), env));
  } catch (error) {
    if (!res.headersSent) res.writeHead(error.status || 500, { 'content-type': 'text/plain; charset=utf-8' });
    res.end(error.status === 413 ? 'Payload too large' : 'ระบบยังไม่พร้อม กรุณาลองใหม่');
    if (!error.status) console.error('[http] request failed', error.message);
  }
});

server.on('upgrade', async (req, socket, head) => {
  socket.on('error', () => socket.destroy());
  try {
    const result = await worker.fetch(toRequest(req, null), env);
    if (result?.upgrade && req.headers['sec-websocket-key']) {
      socket.write([
        'HTTP/1.1 101 Switching Protocols', 'Upgrade: websocket', 'Connection: Upgrade',
        `Sec-WebSocket-Accept: ${acceptKey(req.headers['sec-websocket-key'])}`, '', ''
      ].join('\r\n'));
      const ws = result.webSocket.server;
      result.attach(ws);
      ws.bind(socket, head);
      return;
    }
    const response = result instanceof NativeResponse ? result : new NativeResponse('Upgrade failed', { status: 400 });
    const text = await response.text();
    socket.end(`HTTP/1.1 ${response.status} ${http.STATUS_CODES[response.status] || ''}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: ${Buffer.byteLength(text)}\r\nConnection: close\r\n\r\n${text}`);
  } catch (error) {
    console.error('[ws] upgrade failed', error.message);
    socket.destroy();
  }
});

server.keepAliveTimeout = 65_000;
server.listen(PORT, () => console.log(`[warirak] listening on :${PORT} · data ${paths.dir}`));
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => {
  server.close();
  for (const { ctx } of cameras.values()) for (const ws of ctx.sockets) ws.close(1001, 'Server restarting');
  db.close();
  process.exit(0);
});
