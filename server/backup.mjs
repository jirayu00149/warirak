// Database backups for the self-hosted build.
//   node server/backup.mjs            take a backup now (also used by a Coolify Scheduled Task)
//   node server/backup.mjs --list     list backups
// Each backup is a consistent SQLite copy (VACUUM INTO), gzipped, kept for WARIRAK_BACKUP_KEEP
// runs (default 14). If WARIRAK_BACKUP_S3_* is set, the file is also uploaded off-server
// (any S3-compatible storage: Cloudflare R2, Backblaze B2, MinIO, AWS S3).
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { createHash, createHmac } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { dataPaths } from './database.mjs';

const PREFIX = 'warirak-';

function stamp(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15);
}

export function listBackups(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter(n => n.startsWith(PREFIX) && n.endsWith('.db.gz')).sort()
    .map(name => ({ name, bytes: fs.statSync(path.join(dir, name)).size }));
}

export async function backupNow({ sqlite, paths = dataPaths(), keep = Number(process.env.WARIRAK_BACKUP_KEEP || 14), env = process.env, log = console.log } = {}) {
  fs.mkdirSync(paths.backups, { recursive: true });
  const name = `${PREFIX}${stamp()}.db`;
  const raw = path.join(paths.backups, name + '.tmp');
  const own = !sqlite;
  const db = sqlite || new DatabaseSync(paths.db);
  try {
    fs.rmSync(raw, { force: true });
    db.prepare('VACUUM INTO ?').run(raw);
  } finally {
    if (own) db.close();
  }
  const check = new DatabaseSync(raw, { readOnly: true });
  const ok = check.prepare('PRAGMA integrity_check').get();
  check.close();
  if (Object.values(ok)[0] !== 'ok') { fs.rmSync(raw, { force: true }); throw new Error('Backup failed integrity check'); }
  const gz = path.join(paths.backups, name + '.gz');
  fs.writeFileSync(gz, zlib.gzipSync(fs.readFileSync(raw), { level: 9 }));
  fs.rmSync(raw, { force: true });
  const all = listBackups(paths.backups);
  for (const old of all.slice(0, Math.max(0, all.length - Math.max(1, keep)))) fs.rmSync(path.join(paths.backups, old.name));
  const bytes = fs.statSync(gz).size;
  let uploaded = false;
  if (env.WARIRAK_BACKUP_S3_BUCKET) {
    await s3Put(env, `${env.WARIRAK_BACKUP_S3_PREFIX ?? 'warirak/'}${path.basename(gz)}`, fs.readFileSync(gz));
    uploaded = true;
  }
  const result = { file: path.basename(gz), bytes, kept: Math.min(all.length, keep), uploaded, at: new Date().toISOString() };
  fs.writeFileSync(path.join(paths.backups, 'latest.json'), JSON.stringify(result, null, 2));
  log(`[backup] ${result.file} ${(bytes / 1024).toFixed(1)} KB${uploaded ? ' (uploaded)' : ''}`);
  return result;
}

// Writes a backup to restore-pending.db; the server swaps it in on its next start.
export function stageRestore(file, paths = dataPaths()) {
  const source = path.isAbsolute(file) ? file : path.join(paths.backups, file);
  const data = source.endsWith('.gz') ? zlib.gunzipSync(fs.readFileSync(source)) : fs.readFileSync(source);
  const tmp = paths.pendingRestore + '.tmp';
  fs.writeFileSync(tmp, data);
  const check = new DatabaseSync(tmp, { readOnly: true });
  const ok = Object.values(check.prepare('PRAGMA integrity_check').get())[0];
  check.close();
  if (ok !== 'ok') { fs.rmSync(tmp); throw new Error('Backup file is damaged'); }
  fs.renameSync(tmp, paths.pendingRestore);
  return paths.pendingRestore;
}

// Minimal AWS Signature V4 PUT (path-style), enough for S3-compatible object storage.
export async function s3Put(env, key, body, now = new Date()) {
  const endpoint = new URL(env.WARIRAK_BACKUP_S3_ENDPOINT || `https://s3.${env.WARIRAK_BACKUP_S3_REGION || 'us-east-1'}.amazonaws.com`);
  const region = env.WARIRAK_BACKUP_S3_REGION || 'auto';
  const bucket = env.WARIRAK_BACKUP_S3_BUCKET;
  const objectPath = '/' + [bucket, ...key.split('/')].map(encodeURIComponent).join('/');
  const amzDate = now.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  const day = amzDate.slice(0, 8);
  const payloadHash = createHash('sha256').update(body).digest('hex');
  const headers = { host: endpoint.host, 'x-amz-content-sha256': payloadHash, 'x-amz-date': amzDate };
  const signed = Object.keys(headers).sort();
  const canonical = ['PUT', objectPath, '', ...signed.map(h => `${h}:${headers[h]}`), '', signed.join(';'), payloadHash].join('\n');
  const scope = `${day}/${region}/s3/aws4_request`;
  const toSign = ['AWS4-HMAC-SHA256', amzDate, scope, createHash('sha256').update(canonical).digest('hex')].join('\n');
  const hmac = (k, v) => createHmac('sha256', k).update(v).digest();
  let k = hmac('AWS4' + env.WARIRAK_BACKUP_S3_SECRET_ACCESS_KEY, day);
  for (const part of [region, 's3', 'aws4_request']) k = hmac(k, part);
  const signature = createHmac('sha256', k).update(toSign).digest('hex');
  const response = await fetch(new URL(objectPath, endpoint), {
    method: 'PUT',
    body,
    headers: {
      ...headers,
      'content-type': 'application/gzip',
      authorization: `AWS4-HMAC-SHA256 Credential=${env.WARIRAK_BACKUP_S3_ACCESS_KEY_ID}/${scope}, SignedHeaders=${signed.join(';')}, Signature=${signature}`
    }
  });
  if (!response.ok) throw new Error(`Off-site upload failed: HTTP ${response.status}`);
}

export function scheduleBackups(sqlite, log = console.log) {
  const hours = Number(process.env.WARIRAK_BACKUP_INTERVAL_HOURS ?? 24);
  if (!(hours > 0)) { log('[backup] automatic backups disabled'); return null; }
  const run = () => backupNow({ sqlite, log }).catch(error => log('[backup] failed: ' + error.message));
  setTimeout(run, 60_000).unref();
  return setInterval(run, hours * 3_600_000).unref();
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const paths = dataPaths();
  if (process.argv.includes('--list')) {
    for (const b of listBackups(paths.backups)) console.log(`${b.name}\t${(b.bytes / 1024).toFixed(1)} KB`);
  } else if (process.argv.includes('--restore')) {
    const file = process.argv[process.argv.indexOf('--restore') + 1];
    if (!file) throw new Error('Usage: node server/backup.mjs --restore <backup-file>');
    console.log(`[restore] staged ${stageRestore(file, paths)}; restart the app to apply it`);
  } else {
    await backupNow({ paths });
  }
}
