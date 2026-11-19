import { DurableObject } from 'cloudflare:workers';
import { Access } from '../backend/access.mjs';
import { Camera, jpegDimensions } from '../backend/camera.mjs';
import { Repository } from '../backend/repository.mjs';
import { ApiError, id } from '../backend/validation.mjs';

const MAX_JPEG_BYTES = 262144;
// About 15 FPS ceiling for plain live frames. Frames carrying YOLO metadata have their own
// limit so the slower AI result is never dropped by the live-frame limiter.
const MIN_FRAME_INTERVAL = 60;
const MIN_DETECTION_INTERVAL = 250;
// A viewer that connects (or asks for the next frame) gets the newest frame at once, but
// only while it is still recent. Older frames wait for the publisher instead of being
// replayed as if they were live.
const REPLAY_MAX_AGE = 5000;
const DETECTION_REPLAY_MAX_AGE = 15000;
const YOLO_SIGNATURE = [0x57,0x41,0x52,0x49,0x52,0x41,0x4b,0x2d,0x59,0x4f,0x4c,0x4f,0x00];

export function hasDetectionMetadata(jpeg) {
  // detection_frame.py inserts APP15 ("WARIRAK-YOLO\0" + JSON) directly after SOI.
  if (jpeg.length < 6 + YOLO_SIGNATURE.length || jpeg[2] !== 0xff || jpeg[3] !== 0xef) return false;
  return YOLO_SIGNATURE.every((value, index) => jpeg[6 + index] === value);
}

function packetFor(jpeg, at) {
  const packet = new Uint8Array(8 + jpeg.length);
  new DataView(packet.buffer).setFloat64(0, at);
  packet.set(jpeg, 8);
  return packet.buffer;
}
const SNAPSHOT_INTERVAL = 30000;
const SESSION_MS = 300000;

export async function liveCamera(request, env, owner, user) {
  const path = new URL(request.url).pathname;
  const viewer = path.match(/^\/api\/live\/devices\/([^/]+)\/stream$/);
  const publisher = path === '/api/device/stream';
  if (!viewer && !publisher) return null;
  if (request.method !== 'GET' || request.headers.get('upgrade')?.toLowerCase() !== 'websocket') {
    return new Response('WebSocket upgrade required', { status: 426 });
  }
  const origin = request.headers.get('origin');
  if (viewer && origin && origin !== new URL(request.url).origin) {
    return new Response('Camera requires a same-origin viewer', { status: 403 });
  }
  try {
    let deviceId;
    if (publisher) {
      const token = request.headers.get('authorization')?.match(/^Bearer (wr_[a-f0-9]{64})$/)?.[1];
      if (!token) return new Response('Device token required', { status: 401 });
      const device = await new Repository(env.DB).authenticateDevice(token);
      if (device.owner_id !== owner) return new Response('Device workspace mismatch', { status: 403 });
      deviceId = device.id;
    } else {
      if (env.WARIRAK_PUBLIC_MONITOR !== 'true') {
        const access = new Access(env.DB, owner);
        await access.member(await access.session(user?.id));
      }
      deviceId = id(decodeURIComponent(viewer[1]));
      const device = await env.DB.prepare(
        'SELECT id FROM devices WHERE owner_id=? AND id=? AND revoked_at_ms IS NULL'
      ).bind(owner, deviceId).first();
      if (!device) return new Response('Unknown camera', { status: 404 });
    }
    const camera = env.LIVE_CAMERAS.getByName(JSON.stringify([owner, deviceId]));
    const internal = new URL('https://camera.internal/connect');
    internal.search = new URLSearchParams({ role: publisher ? 'publisher' : 'viewer', owner, deviceId });
    const headers = new Headers(request.headers);
    headers.delete('authorization');
    headers.delete('cookie');
    headers.delete('sec-websocket-extensions');
    return await camera.fetch(new Request(internal, { headers }));
  } catch (error) {
    if (error instanceof ApiError) return new Response(error.message, { status: error.status });
    if (error instanceof URIError) return new Response('Invalid device ID', { status: 400 });
    throw error;
  }
}

export class LiveCamera extends DurableObject {
  lastFrameAt = 0;
  lastDetectionAt = 0;
  lastSnapshotAt = 0;
  savingSnapshot = false;
  // In-memory only: lost if the object is evicted, in which case viewers simply wait.
  latestFrame = null;
  latestDetection = null;

