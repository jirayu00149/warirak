// Node stand-in for the 'cloudflare:workers' module used by worker/live-camera.mjs.
export class DurableObject {
  constructor(ctx, env) { this.ctx = ctx; this.env = env; }
}
