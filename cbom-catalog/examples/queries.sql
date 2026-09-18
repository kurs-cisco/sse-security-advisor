-- Format and version coverage.
SELECT * FROM v_format_coverage ORDER BY source_files DESC;

-- Current source fingerprints and paths that have changed over time.
SELECT source_collection, service_group, source_path, current_checksum,
       fingerprint_versions, verification_observations, last_verified_at
FROM v_source_fingerprint_status
ORDER BY fingerprint_versions DESC, source_collection, source_path;

-- Recent refresh outcomes; unchanged files were hashed but not parsed.
SELECT id, files_seen, files_loaded, files_linked, files_unchanged,
       files_failed, force_reprocess, started_at, completed_at
FROM ingest_run
ORDER BY id DESC;

-- Service groups, including explicit NO_CBOM directories.
SELECT sc.slug AS source_collection, sg.display_name,
       count(sf.id) AS source_files,
       count(DISTINCT sf.document_id) AS unique_documents
FROM service_group sg
JOIN source_collection sc ON sc.id = sg.source_collection_id
LEFT JOIN source_file sf ON sf.service_group_id = sg.id
GROUP BY sg.id, sc.id
ORDER BY source_files DESC, sc.slug, sg.display_name;

-- Canonical component reuse across service groups.
SELECT *
FROM v_component_usage
WHERE name ILIKE '%openssl%'
ORDER BY document_count DESC, name, version;

-- All cryptographic assets with their native CycloneDX crypto data.
SELECT c.name, c.version, dc.bom_ref, dc.crypto_properties,
       sc.slug AS source_collection, sg.display_name AS service_group, sf.source_path
FROM document_component dc
JOIN component c ON c.id = dc.component_id
JOIN source_file sf ON sf.document_id = dc.document_id
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
WHERE c.component_type = 'cryptographic-asset'
   OR dc.crypto_properties IS NOT NULL
ORDER BY service_group, c.name;

-- FIPS-related extension properties.
SELECT cp.property_name, cp.property_value, c.name, c.version, sf.source_path
FROM component_property cp
JOIN document_component dc ON dc.id = cp.occurrence_id
JOIN component c ON c.id = dc.component_id
JOIN source_file sf ON sf.document_id = dc.document_id
WHERE cp.property_name LIKE 'fedramp:fips:%'
ORDER BY cp.property_name, cp.property_value, c.name;

-- FIPS checker observations.
SELECT a.name AS image,
       er.data #>> '{crypto_library,library}' AS library,
       er.data #>> '{crypto_library,fips_enabled}' AS library_fips,
       er.data ->> 'overall_openssl_fips' AS openssl_fips,
       sf.source_path
FROM external_record er
LEFT JOIN artifact a ON a.id = er.artifact_id
JOIN source_file sf ON sf.document_id = er.document_id
WHERE er.record_type = 'fips_tool_result';

-- Exact document content found at multiple source paths.
SELECT * FROM v_duplicate_source_content ORDER BY source_alias_count DESC;

-- Ingestion warnings and errors.
SELECT ii.severity, ii.issue_code, ii.message, sf.source_path, ii.context
FROM ingest_issue ii
LEFT JOIN source_file sf ON sf.id = ii.source_file_id
ORDER BY ii.id DESC;
