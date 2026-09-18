#!/usr/bin/env bash
set -euo pipefail

snapshot_path="${1:-}"
if [[ -z "${snapshot_path}" || -z "${DATABASE_URL:-}" ]]; then
  printf 'Usage: DATABASE_URL=postgresql://... %s /path/to/snapshot.dump\n' "$0" >&2
  exit 2
fi
if [[ ! -f "${snapshot_path}" || ! -f "${snapshot_path}.sha256" ]]; then
  printf 'Snapshot and companion .sha256 file are required.\n' >&2
  exit 2
fi
for command_name in psql pg_restore; do
  command -v "${command_name}" >/dev/null 2>&1 || { printf '%s is required.\n' "${command_name}" >&2; exit 2; }
done

expected_digest="$(awk 'NR == 1 {print $1}' "${snapshot_path}.sha256")"
if command -v sha256sum >/dev/null 2>&1; then
  actual_digest="$(sha256sum "${snapshot_path}" | awk '{print $1}')"
else
  actual_digest="$(shasum -a 256 "${snapshot_path}" | awk '{print $1}')"
fi
if [[ "${expected_digest}" != "${actual_digest}" ]]; then
  printf 'Snapshot checksum verification failed.\n' >&2
  exit 1
fi

table_count="$(psql "${DATABASE_URL}" --no-psqlrc --tuples-only --no-align --command "select count(*) from pg_catalog.pg_tables where schemaname not in ('pg_catalog', 'information_schema');")"
if [[ "${table_count}" != "0" ]]; then
  printf 'Refusing to restore into a non-empty database (%s user tables found).\n' "${table_count}" >&2
  exit 1
fi

pg_restore \
  --dbname "${DATABASE_URL}" \
  --exit-on-error \
  --no-owner \
  --no-acl \
  "${snapshot_path}"

psql "${DATABASE_URL}" --no-psqlrc --tuples-only --no-align --command "
SELECT jsonb_pretty(jsonb_build_object(
  'schema_version', (SELECT value FROM catalog_meta WHERE key = 'schema_version'),
  'source_collections', (SELECT count(*) FROM source_collection),
  'service_groups', (SELECT count(*) FROM service_group),
  'present_source_files', (SELECT count(*) FROM source_file WHERE is_present),
  'unique_present_documents', (SELECT count(DISTINCT document_id) FROM source_file WHERE is_present AND document_id IS NOT NULL),
  'fingerprint_records', (SELECT count(*) FROM source_file_fingerprint)
));"
printf 'Restore completed after SHA-256 verification. Compare these counts with %s if supplied.\n' "${snapshot_path}.manifest.json"
