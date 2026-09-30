-- Presentation name only. Keep the collection/group slug and all evidence links.
BEGIN;

UPDATE service_group AS sg
SET display_name = 'Chromebook Client'
FROM source_collection AS sc
WHERE sg.source_collection_id = sc.id
  AND sc.slug = 'sse-cboms'
  AND sg.slug = 'on-prem-clients'
  AND sg.display_name = 'On Prem / Clients';

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '26')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('026', 'rename On Prem / Clients display label to Chromebook Client')
ON CONFLICT (version) DO NOTHING;

COMMIT;
