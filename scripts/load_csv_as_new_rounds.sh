#!/usr/bin/env bash
set -euo pipefail

# CSV data loader for test environments.
# - Reads multiplier values from CSV
# - Inserts into rounds as "new" data with recent timestamps
# - Optional truncate before load

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CSV_PATH="${1:-$ROOT_DIR/docs/rounds_export_ml.csv}"
TRUNCATE_FIRST="${TRUNCATE_FIRST:-0}"
STEP_SECONDS="${STEP_SECONDS:-5}"

if [[ ! -f "$CSV_PATH" ]]; then
  echo "[ERROR] CSV file not found: $CSV_PATH" >&2
  exit 1
fi

if ! command -v docker-compose >/dev/null 2>&1; then
  echo "[ERROR] docker-compose command is required." >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
MULTIPLIERS_CSV="$TMP_DIR/multipliers.csv"

# Accept both formats:
# 1) id,multiplier,recorded_at
# 2) multiplier
# Also skip optional header line.
awk -F',' '
  function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
  {
    c1 = trim($1)
    c2 = trim($2)

    # single-column CSV: multiplier only
    if (NF == 1) {
      if (c1 ~ /^[0-9]+(\.[0-9]+)?$/) print c1
      next
    }

    # skip header rows like id,multiplier,recorded_at
    if (tolower(c1) == "id" || tolower(c2) == "multiplier") next

    # multi-column CSV: use 2nd column as multiplier
    if (c2 ~ /^[0-9]+(\.[0-9]+)?$/) print c2
  }
' "$CSV_PATH" > "$MULTIPLIERS_CSV"

ROW_COUNT="$(wc -l < "$MULTIPLIERS_CSV" | tr -d ' ')"
if [[ "$ROW_COUNT" -eq 0 ]]; then
  echo "[ERROR] No valid multiplier rows found in: $CSV_PATH" >&2
  exit 1
fi

if [[ "$TRUNCATE_FIRST" == "1" ]]; then
  docker-compose exec -T db psql -U "${POSTGRES_USER:-rocket}" -d "${POSTGRES_DB:-rocket}" -v ON_ERROR_STOP=1 -c "TRUNCATE rounds RESTART IDENTITY;"
fi

{
  cat <<SQL
BEGIN;
CREATE TEMP TABLE _stage_rounds (
  idx BIGSERIAL PRIMARY KEY,
  multiplier NUMERIC(12, 4) NOT NULL
);
COPY _stage_rounds (multiplier) FROM STDIN WITH (FORMAT csv);
SQL
  cat "$MULTIPLIERS_CSV"
  cat <<SQL
\\.
INSERT INTO rounds (multiplier, recorded_at)
SELECT
  multiplier,
  NOW() - ((total_rows - rn) * INTERVAL '${STEP_SECONDS} seconds')
FROM (
  SELECT
    multiplier,
    row_number() OVER (ORDER BY idx) AS rn,
    count(*) OVER () AS total_rows
  FROM _stage_rounds
) s
ORDER BY rn;
COMMIT;
SQL
} | docker-compose exec -T db psql -U "${POSTGRES_USER:-rocket}" -d "${POSTGRES_DB:-rocket}" -v ON_ERROR_STOP=1

echo "[OK] Loaded ${ROW_COUNT} rows from ${CSV_PATH} as fresh rounds."
echo "     TRUNCATE_FIRST=${TRUNCATE_FIRST}, STEP_SECONDS=${STEP_SECONDS}"
