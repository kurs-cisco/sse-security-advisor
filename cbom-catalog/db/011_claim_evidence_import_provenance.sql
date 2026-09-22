BEGIN;

ALTER TABLE target_module_claim_evidence
    ADD COLUMN IF NOT EXISTS evidence_import_id bigint
        REFERENCES target_module_evidence_import(id) ON DELETE RESTRICT;

UPDATE target_module_claim_evidence claim
SET evidence_import_id = external.import_id
FROM target_module_external_evidence external
WHERE external.id = claim.external_evidence_id
  AND claim.evidence_import_id IS NULL;

UPDATE target_module_claim_evidence claim
SET evidence_import_id = imports.id
FROM target_module_evidence_import imports
WHERE claim.source_kind IN ('catalog_component', 'catalog_crypto_property', 'catalog_tool_result')
  AND imports.evidence_set_kind = 'catalog_correlation'
  AND imports.is_active
  AND claim.evidence_import_id IS NULL;

ALTER TABLE target_module_claim_evidence
    DROP CONSTRAINT IF EXISTS target_module_claim_evidence_verdict;
ALTER TABLE target_module_claim_evidence
    ADD CONSTRAINT target_module_claim_evidence_verdict CHECK (verdict IN (
        'corroborates', 'contradicts', 'partially_corroborates',
        'not_observed', 'not_assessable', 'not_applicable', 'conflict'
    ));

UPDATE target_module_claim_evidence
SET verdict = 'not_assessable'
WHERE source_kind = 'catalog_tool_result'
  AND evidence_payload ->> 'catalog_verdict' = 'not_assessable';

DROP INDEX IF EXISTS uq_target_module_claim_evidence_observation;
CREATE UNIQUE INDEX uq_target_module_claim_evidence_observation
    ON target_module_claim_evidence (
        target_module_id, coalesce(evidence_import_id, 0), claim_field,
        source_payload_sha256, coalesce(source_locator, ''),
        coalesce(document_component_id, 0)
    );

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '11')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('011', 'claim-evidence import provenance and not-assessable distinction')
ON CONFLICT (version) DO NOTHING;

COMMIT;
