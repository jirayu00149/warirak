// SQLite file database for the self-hosted (Coolify/Docker) build.
// Uses the same d1_migrations table as Wrangler, so a `wrangler d1 export` dump can be imported
// and only the migrations it has not seen yet are applied.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { SQLiteDatabase } from '../backend/sqlite.mjs';

export const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

export function dataPaths(dataDir = process.env.WARIRAK_DATA_DIR || path.join(ROOT, 'data')) {
  return {
    dir: dataDir,
    db: path.join(dataDir, 'warirak.db'),
    backups: process.env.WARIRAK_BACKUP_DIR || path.join(dataDir, 'backups'),
    imports: path.join(dataDir, 'import'),
    pendingRestore: path.join(dataDir, 'restore-pending.db')
  };
}

export function openDatabase(paths = dataPaths(), log = console.log) {
  fs.mkdirSync(paths.dir, { recursive: true });
  if (fs.existsSync(paths.pendingRestore)) {
    for (const suffix of ['', '-wal', '-shm']) fs.rmSync(paths.db + suffix, { force: true });
    fs.renameSync(paths.pendingRestore, paths.db);
    log('[db] restored database from restore-pending.db');
  }
  let fresh = !fs.existsSync(paths.db);
  if (!fresh && pendingImports(paths).length && isEmpty(paths.db)) {
    // A first deploy may have created an empty database before the dump was copied in.
    const aside = `${paths.db}.before-import-${Date.now()}`;
    fs.renameSync(paths.db, aside);
    for (const suffix of ['-wal', '-shm']) fs.rmSync(paths.db + suffix, { force: true });
    log(`[db] empty database moved to ${path.basename(aside)} to import the dump`);
    fresh = true;
  }
  const db = new SQLiteDatabase(paths.db);
  db.sqlite.exec('PRAGMA busy_timeout=5000;');
  if (fresh) importDumps(db, paths, log);
  migrate(db, log);
  return db;
}

function pendingImports(paths) {
  return fs.existsSync(paths.imports) ? fs.readdirSync(paths.imports).filter(n => n.endsWith('.sql')).sort() : [];
}

function isEmpty(file) {
  const db = new DatabaseSync(file, { readOnly: true });
  try {
    const has = name => !!db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?").get(name);
    return ['auth_users', 'devices'].every(t => !has(t) || !db.prepare(`SELECT 1 FROM ${t} LIMIT 1`).get());
  } finally { db.close(); }
}

function importDumps(db, paths, log) {
  const dumps = pendingImports(paths);
  for (const name of dumps) {
    const file = path.join(paths.imports, name);
    db.sqlite.exec('PRAGMA foreign_keys=OFF;');
    db.sqlite.exec(fs.readFileSync(file, 'utf8'));
    db.sqlite.exec('PRAGMA foreign_keys=ON;');
    fs.renameSync(file, file + '.imported');
    log(`[db] imported ${name}`);
  }
  if (dumps.length && !tableExists(db, 'd1_migrations')) {
    // Old dumps may lack the tracking table; the dump came from a database that was
    // migrated by `npm run deploy`, so treat the bundled migrations as applied.
    ensureTracking(db);
    for (const name of migrationFiles()) db.sqlite.prepare('INSERT OR IGNORE INTO d1_migrations(name) VALUES(?)').run(name);
    log('[db] dump had no d1_migrations table; marked bundled migrations as applied');
  }
}

function tableExists(db, name) {
  return !!db.sqlite.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?").get(name);
}

function ensureTracking(db) {
  db.sqlite.exec('CREATE TABLE IF NOT EXISTS d1_migrations(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL);');
}

function migrationFiles() {
  return fs.readdirSync(path.join(ROOT, 'migrations')).filter(n => n.endsWith('.sql')).sort();
}

export function migrate(db, log = console.log) {
  ensureTracking(db);
  const done = new Set(db.sqlite.prepare('SELECT name FROM d1_migrations').all().map(r => r.name));
  for (const name of migrationFiles()) {
    if (done.has(name)) continue;
    const sql = fs.readFileSync(path.join(ROOT, 'migrations', name), 'utf8');
    db.sqlite.exec('BEGIN IMMEDIATE');
    try {
      db.sqlite.exec(sql);
      db.sqlite.prepare('INSERT INTO d1_migrations(name) VALUES(?)').run(name);
      db.sqlite.exec('COMMIT');
      log(`[db] applied migration ${name}`);
    } catch (error) {
      db.sqlite.exec('ROLLBACK');
      throw new Error(`Migration ${name} failed: ${error.message}`);
    }
  }
}