  fetch(request) {
    const params = new URL(request.url).searchParams;
    const role = params.get('role'), owner = params.get('owner'), deviceId = params.get('deviceId');
    if (role === 'publisher') {
      for (const previous of this.ctx.getWebSockets('publisher')) previous.close(4000, 'Publisher replaced');
    }
    const [client, server] = Object.values(new WebSocketPair());
    this.ctx.acceptWebSocket(server, [role]);
    server.serializeAttachment({
      role, owner, deviceId, expires: Date.now() + SESSION_MS, waiting: false, frameAt: 0, detectionAt: 0
    });
    return new Response(null, { status: 101, webSocket: client });
  }

  // Send the newest unseen packet to a viewer that asked for one. AI frames go first so a
  // fast live stream can never starve the slower detection results.
  deliver(viewer, access, now) {
    const detection = this.latestDetection, frame = this.latestFrame;
    if (detection && detection.at > (access.detectionAt || 0) && now - detection.at <= DETECTION_REPLAY_MAX_AGE) {
      viewer.serializeAttachment({ ...access, waiting: false, detectionAt: detection.at });
      viewer.send(detection.packet);
      return true;
    }
    if (frame && frame.at > (access.frameAt || 0) && now - frame.at <= REPLAY_MAX_AGE) {
      viewer.serializeAttachment({ ...access, waiting: false, frameAt: frame.at });
      viewer.send(frame.packet);
      return true;
    }
    if (!access.waiting) viewer.serializeAttachment({ ...access, waiting: true });
    return false;
  }

  webSocketMessage(socket, message) {
    const session = socket.deserializeAttachment();
    const now = Date.now();
    if (now >= session.expires) {
      socket.close(4001, 'Reconnect to renew access');
      return;
    }
    if (session.role === 'viewer') {
      if (message !== 'next') {
        socket.close(1003, 'Expected a frame request');
        return;
      }
      this.deliver(socket, session, now);
      return;
    }
    if (!(message instanceof ArrayBuffer) || message.byteLength > MAX_JPEG_BYTES) {
      socket.close(1003, 'Expected a JPEG frame');
      return;
    }
    const jpeg = new Uint8Array(message);
    const detection = hasDetectionMetadata(jpeg);
    if (now - (detection ? this.lastDetectionAt : this.lastFrameAt) < (detection ? MIN_DETECTION_INTERVAL : MIN_FRAME_INTERVAL)) {
      socket.send('skip');
      return;
    }
    try {
      jpegDimensions(jpeg);
    } catch {
      socket.close(1003, 'Invalid JPEG frame');
      return;
    }
    // Packets are stamped with the time the server received them; at is unique per kind.
    const at = Math.max(now, (detection ? this.latestDetection?.at : this.latestFrame?.at) + 1 || 0);
    if (detection) {
      this.lastDetectionAt = now;
      this.latestDetection = { at, packet: packetFor(jpeg, at) };
    } else {
      this.lastFrameAt = now;
      this.latestFrame = { at, packet: packetFor(jpeg, at) };
    }
    for (const viewer of this.ctx.getWebSockets('viewer')) {
      const access = viewer.deserializeAttachment();
      if (now >= access.expires) {
        viewer.close(4001, 'Reconnect to renew access');
      } else if (access.waiting && viewer.readyState === WebSocket.OPEN) {
        this.deliver(viewer, access, now);
      }
    }
    socket.send('ok');
    if (!this.savingSnapshot && now - this.lastSnapshotAt >= SNAPSHOT_INTERVAL) {
      this.lastSnapshotAt = now;
      this.savingSnapshot = true;
      this.ctx.waitUntil(this.saveSnapshot(session, message, now));
    }
  }

  async saveSnapshot(session, jpeg, now) {
    try {
      const request = new Request('https://camera.internal/snapshot', {
        method: 'POST',
        headers: {
          'Content-Type': 'image/jpeg',
          'X-Frame-Id': 'frame-' + crypto.randomUUID(),
          'X-Captured-At': new Date(now).toISOString()
        },
        body: jpeg
      });
      await new Camera(this.env.DB).upload({ owner_id: session.owner, id: session.deviceId }, request);
    } catch (error) {
      console.warn('Camera snapshot save failed', error instanceof ApiError ? error.code : 'database_error');
    } finally {
      this.savingSnapshot = false;
    }
  }
}
