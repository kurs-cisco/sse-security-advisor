# Dual product authorization scope plan

Status: **read-only, checksum-attributed product detail is deployed; operational
writes remain closed**. Migrations 016–021 and the audited existing-file
routing backfill are applied and verified in the GovCloud development database.
`enableOidcServiceGroups`, `enableAdminGroupMapping`, and
`enableProductScopedDetailEvidence` are true; `enableAccessRoster` and
`enableOperationalEvidenceNotes` remain false. Product detail is catalog
evidence only: FIPS detail, candidate output, exports, and approval workflows
remain independently denied until their product contract gates are complete.
See [GROUP_ACCESS_ROLLOUT.md](GROUP_ACCESS_ROLLOUT.md) and the [routing change record](CHANGE_RECORD_2026-09-26_DUAL_PRODUCT_ROUTING.md),
[migration 016 change record](CHANGE_RECORD_2026-09-25_MIGRATION_016.md), and
[operational-access schema change record](CHANGE_RECORD_2026-09-26_OPERATIONAL_ACCESS_SCHEMA.md).

## Named contexts and current evidence

The owner declares that the 40 `sse-cboms` service groups support both product
contexts. Current files have checksum-bound routing decisions:

| Configured product-scope ID | Product | Owner-declared boundary name |
| --- | --- | --- |
| `secure-access-government` | Secure Access for Government | `FedRAMP High/IL2` |
| `secure-access-defense` | Secure Access for Defense | `IL5` |

The owner supplied these boundary names and directed that one existing exact
service MyID group covers both products. The names are scope labels, not
authorization package references or proof of compliance. The owner directed
that **existing and new files default to both products**, while an authorized
uploader may choose one or both for a new batch. The 534 current source files
now have append-only routing decisions bound to exact collection, group, path,
and current source SHA-256. This operational attribution is separate from
source/authored data; see the
[change record](CHANGE_RECORD_2026-09-26_DUAL_PRODUCT_ROUTING.md). Product
detail is enabled for read-only, exact-triple requests after staged and
migrated-database query verification. Five retained services with no source files should say
"No source evidence observed" without implying compliance or no risk.

## Implementation sequence

1. Define an exact product-scope registry and use the three-part key
   `(source_collection, service_group, product_scope_id)` in OIDC grants, API
   selection, UI state, cache keys, review proposals, and audit context. Reject
   duplicate or unknown triples. Keep aggregate Overview and POA&M numeric
   summaries independent of a product selection.
2. Add a deployment-owned attribution manifest keyed by exact collection,
   service group, path, and current source/document SHA-256. After a baseline
   check, create an idempotent, audited **both-product** mapping for existing
   present files under the owner's explicit decision. New upload manifests
   carry the uploader's one-or-both choice, default both, in their checksum;
   only a successful committed ingestion records attribution. Dry runs do not.
   Changed file checksums cannot inherit stale attribution. Do not rewrite the
   source corpus or user-authored planning data.
3. Enforce attribution in database queries for every document, component,
   dependency, artifact, issue, assessment, direct-ID route, and export. A
   selected scope with no attributed evidence returns the placeholder/empty
   shape; it never falls back to pair-only data. Keep admin's existing
   unpartitioned evidence view clearly labeled as unassigned inventory.
4. Generate two exact product grants inside each existing
   `fedsse-<service>-leads` or `-engineers` MyID group entry, as the owner
   directed. These grants expose checksum-attributed catalog evidence only after
   triple-aware filtering is verified. Keep FIPS detail, candidate output,
   exports, and operational writes disabled until their independent contract
   and role tests are complete. Migration 021 adds an audited Admin
   registry so later deployments cannot overwrite an Admin-published mapping.
5. Keep leads' write action limited to a scoped evidence observation and
   rationale submitted for a different human administrator's decision. Migration
   020 stores that append-only workflow; a decision does not change an
   assessment or POA&M. Migrations 016 and 018 retain the stricter
   authorization-referenced proposal path. Migration 019 provides the
   append-only access roster and revoke/restore schema; all application
   capabilities stay disabled until their tests and role/view checks pass.
6. Verify disjoint roles and product scopes in API tests, CDK synthesis, and
   Chrome/Playwright: direct IDs, exports, empty states, mixed memberships,
   cross-product denial, candidate-contract gates, and no source/planning
   delta. Review a change set before deploying the API and console. The
   existing ingestion deployment script is not an access-only release path.

## Owner inputs for activation

- The exact MyID group strings observed in a signed claim after the `fedsse-`
  filter change.
- The authorization/package references needed for assessment conclusions.
  The supplied boundary names are sufficient for routing labels, not for
  confirming authorization or FIPS/POA&M eligibility.
