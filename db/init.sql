CREATE TABLE IF NOT EXISTS users (
  id            SERIAL PRIMARY KEY,
  username      VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rounds (
  id          SERIAL PRIMARY KEY,
  multiplier  NUMERIC(12, 4) NOT NULL CHECK (multiplier > 0),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rounds_recorded_at ON rounds (recorded_at);

CREATE TABLE IF NOT EXISTS analysis_snapshots (
  id          SERIAL PRIMARY KEY,
  prob_2x     NUMERIC(6, 4),
  prob_5x     NUMERIC(6, 4),
  prob_10x    NUMERIC(6, 4),
  moving_avg  NUMERIC(12, 4),
  window_size INTEGER,
  snapshot_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
