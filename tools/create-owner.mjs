// Generates credentials locally. Only their SHA-256 verifier is placed in the SQL file.
import fs from'node:fs';import path from'node:path';import{randomBytes,createHash}from'node:crypto';
const args=process.argv.slice(2),option=(name,fallback)=>{const i=args.indexOf(name);return i<0?fallback:args[i+1];};
const sqlFile=path.resolve(option('--sql','../work/warirak-cloudflare-owner.sql')),credentialsFile=path.resolve(option('--credentials','../outputs/Warirak_Cloudflare_Admin_Credentials.json'));
if(fs.existsSync(credentialsFile))throw Error('Credentials file already exists; refusing to replace it');const key='wa_'+randomBytes(32).toString('hex'),hash=createHash('sha256').update(key).digest('hex');
fs.mkdirSync(path.dirname(sqlFile),{recursive:true});fs.mkdirSync(path.dirname(credentialsFile),{recursive:true});
fs.writeFileSync(sqlFile,`INSERT INTO auth_users(id,username,display_name,access_key_hash,active,created_at_ms) VALUES('owner','admin','ผู้ดูแลวารีรักษ์','${hash}',1,${Date.now()});\n`,{mode:0o600});
fs.writeFileSync(credentialsFile,JSON.stringify({username:'admin',access_key:key,login_path:'/login',note:'ข้อมูลส่วนตัวของผู้ดูแล อย่าส่งไฟล์นี้ให้ผู้ใช้งานทั่วไป'},null,2),{mode:0o600});
console.log(JSON.stringify({sql_file:sqlFile,credentials_file:credentialsFile,secret_printed:false}));
