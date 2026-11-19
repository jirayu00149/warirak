import{fail,digest,token}from'./validation.mjs';
export class Access{
 constructor(db,owner){this.db=db;this.owner=owner;}
 stmt(sql,...args){return this.db.prepare(sql).bind(...args);}
 async session(userId,displayName=''){
  if(!this.owner)fail(503,'owner_not_configured','ยังไม่ได้กำหนดบัญชีผู้ดูแลระบบ');
  if(!userId)return{role:'anonymous',authenticated:false,can_admin:false};
  if(userId===this.owner)return{role:'admin',authenticated:true,can_admin:true,is_owner:true,user_id:userId,display_name:displayName||'เจ้าของระบบ'};
  const m=await this.stmt('SELECT * FROM workspace_members WHERE owner_id=? AND user_id=?',this.owner,userId).first();
  return{role:m&&m.active===1?m.role:'pending',authenticated:true,can_admin:m?.active===1&&m.role==='admin',is_owner:false,user_id:userId,display_name:displayName||m?.display_name||'ผู้ใช้งาน',blocked:m?.active===0};
 }
 async member(session,admin=false){if(!session.authenticated)fail(401,'sign_in_required','กรุณาเข้าสู่ระบบ');if(!['admin','viewer'].includes(session.role)||admin&&session.role!=='admin')fail(403,admin?'admin_required':'membership_required',admin?'เฉพาะผู้ดูแลระบบเท่านั้น':'ต้องได้รับสิทธิ์จากผู้ดูแลระบบก่อน');return session;}
 async invitation(){const code=token().replace(/^wr_/,'wi_'),id='invite-'+crypto.randomUUID(),expires=Date.now()+86400000;await this.stmt('INSERT INTO workspace_invitations(owner_id,id,token_hash,expires_at_ms) VALUES(?,?,?,?)',this.owner,id,await digest(code),expires).run();return{id,code,role:'viewer',expires_at:new Date(expires).toISOString(),shown_once:true};}
 async redeem(userId,displayName,code){if(!/^wi_[a-f0-9]{64}$/.test(code||''))fail(400,'invalid_invitation','รหัสเชิญไม่ถูกต้อง');if(userId===this.owner)fail(409,'already_owner','บัญชีเจ้าของมีสิทธิ์อยู่แล้ว');const hash=await digest(code),existing=await this.stmt('SELECT user_id FROM workspace_members WHERE owner_id=? AND user_id=?',this.owner,userId).first();if(existing)fail(409,'already_member','บัญชีนี้มีรายการสมาชิกแล้ว กรุณาติดต่อผู้ดูแล');
  const now=Date.now(),result=await this.db.batch([
   this.stmt(`INSERT INTO workspace_members(owner_id,user_id,display_name,role,active,joined_at_ms) SELECT owner_id,?,?,'viewer',1,? FROM workspace_invitations WHERE owner_id=? AND token_hash=? AND used_by IS NULL AND expires_at_ms>? ON CONFLICT(owner_id,user_id) DO NOTHING`,userId,displayName||'ผู้ใช้งาน',now,this.owner,hash,now),
   this.stmt('UPDATE workspace_invitations SET used_by=?,used_at_ms=? WHERE owner_id=? AND token_hash=? AND used_by IS NULL AND expires_at_ms>?',userId,now,this.owner,hash,now),
  ]);if(!result[0].meta?.changes)fail(400,'expired_invitation','รหัสเชิญหมดอายุหรือถูกใช้แล้ว');return{joined:true,role:'viewer'};
 }
 async members(){const rows=await this.stmt('SELECT user_id,display_name,role,active,joined_at_ms FROM workspace_members WHERE owner_id=? ORDER BY joined_at_ms DESC LIMIT 100',this.owner).all();return[{user_id:this.owner,display_name:'เจ้าของระบบ',role:'admin',active:1,is_owner:true},...rows.results];}
 async update(actor,userId,{role,active}){if(userId===this.owner||userId===actor)fail(403,'protected_account','ไม่อนุญาตแก้สิทธิ์เจ้าของหรือบัญชีที่กำลังใช้งาน');if(!['admin','viewer'].includes(role)||typeof active!=='boolean')fail(400,'invalid_role','สิทธิ์ต้องเป็น admin หรือ viewer และระบุ active');const r=await this.stmt('UPDATE workspace_members SET role=?,active=? WHERE owner_id=? AND user_id=?',role,Number(active),this.owner,userId).run();if(!r.meta?.changes)fail(404,'member_not_found','ไม่พบสมาชิก');return{updated:true};}
}
