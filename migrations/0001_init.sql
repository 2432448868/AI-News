-- Signal AI News — D1 schema v1 (articles + user system)
-- 本文所有时间戳:published_at/updated_at/collected_at 为 ISO 文本,
-- item_ts/expires_at/window_start 为 epoch 毫秒整数。

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
); -- keys: schema_version, generated_at, collect_cursor, sync_status

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  homepage TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','error')),
  last_success_at TEXT,
  item_count INTEGER NOT NULL DEFAULT 0,
  error TEXT
);

CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,              -- sha256(canonical_url)[:20]
  title TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  summary TEXT NOT NULL DEFAULT '',
  source_id TEXT NOT NULL REFERENCES sources(id),
  source_name TEXT NOT NULL,
  published_at TEXT,
  updated_at TEXT,
  collected_at TEXT NOT NULL,
  item_ts INTEGER NOT NULL DEFAULT 0,   -- epoch ms of updatedAt||publishedAt||0
  rank_score REAL NOT NULL CHECK (rank_score >= 0 AND rank_score <= 100),
  metric_label TEXT,
  metric_value INTEGER,
  is_china INTEGER NOT NULL DEFAULT 0,
  search_text TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_items_ts ON items(item_ts DESC, rank_score DESC, id ASC);
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_id);

CREATE TABLE IF NOT EXISTS item_categories (
  item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  category TEXT NOT NULL CHECK (category IN ('news','projects','skills','models','tips','apps','dev')),
  PRIMARY KEY (item_id, category)
);
CREATE INDEX IF NOT EXISTS idx_cat_category ON item_categories(category);

CREATE TABLE IF NOT EXISTS item_tags (
  item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  PRIMARY KEY (item_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON item_tags(tag);

CREATE TABLE IF NOT EXISTS users (
  github_id INTEGER PRIMARY KEY,
  login TEXT NOT NULL,
  display_name TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,      -- b64url(sha256(secret))
  github_id INTEGER NOT NULL REFERENCES users(github_id) ON DELETE CASCADE,
  csrf TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at INTEGER NOT NULL,      -- epoch ms
  window_start INTEGER NOT NULL,    -- epoch ms
  writes_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(github_id);

CREATE TABLE IF NOT EXISTS favorites (
  github_id INTEGER NOT NULL REFERENCES users(github_id) ON DELETE CASCADE,
  item_id TEXT NOT NULL,
  saved_at TEXT NOT NULL,
  PRIMARY KEY (github_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_fav_user ON favorites(github_id);

CREATE TABLE IF NOT EXISTS followed_tags (
  github_id INTEGER NOT NULL REFERENCES users(github_id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  followed_at TEXT NOT NULL,
  PRIMARY KEY (github_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_tags_user ON followed_tags(github_id);
