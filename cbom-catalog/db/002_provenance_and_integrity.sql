BEGIN;

CREATE TABLE IF NOT EXISTS source_collection (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug text NOT NULL UNIQUE,
    display_name text NOT NULL,
    root_uri text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO source_collection (slug, display_name, root_uri)
VALUES (
    'sse-cboms',
    'SSE CBOMs',
    (SELECT root_path FROM ingest_run ORDER BY id DESC LIMIT 1)
)
ON CONFLICT (slug) DO NOTHING;

ALTER TABLE ingest_run ADD COLUMN IF NOT EXISTS source_collection_id bigint;
UPDATE ingest_run
SET source_collection_id = (SELECT id FROM source_collection WHERE slug = 'sse-cboms')
WHERE source_collection_id IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ingest_run_source_collection_fkey'
    ) THEN
        ALTER TABLE ingest_run
            ADD CONSTRAINT ingest_run_source_collection_fkey
            FOREIGN KEY (source_collection_id) REFERENCES source_collection(id);
    END IF;
END $$;

ALTER TABLE source_file ADD COLUMN IF NOT EXISTS source_collection_id bigint;
ALTER TABLE source_file ADD COLUMN IF NOT EXISTS source_uri text;
UPDATE source_file
SET source_collection_id = (SELECT id FROM source_collection WHERE slug = 'sse-cboms')
WHERE source_collection_id IS NULL;
ALTER TABLE source_file ALTER COLUMN source_collection_id SET NOT NULL;

ALTER TABLE source_file DROP CONSTRAINT IF EXISTS source_file_source_path_key;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'source_file_collection_path_key'
    ) THEN
        ALTER TABLE source_file
            ADD CONSTRAINT source_file_collection_path_key
            UNIQUE (source_collection_id, source_path);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'source_file_source_collection_fkey'
    ) THEN
        ALTER TABLE source_file
            ADD CONSTRAINT source_file_source_collection_fkey
            FOREIGN KEY (source_collection_id) REFERENCES source_collection(id);
    END IF;
END $$;

ALTER TABLE document_component ADD COLUMN IF NOT EXISTS source_bom_ref text;
UPDATE document_component SET source_bom_ref = bom_ref WHERE source_bom_ref IS NULL;
ALTER TABLE document_component ALTER COLUMN source_bom_ref SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'document_component_document_id_id_key'
    ) THEN
        ALTER TABLE document_component
            ADD CONSTRAINT document_component_document_id_id_key UNIQUE (document_id, id);
    END IF;
END $$;

ALTER TABLE dependency_edge
    ADD COLUMN IF NOT EXISTS resolution_status text NOT NULL DEFAULT 'resolved';
UPDATE dependency_edge
SET resolution_status = CASE
    WHEN from_occurrence_id IS NOT NULL AND to_occurrence_id IS NOT NULL THEN 'resolved'
    WHEN from_occurrence_id IS NULL AND to_occurrence_id IS NULL THEN 'external'
    ELSE 'partial'
END;

ALTER TABLE dependency_edge
    DROP CONSTRAINT IF EXISTS dependency_edge_from_occurrence_id_fkey;
ALTER TABLE dependency_edge
    DROP CONSTRAINT IF EXISTS dependency_edge_to_occurrence_id_fkey;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'dependency_edge_resolution_status_check'
    ) THEN
        ALTER TABLE dependency_edge
            ADD CONSTRAINT dependency_edge_resolution_status_check
            CHECK (resolution_status IN ('resolved', 'partial', 'ambiguous', 'external'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'dependency_edge_from_occurrence_fk'
    ) THEN
        ALTER TABLE dependency_edge
            ADD CONSTRAINT dependency_edge_from_occurrence_fk
            FOREIGN KEY (document_id, from_occurrence_id)
            REFERENCES document_component(document_id, id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'dependency_edge_to_occurrence_fk'
    ) THEN
        ALTER TABLE dependency_edge
            ADD CONSTRAINT dependency_edge_to_occurrence_fk
            FOREIGN KEY (document_id, to_occurrence_id)
            REFERENCES document_component(document_id, id) ON DELETE CASCADE;
    END IF;
END $$;

ALTER TABLE external_record ADD COLUMN IF NOT EXISTS payload_sha256 char(64);
UPDATE external_record
SET payload_sha256 = encode(sha256(convert_to(data::text, 'UTF8')), 'hex')
WHERE payload_sha256 IS NULL;
ALTER TABLE external_record ALTER COLUMN payload_sha256 SET NOT NULL;
ALTER TABLE external_record
    DROP CONSTRAINT IF EXISTS external_record_document_id_record_type_external_id_key;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'external_record_immutable_observation_key'
    ) THEN
        ALTER TABLE external_record
            ADD CONSTRAINT external_record_immutable_observation_key
            UNIQUE (document_id, record_type, external_id, payload_sha256);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'document_sha256_format_check') THEN
        ALTER TABLE document ADD CONSTRAINT document_sha256_format_check
            CHECK (sha256 ~ '^[0-9a-f]{64}$');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'document_byte_size_check') THEN
        ALTER TABLE document ADD CONSTRAINT document_byte_size_check CHECK (byte_size >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'source_file_hash_format_check') THEN
        ALTER TABLE source_file ADD CONSTRAINT source_file_hash_format_check
            CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'source_file_byte_size_check') THEN
        ALTER TABLE source_file ADD CONSTRAINT source_file_byte_size_check CHECK (byte_size >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'document_artifact_confidence_check') THEN
        ALTER TABLE document_artifact ADD CONSTRAINT document_artifact_confidence_check
            CHECK (confidence BETWEEN 0 AND 1);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'external_record_payload_hash_check') THEN
        ALTER TABLE external_record ADD CONSTRAINT external_record_payload_hash_check
            CHECK (payload_sha256 ~ '^[0-9a-f]{64}$');
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_source_file_collection_path
    ON source_file(source_collection_id, source_path);
CREATE INDEX IF NOT EXISTS idx_document_component_source_ref
    ON document_component(document_id, source_bom_ref);
CREATE INDEX IF NOT EXISTS idx_dependency_type_from
    ON dependency_edge(document_id, relationship_type, from_ref);
CREATE INDEX IF NOT EXISTS idx_component_license_id ON component_license(license_id);
CREATE INDEX IF NOT EXISTS idx_component_license_expression ON component_license(expression);

DROP VIEW IF EXISTS v_duplicate_source_content;
DROP VIEW IF EXISTS v_document_inventory;

CREATE VIEW v_document_inventory AS
SELECT
    d.id AS document_id,
    d.sha256,
    d.document_kind,
    d.format_name,
    d.spec_version,
    d.serial_number,
    d.generated_at_text,
    count(sf.id) AS source_alias_count,
    array_agg(DISTINCT sc.slug ORDER BY sc.slug) AS source_collections,
    array_agg(DISTINCT sg.display_name ORDER BY sg.display_name) AS service_groups,
    array_agg(sf.source_path ORDER BY sc.slug, sf.source_path) AS source_paths,
    array_remove(array_agg(sf.source_uri ORDER BY sc.slug, sf.source_path), NULL) AS source_uris
FROM document d
JOIN source_file sf ON sf.document_id = d.id
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
GROUP BY d.id;

CREATE VIEW v_duplicate_source_content AS
SELECT * FROM v_document_inventory WHERE source_alias_count > 1;

INSERT INTO catalog_meta (key, value)
VALUES ('schema_version', '2')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();

INSERT INTO schema_migration (version, description)
VALUES ('002', 'multi-source provenance, relationship integrity, and query indexes')
ON CONFLICT (version) DO NOTHING;

COMMIT;
