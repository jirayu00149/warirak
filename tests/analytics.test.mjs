import test from'node:test';import assert from'node:assert/strict';import{dayKey,collectionEvents,mergeCollections,dailySummary,recentDays}from'../frontend/analytics.js';
test('Bangkok dates, midnight missions and confirmations are counted independently',()=>{
 const mission={id:'midnight',source:'simulation',started_at:'2026-10-27T16:59:50Z',events:[{type:'detection',occurred_at:'2026-10-27T16:59:55Z'},{type:'collected',occurred_at:'2026-10-27T16:59:59Z',class_id:0},{type:'collected',occurred_at:'2026-10-27T17:00:01Z',class_id:1}]};
 const ledger=mergeCollections([], [mission]);assert.equal(ledger.length,2);assert.equal(mergeCollections(ledger,[mission,mission]).length,2);assert.equal(dayKey('2026-10-27T17:00:00Z'),'2026-10-28');assert.equal(dailySummary(ledger,'2026-10-27').bottles,1);assert.equal(dailySummary(ledger,'2026-10-28').caps,1);assert.equal(dailySummary(ledger,'2026-10-28','hardware').total,0);
});
test('legacy timestamps are labelled estimated and collection ledger survives a trimmed mission list',()=>{
 const missions=Array.from({length:120},(_,i)=>({id:String(i),source:'simulation',started_at:'2026-10-27T01:00:00Z',events:[{type:'collected',time_s:20}]}));const ledger=mergeCollections([],missions);assert.equal(mergeCollections(ledger,missions.slice(0,100)).length,120);assert.equal(dailySummary(ledger,'2026-10-27').estimated,120);assert.equal(collectionEvents({id:'a',source:'hardware',events:[{type:'collected'}]}).length,0);assert.deepEqual(recentDays('2026-01-02',3),['2025-12-31','2026-01-01','2026-01-02']);
});
