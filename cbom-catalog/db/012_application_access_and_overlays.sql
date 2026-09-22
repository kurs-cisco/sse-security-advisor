BEGIN;

CREATE SCHEMA IF NOT EXISTS app_auth;

CREATE TABLE IF NOT EXISTS app_auth.app_user (
    id bigserial PRIMARY KEY,
    oidc_issuer text,
    oidc_subject text,
    email text NOT NULL,
    display_name text,
    role text NOT NULL DEFAULT 'viewer',
    status text NOT NULL DEFAULT 'invited',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz,
    CONSTRAINT app_user_role CHECK (role IN ('viewer', 'admin')),
    CONSTRAINT app_user_status CHECK (status IN ('invited', 'active', 'disabled')),
    CONSTRAINT app_user_bound_identity CHECK (
        (oidc_issuer IS NULL AND oidc_subject IS NULL)
        OR (oidc_issuer IS NOT NULL AND oidc_subject IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_app_user_email
    ON app_auth.app_user (lower(email));
CREATE UNIQUE INDEX IF NOT EXISTS uq_app_user_oidc_identity
    ON app_auth.app_user (oidc_issuer, oidc_subject)
    WHERE oidc_issuer IS NOT NULL AND oidc_subject IS NOT NULL;

CREATE TABLE IF NOT EXISTS app_auth.api_credential (
    id uuid PRIMARY KEY,
    owner_user_id bigint NOT NULL REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    name text NOT NULL,
    token_prefix text NOT NULL UNIQUE,
    token_digest char(64) NOT NULL UNIQUE,
    scopes text[] NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    last_used_at timestamptz,
    revoked_at timestamptz,
    CONSTRAINT api_credential_digest_format CHECK (token_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT api_credential_expiration CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS idx_api_credential_owner
    ON app_auth.api_credential (owner_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_credential_active
    ON app_auth.api_credential (expires_at) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS app_auth.admin_overlay (
    id bigserial PRIMARY KEY,
    resource_type text NOT NULL,
    resource_key text NOT NULL,
    version integer NOT NULL,
    payload jsonb NOT NULL,
    rationale text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_by_user_id bigint REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    created_by_credential_id uuid REFERENCES app_auth.api_credential(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT admin_overlay_resource_type CHECK (
        resource_type IN ('service_group', 'poam_candidate', 'target_module', 'finding')
    ),
    CONSTRAINT admin_overlay_actor CHECK (
        (created_by_user_id IS NOT NULL)::integer
        + (created_by_credential_id IS NOT NULL)::integer = 1
    ),
    UNIQUE (resource_type, resource_key, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_admin_overlay_active
    ON app_auth.admin_overlay (resource_type, resource_key) WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_admin_overlay_history
    ON app_auth.admin_overlay (resource_type, resource_key, version DESC);

CREATE TABLE IF NOT EXISTS app_auth.audit_event (
    id bigserial PRIMARY KEY,
    request_id text NOT NULL,
    actor_user_id bigint REFERENCES app_auth.app_user(id) ON DELETE RESTRICT,
    actor_credential_id uuid REFERENCES app_auth.api_credential(id) ON DELETE RESTRICT,
    action text NOT NULL,
    resource_type text NOT NULL,
    resource_key text NOT NULL,
    before_state jsonb,
    after_state jsonb,
    outcome text NOT NULL DEFAULT 'success',
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_event_actor CHECK (
        (actor_user_id IS NOT NULL)::integer
        + (actor_credential_id IS NOT NULL)::integer = 1
    ),
    CONSTRAINT audit_event_outcome CHECK (outcome IN ('success', 'denied', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_audit_event_occurred
    ON app_auth.audit_event (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_event_resource
    ON app_auth.audit_event (resource_type, resource_key, occurred_at DESC);

INSERT INTO app_auth.app_user (email, role, status, display_name)
VALUES ('kurs@cisco.com', 'admin', 'invited', 'Kurs')
ON CONFLICT ((lower(email))) DO UPDATE
SET role = 'admin',
    updated_at = now();

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '12')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('012', 'application users, scoped API credentials, immutable overlays, and audit events')
ON CONFLICT (version) DO NOTHING;

COMMIT;
