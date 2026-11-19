import test from 'node:test';
import assert from 'node:assert/strict';
import {readDetections, validDetections, detectionView} from '../frontend/yolo-frame.js';
import {jpeg} from './jpeg-fixture.mjs';
import {jpegDimensions} from '../backend/camera.mjs';

const metadata = () => ({schema:'warirak.yolo-frame.v1',model:'public-v4-2026-10-28',
  image_size:[640,480],captured_at:'2026-11-14T07:00:00+00:00',latency_ms:190,
  detections:[{class_id:0,class_name:'plastic_bottle',confidence:.88,xyxy:[10,20,90,200]},
    {class_id:1,class_name:'bottle_cap',confidence:.72,xyxy:[120,30,150,60]}],
  total_detected:2,collection_confirmed:false,control_enabled:false});
function embed(m) {
  const payload=Buffer.from('WARIRAK-YOLO\0'+JSON.stringify(m));
  const prefix=Buffer.from([255,239,(payload.length+2)>>8,(payload.length+2)&255]);
  return new Blob([jpeg.slice(0,2),prefix,payload,jpeg.slice(2)],{type:'image/jpeg'});
}
test('metadata remains paired with a JPEG accepted by existing backend',async()=>{
  const blob=embed(metadata());
  assert.deepEqual(await readDetections(blob),metadata());
  assert.deepEqual(jpegDimensions(new Uint8Array(await blob.arrayBuffer())),jpegDimensions(jpeg));
});
test('old cameras, truncated segments, malformed JSON and oversized frames give no inference',async()=>{
  assert.equal(await readDetections(new Blob([jpeg])),null);
  const tagged=embed(metadata());
  assert.equal(await readDetections(tagged.slice(0,50)),null);
  assert.equal(await readDetections(new Blob([new Uint8Array(262145)])),null);
  const malformed=new Blob([new Uint8Array([255,216,255,239,0,20]),Buffer.from('WARIRAK-YOLO\0{xxx')]);
  assert.equal(await readDetections(malformed),null);
});
test('untrusted classes, confidence, boxes and collection flags are rejected',()=>{
  for(const modify of [m=>m.detections[0].class_name='<img onerror=alert(1)>',
    m=>m.detections[0].confidence=NaN,m=>m.detections[0].xyxy[2]=700,
    m=>m.detections[0].xyxy[2]=5,m=>m.image_size=[0,480],
    m=>m.total_detected=3,m=>m.collection_confirmed=true,m=>m.control_enabled=true,
    m=>m.captured_at='invalid',m=>m.model='<script>',m=>m.latency_ms=Infinity]) {
    const value=metadata();modify(value);assert.equal(validDetections(value),false);
  }
});
test('empty, stale and detected frames do not imply collection',()=>{
  const live=detectionView(metadata(),true,true);
  assert.equal(live.title,'ตรวจพบ 2 ชิ้นในภาพ');
  assert.deepEqual(live.items,[{label:'ขวดพลาสติก',count:1,confidence:88},{label:'ฝาขวด',count:1,confidence:72}]);
  assert.equal(detectionView(metadata(),true,false).state,'stale');
  const empty={...metadata(),detections:[],total_detected:0};
  assert.equal(detectionView(empty,true,true).title,'ไม่พบขยะเป้าหมายในภาพนี้');
  assert.equal(detectionView(null,true,true).state,'waiting');
});
