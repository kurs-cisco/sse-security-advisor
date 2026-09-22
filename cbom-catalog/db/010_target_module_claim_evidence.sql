BEGIN;

ALTER TABLE team_target_module
    ADD COLUMN IF NOT EXISTS target_version text,
    ADD COLUMN IF NOT EXISTS target_status_asserted_at timestamptz,
    ADD COLUMN IF NOT EXISTS assertion_subject_sha256 char(64);

CREATE TABLE IF NOT EXISTS target_module_evidence_import (
    id bigserial PRIMARY KEY,
    source_filename text NOT NULL,
    source_sha256 char(64) NOT NULL UNIQUE,
    evidence_set_kind text NOT NULL,
    retrieved_on date NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    is_active boolean NOT NULL DEFAULT true,
    evidence_record_count integer NOT NULL,
    raw_payload jsonb NOT NULL,
    CONSTRAINT target_module_evidence_import_sha256_format
        CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT target_module_evidence_import_kind
        CHECK (evidence_set_kind IN ('public_authority', 'catalog_correlation'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_target_module_evidence_import_active_kind
    ON target_module_evidence_import (evidence_set_kind) WHERE is_active;

CREATE TABLE IF NOT EXISTS target_module_external_evidence (
    id bigserial PRIMARY KEY,
    import_id bigint NOT NULL REFERENCES target_module_evidence_import(id) ON DELETE RESTRICT,
    evidence_key text NOT NULL,
    authority text NOT NULL,
    source_kind text NOT NULL,
    source_title text NOT NULL,
    source_url text NOT NULL,
    published_on date,
    retrieved_on date NOT NULL,
    certificate_number text,
    module_name text,
    module_version text,
    public_status text,
    evidence_grade text NOT NULL,
    supports_fields text[] NOT NULL DEFAULT '{}',
    limitations text[] NOT NULL DEFAULT '{}',
    payload_sha256 char(64) NOT NULL,
    raw_record jsonb NOT NULL,
    UNIQUE (import_id, evidence_key),
    CONSTRAINT target_module_external_evidence_payload_sha256_format
        CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT target_module_external_evidence_grade
        CHECK (evidence_grade IN ('primary', 'tool_observation', 'inventory', 'curated_analysis'))
);

CREATE TABLE IF NOT EXISTS target_module_claim_evidence (
    id bigserial PRIMARY KEY,
    target_module_id bigint NOT NULL REFERENCES team_target_module(id) ON DELETE RESTRICT,
    evidence_import_id bigint REFERENCES target_module_evidence_import(id) ON DELETE RESTRICT,
    external_evidence_id bigint REFERENCES target_module_external_evidence(id) ON DELETE RESTRICT,
    claim_field text NOT NULL,
    claim_value jsonb NOT NULL,
    observed_value jsonb NOT NULL,
    verdict text NOT NULL,
    evidence_grade text NOT NULL,
    source_kind text NOT NULL,
    correlation_strength text NOT NULL,
    document_id bigint REFERENCES document(id) ON DELETE RESTRICT,
    source_file_id bigint REFERENCES source_file(id) ON DELETE RESTRICT,
    document_component_id bigint REFERENCES document_component(id) ON DELETE RESTRICT,
    provider text,
    source_url text,
    source_title text,
    source_locator text,
    source_payload_sha256 char(64) NOT NULL,
    retrieved_at timestamptz NOT NULL,
    published_at timestamptz,
    evidence_payload jsonb NOT NULL,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT target_module_claim_evidence_field CHECK (claim_field IN (
        'current_module_identity', 'current_version', 'target_module_identity',
        'target_version', 'current_certificate', 'target_certificate',
        'target_public_status', 'team_deployment_applicability'
    )),
    CONSTRAINT target_module_claim_evidence_verdict CHECK (verdict IN (
        'corroborates', 'contradicts', 'partially_corroborates',
        'not_observed', 'not_assessable', 'not_applicable', 'conflict'
    )),
    CONSTRAINT target_module_claim_evidence_grade CHECK (evidence_grade IN (
        'primary', 'tool_observation', 'inventory', 'curated_analysis', 'user_asserted'
    )),
    CONSTRAINT target_module_claim_evidence_source_kind CHECK (source_kind IN (
        'catalog_component', 'catalog_crypto_property', 'catalog_tool_result',
        'cmvp_certificate', 'cmvp_modules_in_process', 'vendor_security_policy',
        'vendor_release_note', 'vendor_blog', 'deployment_attestation',
        'approved_assessment_artifact', 'analyst_note'
    )),
    CONSTRAINT target_module_claim_evidence_correlation CHECK (correlation_strength IN (
        'exact_artifact_digest', 'exact_document_sha256', 'explicit_service_attestation',
        'service_group_scope', 'name_version_match', 'name_only', 'uncorrelated'
    )),
    CONSTRAINT target_module_claim_evidence_sha256_format
        CHECK (source_payload_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_target_module_claim_evidence_observation
    ON target_module_claim_evidence (
        target_module_id, coalesce(evidence_import_id, 0), claim_field, source_payload_sha256,
        coalesce(source_locator, ''), coalesce(document_component_id, 0)
    );
CREATE INDEX IF NOT EXISTS idx_target_module_claim_evidence_target
    ON target_module_claim_evidence (target_module_id, claim_field, verdict);

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '10')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('010', 'immutable target-module claim evidence and independent verdicts')
ON CONFLICT (version) DO NOTHING;

COMMIT;
