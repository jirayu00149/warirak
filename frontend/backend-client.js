// Browser-local records are an offline outbox; acknowledged totals come from the API.
export class BackendClient{
 constructor({onChange,getMissions,getCollections}){this.onChange=onChange;this.getMissions=getMissions;this.getCollections=getCollections;this.available=false;this.authenticated=false;this.storage='';this.status='connecting';this.error='';this.snapshot=null;this.snapshotKnownIds=new Set();this.ackedIds=new Set();this.pendingMissions=new Map();this.pendingCollections=new Map();this.busy=false;this.desired={date:null,source:'simulation'};
  try{const saved=JSON.parse(localStorage.getItem('warirak.backend-outbox.v1'));for(const m of saved?.missions||[])this.pendingMissions.set(m.id,m);for(const e of saved?.collections||[])this.pendingCollections.set(e.id,e);}catch{}
 }
 persist(){try{localStorage.setItem('warirak.backend-outbox.v1',JSON.stringify({missions:[...this.pendingMissions.values()],collections:[...this.pendingCollections.values()]}));}catch{this.error='พื้นที่เก็บคิวในเบราว์เซอร์ไม่เพียงพอ กรุณาส่งออก CSV';}this.onChange();}
 queue(mission,live=true){if(mission?.id&&mission.source==='simulation'){
  const events=(mission.events||[]).filter(e=>e.type==='collected');const revision=live?Date.now():mission.client_updated_at||mission.ended_at||Math.max(Date.parse(mission.started_at)||0,...events.map(e=>Date.parse(e.occurred_at)||0));
  const data={id:mission.id,source:'simulation',scenario:mission.scenario||'imported',state:mission.state,started_at:mission.started_at,elapsed_s:mission.elapsed_s||0,detected_count:mission.detected_count||0,events,client_updated_at:revision};this.pendingMissions.set(data.id,data);
 }for(const e of this.getCollections())if(e.source==='simulation'&&!this.ackedIds.has(e.id))this.pendingCollections.set(e.id,e);this.persist();clearTimeout(this.timer);this.timer=setTimeout(()=>this.sync(),150);}
 async request(path,{method='GET',body}={}){const response=await fetch(path,{method,credentials:'same-origin',headers:method==='GET'?{}:{'Content-Type':'application/json','X-Warirak-Client':'dashboard'},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(10000)});let value;try{value=await response.json();}catch{throw Error('เซิร์ฟเวอร์ไม่ได้ส่งข้อมูล API กรุณาเปิดผ่าน backend');}if(!response.ok){const error=Error(value.error?.message||'API ไม่ตอบสนอง');error.status=response.status;throw error;}return value;}
 async start(date,source='simulation'){this.desired={date,source};try{const health=await this.request('/api/health');this.available=true;this.authenticated=health.authenticated;this.storage=health.storage;if(!health.authenticated){this.status='sign-in';this.onChange();return;}const session=await this.request('/api/session');this.userId=session.user_id;this.role=session.role;if(session.role!=='admin'){location.replace('/');return;}
   for(const m of this.getMissions())this.queue(m,false);for(const e of this.getCollections())if(e.source==='simulation')this.pendingCollections.set(e.id,e);this.persist();await this.sync();
  }catch(e){this.status='offline';this.error=e.message;this.onChange();}
  this.poll=setInterval(()=>this.sync(),10000);
 }
 select(date,source){this.desired={date,source};this.sync();}
 async sync(){if(this.busy||!this.available||!this.authenticated)return;this.busy=true;this.status='syncing';this.onChange();try{
   while(this.pendingMissions.size||this.pendingCollections.size){const missions=[...this.pendingMissions.values()].slice(0,10),collections=[...this.pendingCollections.values()].slice(0,100);const result=await this.request('/api/simulation/sync',{method:'POST',body:{missions,collections}});
    for(const m of missions)if(this.pendingMissions.get(m.id)===m)this.pendingMissions.delete(m.id);for(const e of collections)if(this.pendingCollections.get(e.id)===e)this.pendingCollections.delete(e.id);for(const eventId of result.accepted_event_ids)this.ackedIds.add(eventId);this.persist();
   }
   const wanted={...this.desired},known=new Set(this.ackedIds),snapshot=await this.request(`/api/dashboard?date=${encodeURIComponent(wanted.date)}&source=${wanted.source}`);this.snapshot=snapshot;this.snapshotKnownIds=known;this.status='online';this.error='';this.persist();
  }catch(e){this.status=e.status===401?'sign-in':'offline';this.error=e.message;if(e.status===401)this.authenticated=false;this.onChange();}finally{this.busy=false;if(this.status==='online'&&(this.pendingMissions.size||this.snapshot?.date!==this.desired.date||this.snapshot?.source!==this.desired.source))setTimeout(()=>this.sync(),100);}
 }
 async createDevice(name){const value=await this.request('/api/devices',{method:'POST',body:{name}});await this.sync();return value;}
 async revokeDevice(deviceId){await this.request('/api/devices/'+encodeURIComponent(deviceId),{method:'DELETE'});await this.sync();}
 get pending(){return this.pendingMissions.size+this.pendingCollections.size;}
}
