BEGIN;

-- The deployment policy remains the bootstrap source until an administrator
-- publishes the first revision. Revisions are immutable; the singleton pointer
-- is the sole mutable activation state. Neither table changes catalog evidence.
CREATE TABLE IF NOT EXISTS app_auth.oidc_group_policy_revision (
    id bigserial PRIMARY KEY,
    policy_sha256 char(64) NOT NULL CHECK (policy_sha256 ~ '^[0-9a-f]{64}$'),
    previous_sha256 char(64) NOT NULL CHECK (previous_sha256 ~ '^[0-9a-f]{64}$'),
    groups jsonb NOT NULL CHECK (jsonb_typeof(groups) = 'object'),
    reason text NOT NULL CHECK (length(btrim(reason)) >= 8),
    actor_user_id bigint NOT NULL REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    request_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_auth.oidc_group_policy_active (
    singleton smallint PRIMARY KEY DEFAULT 1 CHECK (singleton = 1),
    revision_id bigint NOT NULL REFERENCES app_auth.oidc_group_policy_revision(id) ON DELETE RESTRICT,
    activated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER oidc_group_policy_revision_append_only
BEFORE UPDATE OR DELETE ON app_auth.oidc_group_policy_revision
FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_mutation();

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '21')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('021', 'audited administrator-maintained OIDC group-to-service policy revisions')
ON CONFLICT (version) DO NOTHING;

COMMIT;
