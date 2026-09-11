-- karaoke.rodeo schema, version 1 (later changes go into db.py MIGRATIONS)
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  avatar_ver INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL DEFAULT 140,
  created_at TEXT NOT NULL,
  last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS login_tokens (
  token_hash TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  ip TEXT,
  next_url TEXT,
  code_hash TEXT,                        -- 6-digit code from the same mail, for installed (standalone) apps
  code_attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_login_tokens_email ON login_tokens(email, created_at);
CREATE INDEX IF NOT EXISTS idx_login_tokens_ip ON login_tokens(ip, created_at);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_seen_at TEXT,
  user_agent TEXT
);
CREATE TABLE IF NOT EXISTS songs (
  id TEXT PRIMARY KEY,                 -- youtube video id, or legacy v1..v5
  youtube_url TEXT,
  title_jp TEXT, artist_jp TEXT, title_en TEXT, artist_en TEXT,
  duration REAL, n_notes INTEGER, n_pages INTEGER, family TEXT,
  status TEXT NOT NULL DEFAULT 'processing',   -- processing | labeling | published | failed | hidden
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  published_at TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  song_id TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'ingest',        -- ingest (download + pipeline) | reprocess (pipeline only)
  status TEXT NOT NULL DEFAULT 'queued',      -- queued | running | done | failed | cancelled
  stage TEXT,                                 -- download | extract | geotime | anchor | lyrics | finalize
  progress REAL NOT NULL DEFAULT 0,
  log TEXT NOT NULL DEFAULT '',
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT, finished_at TEXT, heartbeat_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE TABLE IF NOT EXISTS parties (
  code TEXT PRIMARY KEY,
  host_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  ended_at TEXT,
  current_member_id INTEGER
);
CREATE TABLE IF NOT EXISTS party_members (
  id INTEGER PRIMARY KEY,
  party_code TEXT NOT NULL REFERENCES parties(code) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  guest_name TEXT,
  guest_token_hash TEXT,
  joined_at TEXT NOT NULL,
  queue_pos INTEGER
);
CREATE INDEX IF NOT EXISTS idx_party_members_party ON party_members(party_code);
CREATE TABLE IF NOT EXISTS plays (
  id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  party_member_id INTEGER REFERENCES party_members(id) ON DELETE SET NULL,
  party_code TEXT,
  song_id TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
  score REAL NOT NULL,
  n_perfect INTEGER NOT NULL DEFAULT 0, n_great INTEGER NOT NULL DEFAULT 0,
  n_good INTEGER NOT NULL DEFAULT 0, n_miss INTEGER NOT NULL DEFAULT 0,
  max_combo INTEGER NOT NULL DEFAULT 0,
  completed INTEGER NOT NULL DEFAULT 1,
  latency_ms INTEGER,
  results TEXT,                                -- JSON: {"notes":[[rating,acc,cents],...]}
  played_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plays_user ON plays(user_id, played_at);
CREATE INDEX IF NOT EXISTS idx_plays_song_score ON plays(song_id, score DESC);
