#!/bin/sh
set -eu

MIGRATION_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

PSQL="psql -v ON_ERROR_STOP=1 -h ${PGHOST:-postgres} -U ${PGUSER:-cbom} -d ${PGDATABASE:-cbom_catalog}"

$PSQL -c "CREATE TABLE IF NOT EXISTS schema_migration (
  version text PRIMARY KEY,
  description text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now()
)" >/dev/null

has_catalog_meta=$($PSQL -Atqc "SELECT to_regclass('public.catalog_meta')")
if [ "$has_catalog_meta" = "catalog_meta" ]; then
  legacy_version=$($PSQL -Atqc "SELECT value FROM catalog_meta WHERE key = 'schema_version'")
  if [ "$legacy_version" = "1" ]; then
    $PSQL -c "INSERT INTO schema_migration(version, description)
      VALUES ('001', 'initial catalog schema (legacy installation)')
      ON CONFLICT (version) DO NOTHING" >/dev/null
  fi
fi

for migration in "$MIGRATION_DIR"/[0-9][0-9][0-9]_*.sql; do
  filename=${migration##*/}
  version=${filename%%_*}
  applied=$($PSQL -Atqc "SELECT 1 FROM schema_migration WHERE version = '$version'")
  if [ "$applied" = "1" ]; then
    echo "Skipping migration $version (already applied)"
  else
    echo "Applying migration $version from $filename"
    $PSQL -f "$migration"
  fi
done
