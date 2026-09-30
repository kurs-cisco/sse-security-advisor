# Dual product authorization scope plan

Status: **read-only, checksum-attributed product detail and Service Catalog
management are deployed**. Access-roster actions, operational evidence notes,
and separate evidence-review proposals remain closed. Existing-file routing and
the related operational schema are applied in the development deployment.
`enableOidcServiceGroups`, `enableAdminGroupMapping`, and
`enableProductScopedDetailEvidence` are true; `enableServiceCatalog` is true;
`enableAccessRoster`, `enableLeadReviewProposals`, and
`enableOperationalEvidenceNotes` remain false. Product detail is catalog
evidence only: FIPS detail, candidate output, and exports remain independently
denied until their product contract gates are complete.
See [GROUP_ACCESS_ROLLOUT.md](GROUP_ACCESS_ROLLOUT.md) for the verified-group
policy and operational write gates.

## Named contexts and current evidence

The owner declares that the 40 `sse-cboms` service groups support both product
contexts. Current files have checksum-bound routing decisions:

| Configured product-scope ID | Product | Owner-declared boundary name |
| --- | --- | --- |
| `secure-access-government` | Secure Access for Government | `FedRAMP High/IL2` |
| `secure-access-defense` | Secure Access for Defense | `IL5` |

One existing exact service MyID group covers both products. The names are scope
labels, not authorization package references or proof of compliance. The owner directed
that **existing and new files default to both products**, while an authorized
uploader may choose one or both for a new batch. Routing decisions are
append-only and bound to the exact collection, group, path, and current source
SHA-256. This operational attribution is separate from source and authored
data. Product detail is enabled only for read-only, exact-triple requests. A
service with no source files must say "No source evidence observed" without
implying compliance or no risk.

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
   triple-aware filtering is verified. Keep FIPS detail, candidate output, and
   exports disabled until their independent contract and role tests are complete.
   The audited Admin registry prevents later deployments from overwriting an
   Admin-published mapping.
5. Service Catalog leads may submit exact-scope metadata proposals for a
   different human Administrator's decision. This workflow is separate from
   evidence observations and strict assessment-review proposals. Those separate
   workflows, and the access roster, remain disabled until their tests and
   role/view checks pass.
6. Verify disjoint roles and product scopes in API tests, CDK synthesis, and
   Chrome/Playwright: direct IDs, exports, empty states, mixed memberships,
   cross-product denial, candidate-contract gates, and no source/planning
   delta. Review a change set before deploying the API and console. The
   existing ingestion deployment script is not an access-only release path.

## Remaining input for gated assessment output

- The authorization/package references needed for assessment conclusions.
  The supplied boundary names are sufficient for routing labels, not for
  confirming authorization or FIPS/POA&M eligibility.
