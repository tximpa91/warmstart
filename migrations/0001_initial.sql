-- Original fictional content only. Application data and coordinator state are separate.
CREATE TABLE IF NOT EXISTS policies (
  profile TEXT NOT NULL, version TEXT NOT NULL, payload TEXT NOT NULL,
  PRIMARY KEY(profile, version)
);
CREATE TABLE IF NOT EXISTS seeds (
  id TEXT PRIMARY KEY, profile TEXT NOT NULL, version TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS policies_no_update BEFORE UPDATE ON policies
 BEGIN SELECT RAISE(ABORT, 'Published policies are immutable'); END;
CREATE TRIGGER IF NOT EXISTS policies_no_delete BEFORE DELETE ON policies
 BEGIN SELECT RAISE(ABORT, 'Published policies are immutable'); END;
CREATE INDEX IF NOT EXISTS seed_scope ON seeds(profile, version);
CREATE TABLE IF NOT EXISTS exact_cache (
  key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS cache_expiry ON exact_cache(expires_at);
CREATE TABLE IF NOT EXISTS events (
  request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, latency_ms REAL NOT NULL
);
