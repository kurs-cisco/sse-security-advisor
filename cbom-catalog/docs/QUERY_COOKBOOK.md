# Query cookbook

Use these queries after ingestion. The API exposes common searches; SQL is the
best surface for investigations that combine provenance, custom properties, and
graph edges.

## Inventory and coverage

```sql
SELECT *
FROM v_format_coverage
ORDER BY source_files DESC;
```

```sql
SELECT sc.slug, sc.root_uri,
       count(sf.id) AS source_files,
       count(DISTINCT sf.document_id) AS unique_documents
FROM source_collection sc
LEFT JOIN source_file sf ON sf.source_collection_id = sc.id
GROUP BY sc.id
ORDER BY sc.slug;
```

```sql
SELECT sc.slug AS source_collection, sg.display_name,
       count(sf.id) AS files,
       count(DISTINCT sf.document_id) AS unique_documents,
       count(*) FILTER (WHERE sf.parse_status IN ('empty', 'invalid', 'error')) AS issues
FROM service_group sg
JOIN source_collection sc ON sc.id = sg.source_collection_id
LEFT JOIN source_file sf ON sf.service_group_id = sg.id
GROUP BY sg.id, sc.id
ORDER BY files DESC, sc.slug, sg.display_name;
```

## Refresh fingerprints

Current checksum and verification state:

```sql
SELECT source_collection, service_group, source_path,
       fingerprint_algorithm, current_checksum, byte_size,
       fingerprint_versions, verification_observations, last_verified_at
FROM v_source_fingerprint_status
ORDER BY source_collection, source_path;
```

Checksum history for paths whose content changed:

```sql
SELECT sc.slug AS source_collection, sf.source_path,
       history.algorithm, history.checksum, history.byte_size,
       history.first_seen_run_id, history.last_seen_run_id,
       history.first_seen_at, history.last_seen_at,
       history.observation_count
FROM source_file_fingerprint history
JOIN source_file sf ON sf.id = history.source_file_id
JOIN source_collection sc ON sc.id = sf.source_collection_id
WHERE sf.id IN (
    SELECT source_file_id
    FROM source_file_fingerprint
    GROUP BY source_file_id
    HAVING count(*) > 1
)
ORDER BY sc.slug, sf.source_path, history.first_seen_at;
```

Refresh results:

```sql
SELECT ir.id, sc.slug AS source_collection, ir.force_reprocess,
       ir.files_seen, ir.files_loaded, ir.files_linked,
       ir.files_unchanged, ir.files_failed,
       ir.started_at, ir.completed_at
FROM ingest_run ir
LEFT JOIN source_collection sc ON sc.id = ir.source_collection_id
ORDER BY ir.id DESC;
```

The following should return no rows; any result indicates a source/document link
that failed the checksum integrity invariant:

```sql
SELECT source_collection, source_path, current_checksum, document_checksum
FROM v_source_fingerprint_status
WHERE document_id IS NOT NULL
  AND current_checksum IS DISTINCT FROM document_checksum;
```

## Where is a package used?

Exact PURL:

```sql
SELECT *
FROM v_component_usage
WHERE canonical_purl = 'pkg:deb/debian/libgcrypt20@1.8.7-6?arch=amd64&distro=debian-11.11';
```

Name/version with source paths:

```sql
SELECT c.name, c.version, c.canonical_purl,
       sc.slug AS source_collection, sg.display_name AS service_group,
       sf.source_path, dc.bom_ref
FROM component c
JOIN document_component dc ON dc.component_id = c.id
JOIN source_file sf ON sf.document_id = dc.document_id
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
WHERE c.name ILIKE '%openssl%'
ORDER BY c.name, c.version, sc.slug, sg.display_name, sf.source_path;
```

## Find cryptographic assets

```sql
SELECT c.name, c.version, dc.bom_ref, dc.crypto_properties,
       sc.slug AS source_collection, sf.source_path,
       sg.display_name AS service_group
FROM document_component dc
JOIN component c ON c.id = dc.component_id
JOIN source_file sf ON sf.document_id = dc.document_id
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
WHERE c.component_type = 'cryptographic-asset'
   OR dc.crypto_properties IS NOT NULL
ORDER BY sg.display_name, c.name;
```

Certificate expiry fields can be extracted without assuming every crypto asset is
a certificate:

```sql
SELECT c.name,
       dc.crypto_properties #>> '{certificateProperties,notValidAfter}' AS expires_at,
       dc.crypto_properties #>> '{certificateProperties,issuerName}' AS issuer,
       sf.source_path
FROM document_component dc
JOIN component c ON c.id = dc.component_id
JOIN source_file sf ON sf.document_id = dc.document_id
WHERE dc.crypto_properties ? 'certificateProperties';
```

## Query FedRAMP/custom properties

