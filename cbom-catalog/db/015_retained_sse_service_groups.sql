BEGIN;

-- Keep approved SSE planning categories visible even when the current corpus
-- has no directory or parsed document for them. This mirrors the ingester's
-- collection-scoped retention contract and makes existing deployments converge
-- without requiring a synthetic or destructive corpus refresh.
INSERT INTO service_group (
    source_collection_id,
    slug,
    display_name,
    source_path
)
SELECT
    collection.id,
    retained.slug,
    retained.display_name,
    retained.source_path
FROM source_collection collection
CROSS JOIN (
    VALUES
        ('android-no-cbom', 'ANDROID-NO_CBOM', 'ANDROID-NO_CBOM'),
        ('ios-no-cbom', 'IOS-NO_CBOM', 'IOS-NO_CBOM'),
        ('rsm-secure-client-no-cbom', 'RSM-SECURE_CLIENT-NO_CBOM', 'RSM-SECURE_CLIENT-NO_CBOM'),
        ('swg-roaming-client-no-cbom', 'SWG-ROAMING-CLIENT-NO_CBOM', 'SWG-ROAMING-CLIENT-NO_CBOM'),
        ('on-prem-clients', 'On Prem / Clients', 'ON-PREM-CLIENTS-NO_CBOM')
) AS retained(slug, display_name, source_path)
WHERE collection.slug = 'sse-cboms'
ON CONFLICT (source_collection_id, slug) DO NOTHING;

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '15')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('015', 'retain approved empty SSE service-group planning categories')
ON CONFLICT (version) DO NOTHING;

COMMIT;
