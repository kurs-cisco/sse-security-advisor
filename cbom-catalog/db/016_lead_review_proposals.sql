BEGIN;

-- Operational review workflow only.  These records are deliberately separate
-- from source evidence, planning imports, and admin_overlay.  Approval does
-- not amend a catalog assertion or an authoritative POA&M record.
CREATE TABLE IF NOT EXISTS app_auth.lead_review_proposal (
    id uuid PRIMARY KEY,
    source_collection text NOT NULL,
    service_group text NOT NULL,
    resource_type text NOT NULL,
    resource_key text NOT NULL,
    proposed_note text NOT NULL,
    rationale text NOT NULL,
    policy_version text NOT NULL,
    scope_fingerprint char(64) NOT NULL,
    ato_boundary text NOT NULL,
    -- Catalog revision is a compound Python integer; it can exceed PostgreSQL
    -- bigint because it combines several counters with large multipliers.
    assessment_revision text NOT NULL,
    assessment_fingerprint char(64) NOT NULL,
    submitted_by_user_id bigint NOT NULL REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    submitted_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT lead_review_proposal_resource_type CHECK (
        resource_type IN ('poam_candidate', 'finding')
    ),
    CONSTRAINT lead_review_proposal_note_nonempty CHECK (length(btrim(proposed_note)) >= 8),
    CONSTRAINT lead_review_proposal_rationale_nonempty CHECK (length(btrim(rationale)) >= 8),
    CONSTRAINT lead_review_proposal_scope_fingerprint_format
        CHECK (scope_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT lead_review_proposal_assessment_fingerprint_format
        CHECK (assessment_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_lead_review_proposal_scope
    ON app_auth.lead_review_proposal (source_collection, service_group, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_lead_review_proposal_resource
    ON app_auth.lead_review_proposal (resource_type, resource_key, submitted_at DESC);

-- One append-only decision per proposal.  Neither approval nor rejection
-- changes the proposal and no decision writes an admin overlay.
CREATE TABLE IF NOT EXISTS app_auth.lead_review_decision (
    proposal_id uuid PRIMARY KEY REFERENCES app_auth.lead_review_proposal(id) ON DELETE RESTRICT,
    decision text NOT NULL,
    decision_reason text NOT NULL,
    decided_by_user_id bigint NOT NULL REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    decided_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT lead_review_decision_value CHECK (decision IN ('approved', 'rejected')),
    CONSTRAINT lead_review_decision_reason_nonempty CHECK (length(btrim(decision_reason)) >= 8)
);

-- The two workflow records and their audit trail must remain append-only.
-- An attempted alteration is rejected even if a caller reaches the database
-- outside the API.  `admin_overlay` is intentionally not involved here.
CREATE OR REPLACE FUNCTION app_auth.reject_lead_review_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'lead review workflow records are append-only';
END;
$$;

CREATE TRIGGER lead_review_proposal_append_only
BEFORE UPDATE OR DELETE ON app_auth.lead_review_proposal
FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_mutation();

CREATE TRIGGER lead_review_decision_append_only
BEFORE UPDATE OR DELETE ON app_auth.lead_review_decision
FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_mutation();

CREATE OR REPLACE FUNCTION app_auth.reject_lead_review_self_approval()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    submitter_id bigint;
BEGIN
    SELECT submitted_by_user_id INTO submitter_id
    FROM app_auth.lead_review_proposal
    WHERE id = NEW.proposal_id;
    IF submitter_id IS NOT NULL AND NEW.decided_by_user_id = submitter_id THEN
        RAISE EXCEPTION 'a separate administrator must decide a lead review proposal';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER lead_review_decision_separate_approver
BEFORE INSERT ON app_auth.lead_review_decision
FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_self_approval();

-- audit_event is shared with other operational workflows.  It has no update
-- path in the application and this trigger makes its immutable audit contract
-- explicit without affecting inserts.
CREATE TRIGGER audit_event_append_only
BEFORE UPDATE OR DELETE ON app_auth.audit_event
FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_mutation();

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '16')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('016', 'append-only service-lead operational review proposals and decisions')
ON CONFLICT (version) DO NOTHING;

COMMIT;
