#!/usr/bin/env bash
set -euo pipefail

# Random rounds loader for test environments.
# Inserts synthetic multipliers as fresh data with recent timestamps.

COUNT="${COUNT:-72}"
MIN_MULTIPLIER="${MIN_MULTIPLIER:-1.01}"
MAX_MULTIPLIER="${MAX_MULTIPLIER:-20.00}"
STEP_SECONDS="${STEP_SECONDS:-5}"
TRUNCATE_FIRST="${TRUNCATE_FIRST:-0}"

if ! [[ "$COUNT" =~ ^[0-9]+$ ]] || [[ "$COUNT" -le 0 ]]; then
  echo "[ERROR] COUNT must be a positive integer. got: $COUNT" >&2
  exit 1
fi

if ! command -v docker-compose >/dev/null 2>&1; then
  echo "[ERROR] docker-compose command is required." >&2
  exit 1
fi

if [[ "$TRUNCATE_FIRST" == "1" ]]; then
  docker-compose exec -T db psql -U "${POSTGRES_USER:-rocket}" -d "${POSTGRES_DB:-rocket}" -v ON_ERROR_STOP=1 -c "TRUNCATE rounds RESTART IDENTITY;"
fi

docker-compose exec -T db psql -U "${POSTGRES_USER:-rocket}" -d "${POSTGRES_DB:-rocket}" -v ON_ERROR_STOP=1 <<SQL
WITH cfg AS (
  SELECT
    ${COUNT}::int AS cnt,
    ${MIN_MULTIPLIER}::numeric AS min_v,
    ${MAX_MULTIPLIER}::numeric AS max_v,
    ${STEP_SECONDS}::int AS step_sec
)
INSERT INTO rounds (multiplier, recorded_at)
SELECT
  round((cfg.min_v + random() * (cfg.max_v - cfg.min_v))::numeric, 4) AS multiplier,
  now() - ((cfg.cnt - g.i) * make_interval(secs => cfg.step_sec)) AS recorded_at
FROM cfg
CROSS JOIN LATERAL generate_series(1, cfg.cnt) AS g(i)
ORDER BY g.i;
SQL

echo "[OK] Inserted ${COUNT} random rows."
echo "     range=${MIN_MULTIPLIER}..${MAX_MULTIPLIER}, step=${STEP_SECONDS}s, truncate=${TRUNCATE_FIRST}"
