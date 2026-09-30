BEGIN;

-- The current workspace role can be lower than an identity's verified OIDC
-- entitlement. Keep that entitlement separate so a mode switch cannot weaken
-- the last-active-administrator safeguard.
ALTER TABLE app_auth.access_roster_snapshot
    ADD COLUMN IF NOT EXISTS verified_admin boolean NOT NULL DEFAULT false;

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '25')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('025', 'separate verified Administrator entitlement from selected roster workspace role')
ON CONFLICT (version) DO NOTHING;

COMMIT;
