BEGIN;

-- Managed Service Catalog metadata is operational data.  It overlays UI/API
-- presentation and never rewrites the imported corpus, Team Tracker, or
-- service-impact source records.
CREATE TABLE IF NOT EXISTS app_auth.service_catalog_entry (
    id bigserial PRIMARY KEY,
    source_collection_id bigint NOT NULL REFERENCES source_collection(id) ON DELETE RESTRICT,
    service_group text NOT NULL,
    -- Existing catalog evidence identity is linked when present.  New managed
    -- groups deliberately leave this NULL: no synthetic evidence group, file,
    -- source path, or routing record is created.
    catalog_service_group_id bigint REFERENCES service_group(id) ON DELETE RESTRICT,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    display_name text,
    owner text,
    owner_user_id bigint REFERENCES app_auth.app_user(id) ON DELETE SET NULL,
    lead text,
    lead_user_id bigint REFERENCES app_auth.app_user(id) ON DELETE SET NULL,
    -- NULL means the current imported planning value remains displayed.  A
    -- non-null value is an explicitly approved catalog override.
    il2_status text CHECK (il2_status IN ('not_supplied','planned','in_progress','complete','blocked','not_applicable')),
    il2_target_date date,
    il5_status text CHECK (il5_status IN ('not_supplied','planned','in_progress','complete','blocked','not_applicable')),
    il5_target_date date,
    service_impact_risk text CHECK (service_impact_risk IN ('low','moderate','high','critical')),
    comments text,
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(attributes) = 'object'),
    updated_by_user_id bigint NOT NULL REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (NOT (il2_status = 'not_applicable' AND il2_target_date IS NOT NULL)),
    CHECK (NOT (il5_status = 'not_applicable' AND il5_target_date IS NOT NULL)),
    CONSTRAINT service_catalog_entry_collection_group_key UNIQUE (source_collection_id, service_group)
);
CREATE UNIQUE INDEX IF NOT EXISTS service_catalog_entry_evidence_identity_unique
    ON app_auth.service_catalog_entry (catalog_service_group_id)
    WHERE catalog_service_group_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS app_auth.service_catalog_proposal (
    id uuid PRIMARY KEY,
    source_collection_id bigint NOT NULL REFERENCES source_collection(id) ON DELETE RESTRICT,
    service_group text NOT NULL,
    proposed_payload jsonb NOT NULL CHECK (jsonb_typeof(proposed_payload) = 'object'),
    rationale text NOT NULL CHECK (length(btrim(rationale)) >= 8),
    base_revision bigint NOT NULL CHECK (base_revision >= 0),
    submitted_by_user_id bigint NOT NULL REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    submitted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_service_catalog_proposal_group
    ON app_auth.service_catalog_proposal (source_collection_id, service_group, submitted_at DESC);

-- Each authoritative version is retained independently of the mutable current
-- row.  Together with audit_event this makes direct edits and approvals fully
-- reconstructible without touching source/planning imports.
CREATE TABLE IF NOT EXISTS app_auth.service_catalog_entry_revision (
    id bigserial PRIMARY KEY,
    service_catalog_entry_id bigint NOT NULL REFERENCES app_auth.service_catalog_entry(id) ON DELETE RESTRICT,
    revision bigint NOT NULL CHECK (revision > 0),
    operation text NOT NULL CHECK (operation IN ('create','admin_update','proposal_approved')),
    reason text NOT NULL CHECK (length(btrim(reason)) >= 8),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    actor_user_id bigint NOT NULL REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (service_catalog_entry_id, revision)
);

CREATE TABLE IF NOT EXISTS app_auth.service_catalog_proposal_decision (
    proposal_id uuid PRIMARY KEY REFERENCES app_auth.service_catalog_proposal(id) ON DELETE RESTRICT,
    decision text NOT NULL CHECK (decision IN ('approved','rejected')),
    decision_reason text NOT NULL CHECK (length(btrim(decision_reason)) >= 8),
    decided_by_user_id bigint NOT NULL REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    decided_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER service_catalog_proposal_append_only
BEFORE UPDATE OR DELETE ON app_auth.service_catalog_proposal
FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_mutation();
CREATE TRIGGER service_catalog_proposal_decision_append_only
BEFORE UPDATE OR DELETE ON app_auth.service_catalog_proposal_decision
FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_mutation();
CREATE TRIGGER service_catalog_entry_revision_append_only
BEFORE UPDATE OR DELETE ON app_auth.service_catalog_entry_revision
FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_mutation();

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '22')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('022', 'managed Service Catalog with scoped lead proposals')
ON CONFLICT (version) DO NOTHING;

COMMIT;
