BEGIN;

-- Operational authorization telemetry. These records never grant a role and
-- are separate from source evidence, assessment/planning data, and OIDC policy.
CREATE TABLE IF NOT EXISTS app_auth.access_roster_snapshot (
    id bigserial PRIMARY KEY,
    app_user_id bigint NOT NULL REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    effective_role text NOT NULL CHECK (effective_role IN ('admin','lead','engineer','summary','none')),
    exact_grants jsonb NOT NULL DEFAULT '[]'::jsonb,
    policy_version text NOT NULL,
    policy_fingerprint char(64) NOT NULL CHECK (policy_fingerprint ~ '^[0-9a-f]{64}$'),
    verified_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(exact_grants) = 'array')
);
CREATE INDEX IF NOT EXISTS idx_access_roster_snapshot_current
    ON app_auth.access_roster_snapshot (app_user_id, verified_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS app_auth.user_access_action (
    id bigserial PRIMARY KEY,
    target_user_id bigint NOT NULL REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    action text NOT NULL CHECK (action IN ('revoke','restore')),
    reason text NOT NULL CHECK (length(btrim(reason)) >= 8),
    actor_user_id bigint NOT NULL REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    request_id text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CHECK (target_user_id <> actor_user_id)
);
CREATE INDEX IF NOT EXISTS idx_user_access_action_current
    ON app_auth.user_access_action (target_user_id, occurred_at DESC, id DESC);

-- Snapshot and revoke/restore history are immutable. Token revocation is an
-- intentional one-way operational state change and restoration never unrevokes
-- credentials.
CREATE TRIGGER access_roster_snapshot_append_only
BEFORE UPDATE OR DELETE ON app_auth.access_roster_snapshot
FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_mutation();
CREATE TRIGGER user_access_action_append_only
BEFORE UPDATE OR DELETE ON app_auth.user_access_action
FOR EACH ROW EXECUTE FUNCTION app_auth.reject_lead_review_mutation();

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '19')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('019', 'operational OIDC roster snapshots and reversible user access actions')
ON CONFLICT (version) DO NOTHING;

COMMIT;
