BEGIN;

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

INSERT INTO catalog_meta (key, value)
VALUES ('schema_version', '3')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();

INSERT INTO schema_migration (version, description)
VALUES ('003', 'immutable external observation payloads')
ON CONFLICT (version) DO NOTHING;

COMMIT;
