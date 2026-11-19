import test from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { jpeg } from './jpeg-fixture.mjs';

// The Worker runtime module is not available in Node; stub only the base class.
register('data:text/javascript,' + encodeURIComponent(`
export async function resolve(specifier, context, next) {
  if (specifier === 'cloudflare:workers') return { url: 'data:text/javascript,export class DurableObject{constructor(ctx,env){this.ctx=ctx;this.env=env;}}', shortCircuit: true };
  return next(specifier, context);
}`));
const { LiveCamera, hasDetectionMetadata } = await import('../worker/live-camera.mjs');

function withMetadata(image) {
  const payload = new TextEncoder().encode('WARIRAK-YOLO\0{"schema":"warirak.yolo-frame.v1"}');
  const out = new Uint8Array(image.length + 4 + payload.length);
  out.set(image.slice(0, 2));
  out.set([0xff, 0xef, (payload.length + 2) >> 8, (payload.length + 2) & 255], 2);
  out.set(payload, 6);
  out.set(image.slice(2), 6 + payload.length);
  return out;
}

function socket(role) {
  let attachment = { role, owner: 'owner', deviceId: 'boat', expires: Date.now() + 60000, waiting: false, frameAt: 0, detectionAt: 0 };
  return {
    role, sent: [], closed: null, readyState: WebSocket.OPEN,
    serializeAttachment(value) { attachment = structuredClone(value); },
    deserializeAttachment() { return structuredClone(attachment); },
    send(value) { this.sent.push(value); },
    close(code, reason) { this.closed = { code, reason }; }
  };
}

function relay() {
  const sockets = [];
  const ctx = { getWebSockets: tag => sockets.filter(s => s.role === tag), waitUntil() {} };
  const camera = new LiveCamera(ctx, { DB: null });
  camera.saveSnapshot = async () => {};
  const publisher = socket('publisher'), viewer = socket('viewer');
  sockets.push(publisher, viewer);
  return { camera, publisher, viewer, sockets };
}

const frames = s => s.sent.filter(x => x instanceof ArrayBuffer);
const body = packet => new Uint8Array(packet).slice(8);
const publish = (r, image) => r.camera.webSocketMessage(r.publisher, image.slice().buffer);

test('APP15 YOLO metadata is recognised only directly after SOI', () => {
  assert.equal(hasDetectionMetadata(jpeg), false);
  assert.equal(hasDetectionMetadata(withMetadata(jpeg)), true);
});

test('viewer gets the newest frame immediately instead of waiting for the next publish', () => {
  const r = relay();
  publish(r, jpeg);
  assert.equal(frames(r.viewer).length, 0, 'not waiting yet: nothing is pushed');
  r.camera.webSocketMessage(r.viewer, 'next');
  assert.equal(frames(r.viewer).length, 1, 'the latest frame is sent at once');
  assert.deepEqual(body(frames(r.viewer)[0]), jpeg);
  r.camera.webSocketMessage(r.viewer, 'next');
  assert.equal(frames(r.viewer).length, 1, 'the same frame is never sent twice');
  r.camera.lastFrameAt = 0;
  publish(r, jpeg);
  assert.equal(frames(r.viewer).length, 2, 'a waiting viewer receives the next publish');
  assert.deepEqual(r.publisher.sent.filter(x => typeof x === 'string'), ['ok', 'ok']);
});

test('AI frames bypass the live limiter and are delivered before plain frames', () => {
  const r = relay();
  publish(r, jpeg);
  publish(r, withMetadata(jpeg));
  assert.deepEqual(r.publisher.sent, ['ok', 'ok'], 'the detection frame right after a live frame is not skipped');
  publish(r, jpeg);
  assert.equal(r.publisher.sent.at(-1), 'skip', 'plain frames remain rate limited');
  r.camera.webSocketMessage(r.viewer, 'next');
  assert.equal(hasDetectionMetadata(body(frames(r.viewer)[0])), true);
  r.camera.webSocketMessage(r.viewer, 'next');
  assert.equal(hasDetectionMetadata(body(frames(r.viewer)[1])), false);
});

test('an old frame is not replayed to a new viewer as if it were live', () => {
  const r = relay();
  publish(r, jpeg);
  r.camera.latestFrame.at -= 6000;
  r.camera.webSocketMessage(r.viewer, 'next');
  assert.equal(frames(r.viewer).length, 0);
  assert.equal(r.viewer.deserializeAttachment().waiting, true);
});

test('expired viewer access is closed rather than served', () => {
  const r = relay();
  r.viewer.serializeAttachment({ ...r.viewer.deserializeAttachment(), expires: Date.now() - 1 });
  r.camera.webSocketMessage(r.viewer, 'next');
  assert.equal(r.viewer.closed.code, 4001);
});
