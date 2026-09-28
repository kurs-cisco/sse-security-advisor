-- One-off owner-authorized operational routing backfill for the reviewed
-- GovCloud development corpus.  Do not run through db/migrate.sh or against a
-- different collection.  It never updates source_file, document, planning, or
-- assessment records.
--
-- Run only after read-only preflight, for example:
--   psql -X -v ON_ERROR_STOP=1 \
--     -v expected_manifest_sha256='<preflight SHA-256>' \
--     -v backfill_actor_email='kurs@cisco.com' \
--     -f ops/backfill_existing_product_scopes_20260926.sql
-- `backfill_actor_email` records the owner authorization on whose behalf this
-- operation runs; session_user/current_user are retained in the audit record
-- as the database executor identity. `expected_manifest_sha256` is a canonical SHA-256 over each exact current
-- (collection, group, path, source SHA-256) tuple; it is not the old MD5
-- corpus continuity value.  The script prints the same digest post-write.
\if :{?expected_manifest_sha256}
\else
\warn expected_manifest_sha256 is required from reviewed read-only preflight
\quit
\endif
\if :{?backfill_actor_email}
\else
\warn backfill_actor_email is required for immutable operational audit
\quit
\endif

BEGIN;
SET LOCAL cbom.expected_manifest_sha256 TO :'expected_manifest_sha256';
SET LOCAL cbom.backfill_actor_email TO :'backfill_actor_email';

-- Hold the current-source identity stable through preflight, decision write,
-- and postcondition checks.  This conflicts with the ingestion worker's
-- source_file updates and with concurrent routing-decision inserts.
LOCK TABLE source_file IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE app_auth.evidence_product_scope_decision IN SHARE ROW EXCLUSIVE MODE;

DO $$
DECLARE
    canonical_manifest_sha256 text;
    sse_source_count bigint;
    sse_group_count bigint;
    missing_hash_count bigint;
    audit_actor_count bigint;
BEGIN
    IF to_regprocedure('sha256(bytea)') IS NULL THEN
        RAISE EXCEPTION 'Refusing product attribution backfill: PostgreSQL sha256(bytea) is unavailable';
    END IF;
    SELECT encode(sha256(convert_to(coalesce(string_agg(
        sc.slug || E'\x1f' || sg.slug || E'\x1f' || sf.source_path || E'\x1f' || sf.content_sha256,
        E'\n' ORDER BY sc.slug, sg.slug, sf.source_path, sf.content_sha256
    ), ''), 'UTF8')), 'hex')
    INTO canonical_manifest_sha256
    FROM source_file sf
    JOIN source_collection sc ON sc.id = sf.source_collection_id
    JOIN service_group sg ON sg.id = sf.service_group_id
    WHERE sf.is_present AND sc.slug = 'sse-cboms';

    SELECT count(*), count(*) FILTER (WHERE content_sha256 IS NULL)
    INTO sse_source_count, missing_hash_count
    FROM source_file sf
    JOIN source_collection sc ON sc.id = sf.source_collection_id
    WHERE sc.slug = 'sse-cboms' AND sf.is_present;

    SELECT count(*) INTO sse_group_count
    FROM service_group sg
    JOIN source_collection sc ON sc.id = sg.source_collection_id
    WHERE sc.slug = 'sse-cboms';

    SELECT count(*) INTO audit_actor_count
    FROM app_auth.app_user
    WHERE lower(email) = lower(current_setting('cbom.backfill_actor_email'))
      AND status = 'active';

    IF canonical_manifest_sha256 <> current_setting('cbom.expected_manifest_sha256')
       OR sse_source_count <> 534
       OR sse_group_count <> 40
       OR missing_hash_count <> 0
       OR audit_actor_count <> 1 THEN
        RAISE EXCEPTION
            'Refusing product attribution backfill: manifest/count/group/actor preflight failed (sha256 %, sources %, groups %, missing hashes %, actors %)',
            canonical_manifest_sha256, sse_source_count, sse_group_count, missing_hash_count, audit_actor_count;
    END IF;
