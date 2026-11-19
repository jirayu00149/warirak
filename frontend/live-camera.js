// Live viewer for /api/live/devices/:id/stream.
// Packet = 8-byte server receive time (float64 ms) + JPEG.
// Flow control: the viewer asks for the next frame while it decodes the current one, so a
// network round trip never sits between two frames; at most one extra frame is held, and a
// newer one replaces it, so a slow device never builds a backlog of old images.
export function watchCamera(deviceId, displayFrame) {
  const url = new URL('/api/live/devices/' + encodeURIComponent(deviceId) + '/stream', location.href);
  url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  let socket, retry, stopped = false, delay = 1000;
  function connect() {
    const connection = new WebSocket(url);
    socket = connection;
    connection.binaryType = 'arraybuffer';
    let decoding = false, pending = null;
    const active = () => !stopped && socket === connection && connection.readyState === WebSocket.OPEN;
    const request = () => { if (active()) connection.send('next'); };
    async function show(data) {
      decoding = true;
      const time = new DataView(data).getFloat64(0);
      if (Number.isFinite(time)) {
        try {
          await displayFrame(new Blob([data.slice(8)], { type: 'image/jpeg' }), time, active);
          delay = 1000;
        } catch {
          // A decode failure leaves the last usable image on screen.
        }
      }
      decoding = false;
      if (pending && active()) {
        const next = pending;
        pending = null;
        request();
        show(next);
      }
      // Otherwise the request sent when this frame arrived is still outstanding.
    }
    connection.onopen = request;
    connection.onmessage = ({ data }) => {
      if (!active() || !(data instanceof ArrayBuffer) || data.byteLength <= 8) return;
      if (decoding) {
        // Keep only the newest waiting frame; ask again once it is being shown.
        pending = data;
        return;
      }
      request();
      show(data);
    };
    connection.onclose = event => {
      if (stopped || socket !== connection) return;
      retry = setTimeout(connect, event.code === 4001 ? 0 : delay);
      delay = Math.min(delay * 2, 30000);
    };
  }
  connect();
  return () => {
    stopped = true;
    clearTimeout(retry);
    if (socket?.readyState <= WebSocket.OPEN) socket.close();
  };
}