```sql
SELECT cp.property_name, cp.property_value,
       c.name, c.version, sf.source_path
FROM component_property cp
JOIN document_component dc ON dc.id = cp.occurrence_id
JOIN component c ON c.id = dc.component_id
JOIN source_file sf ON sf.document_id = dc.document_id
WHERE cp.property_name LIKE 'fedramp:fips:%'
ORDER BY cp.property_name, cp.property_value, c.name;
```

`syft:location:*` properties remain in `document_component.properties` by default:

```sql
SELECT c.name, c.version, property
FROM document_component dc
JOIN component c ON c.id = dc.component_id
CROSS JOIN LATERAL jsonb_array_elements(dc.properties) AS property
WHERE property->>'name' LIKE 'syft:location:%:path'
  AND property->>'value' = '/var/lib/dpkg/status';
```

## Inspect FIPS and OSCAL evidence

```sql
SELECT a.name AS image,
       er.data #>> '{crypto_library,library}' AS library,
       er.data #>> '{crypto_library,fips_enabled}' AS library_fips,
       er.data ->> 'overall_openssl_fips' AS openssl_fips,
       sf.source_path
FROM external_record er
LEFT JOIN artifact a ON a.id = er.artifact_id
JOIN source_file sf ON sf.document_id = er.document_id
WHERE er.record_type = 'fips_tool_result';
```

```sql
SELECT child.record_type, child.external_id, child.observed_at_text,
       child.data->>'title' AS title,
       parent.external_id AS parent_result_id,
       sf.source_path
FROM external_record child
LEFT JOIN external_record parent ON parent.id = child.parent_record_id
JOIN source_file sf ON sf.document_id = child.document_id
WHERE child.record_type LIKE 'oscal_%'
ORDER BY sf.source_path, child.record_type, child.external_id;
```

## Compare summary observations without overwriting BOM truth

```sql
SELECT a.name,
       (er.data->>'components')::integer AS reported_components,
       (er.data->>'crypto_assets')::integer AS reported_crypto_assets,
       er.data->>'openssl_fips_status' AS reported_fips_status,
       er.data->>'enriched' AS reported_enriched
FROM external_record er
JOIN artifact a ON a.id = er.artifact_id
WHERE er.record_type = 'cbom_generation_summary_image'
ORDER BY a.name;
```

These are producer-reported values. Use `count(*)` over `document_component` for
counts calculated from a specific BOM document.

## Dependency closure

```sql
WITH RECURSIVE closure AS (
    SELECT 1 AS depth, from_ref, to_ref,
           ARRAY[from_ref, to_ref]::text[] AS path
    FROM dependency_edge
    WHERE document_id = 42
      AND from_ref = 'root-bom-ref'
      AND relationship_type = 'DEPENDS_ON'
      AND resolution_status <> 'ambiguous'
  UNION ALL
    SELECT closure.depth + 1, edge.from_ref, edge.to_ref,
           closure.path || edge.to_ref
    FROM closure
    JOIN dependency_edge edge
      ON edge.document_id = 42
     AND edge.from_ref = closure.to_ref
     AND edge.relationship_type = 'DEPENDS_ON'
     AND edge.resolution_status <> 'ambiguous'
    WHERE closure.depth < 20
      AND NOT edge.to_ref = ANY(closure.path)
)
SELECT * FROM closure ORDER BY depth, from_ref, to_ref;
```

Do not interpret an empty result as proof of no dependency: most current
CycloneDX inputs do not provide dependency arrays.

SPDX `CONTAINS`, `DESCRIBES`, and other relationships are deliberately not part
of a dependency closure. Use the raw `dependency_edge` table for an explicitly
typed relationship traversal.

## Vulnerability blast radius

```sql
SELECT v.vulnerability_id, v.source_name, va.affected_ref,
       c.name, c.version, sc.slug AS source_collection,
       sf.source_path, sg.display_name AS service_group
FROM vulnerability v
JOIN document_vulnerability dv ON dv.vulnerability_id = v.id
JOIN vulnerability_affect va
  ON va.document_id = dv.document_id AND va.vulnerability_id = dv.vulnerability_id
LEFT JOIN document_component dc
  ON dc.document_id = va.document_id AND dc.source_bom_ref = va.affected_ref
LEFT JOIN component c ON c.id = dc.component_id
JOIN source_file sf ON sf.document_id = dv.document_id
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
WHERE v.vulnerability_id = 'CVE-YYYY-NNNN';
```

## Duplicates and data quality

```sql
SELECT * FROM v_duplicate_source_content ORDER BY source_alias_count DESC;
```

```sql
SELECT ii.severity, ii.issue_code, ii.message, sf.source_path, ii.context
FROM ingest_issue ii
LEFT JOIN source_file sf ON sf.id = ii.source_file_id
ORDER BY ii.id DESC;
```

```sql
SELECT sf.source_path, sf.parse_status, sf.parse_message
FROM source_file sf
WHERE sf.parse_status NOT IN ('loaded', 'linked')
ORDER BY sf.source_path;
```
