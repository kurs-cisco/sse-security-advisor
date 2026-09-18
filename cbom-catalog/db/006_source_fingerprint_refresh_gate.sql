BEGIN;

ALTER TABLE ingest_run
    ADD COLUMN IF NOT EXISTS files_unchanged integer NOT NULL DEFAULT 0
        CHECK (files_unchanged >= 0),
    ADD COLUMN IF NOT EXISTS fingerprint_algorithm text NOT NULL DEFAULT 'sha256',
    ADD COLUMN IF NOT EXISTS force_reprocess boolean NOT NULL DEFAULT false;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ingest_run_fingerprint_algorithm_check'
    ) THEN
        ALTER TABLE ingest_run
            ADD CONSTRAINT ingest_run_fingerprint_algorithm_check
            CHECK (fingerprint_algorithm = 'sha256');
    END IF;
END
$$;

ALTER TABLE source_file
    ADD COLUMN IF NOT EXISTS fingerprint_algorithm text NOT NULL DEFAULT 'sha256',
    ADD COLUMN IF NOT EXISTS fingerprinted_at timestamptz;

UPDATE source_file
SET fingerprinted_at = coalesce(updated_at, discovered_at)
WHERE content_sha256 IS NOT NULL
  AND fingerprinted_at IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_file_fingerprint_algorithm_check'
    ) THEN
        ALTER TABLE source_file
            ADD CONSTRAINT source_file_fingerprint_algorithm_check
            CHECK (fingerprint_algorithm = 'sha256');
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS source_file_fingerprint (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_file_id bigint NOT NULL REFERENCES source_file(id) ON DELETE CASCADE,
    algorithm text NOT NULL DEFAULT 'sha256'
        CHECK (algorithm = 'sha256'),
    checksum char(64) NOT NULL
        CHECK (checksum ~ '^[0-9a-f]{64}$'),
    byte_size bigint NOT NULL CHECK (byte_size >= 0),
    first_seen_run_id bigint REFERENCES ingest_run(id) ON DELETE SET NULL,
    last_seen_run_id bigint REFERENCES ingest_run(id) ON DELETE SET NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    observation_count bigint NOT NULL DEFAULT 1 CHECK (observation_count >= 1),
    CONSTRAINT source_file_fingerprint_identity
        UNIQUE (source_file_id, algorithm, checksum)
);

INSERT INTO source_file_fingerprint (
    source_file_id, algorithm, checksum, byte_size,
    first_seen_run_id, last_seen_run_id, first_seen_at, last_seen_at
)
SELECT
    sf.id,
    'sha256',
    sf.content_sha256,
    sf.byte_size,
    sf.last_seen_run_id,
    sf.last_seen_run_id,
    coalesce(sf.discovered_at, now()),
    coalesce(sf.fingerprinted_at, sf.updated_at, now())
FROM source_file sf
WHERE sf.content_sha256 IS NOT NULL
ON CONFLICT (source_file_id, algorithm, checksum) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_source_file_fingerprint_checksum
    ON source_file_fingerprint(algorithm, checksum);
CREATE INDEX IF NOT EXISTS idx_source_file_fingerprint_last_seen
    ON source_file_fingerprint(last_seen_run_id);
CREATE INDEX IF NOT EXISTS idx_source_file_current_checksum
    ON source_file(content_sha256)
    WHERE content_sha256 IS NOT NULL;

CREATE OR REPLACE VIEW v_source_fingerprint_status AS
SELECT
    sf.id AS source_file_id,
    sc.slug AS source_collection,
    sg.slug AS service_group,
    sf.source_path,
    sf.source_uri,
    sf.byte_size,
    sf.fingerprint_algorithm,
    sf.content_sha256 AS current_checksum,
    sf.fingerprinted_at,
    sf.modified_at,
    sf.parse_status,
    sf.document_id,
    d.sha256 AS document_checksum,
    count(history.id) AS fingerprint_versions,
    coalesce(sum(history.observation_count), 0) AS verification_observations,
    max(history.last_seen_at) AS last_verified_at
FROM source_file sf
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
LEFT JOIN document d ON d.id = sf.document_id
LEFT JOIN source_file_fingerprint history ON history.source_file_id = sf.id
GROUP BY sf.id, sc.id, sg.id, d.id;

INSERT INTO catalog_meta (key, value)
VALUES ('schema_version', '6')
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value, updated_at = now();

INSERT INTO schema_migration (version, description)
VALUES ('006', 'source checksum history and refresh gate')
ON CONFLICT (version) DO NOTHING;

COMMIT;
