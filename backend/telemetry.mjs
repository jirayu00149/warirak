import {fail, text, timestamp} from './validation.mjs';

function optionalNumber(value, name, min, max, whole=false) {
  if (value == null) return null;
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max || (whole && !Number.isSafeInteger(value))) {
    fail(400, 'invalid_telemetry', `${name} ไม่ถูกต้อง`);
  }
  return value;
}

export function telemetryObservation(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) fail(400, 'invalid_telemetry', 'ข้อมูลสถานะไม่ถูกต้อง');
  if (input.control_enabled === true) fail(400, 'control_not_supported', 'ช่องทางนี้รับสถานะเครื่องเท่านั้น');
  return {
    observed_at_ms: timestamp(input.observed_at, 'observed_at'),
    battery_percent: optionalNumber(input.battery_percent, 'battery_percent', 0, 100),
    state: text(input.state, 'state', 50),
    cpu_temperature_c: optionalNumber(input.cpu_temperature_c, 'cpu_temperature_c', -40, 125),
    memory_used_percent: optionalNumber(input.memory_used_percent, 'memory_used_percent', 0, 100),
    disk_free_gb: optionalNumber(input.disk_free_gb, 'disk_free_gb', 0, 100000),
    uptime_s: optionalNumber(input.uptime_s, 'uptime_s', 0, 315576000, true),
    agent_version: input.agent_version == null ? null : text(input.agent_version, 'agent_version', 32),
  };
}
