BEGIN;

-- The API normalizes these fields before comparison. Matching expression and
-- partial indexes avoid repeatedly scanning every component property row.
CREATE INDEX IF NOT EXISTS idx_component_property_crypto_relevant_true
    ON component_property(occurrence_id)
    WHERE lower(property_name) = 'fedramp:fips:crypto-relevant'
      AND lower(trim(coalesce(property_value, ''))) IN
          ('1', 'true', 'yes', 'on', 'enabled', 'validated');

CREATE INDEX IF NOT EXISTS idx_component_property_name_lower_occurrence
    ON component_property(lower(property_name), occurrence_id);

CREATE INDEX IF NOT EXISTS idx_document_property_name_lower_document
    ON document_property(lower(property_name), document_id);

CREATE INDEX IF NOT EXISTS idx_source_file_path_trgm
    ON source_file USING gin (source_path gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_component_purl_trgm
    ON component USING gin (canonical_purl gin_trgm_ops)
    WHERE canonical_purl IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_component_cpe_trgm
    ON component USING gin (cpe gin_trgm_ops)
    WHERE cpe IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_artifact_key_trgm
    ON artifact USING gin (canonical_key gin_trgm_ops);

INSERT INTO catalog_meta (key, value)
VALUES ('schema_version', '7')
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value, updated_at = now();

INSERT INTO schema_migration (version, description)
VALUES ('007', 'API query performance indexes')
ON CONFLICT (version) DO NOTHING;

COMMIT;
