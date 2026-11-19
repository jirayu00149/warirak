CREATE TABLE IF NOT EXISTS ai_datasets (
  owner_id TEXT NOT NULL,
  id TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('preparing','ready','failed')),
  image_count INTEGER NOT NULL DEFAULT 0 CHECK(image_count >= 0),
  train_count INTEGER NOT NULL DEFAULT 0 CHECK(train_count >= 0),
  val_count INTEGER NOT NULL DEFAULT 0 CHECK(val_count >= 0),
  test_count INTEGER NOT NULL DEFAULT 0 CHECK(test_count >= 0),
  manifest_sha256 TEXT,
  provenance_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(provenance_json)),
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  PRIMARY KEY(owner_id,id),
  CHECK(image_count = train_count + val_count + test_count)
);

CREATE TABLE IF NOT EXISTS ai_training_runs (
  owner_id TEXT NOT NULL,
  id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('preparing','training','validating','exporting','completed','retained_baseline','failed')),
  epoch INTEGER NOT NULL DEFAULT 0 CHECK(epoch >= 0),
  total_epochs INTEGER NOT NULL CHECK(total_epochs > 0 AND epoch <= total_epochs),
  validation_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(validation_json)),
  details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
  started_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  finished_at_ms INTEGER,
  PRIMARY KEY(owner_id,id),
  FOREIGN KEY(owner_id,dataset_id) REFERENCES ai_datasets(owner_id,id)
);
CREATE INDEX IF NOT EXISTS ai_runs_owner_updated ON ai_training_runs(owner_id,updated_at_ms DESC);

CREATE TABLE IF NOT EXISTS ai_model_releases (
  owner_id TEXT NOT NULL,
  id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  weights_sha256 TEXT NOT NULL CHECK(length(weights_sha256)=64),
  input_size INTEGER NOT NULL CHECK(input_size > 0),
  release_json TEXT NOT NULL CHECK(json_valid(release_json)),
  evaluation_json TEXT NOT NULL CHECK(json_valid(evaluation_json)),
  active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)),
  published_at_ms INTEGER NOT NULL,
  PRIMARY KEY(owner_id,id),
  FOREIGN KEY(owner_id,run_id) REFERENCES ai_training_runs(owner_id,id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ai_one_active_release ON ai_model_releases(owner_id) WHERE active=1;
