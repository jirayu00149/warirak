// Count collection confirmations by their actual event date in Bangkok, never by detections.
export const TIME_ZONE='Asia/Bangkok';
const dateFormatter=new Intl.DateTimeFormat('en-US',{timeZone:TIME_ZONE,year:'numeric',month:'2-digit',day:'2-digit'});
export function dayKey(value=new Date()){
 const date=new Date(value);if(!Number.isFinite(date.getTime()))return null;
 const parts=dateFormatter.formatToParts(date);
 const get=k=>parts.find(p=>p.type===k).value;return`${get('year')}-${get('month')}-${get('day')}`;
}
export function collectionEvents(mission){
 if(!mission?.id||mission.source!=='simulation')return[];
 return(mission.events||[]).flatMap((event,index)=>{
  if(event.type!=='collected')return[];
  const exact=event.occurred_at&&Number.isFinite(Date.parse(event.occurred_at));if(!exact&&!Number.isFinite(Date.parse(mission.started_at)))return[];
  const timestamp=exact?event.occurred_at:new Date(Date.parse(mission.started_at)+Number(event.time_s||0)*1000).toISOString();
  return[{id:event.id||`${mission.id}:${index}`,mission_id:mission.id,source:'simulation',occurred_at:timestamp,count:1,class_id:[0,1].includes(event.class_id)?event.class_id:null,time_estimated:!exact}];
 });
}
export function mergeCollections(ledger,missions){
 const map=new Map(ledger.map(e=>[e.id,e]));
 for(const m of missions)for(const e of collectionEvents(m))if(!map.has(e.id))map.set(e.id,e);
 return[...map.values()].sort((a,b)=>a.occurred_at.localeCompare(b.occurred_at));
}
export function dailySummary(ledger,date,source='simulation'){
 const events=ledger.filter(e=>e.source===source&&dayKey(e.occurred_at)===date);
 return{date,source,total:events.length,bottles:events.filter(e=>e.class_id===0).length,caps:events.filter(e=>e.class_id===1).length,unknown:events.filter(e=>e.class_id===null).length,missions:new Set(events.map(e=>e.mission_id)).size,estimated:events.filter(e=>e.time_estimated).length};
}
export function recentDays(end=dayKey(),count=7){
 const d=new Date(end+'T12:00:00+07:00');return Array.from({length:count},(_,i)=>dayKey(d.getTime()-(count-1-i)*86400000));
}
