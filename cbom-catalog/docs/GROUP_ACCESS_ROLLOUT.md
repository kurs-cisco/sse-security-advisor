# OIDC group access rollout

Status: **read-only, product-scoped catalog evidence is enabled; roster actions
and operational notes remain disabled**. FIPS detail, candidate output, and
exports remain closed by their separate product-contract gate. Exact group
authorization, aggregate endpoints, local admin mode, and deployment policy
are in the GovCloud development API and console. Policy version `2026-09-27.2`
contains 83 exact entries: three global groups and 80 generated service lead
and engineer groups. Migrations 016–021 remain applied and the operational
review tables remain empty. `enableOidcServiceGroups` is true;
`enableProductScopedDetailEvidence` and `enableAdminGroupMapping` are true;
`enableAccessRoster` and `enableOperationalEvidenceNotes` are false.

The deployed UI image `deploy-20260927-5` added the Reviews grant-only
placeholder for assigned product roles and corrected the aggregate page heading
to **POA&M overview**. Fresh Duo verification completed on that image.
`deploy-20260927-6` was an interim UI build and was not deployed.
`deploy-20260927-7` is deployed on ECS revision 26 and its signed Playwright
checks verified the read-only current-session roster panel and historical rows,
corrected ingestion copy, aggregate portfolio counts/summaries wording, and
evidence observations requiring review wording. Lead register access remained
200; Admin and FIPS detail remained 403; normal navigation produced no
JavaScript errors. These images do not change group policy, capability flags,
source corpus, planning data, assessment data, or POA&M data.

Image `deploy-20260927-10` supersedes image 9 and carries migration 021 and
the Administrator mapping registry. The mapping view displays
current-source-file and fingerprinted-source-file **catalog inventory** counts
for each exact mapping target. When the fingerprinted count is zero, it renders
an **Evidence gap** and says coverage is unknown; it never infers compliance,
validation, authorization, product evidence, FIPS evidence, or absence of risk
from those counts. Image 10 reached CloudFormation `UPDATE_COMPLETE`, completed
the ECS web task revision-29 rollout at 1/1, and returned HTTP 200 from
`/healthz`. A signed Admin Chrome/Playwright flow loaded the mapping API with
40 rows, 534 current files, and five zero-SHA/zero-file rows. The DOM contained
the inventory-only disclaimer, no retired “CBOM source evidence” label, and
five **Evidence gap** pills: Android, iOS, On Prem/Clients, RSM Secure Client,
and SWG Roaming Client. No source, planning, assessment, POA&M, or mapping data
changed in this deployment.

A fresh signed Duo session confirmed exactly `fedsse-admins`,
`fedsse-dlp-leads`, `fedsse-dlp-engineers`, and `fedsse-scr2-leads`; no SaaS
API group was present. The signed Product Lead mode showed **Admin access
required** and its direct mapping API call returned 403. Accountability showed
only DLP Government and Defense grant cards with evidence detail pending.
Admin Inventory listed all 40 services. Explicit Product Lead and Product
Engineer modes returned only the two DLP product-grant cards, with Engineer
cards read-only. Aggregate summary access succeeded. Missing or invalid mode
selection, product Admin, and FIPS detail failed closed. Product detail was
subsequently activated in image 11; see
[CHANGE_RECORD_2026-09-27_PRODUCT_DETAIL_ACTIVATION.md](CHANGE_RECORD_2026-09-27_PRODUCT_DETAIL_ACTIVATION.md).
The
Admin users API returned 200 with two rows.

Image 13 completed ECS revision 31 after a signed Product Lead clean-tab check
of both DLP product contexts. The POA&M and Reviews pages showed verification
pending without gated FIPS/review background requests or export actions. The
exact DLP product document endpoint returned 7 records for both Lead and
Engineer; unassigned, direct-ID, FIPS, review-proposal-without-reference, and
Engineer-to-Admin requests failed closed. The test identity has no SaaS grant,
and no disjoint second identity is available for a live cross-user check.

Approved notes remain separate from assessment and POA&M results. The 40 exact collection/service-group pairs
are registered in `infra/lib/oidc-service-groups.ts`, including five retained
zero-evidence scopes. The owner declares this portfolio intended to support
two product contexts: Secure Access for Government in Cisco Security for
Government — FedRAMP High baseline context, and Secure Access for Defense in
Cisco Security for Defense — DoD Impact Level 5 (IL5) context. These are
display labels with stable policy IDs, not
immutable package IDs or proof of authorization. The owner-directed,
checksum-bound default-both routing for all 534 current source files is now
recorded in `app_auth`, separately from authored evidence. New uploads default
to both; the uploader may select one or both. Cloud access to verified grant
metadata and read-only, exact-triple catalog detail are active. Operational
writes remain disabled. Migrations 016–020 and the one-off
routing backfill are verified live without source or planning changes; see the
[routing change record](CHANGE_RECORD_2026-09-26_DUAL_PRODUCT_ROUTING.md),
[migration 016 change record](CHANGE_RECORD_2026-09-25_MIGRATION_016.md), and
[operational-access schema change record](CHANGE_RECORD_2026-09-26_OPERATIONAL_ACCESS_SCHEMA.md).

## Approved policy shape

| Exact verified group | Portfolio Overview and POA&M | Service detail | Write |
| --- | --- | --- | --- |
| `fedsse-admins` | Full | All configured services and Admin | Administrative actions |
| `fedsse-<registered-key>-leads` | Numeric aggregates | Read-only catalog detail when the exact collection, service group, product context, and current-file routing all match; Reviews remains grant-only | Proposed operational writes require a later gate and another admin's decision; no authored-data edit |
| `fedsse-<registered-key>-engineers` | Numeric aggregates | Read-only catalog detail when the exact collection, service group, product context, and current-file routing all match; Reviews remains grant-only | None |
| `fedsse-external` | Numeric aggregates only | None | None |
| `fedsse-scr2-leads` | Numeric aggregates only | None until separately mapped | None until separately mapped |

