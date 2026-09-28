BEGIN;

-- Migration 016 has no live proposal rows.  Refuse an implicit reinterpretation
-- if this forward migration is ever pointed at a different environment.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM app_auth.lead_review_proposal) THEN
        RAISE EXCEPTION
            'Cannot add product scope to existing lead review proposals; export and review existing operational records first';
    END IF;
END
$$;

ALTER TABLE app_auth.lead_review_proposal
    ADD COLUMN product_scope_id text;
ALTER TABLE app_auth.lead_review_proposal
    ADD COLUMN assessment_authorization_reference text;

ALTER TABLE app_auth.lead_review_proposal
    ADD CONSTRAINT lead_review_proposal_product_scope_check CHECK (
        product_scope_id IN ('secure-access-government', 'secure-access-defense')
    );
ALTER TABLE app_auth.lead_review_proposal
    ADD CONSTRAINT lead_review_proposal_authorization_reference_nonempty CHECK (
        btrim(assessment_authorization_reference) <> ''
    );

ALTER TABLE app_auth.lead_review_proposal
    ALTER COLUMN product_scope_id SET NOT NULL;
ALTER TABLE app_auth.lead_review_proposal
    ALTER COLUMN assessment_authorization_reference SET NOT NULL;

CREATE INDEX idx_lead_review_proposal_product_scope
    ON app_auth.lead_review_proposal (
        source_collection, service_group, product_scope_id, submitted_at DESC
    );

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '18')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('018', 'product-scoped append-only lead review proposals')
ON CONFLICT (version) DO NOTHING;

COMMIT;
