import{handleApi}from'../backend/api.mjs';
import{Access}from'../backend/access.mjs';
import{Auth}from'../backend/auth.mjs';
import{liveCamera}from'./live-camera.mjs';
export{LiveCamera}from'./live-camera.mjs';
import{adminHtml,loginHtml,portalHtml,demoHtml,updatesHtml}from'../build/templates.mjs';
function html(value,status=200){return new Response(value,{status,headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});}
export default{async fetch(request,env){try{
 const url=new URL(request.url);if(url.protocol!=='https:'&&!['127.0.0.1','localhost','[::1]'].includes(url.hostname)){url.protocol='https:';return Response.redirect(url,308);}
 const owner=env.WARIRAK_OWNER_USER_ID||'owner',auth=new Auth(env.DB,owner),user=await auth.principal(request);
 if(url.pathname.startsWith('/api/auth/'))return auth.handle(request);
 const stream=await liveCamera(request,env,owner,user);if(stream)return stream;
 if(url.pathname.startsWith('/api/'))return handleApi(request,{db:env.DB,userId:user?.id||null,displayName:user?.display_name||'',ownerUserId:owner,publicMonitorEnabled:env.WARIRAK_PUBLIC_MONITOR==='true',storage:'Cloudflare D1'});
 if(['/monitor/','/monitor.html'].includes(url.pathname))return Response.redirect(new URL('/monitor'+url.search,request.url),308);
 if(url.pathname==='/monitor')return html(portalHtml);
 if(url.pathname==='/demo')return html(demoHtml);
 if(url.pathname==='/updates')return html(updatesHtml);
 if(url.pathname==='/login'){if(user){const s=await new Access(env.DB,owner).session(user.id);if(s.can_admin)return Response.redirect(new URL('/admin',request.url),303);}return html(loginHtml);}
 if(['/admin.html','/admin/'].includes(url.pathname))return Response.redirect(new URL('/admin',request.url),308);
 if(url.pathname==='/admin'){if(!user)return Response.redirect(new URL('/login',request.url),302);try{const access=new Access(env.DB,owner);await access.member(await access.session(user.id),true);}catch{return html('<html lang="th"><meta charset="utf-8"><p>บัญชีนี้ไม่มีสิทธิ์ผู้ดูแลระบบ</p><a href="/">กลับหน้าติดตามเรือ</a></html>',403);}return html(adminHtml);}
 return env.ASSETS.fetch(request);
 }catch(error){console.error('Worker request failed');return new Response('ระบบยังไม่พร้อม กรุณาลองใหม่',{status:503,headers:{'Content-Type':'text/plain; charset=utf-8','Cache-Control':'no-store'}});}}};