No recognized group means no catalog access. The same exact service group covers
Government (`FedRAMP High/IL2`) and Defense (`IL5`), as the owner directed.
Memberships combine per service;
lead access to one service never grants writes to another. The `scr2-leads`
name is an explicit summary exception, not a wildcard service-lead match. No
canonical `SCR2` service group exists in the current catalog snapshot.

The deployment-owned `oidcGroupScope` policy is passed to FastAPI as
`CBOM_OIDC_GROUP_SCOPE_JSON`. A service group entry requires exact
`source_collection`, `service_group`, `product_scope_id`, and `boundary_name`
strings. It also
requires a canonical `service_key` that exactly matches the stem of its
`fedsse-<service_key>-leads` or `fedsse-<service_key>-engineers` group name;
the key labels the MyID group while the explicit triples select catalog data.
Placeholder boundary values fail synthesis. The CDK design generates 80 exact
service-group names, each with two product grants. Assigned detail is enabled
only after the exact pair, product scope, and current-file routing predicate
all match. The deployed policy contains the three global groups and the
generated service groups; its 83 entries are exact matches, never prefixes.
The OIDC client requests `openid email groups`. The exact administrator,
DLP-lead, and SCR2-summary names were observed in direct MyID UserInfo; the
standard `groups` claim is the product authorization input. The optional
`memberships` scope was used only for diagnosis and is not requested by the
deployed ALB.
The [service-group map](OIDC_SERVICE_GROUP_MAPPING_DRAFT.md) lists the
registered MyID stems and exact API keys. A user receives only entries present
in their verified claim; the 83-entry policy does not grant all 40 services to
every user.

## Admin access roster and local mode

Cloud human permissions come only from verified OIDC groups. The legacy
`app_auth.app_user.role` column remains in historical records but does not
authorize cloud access; the manual role/status PATCH returns HTTP 410. Migration
019 provides append-only verified-role snapshots and revoke/restore decisions.
The staged roster and mutation endpoints are still disabled by capability
defaults, so the Admin users table must remain read-only until the release gates
pass. Once enabled, a revoke requires a reason, rejects self-revocation,
protects the last active administrator, permanently revokes owned API
credentials, and records an audit event. A different administrator may restore
the local deny state, but restoration never revives a credential. A snapshot is
only a prior verified sign-in; it is not a live MyID directory or a record of
people who have never signed in.

Local Docker and localhost development use explicit `local-admin` mode. Both
web and API ports bind to loopback. The browser login has one local admin
identity, and cloud ECS tasks remain `alb-oidc` plus bearer-only API. No local
login or legacy database-admin fallback is allowed in cloud.

## Operational review and observation records

Migrations 016, 018, and 020 keep operational review material in append-only
`app_auth` tables. Migration 018 requires an exact product scope and immutable
authorization reference for the strict proposal workflow. Migration 020 stores
product-scoped finding-evidence observations and a separate-administrator
decision without creating, changing, or approving an assessment candidate,
POA&M, planning record, source file, or `admin_overlay` entry. This permits a
lead to submit a bounded evidence observation for their granted service and an
independent administrator to accept or reject that operational record.

All of those tables are empty in the verified development database. The
observation and strict-proposal endpoints remain capability-disabled until the
final application and role tests complete. `can_edit` remains administrator-only
for existing edit endpoints.

## Remaining gates before operational writes or gated assessment outputs

Migration 021 stores append-only policy revisions and an active pointer in
`app_auth`; the deployed registry remains the seed until a signed human
administrator publishes the first change. The editor changes the application's exact group
mapping, not MyID memberships, source records, product attribution, assessment
facts, or authorization status. Each publish must use a catalog-registered
collection/service, one or both configured product contexts, an expected
revision, a reason, and a transactionally recorded actor/request/before/after
audit event. Protect `fedsse-admins` and both summary groups from edits.
Before publishing an operational policy change, verify add, remap, retire,
stale-revision denial, duplicate-target denial, unknown group/product denial,
and an immediate next-request scope change with two disjoint signed principals.
The Admin UI must report current and fingerprinted source-file **catalog
inventory** counts for every mapping target. A zero fingerprinted count must
show **Evidence gap** with coverage unknown, never a favorable compliance,
product-evidence, or FIPS conclusion. A disposable PostgreSQL count test passed
for invalid, empty, historical, and separate-collection inputs. No registry
revision was published as part of the image 9 deployment.

1. Verify the MyID claim for an intended SaaS API service group in a fresh signed
   ALB session. The available test identity did not contain such a group.
2. Enforce and verify the product triple across every evidence, direct-ID,
   assessment, export, and review query. Keep API credentials on their own
   explicit scope path; never inherit OIDC groups.
3. Exercise the applied roster, revoke/restore, strict proposal, and evidence
   observation schemas through isolated test data. Verify request ID, actor,
   reason, before/after audit, last-admin protection, permanent token
   revocation, stale-item rejection, and different-administrator decisions.
4. Run API tests, console lint/typecheck/build, CDK tests and diff, then
   Chrome/Playwright role flows. Check direct IDs, exports, unknown/malformed
   groups, mixed memberships, revocation/restore, and local/cloud separation.
5. Obtain separately approved product authorization references and a complete
   product contract before releasing scoped FIPS detail, candidate outputs, or
   exports. Do not run source ingestion or modify planning or assessment data
   as part of these access releases.

The source corpus, normalized evidence, hashes, user-authored planning, and
assessment inputs remain unchanged throughout this access rollout.
