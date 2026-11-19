import{digest}from'./validation.mjs';

const iterations=100000;
const hex=bytes=>[...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,'0')).join('');
const unhex=value=>Uint8Array.from(value.match(/../g)||[],v=>parseInt(v,16));
export const validPassword=value=>typeof value==='string'&&value.length>=6&&value.length<=128;

async function derive(value,salt){
 const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(value),'PBKDF2',false,['deriveBits']);
 return new Uint8Array(await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',salt,iterations},key,256));
}
function equal(a,b){
 if(a.byteLength!==b.byteLength)return false;
 if(typeof crypto.subtle.timingSafeEqual==='function')return crypto.subtle.timingSafeEqual(a,b);
 let difference=0;for(let i=0;i<a.length;i++)difference|=a[i]^b[i];return difference===0;
}
export async function hashPassword(value){
 if(!validPassword(value))throw new TypeError('Password must contain 6–128 characters');
 const salt=crypto.getRandomValues(new Uint8Array(16));
 return `pbkdf2-sha256$${iterations}$${hex(salt)}$${hex(await derive(value,salt))}`;
}
export async function verifyPassword(value,stored){
 if(!validPassword(value)||typeof stored!=='string')return false;
 const match=stored.match(/^pbkdf2-sha256\$100000\$([a-f0-9]{32})\$([a-f0-9]{64})$/);
 if(match)return equal(await derive(value,unhex(match[1])),unhex(match[2]));
 // The earlier SHA-256 verifier is allowed only for the original random 256-bit keys.
 if(/^[a-f0-9]{64}$/.test(stored)&&/^wa_[a-f0-9]{64}$/.test(value))return equal(unhex(await digest(value)),unhex(stored));
 return false;
}
