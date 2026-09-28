BEGIN;
CREATE TABLE app_auth.operational_evidence_note (
 id uuid PRIMARY KEY, source_collection text NOT NULL, service_group text NOT NULL,
 product_scope_id text NOT NULL CHECK (product_scope_id IN ('secure-access-government','secure-access-defense')),
 finding_id text NOT NULL, source_tuple_digest char(64) NOT NULL CHECK (source_tuple_digest ~ '^[0-9a-f]{64}$'),
 finding_observation_digest char(64) NOT NULL CHECK (finding_observation_digest ~ '^[0-9a-f]{64}$'),
 policy_fingerprint char(64) NOT NULL CHECK (policy_fingerprint ~ '^[0-9a-f]{64}$'), assessment_revision text NOT NULL,
 note text NOT NULL CHECK (length(btrim(note)) >= 8), lead_rationale text NOT NULL CHECK (length(btrim(lead_rationale)) >= 8), submitted_by_user_id bigint NOT NULL REFERENCES app_auth.app_user(id), submitted_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE app_auth.operational_evidence_note_decision (
 note_id uuid PRIMARY KEY REFERENCES app_auth.operational_evidence_note(id) ON DELETE RESTRICT,
 decision text NOT NULL CHECK (decision IN ('approved','rejected')), reason text NOT NULL CHECK (length(btrim(reason)) >= 8),
 decided_by_user_id bigint NOT NULL REFERENCES app_auth.app_user(id), decided_at timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION app_auth.reject_evidence_note_self_decision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE submitter bigint; BEGIN SELECT submitted_by_user_id INTO submitter FROM app_auth.operational_evidence_note WHERE id=NEW.note_id; IF submitter=NEW.decided_by_user_id THEN RAISE EXCEPTION 'a separate administrator must decide an evidence note'; END IF; RETURN NEW; END; $$;
CREATE TRIGGER operational_evidence_note_append_only BEFORE UPDATE OR DELETE ON app_auth.operational_evidence_note FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_mutation();
CREATE TRIGGER operational_evidence_note_decision_append_only BEFORE UPDATE OR DELETE ON app_auth.operational_evidence_note_decision FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_mutation();
CREATE TRIGGER operational_evidence_note_separate_admin BEFORE INSERT ON app_auth.operational_evidence_note_decision FOR EACH ROW EXECUTE FUNCTION app_auth.reject_evidence_note_self_decision();
INSERT INTO catalog_meta (key,value) VALUES ('schema_version','20') ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
INSERT INTO schema_migration(version,description) VALUES ('020','append-only product-scoped finding evidence observations') ON CONFLICT (version) DO NOTHING;
COMMIT;
