CREATE TABLE auth_users (
 id TEXT PRIMARY KEY,
 username TEXT NOT NULL UNIQUE,
 display_name TEXT NOT NULL,
 access_key_hash TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1,
 created_at_ms INTEGER NOT NULL
);
CREATE TABLE auth_sessions (
 token_hash TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES auth_users(id),
 expires_at_ms INTEGER NOT NULL,
 created_at_ms INTEGER NOT NULL
);
CREATE INDEX auth_session_expiry ON auth_sessions(expires_at_ms);
CREATE TABLE auth_login_limits (
 bucket TEXT PRIMARY KEY,
 attempts INTEGER NOT NULL,
 expires_at_ms INTEGER NOT NULL
);