END
$$;

INSERT INTO app_auth.audit_event (
    request_id, actor_user_id, action, resource_type, resource_key, after_state
)
SELECT
    'ops:product-scope-backfill:2026-09-26',
    actor.id,
    'evidence.product_scope.backfill',
    'evidence_product_scope_decision',
    'owner_instruction_2026-09-26_default_both',
    jsonb_build_object(
        'instruction_reference', 'owner_instruction_2026-09-26_default_both',
        'declared_on_behalf_of_email', current_setting('cbom.backfill_actor_email'),
        'database_session_user', session_user,
        'database_current_user', current_user,
        'canonical_manifest_sha256', current_setting('cbom.expected_manifest_sha256'),
        'source_collection', 'sse-cboms',
        'expected_current_sources', 534,
        'expected_registered_groups', 40,
        'product_scope_ids', ARRAY['secure-access-defense', 'secure-access-government']::text[]
    )
FROM app_auth.app_user actor
WHERE lower(actor.email) = lower(current_setting('cbom.backfill_actor_email'))
  AND actor.status = 'active'
  AND NOT EXISTS (
      SELECT 1 FROM app_auth.audit_event prior
      WHERE prior.action = 'evidence.product_scope.backfill'
        AND prior.resource_type = 'evidence_product_scope_decision'
        AND prior.resource_key = 'owner_instruction_2026-09-26_default_both'
  );

-- A previously committed uploader selection is intentional and is preserved.
-- Any other existing latest decision is malformed operational state and stops
-- this one-off before it can imply a default decision was accepted.
DO $$
DECLARE
    invalid_prior_count bigint;
BEGIN
    SELECT count(*) INTO invalid_prior_count
    FROM source_file sf
    JOIN source_collection sc ON sc.id = sf.source_collection_id
    JOIN LATERAL (
        SELECT eps.decision_basis, eps.decision_reference,
               eps.attributed_by_batch_id
        FROM app_auth.evidence_product_scope_decision eps
        WHERE eps.source_collection_id = sf.source_collection_id
          AND eps.service_group_id = sf.service_group_id
          AND eps.source_path = sf.source_path
          AND eps.source_sha256 = sf.content_sha256
        ORDER BY eps.attributed_at DESC, eps.id DESC
        LIMIT 1
    ) latest ON TRUE
    WHERE sc.slug = 'sse-cboms'
      AND sf.is_present
      AND sf.content_sha256 IS NOT NULL
      AND NOT (
          (latest.decision_basis = 'owner default both'
           AND latest.decision_reference = 'owner_instruction_2026-09-26_default_both'
           AND latest.attributed_by_batch_id IS NULL)
          OR (latest.decision_basis = 'uploader selection'
              AND latest.attributed_by_batch_id IS NOT NULL)
      );
    IF invalid_prior_count <> 0 THEN
        RAISE EXCEPTION
            'Refusing product attribution backfill: % current sources have an unrecognized latest routing decision',
            invalid_prior_count;
    END IF;
END
$$;

-- Insert only for a current exact source identity with no prior routing
-- decision.  Re-running this script is idempotent and cannot overwrite a
-- later uploader selection for the same collection/group/path/SHA-256.
INSERT INTO app_auth.evidence_product_scope_decision (
    source_collection_id, service_group_id, source_path, source_sha256,
    product_scope_ids, decision_basis, decision_reference
)
SELECT
    sf.source_collection_id,
    sf.service_group_id,
    sf.source_path,
    sf.content_sha256,
    ARRAY['secure-access-defense', 'secure-access-government']::text[],
    'owner default both',
    'owner_instruction_2026-09-26_default_both'
