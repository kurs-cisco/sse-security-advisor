BEGIN;

CREATE TABLE IF NOT EXISTS service_impact_import (
    id bigserial PRIMARY KEY,
    source_collection text NOT NULL,
    source_filename text NOT NULL,
    source_sha256 char(64) NOT NULL,
    source_encoding text NOT NULL,
    source_delimiter text NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    is_active boolean NOT NULL DEFAULT true,
    row_count integer NOT NULL,
    selected_payload jsonb NOT NULL,
    UNIQUE (source_collection, source_sha256),
    CONSTRAINT service_impact_import_sha256_format
        CHECK (source_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_service_impact_import_active
    ON service_impact_import (source_collection) WHERE is_active;

CREATE TABLE IF NOT EXISTS team_service_impact (
    id bigserial PRIMARY KEY,
    import_id bigint NOT NULL REFERENCES service_impact_import(id) ON DELETE RESTRICT,
    source_row integer NOT NULL,
    team_key text NOT NULL,
    team_name text NOT NULL,
    service_groups text[] NOT NULL,
    poam_impact text,
    risk_category text,
    comments text,
    evidence_grade text NOT NULL DEFAULT 'user_asserted',
    review_required boolean NOT NULL DEFAULT true,
    record_sha256 char(64) NOT NULL,
    selected_record jsonb NOT NULL,
    UNIQUE (import_id, team_key),
    CONSTRAINT team_service_impact_source_row CHECK (source_row > 1),
    CONSTRAINT team_service_impact_service_groups CHECK (cardinality(service_groups) > 0),
    CONSTRAINT team_service_impact_evidence_grade CHECK (evidence_grade = 'user_asserted'),
    CONSTRAINT team_service_impact_record_sha256_format
        CHECK (record_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_team_service_impact_groups
    ON team_service_impact USING gin (service_groups);

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '13')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('013', 'checksum-gated team service-impact planning metadata')
ON CONFLICT (version) DO NOTHING;

COMMIT;
