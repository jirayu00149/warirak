// Timestamped synthetic range evidence. Cached frames are for diagnosis, never actuation.
const finite=x=>typeof x==='number'&&Number.isFinite(x);
export const RANGE_EVIDENCE_SCHEMA='warirak.sim-range.v2';
export class SimRangeEvidence{
 constructor(maxAgeMs=300){if(!Number.isInteger(maxAgeMs)||maxAgeMs<1||maxAgeMs>300)throw Error('Invalid range evidence age');this.maxAgeMs=maxAgeMs;this.lastValid=null;this.lastSequence=-1;this.lastCapture=null;this.lastSignature=null;this.lastNow=null;this.missingSince=null;this.status='missing_wait';this.reason='no_range_packet';}
 _invalid(reason){this.lastValid=null;this.status='invalid';this.reason=reason;return this;}
 ingest(packet,now,{invalid=false}={}){
  if(!finite(now)||now<=0)throw Error('Finite receiver clock required');
  if(this.lastNow!==null&&now<this.lastNow){this._invalid('receiver_clock_regression');return this.snapshot(now);}
  this.lastNow=now;
  if(invalid){this._invalid('explicit_range_failure');return this.snapshot(now);}
  if(packet===null){
   if(this.status==='invalid')return this.snapshot(now);
   if(this.missingSince===null)this.missingSince=now;
   const age=this.lastValid?now-this.lastValid.timestamp_unix_ms:now-this.missingSince;
   this.status=age>this.maxAgeMs?'stale':this.lastValid?'cached_wait':'missing_wait';this.reason=age>this.maxAgeMs?'range_watchdog':'no_new_range_packet';return this.snapshot(now);
  }
  const valid=packet&&packet.schema===RANGE_EVIDENCE_SCHEMA&&packet.source==='simulation'&&packet.units==='m'&&packet.frame==='body'&&packet.calibrated===true&&Number.isInteger(packet.sequence)&&packet.sequence>=0&&finite(packet.timestamp_unix_ms)&&packet.timestamp_unix_ms>0&&packet.timestamp_unix_ms<=now&&Array.isArray(packet.ranges)&&packet.ranges.length===8&&packet.ranges.every(x=>x===null||finite(x)&&x>=0&&x<=1.5);
  if(!valid){this._invalid('invalid_range_packet');return this.snapshot(now);}
  const signature=JSON.stringify(packet);
  if(packet.sequence<this.lastSequence||this.lastCapture!==null&&packet.timestamp_unix_ms<this.lastCapture){this._invalid('range_clock_or_sequence_regression');return this.snapshot(now);}
  if(packet.sequence===this.lastSequence){
   if(signature!==this.lastSignature){this._invalid('range_sequence_conflict');return this.snapshot(now);}
   return this.ingest(null,now);
  }
  this.lastValid=structuredClone(packet);this.lastSequence=packet.sequence;this.lastCapture=packet.timestamp_unix_ms;this.lastSignature=signature;this.missingSince=null;
  this.status=now-packet.timestamp_unix_ms>this.maxAgeMs?'stale':'fresh';this.reason=this.status==='fresh'?'new_original_range_frame':'range_watchdog';return this.snapshot(now);
 }
 snapshot(now){
  const age=this.lastValid?now-this.lastValid.timestamp_unix_ms:null;
  const status=this.status!=='invalid'&&age!==null&&age>this.maxAgeMs?'stale':this.status;
  return{schema:'warirak.range-evidence-state.v2',source:'simulation',status,reason:status==='stale'?'range_watchdog':this.reason,captured_at_ms:this.lastValid?.timestamp_unix_ms??null,age_ms:age,sequence:this.lastValid?.sequence??null,ranges:this.lastValid?structuredClone(this.lastValid.ranges):null,fresh_frame_received:status==='fresh',cached_for_diagnosis_only:status==='cached_wait'||status==='stale',control_enabled:false};
 }
}
