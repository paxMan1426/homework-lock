-- Scan sessions. Photos and camera frames are never stored: only the verdict text.
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  install TEXT NOT NULL,
  created INTEGER NOT NULL,          -- ms since epoch
  status TEXT NOT NULL DEFAULT 'open', -- open | checking | done
  result TEXT,                       -- JSON verdict once done
  reads INTEGER NOT NULL DEFAULT 0,
  allow_uploads INTEGER NOT NULL DEFAULT 1
);

-- Per-install daily counters for rate limits.
CREATE TABLE IF NOT EXISTS usage (
  install TEXT NOT NULL,
  day TEXT NOT NULL,                 -- UTC yyyy-mm-dd
  checks INTEGER NOT NULL DEFAULT 0,
  sessions INTEGER NOT NULL DEFAULT 0,
  reports INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (install, day)
);

-- SHA-256 of every photo already judged, so the same file can't be reused.
CREATE TABLE IF NOT EXISTS used_images (
  install TEXT NOT NULL,
  sha TEXT NOT NULL,
  PRIMARY KEY (install, sha)
);
