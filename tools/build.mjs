import fs from'node:fs';import path from'node:path';import{fileURLToPath}from'node:url';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))),source=path.join(root,'frontend'),target=path.join(root,'public');fs.mkdirSync(target,{recursive:true});fs.mkdirSync(path.join(root,'build'),{recursive:true});
// Drop obsolete generated entry files when frontend modules have been removed.
for(const p of fs.readdirSync(target,{withFileTypes:true}))if(p.isFile()&&p.name!=='index.html'&&!fs.existsSync(path.join(source,p.name)))fs.unlinkSync(path.join(target,p.name));
// Copy file contents directly: cpSync's unlink/replace fails on some OneDrive files.
function copyTree(from,to){if(fs.statSync(from).isDirectory()){fs.mkdirSync(to,{recursive:true});for(const p of fs.readdirSync(from))copyTree(path.join(from,p),path.join(to,p));}else fs.copyFileSync(from,to);}
for(const p of fs.readdirSync(source,{withFileTypes:true})){if(p.name.endsWith('.html'))continue;copyTree(path.join(source,p.name),path.join(target,p.name));}
fs.copyFileSync(path.join(source,'landing.html'),path.join(target,'index.html'));
const templates=['admin','login','portal','demo','updates'].map(name=>`export const ${name}Html=${JSON.stringify(fs.readFileSync(path.join(source,name+'.html'),'utf8'))};`).join('\n');fs.writeFileSync(path.join(root,'build/templates.mjs'),templates);
console.log('Built independent Cloudflare Worker assets and protected HTML templates');
