// Creates the first admin account in the self-hosted database (only when none exists).
//   node server/create-owner.mjs
// Prints the new access key ONCE to your own terminal. Store it in a password manager.
import { randomBytes } from 'node:crypto';
import { hashPassword } from '../backend/password.mjs';
import { dataPaths, openDatabase } from './database.mjs';

const db = openDatabase(dataPaths(), () => {});
const owner = process.env.WARIRAK_OWNER_USER_ID || 'owner';
if (db.sqlite.prepare('SELECT 1 FROM auth_users WHERE id=?').get(owner)) {
  console.log('An owner account already exists; nothing changed. Use the admin page to rotate the key.');
} else {
  const key = 'wa_' + randomBytes(32).toString('hex');
  db.sqlite.prepare('INSERT INTO auth_users(id,username,display_name,access_key_hash,active,created_at_ms) VALUES(?,?,?,?,1,?)')
    .run(owner, 'admin', 'ผู้ดูแลวารีรักษ์', await hashPassword(key), Date.now());
  console.log('username: admin');
  console.log('access key (shown once): ' + key);
}
db.close();
