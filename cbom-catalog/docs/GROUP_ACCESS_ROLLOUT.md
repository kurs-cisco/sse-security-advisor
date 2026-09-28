# OIDC group access rollout

Status: **read-only, product-scoped catalog evidence is enabled; roster actions
and operational notes remain disabled**. FIPS detail, candidate output, and
exports remain closed by their separate product-contract gate. The synthesized
baseline policy version `2026-09-27.2` contains 83 exact entries: three global
groups and 80 generated service Lead and Engineer groups. A signed Admin
mapping revision supersedes that baseline; a missing, corrupt, or ambiguous
active revision fails closed. `enableOidcServiceGroups`,
`enableProductScopedDetailEvidence`, and `enableAdminGroupMapping` are enabled;
`enableAccessRoster` and `enableOperationalEvidenceNotes` are disabled.

The 40 collection/service-group pairs are registered in
`infra/lib/oidc-service-groups.ts`, including five retained zero-evidence
scopes. Each exact service group has Government and Defense access contexts.
Those labels route application access; they do not establish an authorization,
CMVP validation, FIPS conclusion, or compliance result. Current-file routing is
checksum-bound and separate from authored evidence. A new upload defaults to
both contexts unless its authorized uploader selects otherwise.

The Admin mapping view reports current and fingerprinted **catalog inventory**
counts. A zero fingerprinted count is an **Evidence gap** with unknown coverage;
it does not establish compliance, validation, authorization, product evidence,
FIPS evidence, or absence of risk. Operational notes remain separate from
assessment and POA&M results.

For dated migration, deployment, and browser-verification evidence, use the
[migration 016 record](CHANGE_RECORD_2026-09-25_MIGRATION_016.md),
[routing record](CHANGE_RECORD_2026-09-26_DUAL_PRODUCT_ROUTING.md),
[operational-access schema record](CHANGE_RECORD_2026-09-26_OPERATIONAL_ACCESS_SCHEMA.md),
[mapping deployment record](CHANGE_RECORD_2026-09-27_ADMIN_GROUP_MAPPING.md),
and [product-detail activation record](CHANGE_RECORD_2026-09-27_PRODUCT_DETAIL_ACTIVATION.md).

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
The [service-group map](OIDC_SERVICE_GROUP_MAPPING.md) lists the
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
