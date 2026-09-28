# Administrator group-mapping deployment — 2026-09-27

## Scope

Image `deploy-20260927-10` supersedes image 9 and carries the
Administrator-maintained exact OIDC group-to-service mapping registry. It
includes migration 021, the Admin mapping editor, and a read-only catalog
inventory summary for each registered target. The registry controls application
access mappings only. It does not
modify MyID memberships, source files, routing decisions, planning records,
assessment records, POA&M records, or authorization conclusions.

The deployment policy contains 83 exact groups: protected global Admin and
summary groups plus paired Lead and Engineer groups for 40 registered services.
Each service mapping uses exact `(source_collection, service_group,
product_scope_id)` triples. The product IDs are
`secure-access-government` and `secure-access-defense`; their display labels
route application access and are not ATO, CMVP, or FIPS evidence.

## Deployment evidence

| Item | Recorded result |
| --- | --- |
| Image 10 catalog image (unchanged) | `sha256:1310afd268a65adb738841734fe911231c8d94578eccc2e75ee9f21acdc91e97` |
| Image 9 web image (superseded) | `sha256:72f4fbc4b8fa9104e988d73f3ce200342e9afde94cf6f00049dabb6c74496ea5` |
| Image 10 web image | `sha256:8125c552c310e63e126b24af43a7558f6e4d32b718376e0710b470924ae08b3a` |
| Image 9 CloudFormation | `UPDATE_COMPLETE` |
| Image 9 ECS web rollout | task definition revision 28 completed |
| Image 9 health check | `/healthz` returned HTTP 200 |
| Image 10 CloudFormation | `UPDATE_COMPLETE` |
| Image 10 ECS web rollout | task definition revision 29 completed at 1/1 |
| Image 10 health check | `/healthz` returned HTTP 200 |
| Image 10 signed browser check | Completed; details recorded below |

## Implemented controls

- Migration 021 stores append-only mapping revisions and an active revision
  pointer. After the first human Administrator publish, a missing, corrupt, or
  ambiguous active revision fails closed.
- A signed human `fedsse-admins` session may publish a mapping revision only
  with a registered target, configured product scope, change reason, and the
  current compare-and-swap revision token. Protected global groups cannot be
  edited. API credentials cannot read or publish registry mappings.
- Each publish records the signed actor, request ID, before/after mapping, and
  policy content hash in the audit trail.
- The Admin mapping view shows current-source-file and fingerprinted-source-file
  **catalog inventory** counts per target. A zero fingerprinted count renders
  **Evidence gap** and states that coverage is unknown. These counts do not
  expose detailed source evidence and do not establish compliance, validation,
  authorization, product evidence, FIPS evidence, or risk status.

## Verification status

Focused authorization and mapping tests completed before deployment: 44 OIDC
policy/registry tests and 33 scoped-query, roster, observation, review, and
FIPS-contract tests. A disposable PostgreSQL count test passed for invalid,
empty, historical, and separate-collection inputs. The full API suite passed
151 tests; console lint, nonincremental typecheck, and production build passed;
the CDK suite passed 10 tests, build and strict synthesis passed. Two final
integration tests passed in a disposable PostgreSQL database migrated through
021. The policy lifecycle test exercised add, stale-revision denial, remap,
retire, immediate next-request grant changes, revision chaining, and audit
records. Its connection guard requires loopback and a `cbom_test_*` database.
The disposable container was removed after verification.

A fresh signed Duo claim session confirmed exactly `fedsse-admins`,
`fedsse-dlp-leads`, `fedsse-dlp-engineers`, and `fedsse-scr2-leads`; no SaaS
API group was present. The signed image-10 Admin Chrome/Playwright flow loaded
the mapping API with the proper active-mode header and received HTTP 200 with
40 rows: 534 current files and five zero-SHA/zero-file rows. Its DOM showed the
inventory-only disclaimer, no retired “CBOM source evidence” label, and five
**Evidence gap** pills for Android, iOS, On Prem/Clients, RSM Secure Client,
and SWG Roaming Client. An initial direct API fetch without an active-mode
header correctly returned 403. Product Lead mode showed **Admin access
required**, its direct mapping API request returned 403, and Accountability
showed only DLP Government and Defense grant cards with evidence detail pending.
No live mapping write was performed. Follow
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for the complete browser and role
matrix.

## Limitations and next gates

Detailed product evidence, access-roster actions, operational evidence notes,
strict proposals, FIPS detail, candidate exports, and reportable 20x output
remain disabled. A mapping with no observed files or fingerprints is a coverage
gap with unknown status; it is not product evidence or FIPS evidence and does
not establish compliance or noncompliance. No mapping policy revision was
published during either image 9 or image 10 deployment.

Before enabling detailed evidence or operational writes, validate disjoint live
MyID identities, exact product-triple enforcement on every direct route and
export, and revoke/restore with two distinct administrator identities. The
mapping publish lifecycle has passed isolated PostgreSQL testing; a live
Admin publish remains untested to avoid changing the authoritative access
policy. The deployment does not authorize source ingestion, changes to
planning or assessment data, or an ATO decision.

See [GROUP_ACCESS_ROLLOUT.md](GROUP_ACCESS_ROLLOUT.md) and
[INTERNAL_ROLLOUT_PLAN.md](INTERNAL_ROLLOUT_PLAN.md) for the controlled rollout
state.
