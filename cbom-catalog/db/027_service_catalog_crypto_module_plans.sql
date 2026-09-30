BEGIN;

-- Approved operational module plans are an overlay. Imported target-module
-- assertions and public-evidence records remain immutable and independently
-- addressable by their original checksums.
ALTER TABLE app_auth.service_catalog_entry
    ADD COLUMN IF NOT EXISTS crypto_module_plans jsonb;

ALTER TABLE app_auth.service_catalog_entry
    ADD CONSTRAINT service_catalog_crypto_module_plans_array CHECK (
        crypto_module_plans IS NULL OR
        (jsonb_typeof(crypto_module_plans) = 'array' AND jsonb_array_length(crypto_module_plans) <= 16)
    );

ALTER TABLE app_auth.service_catalog_entry
    DROP CONSTRAINT IF EXISTS service_catalog_entry_overridden_fields_valid;
ALTER TABLE app_auth.service_catalog_entry
    ADD CONSTRAINT service_catalog_entry_overridden_fields_valid CHECK (
        overridden_fields <@ ARRAY[
            'display_name', 'owner', 'owner_user_id', 'lead', 'lead_user_id',
            'il2_status', 'il2_target_date', 'il5_status', 'il5_target_date',
            'service_impact_risk', 'comments', 'attributes', 'crypto_module_plans'
        ]::text[]
    );

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '27')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('027', 'reviewed Service Catalog crypto-module planning overlay')
ON CONFLICT (version) DO NOTHING;

COMMIT;
