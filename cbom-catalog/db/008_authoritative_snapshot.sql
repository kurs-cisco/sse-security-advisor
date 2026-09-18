BEGIN;

ALTER TABLE source_file
    ADD COLUMN IF NOT EXISTS is_present boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS absent_since_run_id bigint REFERENCES ingest_run(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_source_file_present_collection
    ON source_file(source_collection_id, service_group_id, document_id)
    WHERE is_present;

CREATE OR REPLACE VIEW v_document_inventory AS
SELECT d.id AS document_id, d.sha256, d.document_kind, d.format_name,
       d.spec_version, d.serial_number, d.generated_at_text,
       count(sf.id) AS source_alias_count,
       array_agg(DISTINCT sc.slug ORDER BY sc.slug) AS source_collections,
       array_agg(DISTINCT sc.slug || '/' || sg.display_name
                 ORDER BY sc.slug || '/' || sg.display_name) AS service_groups,
       array_agg(sf.source_path ORDER BY sc.slug, sf.source_path) AS source_paths,
       array_remove(array_agg(sf.source_uri ORDER BY sc.slug, sf.source_path), NULL) AS source_uris
FROM document d
JOIN source_file sf ON sf.document_id = d.id AND sf.is_present
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
GROUP BY d.id;

CREATE OR REPLACE VIEW v_component_usage AS
SELECT c.id AS component_id, c.component_type, c.namespace, c.name, c.version,
       c.canonical_purl, c.cpe,
       count(DISTINCT dc.document_id) AS document_count,
       array_agg(DISTINCT sc.slug || '/' || sg.display_name
                 ORDER BY sc.slug || '/' || sg.display_name) AS service_groups
FROM component c
JOIN document_component dc ON dc.component_id = c.id
JOIN source_file sf ON sf.document_id = dc.document_id AND sf.is_present
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
GROUP BY c.id;

CREATE OR REPLACE VIEW v_format_coverage AS
SELECT d.document_kind, coalesce(d.format_name, '') AS format_name,
       coalesce(d.spec_version, '') AS spec_version,
       count(DISTINCT d.id) AS unique_documents,
       count(DISTINCT sf.id) AS source_files,
       count(DISTINCT dc.id) AS component_occurrences
FROM source_file sf
JOIN document d ON d.id = sf.document_id
LEFT JOIN document_component dc ON dc.document_id = d.id
WHERE sf.is_present
GROUP BY d.document_kind, d.format_name, d.spec_version;

CREATE OR REPLACE VIEW v_duplicate_source_content AS
SELECT * FROM v_document_inventory WHERE source_alias_count > 1;

CREATE OR REPLACE VIEW v_source_fingerprint_status AS
SELECT sf.id AS source_file_id, sc.slug AS source_collection,
       sg.slug AS service_group, sf.source_path, sf.source_uri, sf.byte_size,
       sf.fingerprint_algorithm, sf.content_sha256 AS current_checksum,
       sf.fingerprinted_at, sf.modified_at, sf.parse_status, sf.document_id,
       d.sha256 AS document_checksum,
       count(history.id) AS fingerprint_versions,
       coalesce(sum(history.observation_count), 0) AS verification_observations,
       max(history.last_seen_at) AS last_verified_at,
       sf.is_present, sf.absent_since_run_id
FROM source_file sf
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
LEFT JOIN document d ON d.id = sf.document_id
LEFT JOIN source_file_fingerprint history ON history.source_file_id = sf.id
GROUP BY sf.id, sc.id, sg.id, d.id;

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '8')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('008', 'authoritative snapshot presence with retained fingerprint history')
ON CONFLICT (version) DO NOTHING;

COMMIT;
