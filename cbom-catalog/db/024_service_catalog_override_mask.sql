BEGIN;

-- A NULL in a managed catalog column used to be indistinguishable from an
-- untouched import.  Preserve that distinction explicitly so an approved
-- administrator or lead decision can intentionally clear an imported value
-- without changing the imported Team Tracker or service-impact records.
ALTER TABLE app_auth.service_catalog_entry
    ADD COLUMN IF NOT EXISTS overridden_fields text[] NOT NULL DEFAULT '{}'::text[];

ALTER TABLE app_auth.service_catalog_entry
    ADD CONSTRAINT service_catalog_entry_overridden_fields_valid CHECK (
        overridden_fields <@ ARRAY[
            'display_name', 'owner', 'owner_user_id', 'lead', 'lead_user_id',
            'il2_status', 'il2_target_date', 'il5_status', 'il5_target_date',
            'service_impact_risk', 'comments', 'attributes'
        ]::text[]
    );

-- Rows created before this migration already used non-NULL managed values as
-- overrides.  Mark those values so their rendered meaning does not change.
UPDATE app_auth.service_catalog_entry
SET overridden_fields = ARRAY_REMOVE(ARRAY[
    CASE WHEN display_name IS NOT NULL THEN 'display_name' END,
    CASE WHEN owner IS NOT NULL THEN 'owner' END,
    CASE WHEN owner_user_id IS NOT NULL THEN 'owner_user_id' END,
    CASE WHEN lead IS NOT NULL THEN 'lead' END,
    CASE WHEN lead_user_id IS NOT NULL THEN 'lead_user_id' END,
    CASE WHEN il2_status IS NOT NULL THEN 'il2_status' END,
    CASE WHEN il2_target_date IS NOT NULL THEN 'il2_target_date' END,
    CASE WHEN il5_status IS NOT NULL THEN 'il5_status' END,
    CASE WHEN il5_target_date IS NOT NULL THEN 'il5_target_date' END,
    CASE WHEN service_impact_risk IS NOT NULL THEN 'service_impact_risk' END,
    CASE WHEN comments IS NOT NULL THEN 'comments' END,
    'attributes'
], NULL)
WHERE overridden_fields = '{}'::text[];

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '24')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('024', 'preserve explicit managed Service Catalog clears')
ON CONFLICT (version) DO NOTHING;

COMMIT;
