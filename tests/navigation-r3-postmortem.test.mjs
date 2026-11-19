import test from 'node:test';
import assert from 'node:assert/strict';
import {clearanceOnlyStop} from '../ai/diagnose_navigation_r3.mjs';
const observation=()=>({timestamp_unix_ms:1000,sensors:{armed:true,manual_override:false,range_evidence:{status:'fresh',captured_at_ms:1000},clearance_m:[1,1,1,1,1,1,.34,1]},mission:{mode:'TRACKING'}});
test('Clearance-only STOP requires a fresh complete front frame and an exclusively neutral mask',()=>{
 const o=observation();assert.equal(clearanceOnlyStop(o,[0]),true);
 assert.equal(clearanceOnlyStop(o,[0,4]),false);
 o.sensors.clearance_m[0]=null;assert.equal(clearanceOnlyStop(o,[0]),false);
});
test('Missing or old range and a pre-existing assistance latch are not clearance-only STOP',()=>{
 const o=observation();o.sensors.range_evidence.status='waiting';assert.equal(clearanceOnlyStop(o,[0]),false);
 o.sensors.range_evidence.status='fresh';o.sensors.range_evidence.captured_at_ms=699;assert.equal(clearanceOnlyStop(o,[0]),false);
 o.sensors.range_evidence.captured_at_ms=1000;o.mission.mode='ACTUATION_UNAVAILABLE';assert.equal(clearanceOnlyStop(o,[0]),false);
});
test('Operator override/disarm, invalid clearances and the exact threshold are distinguished',()=>{
 const o=observation();o.sensors.manual_override=true;assert.equal(clearanceOnlyStop(o,[0]),false);
 o.sensors.manual_override=false;o.sensors.armed=false;assert.equal(clearanceOnlyStop(o,[0]),false);
 o.sensors.armed=true;o.sensors.clearance_m[6]=NaN;assert.equal(clearanceOnlyStop(o,[0]),false);
 o.sensors.clearance_m[6]=.35;assert.equal(clearanceOnlyStop(o,[0]),false);
});
