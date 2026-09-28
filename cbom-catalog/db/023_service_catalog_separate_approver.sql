BEGIN;

-- Keep the Service Catalog approval separation enforceable even if a write
-- reaches the database outside the API.  The API already performs this check;
-- this trigger makes the authoritative approval boundary durable.
CREATE OR REPLACE FUNCTION app_auth.reject_service_catalog_self_approval()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    submitter_id bigint;
BEGIN
    SELECT submitted_by_user_id INTO submitter_id
    FROM app_auth.service_catalog_proposal
    WHERE id = NEW.proposal_id;

    IF submitter_id IS NOT NULL AND NEW.decided_by_user_id = submitter_id THEN
        RAISE EXCEPTION 'a separate administrator must decide a Service Catalog proposal';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER service_catalog_proposal_decision_separate_approver
BEFORE INSERT ON app_auth.service_catalog_proposal_decision
FOR EACH ROW EXECUTE FUNCTION app_auth.reject_service_catalog_self_approval();

INSERT INTO catalog_meta (key, value) VALUES ('schema_version', '23')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
INSERT INTO schema_migration (version, description)
VALUES ('023', 'enforce separate Service Catalog proposal approver')
ON CONFLICT (version) DO NOTHING;

COMMIT;