FROM source_file sf
JOIN source_collection sc ON sc.id = sf.source_collection_id
WHERE sc.slug = 'sse-cboms'
  AND sf.is_present
  AND sf.content_sha256 IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM app_auth.evidence_product_scope_decision prior
      WHERE prior.source_collection_id = sf.source_collection_id
        AND prior.service_group_id = sf.service_group_id
        AND prior.source_path = sf.source_path
        AND prior.source_sha256 = sf.content_sha256
  );

DO $$
DECLARE
    unmatched_count bigint;
    invalid_latest_count bigint;
BEGIN
    SELECT count(*) INTO unmatched_count
    FROM source_file sf
    JOIN source_collection sc ON sc.id = sf.source_collection_id
    WHERE sc.slug = 'sse-cboms'
      AND sf.is_present
      AND sf.content_sha256 IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM app_auth.evidence_product_scope_decision decision
          WHERE decision.source_collection_id = sf.source_collection_id
            AND decision.service_group_id = sf.service_group_id
            AND decision.source_path = sf.source_path
            AND decision.source_sha256 = sf.content_sha256
      );
    IF unmatched_count <> 0 THEN
        RAISE EXCEPTION 'Refusing partial product attribution backfill: % current sources remain unmatched', unmatched_count;
    END IF;
    SELECT count(*) INTO invalid_latest_count
    FROM source_file sf
    JOIN source_collection sc ON sc.id = sf.source_collection_id
    JOIN LATERAL (
        SELECT eps.product_scope_ids, eps.decision_basis, eps.decision_reference,
               eps.attributed_by_batch_id
        FROM app_auth.evidence_product_scope_decision eps
        WHERE eps.source_collection_id = sf.source_collection_id
          AND eps.service_group_id = sf.service_group_id
          AND eps.source_path = sf.source_path
          AND eps.source_sha256 = sf.content_sha256
        ORDER BY eps.attributed_at DESC, eps.id DESC
        LIMIT 1
    ) latest ON TRUE
    WHERE sc.slug = 'sse-cboms'
      AND sf.is_present
      AND sf.content_sha256 IS NOT NULL
      AND NOT (
          (latest.decision_basis = 'owner default both'
           AND latest.decision_reference = 'owner_instruction_2026-09-26_default_both'
           AND latest.product_scope_ids = ARRAY[
               'secure-access-defense', 'secure-access-government'
           ]::text[])
          OR (latest.decision_basis = 'uploader selection'
              AND latest.attributed_by_batch_id IS NOT NULL)
      );
    IF invalid_latest_count <> 0 THEN
        RAISE EXCEPTION
            'Refusing incomplete product attribution backfill: % current sources have an invalid latest decision',
            invalid_latest_count;
    END IF;
END
$$;

SELECT
    encode(sha256(convert_to(coalesce(string_agg(
        sc.slug || E'\x1f' || sg.slug || E'\x1f' || sf.source_path || E'\x1f' || sf.content_sha256,
        E'\n' ORDER BY sc.slug, sg.slug, sf.source_path, sf.content_sha256
    ), ''), 'UTF8')), 'hex') AS canonical_manifest_sha256,
    count(*) AS current_sse_sources,
    count(*) FILTER (
        WHERE decision.product_scope_ids = ARRAY[
            'secure-access-defense', 'secure-access-government'
        ]::text[]
    ) AS default_both_decisions,
    count(*) FILTER (WHERE decision.decision_basis = 'owner default both') AS owner_default_decisions
FROM source_file sf
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
JOIN LATERAL (
    SELECT eps.product_scope_ids, eps.decision_basis
    FROM app_auth.evidence_product_scope_decision eps
    WHERE eps.source_collection_id = sf.source_collection_id
      AND eps.service_group_id = sf.service_group_id
      AND eps.source_path = sf.source_path
      AND eps.source_sha256 = sf.content_sha256
    ORDER BY eps.attributed_at DESC, eps.id DESC
    LIMIT 1
) decision ON TRUE
WHERE sc.slug = 'sse-cboms' AND sf.is_present AND sf.content_sha256 IS NOT NULL;

COMMIT;
