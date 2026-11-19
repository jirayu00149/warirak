// Loaded with `node --import ./server/register.mjs`: maps 'cloudflare:workers' to the Node shim.
import { register } from 'node:module';
register('./cf-hooks.mjs', import.meta.url);
