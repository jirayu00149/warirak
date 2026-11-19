// Minimal RFC 6455 WebSocket server side, no dependencies. Enough for the live-camera relay:
// text + binary messages, fragmentation, ping/pong, close. It stands in for the Cloudflare
// WebSocketPair/hibernation API so worker/live-camera.mjs runs unchanged on Node.
import { createHash } from 'node:crypto';

const GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';
const MAX_MESSAGE = 1024 * 1024;

export function acceptKey(key) {
  return createHash('sha1').update(key + GUID).digest('base64');
}

export class NodeWebSocket {
  readyState = 0; // CONNECTING until bound to a socket
  tags = [];
  #attachment = null;
  #socket = null;
  #buffer = Buffer.alloc(0);
  #fragments = [];
  #fragmentOpcode = 0;
  onmessage = null;
  onclose = null;

  serializeAttachment(value) { this.#attachment = structuredClone(value); }
  deserializeAttachment() { return structuredClone(this.#attachment); }

  bind(socket, head) {
    this.#socket = socket;
    this.readyState = 1;
    socket.setNoDelay(true);
    socket.on('data', chunk => this.#receive(chunk));
    socket.on('close', () => this.#closed(1006, ''));
    socket.on('error', () => socket.destroy());
    if (head?.length) this.#receive(head);
  }

  send(data) {
    if (this.readyState !== 1) return;
    if (typeof data === 'string') this.#frame(0x1, Buffer.from(data));
    else this.#frame(0x2, Buffer.from(data instanceof ArrayBuffer ? new Uint8Array(data) : data));
  }

  close(code = 1000, reason = '') {
    if (this.readyState > 1) return;
    if (this.readyState === 0) { this.readyState = 3; return; }
    this.readyState = 2;
    const body = Buffer.alloc(2 + Buffer.byteLength(reason));
    body.writeUInt16BE(code, 0);
    body.write(reason, 2);
    this.#frame(0x8, body);
    this.#socket.end();
    setTimeout(() => this.#socket?.destroy(), 2000).unref();
    this.#closed(code, reason);
  }

  #closed(code, reason) {
    if (this.readyState === 3 && !this.onclose) return;
    this.readyState = 3;
    const handler = this.onclose;
    this.onclose = null;
    handler?.(code, reason);
  }

  #frame(opcode, payload) {
    const length = payload.length;
    const header = length < 126 ? Buffer.alloc(2) : length < 65536 ? Buffer.alloc(4) : Buffer.alloc(10);
    header[0] = 0x80 | opcode;
    if (length < 126) header[1] = length;
    else if (length < 65536) { header[1] = 126; header.writeUInt16BE(length, 2); }
    else { header[1] = 127; header.writeBigUInt64BE(BigInt(length), 2); }
    this.#socket.write(Buffer.concat([header, payload]));
  }

  #receive(chunk) {
    this.#buffer = Buffer.concat([this.#buffer, chunk]);
    while (this.readyState === 1) {
      const b = this.#buffer;
      if (b.length < 2) return;
      const fin = (b[0] & 0x80) !== 0, opcode = b[0] & 0x0f, masked = (b[1] & 0x80) !== 0;
      let length = b[1] & 0x7f, offset = 2;
      if (length === 126) { if (b.length < 4) return; length = b.readUInt16BE(2); offset = 4; }
      else if (length === 127) { if (b.length < 10) return; length = Number(b.readBigUInt64BE(2)); offset = 10; }
      if (length > MAX_MESSAGE) return this.close(1009, 'Message too large');
      if (!masked) return this.close(1002, 'Client frames must be masked');
      if (b.length < offset + 4 + length) return;
      const mask = b.subarray(offset, offset + 4);
      const payload = Buffer.from(b.subarray(offset + 4, offset + 4 + length));
      for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i & 3];
      this.#buffer = b.subarray(offset + 4 + length);
      this.#handle(fin, opcode, payload);
    }
  }

  #handle(fin, opcode, payload) {
    if (opcode === 0x8) {
      const code = payload.length >= 2 ? payload.readUInt16BE(0) : 1005;
      return this.close(code === 1005 ? 1000 : code, '');
    }
    if (opcode === 0x9) return this.#frame(0xA, payload);
    if (opcode === 0xA) return;
    if (opcode === 0x1 || opcode === 0x2) { this.#fragmentOpcode = opcode; this.#fragments = []; }
    else if (opcode !== 0x0) return this.close(1002, 'Unknown opcode');
    this.#fragments.push(payload);
    if (!fin) {
      if (this.#fragments.reduce((n, p) => n + p.length, 0) > MAX_MESSAGE) this.close(1009, 'Message too large');
      return;
    }
    const data = Buffer.concat(this.#fragments);
    this.#fragments = [];
    const message = this.#fragmentOpcode === 0x1
      ? data.toString('utf8')
      : data.buffer.slice(data.byteOffset, data.byteOffset + data.length);
    this.onmessage?.(message);
  }
}

// Stand-in for Cloudflare's WebSocketPair: [client, server]. The client half only carries a
// reference to the server half so the Node server can bind the real socket to it.
export class WebSocketPair {
  constructor() {
    const server = new NodeWebSocket();
    return { 0: { server }, 1: server };
  }
}
