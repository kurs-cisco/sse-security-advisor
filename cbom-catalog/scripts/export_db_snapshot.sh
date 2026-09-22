#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
catalog_dir="$(cd "${script_dir}/.." && pwd)"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output_path="${1:-${catalog_dir}/snapshots/cbom-catalog-${timestamp}.dump}"
temporary_path="${output_path}.partial"
manifest_path="${output_path}.manifest.json"
temporary_manifest_path="${manifest_path}.partial"

mkdir -p "$(dirname "${output_path}")"
trap 'rm -f "${temporary_path}" "${temporary_manifest_path}"' EXIT

cd "${catalog_dir}"
docker compose exec -T postgres pg_dump \
  --username "${POSTGRES_USER:-cbom}" \
  --dbname "${POSTGRES_DB:-cbom_catalog}" \
  --format custom \
  --compress 9 \
  --no-owner \
  --no-acl \
  --exclude-schema app_auth > "${temporary_path}"

mv "${temporary_path}" "${output_path}"
chmod 600 "${output_path}"
if command -v sha256sum >/dev/null 2>&1; then
  digest="$(sha256sum "${output_path}" | awk '{print $1}')"
else
  digest="$(shasum -a 256 "${output_path}" | awk '{print $1}')"
fi
printf '%s  %s\n' "${digest}" "$(basename "${output_path}")" > "${output_path}.sha256"
chmod 600 "${output_path}.sha256"

docker compose exec -T postgres psql \
  --username "${POSTGRES_USER:-cbom}" \
  --dbname "${POSTGRES_DB:-cbom_catalog}" \
  --no-psqlrc --tuples-only --no-align \
  --set=snapshot_file="$(basename "${output_path}")" \
  --set=snapshot_sha256="${digest}" > "${temporary_manifest_path}" <<'SQL'
SELECT jsonb_pretty(jsonb_build_object(
    'manifest_version', '1.0',
    'snapshot_file', :'snapshot_file',
    'snapshot_sha256', :'snapshot_sha256',
    'exported_at', to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"'),
    'database_engine', 'PostgreSQL',
    'database_server_version', current_setting('server_version'),
    'schema_version', (SELECT value FROM catalog_meta WHERE key = 'schema_version'),
    'schema_migrations', (SELECT coalesce(jsonb_agg(version ORDER BY version), '[]'::jsonb) FROM schema_migration),
    'counts', jsonb_build_object(
      'source_collections', (SELECT count(*) FROM source_collection),
      'service_groups', (SELECT count(*) FROM service_group),
      'present_source_files', (SELECT count(*) FROM source_file WHERE is_present),
      'unique_present_documents', (SELECT count(DISTINCT document_id) FROM source_file WHERE is_present AND document_id IS NOT NULL),
      'artifacts', (SELECT count(DISTINCT da.artifact_id) FROM document_artifact da JOIN source_file sf ON sf.document_id = da.document_id WHERE sf.is_present),
      'components', (SELECT count(DISTINCT dc.component_id) FROM document_component dc JOIN source_file sf ON sf.document_id = dc.document_id WHERE sf.is_present),
      'component_occurrences', (SELECT count(DISTINCT dc.id) FROM document_component dc JOIN source_file sf ON sf.document_id = dc.document_id WHERE sf.is_present),
      'fingerprint_records', (SELECT count(*) FROM source_file_fingerprint)
    ),
    'source_collections', (SELECT coalesce(jsonb_agg(slug ORDER BY slug), '[]'::jsonb) FROM source_collection),
    'latest_ingest_run', (SELECT to_jsonb(run_row) FROM (
      SELECT ir.id, sc.slug AS source_collection, ir.status, ir.files_seen,
             ir.files_loaded, ir.files_linked, ir.files_unchanged, ir.files_failed,
             ir.started_at, ir.completed_at
      FROM ingest_run ir
      LEFT JOIN source_collection sc ON sc.id = ir.source_collection_id
      ORDER BY ir.id DESC LIMIT 1
    ) run_row),
    'data_classification', 'Candidate crypto inventory and assessment working data; authorized review required',
    'raw_source_bytes_included', false,
    'application_identity_schema_included', false
  ));
SQL
mv "${temporary_manifest_path}" "${manifest_path}"
chmod 600 "${manifest_path}"

printf 'Snapshot: %s\nSHA-256: %s\nManifest: %s\n' \
  "${output_path}" "${digest}" "${manifest_path}"
