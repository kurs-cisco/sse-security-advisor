BEGIN;

CREATE TABLE IF NOT EXISTS target_module_import (
    id bigserial PRIMARY KEY,
    source_filename text NOT NULL,
    source_sha256 char(64) NOT NULL UNIQUE,
    retrieved_on date,
    imported_at timestamptz NOT NULL DEFAULT now(),
    is_active boolean NOT NULL DEFAULT true,
    team_count integer NOT NULL,
    module_record_count integer NOT NULL,
    raw_payload jsonb NOT NULL,
    CONSTRAINT target_module_import_sha256_format
        CHECK (source_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_target_module_import_active
    ON target_module_import (is_active) WHERE is_active;

CREATE TABLE IF NOT EXISTS team_target_module (
    id bigserial PRIMARY KEY,
    import_id bigint NOT NULL REFERENCES target_module_import(id) ON DELETE RESTRICT,
    team_key text NOT NULL,
    team_name text NOT NULL,
    owner_name text,
    lead_name text,
    il2_raw text,
    il5_raw text,
    service_groups text[] NOT NULL DEFAULT '{}',
    module_position integer NOT NULL,
    current_module text,
    current_version text,
    used_by text,
    target_module text,
    asserted_status text,
    normalized_status text NOT NULL,
    current_cmvp_cert text,
    target_cmvp_cert text,
    target_disposition text NOT NULL,
    disposition_basis text NOT NULL,
    reason text,
    evidence_grade text NOT NULL DEFAULT 'user_asserted',
    review_required boolean NOT NULL DEFAULT true,
    record_sha256 char(64) NOT NULL,
    raw_record jsonb NOT NULL,
    UNIQUE (import_id, team_key, module_position),
    CONSTRAINT team_target_module_record_sha256_format
        CHECK (record_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT team_target_module_normalized_status
        CHECK (normalized_status IN (
            'asserted_compliant', 'asserted_not_compliant',
            'pending_certification', 'not_applicable', 'not_determined'
        )),
    CONSTRAINT team_target_module_disposition
        CHECK (target_disposition IN (
            'active_certificate', 'cmvp_in_process', 'planned_unverified',
            'not_supplied', 'not_applicable', 'not_determined'
        ))
);

CREATE INDEX IF NOT EXISTS idx_team_target_module_active_team
    ON team_target_module (team_key, target_disposition, module_position);
CREATE INDEX IF NOT EXISTS idx_team_target_module_service_groups
    ON team_target_module USING gin (service_groups);

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '9')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('009', 'immutable team target-module inventory and CMVP planning disposition')
ON CONFLICT (version) DO NOTHING;

COMMIT;
