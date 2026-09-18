BEGIN;

ALTER TABLE service_group
    ADD COLUMN IF NOT EXISTS source_collection_id bigint;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'service_group_source_collection_fkey'
    ) THEN
        ALTER TABLE service_group
            ADD CONSTRAINT service_group_source_collection_fkey
            FOREIGN KEY (source_collection_id) REFERENCES source_collection(id);
    END IF;
END
$$;

CREATE TEMP TABLE service_group_collection_map ON COMMIT DROP AS
SELECT DISTINCT
    sg.id AS old_group_id,
    sf.source_collection_id
FROM service_group sg
JOIN source_file sf ON sf.service_group_id = sg.id;

UPDATE service_group sg
SET source_collection_id = mapping.source_collection_id
FROM (
    SELECT old_group_id, min(source_collection_id) AS source_collection_id
    FROM service_group_collection_map
    GROUP BY old_group_id
) mapping
WHERE sg.id = mapping.old_group_id
  AND sg.source_collection_id IS NULL;

DO $$
DECLARE
    collection_count integer;
BEGIN
    SELECT count(*) INTO collection_count FROM source_collection;
    IF collection_count = 1 THEN
        UPDATE service_group
        SET source_collection_id = (SELECT id FROM source_collection LIMIT 1)
        WHERE source_collection_id IS NULL;
    ELSIF EXISTS (
        SELECT 1 FROM service_group WHERE source_collection_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'Cannot infer a source collection for unreferenced service groups; assign them before migration 004';
    END IF;
END
$$;

ALTER TABLE service_group
    DROP CONSTRAINT IF EXISTS service_group_slug_key;

INSERT INTO service_group (
    source_collection_id, slug, display_name, source_path, created_at
)
SELECT
    mapping.source_collection_id,
    original.slug,
    original.display_name,
    original.source_path,
    original.created_at
FROM service_group_collection_map mapping
JOIN service_group original ON original.id = mapping.old_group_id
WHERE mapping.source_collection_id <> original.source_collection_id
  AND NOT EXISTS (
      SELECT 1
      FROM service_group existing
      WHERE existing.source_collection_id = mapping.source_collection_id
        AND existing.slug = original.slug
  );

UPDATE source_file sf
SET service_group_id = target.id
FROM service_group original
JOIN service_group target ON target.slug = original.slug
WHERE original.id = sf.service_group_id
  AND target.source_collection_id = sf.source_collection_id;

ALTER TABLE service_group
    ALTER COLUMN source_collection_id SET NOT NULL;

ALTER TABLE service_group
    ADD CONSTRAINT service_group_collection_slug_key
    UNIQUE (source_collection_id, slug);

ALTER TABLE service_group
    ADD CONSTRAINT service_group_collection_id_id_key
    UNIQUE (source_collection_id, id);

ALTER TABLE source_file
    ADD CONSTRAINT source_file_collection_group_fk
    FOREIGN KEY (source_collection_id, service_group_id)
    REFERENCES service_group(source_collection_id, id);

CREATE OR REPLACE VIEW v_document_inventory AS
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
    array_agg(
        DISTINCT sc.slug || '/' || sg.display_name
        ORDER BY sc.slug || '/' || sg.display_name
    ) AS service_groups,
    array_agg(sf.source_path ORDER BY sc.slug, sf.source_path) AS source_paths,
    array_remove(
        array_agg(sf.source_uri ORDER BY sc.slug, sf.source_path), NULL
    ) AS source_uris
FROM document d
JOIN source_file sf ON sf.document_id = d.id
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
GROUP BY d.id;

CREATE OR REPLACE VIEW v_component_usage AS
SELECT
    c.id AS component_id,
    c.component_type,
    c.namespace,
    c.name,
    c.version,
    c.canonical_purl,
    c.cpe,
    count(DISTINCT dc.document_id) AS document_count,
    array_agg(
        DISTINCT sc.slug || '/' || sg.display_name
        ORDER BY sc.slug || '/' || sg.display_name
    ) AS service_groups
FROM component c
JOIN document_component dc ON dc.component_id = c.id
JOIN source_file sf ON sf.document_id = dc.document_id
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
GROUP BY c.id;

INSERT INTO catalog_meta (key, value)
VALUES ('schema_version', '4')
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value, updated_at = now();

INSERT INTO schema_migration (version, description)
VALUES ('004', 'collection-scoped service groups')
ON CONFLICT (version) DO NOTHING;

COMMIT;
