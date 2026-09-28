BEGIN;

-- Routing metadata is operational and deliberately separate from authoritative
-- source evidence.  Existing corpus attribution is performed only by the
-- separately reviewed, checksum-gated operations script.
ALTER TABLE app_auth.ingestion_batch
    ADD COLUMN IF NOT EXISTS product_scope_ids text[];

ALTER TABLE app_auth.ingestion_batch
    DROP CONSTRAINT IF EXISTS ingestion_batch_product_scope_ids_check;
ALTER TABLE app_auth.ingestion_batch
    ADD CONSTRAINT ingestion_batch_product_scope_ids_check CHECK (
        product_scope_ids IS NULL OR product_scope_ids IN (
            ARRAY['secure-access-government']::text[],
            ARRAY['secure-access-defense']::text[],
            ARRAY['secure-access-defense', 'secure-access-government']::text[]
        )
    );

CREATE TABLE IF NOT EXISTS app_auth.evidence_product_scope_decision (
    id bigserial PRIMARY KEY,
    source_collection_id bigint NOT NULL REFERENCES source_collection(id) ON DELETE RESTRICT,
    service_group_id bigint NOT NULL REFERENCES service_group(id) ON DELETE RESTRICT,
    source_path text NOT NULL,
    source_sha256 char(64) NOT NULL,
    product_scope_ids text[] NOT NULL,
    decision_basis text NOT NULL CHECK (decision_basis IN (
        'uploader selection', 'owner default both'
    )),
    decision_reference text NOT NULL,
    attributed_by_batch_id uuid REFERENCES app_auth.ingestion_batch(id) ON DELETE RESTRICT,
    attributed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT evidence_product_scope_decision_sha256_format
        CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT evidence_product_scope_decision_path_nonempty CHECK (btrim(source_path) <> ''),
    CONSTRAINT evidence_product_scope_decision_reference_nonempty CHECK (btrim(decision_reference) <> ''),
    CONSTRAINT evidence_product_scope_decision_selection CHECK (product_scope_ids IN (
        ARRAY['secure-access-government']::text[],
        ARRAY['secure-access-defense']::text[],
        ARRAY['secure-access-defense', 'secure-access-government']::text[]
    )),
    CONSTRAINT evidence_product_scope_decision_batch_basis CHECK (
        (decision_basis = 'uploader selection' AND attributed_by_batch_id IS NOT NULL)
        OR (decision_basis = 'owner default both' AND attributed_by_batch_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_evidence_product_scope_decision_current
    ON app_auth.evidence_product_scope_decision (
        source_collection_id, service_group_id, source_path, source_sha256,
        attributed_at DESC, id DESC
    );
CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_product_scope_owner_default
    ON app_auth.evidence_product_scope_decision (
        source_collection_id, service_group_id, source_path, source_sha256,
        decision_reference
    ) WHERE decision_basis = 'owner default both';

-- Decisions are operational audit records.  A later upload supersedes an
-- earlier routing choice through a new row; it never rewrites history.
CREATE TRIGGER evidence_product_scope_decision_append_only
BEFORE UPDATE OR DELETE ON app_auth.evidence_product_scope_decision
FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_mutation();

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '17')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('017', 'dual product evidence routing for committed uploads')
ON CONFLICT (version) DO NOTHING;

COMMIT;
