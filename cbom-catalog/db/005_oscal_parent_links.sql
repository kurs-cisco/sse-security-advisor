BEGIN;

WITH parent_result AS (
    SELECT document_id, external_id, max(id) AS id
    FROM external_record
    WHERE record_type = 'oscal_result'
    GROUP BY document_id, external_id
)
UPDATE external_record child
SET parent_record_id = parent.id
FROM parent_result parent
WHERE child.document_id = parent.document_id
  AND child.data->>'parent_result' = parent.external_id
  AND child.record_type <> 'oscal_result'
  AND child.parent_record_id IS DISTINCT FROM parent.id;

CREATE INDEX IF NOT EXISTS idx_external_record_parent
    ON external_record(parent_record_id)
    WHERE parent_record_id IS NOT NULL;

INSERT INTO catalog_meta (key, value)
VALUES ('schema_version', '5')
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value, updated_at = now();

INSERT INTO schema_migration (version, description)
VALUES ('005', 'relational OSCAL parent links')
ON CONFLICT (version) DO NOTHING;

COMMIT;
