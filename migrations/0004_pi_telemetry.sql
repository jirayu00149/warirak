-- Preserve every existing observation while allowing an unmeasured battery.
-- Pi health is the latest snapshot only; no unbounded heartbeat history.
CREATE TABLE device_telemetry_next (
  owner_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  observed_at_ms INTEGER NOT NULL,
  received_at_ms INTEGER NOT NULL,
  battery_percent REAL,
  state TEXT NOT NULL,
  cpu_temperature_c REAL,
  memory_used_percent REAL,
  disk_free_gb REAL,
  uptime_s INTEGER,
  agent_version TEXT,
  PRIMARY KEY(owner_id, device_id)
);
INSERT INTO device_telemetry_next(owner_id,device_id,observed_at_ms,received_at_ms,battery_percent,state)
SELECT owner_id,device_id,observed_at_ms,received_at_ms,battery_percent,state FROM device_telemetry;
DROP TABLE device_telemetry;
ALTER TABLE device_telemetry_next RENAME TO device_telemetry;
