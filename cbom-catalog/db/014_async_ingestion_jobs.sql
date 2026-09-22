BEGIN;

CREATE TABLE IF NOT EXISTS app_auth.ingestion_batch (
    id uuid PRIMARY KEY,
    source_collection text NOT NULL,
    manifest_sha256 char(64) NOT NULL,
    manifest_version integer NOT NULL DEFAULT 1,
    dry_run boolean NOT NULL DEFAULT false,
    authoritative_snapshot boolean NOT NULL DEFAULT false,
    state text NOT NULL DEFAULT 'uploading',
    expected_file_count integer NOT NULL,
    expected_total_bytes bigint NOT NULL,
    verified_file_count integer NOT NULL DEFAULT 0,
    upload_prefix text NOT NULL UNIQUE,
    upload_expires_at timestamptz NOT NULL,
    ecs_task_arn text,
    ingest_run_id bigint REFERENCES ingest_run(id) ON DELETE RESTRICT,
    result jsonb,
    error_summary text,
    created_by_user_id bigint REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    created_by_credential_id uuid REFERENCES app_auth.api_credential(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    submitted_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    CONSTRAINT ingestion_batch_manifest_sha256_format
        CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ingestion_batch_collection_format
        CHECK (source_collection ~ '^[a-z0-9]([a-z0-9-]{0,78}[a-z0-9])?$'),
    CONSTRAINT ingestion_batch_state CHECK (
        state IN ('uploading', 'submitting', 'queued', 'validating', 'running',
                  'succeeded', 'failed', 'expired')
    ),
    CONSTRAINT ingestion_batch_counts CHECK (
        expected_file_count > 0
        AND expected_total_bytes >= 0
        AND verified_file_count >= 0
        AND verified_file_count <= expected_file_count
    ),
    CONSTRAINT ingestion_batch_mode CHECK (NOT (dry_run AND authoritative_snapshot)),
    CONSTRAINT ingestion_batch_actor CHECK (
        (created_by_user_id IS NOT NULL)::integer
        + (created_by_credential_id IS NOT NULL)::integer = 1
    )
);

CREATE INDEX IF NOT EXISTS idx_ingestion_batch_created
    ON app_auth.ingestion_batch (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_batch_active
    ON app_auth.ingestion_batch (state, created_at)
    WHERE state IN ('submitting', 'queued', 'validating', 'running');

CREATE TABLE IF NOT EXISTS app_auth.ingestion_object (
    batch_id uuid NOT NULL REFERENCES app_auth.ingestion_batch(id) ON DELETE CASCADE,
    relative_path text NOT NULL,
    object_key text NOT NULL UNIQUE,
    sha256 char(64) NOT NULL,
    size_bytes bigint NOT NULL,
    content_type text NOT NULL,
    source_modified_at timestamptz,
    verified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (batch_id, relative_path),
    CONSTRAINT ingestion_object_sha256_format CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ingestion_object_size CHECK (size_bytes >= 0),
    CONSTRAINT ingestion_object_relative_path CHECK (
        relative_path <> ''
        AND relative_path !~ '^/'
        AND relative_path !~ '(^|/)\.\.(/|$)'
        AND relative_path !~ E'\\\\'
    )
);

CREATE INDEX IF NOT EXISTS idx_ingestion_object_verification
    ON app_auth.ingestion_object (batch_id, verified_at);

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '14')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('014', 'presigned S3 upload manifests and asynchronous ECS ingestion jobs')
ON CONFLICT (version) DO NOTHING;

COMMIT;
