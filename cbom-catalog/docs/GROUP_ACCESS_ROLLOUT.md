# OIDC group access rollout

Status: **product-scoped catalog evidence and Service Catalog management are
enabled; access-roster actions, operational evidence notes, and separate
evidence-review proposals remain disabled**. FIPS detail, candidate output, and
exports remain closed by their separate product-contract gate. The synthesized
baseline policy version `2026-09-27.2` contains 83 exact entries: three global
groups and 80 generated service Lead and Engineer groups. A signed Admin
mapping revision supersedes that baseline; a missing, corrupt, or ambiguous
active revision fails closed. `enableOidcServiceGroups`,
`enableProductScopedDetailEvidence`, `enableAdminGroupMapping`, and
`enableServiceCatalog` are enabled; `enableAccessRoster`,
`enableLeadReviewProposals`, and `enableOperationalEvidenceNotes` are disabled.

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

## Approved policy shape

| Exact verified group | Portfolio Overview and POA&M | Service detail | Write |
| --- | --- | --- | --- |
| `fedsse-admins` | Full | All configured services and Admin | Create or publish Service Catalog metadata; decide Service Catalog proposals. Access-roster, operational evidence, and separate evidence-review actions are disabled. |
| `fedsse-<registered-key>-leads` | Aggregates and read-only Planning/Team milestones | Read-only catalog detail when the exact collection, service group, product context, and current-file routing all match; Reviews remains grant-only | Submit an exact-scope Service Catalog metadata proposal for a different Administrator's decision. Separate operational evidence-review proposals are disabled. |
| `fedsse-<registered-key>-engineers` | Aggregates and read-only Planning/Team milestones | Read-only catalog detail when the exact collection, service group, product context, and current-file routing all match; Reviews remains grant-only | None |
| `fedsse-external` | Aggregates and read-only Planning/Team milestones | None | None |
| `fedsse-scr2-leads` | Aggregates and read-only Planning/Team milestones | None until separately mapped | None until separately mapped |

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

## OIDC claim contract

The cloud ALB requests `openid email groups`. The Next.js server verifies the
ALB-signed identity and FastAPI authorizes only the verified `groups` array.
The parser accepts a valid bounded claim, ignores unrelated groups, and rejects
malformed `fedsse-` values. It never normalizes group names. `fedsse-admins`
takes precedence over Summary and service roles when a verified claim contains
more than one recognized group.

Use the MyID `groups` claim with a `fedsse-` selector or exact allowlist. The
custom `memberships` claim is not an application authorization input and should
not be requested through the ALB. A persisted roster record or an email address
does not grant cloud access.

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

## Service Catalog control plane

The Service Catalog is a separate control plane from source evidence and group
policy. An Administrator may create or publish managed service metadata. A
Product Lead may propose a change only for an exact granted service group and
its required product context; a different Administrator approves or rejects the
proposal with a reason. Product Engineers are read-only, and Summary users
cannot enumerate the catalog. Profile links for an owner or lead are optional
metadata and never create access grants.

Managed changes use optimistic revisions, append-only snapshots, and audit
events. They may override imported operational fields after approval, including
an intentional clear, while source identities, routing, checksums, planning
imports, and assessment evidence remain immutable.

## Separate operational review and observation records

Migrations 016, 018, and 020 keep operational review material in append-only
`app_auth` tables. Migration 018 requires an exact product scope and immutable
authorization reference for the strict proposal workflow. Migration 020 stores
product-scoped finding-evidence observations and a separate-administrator
decision without creating, changing, or approving an assessment candidate,
POA&M, planning record, source file, or `admin_overlay` entry. This permits a
lead to submit a bounded evidence observation for their granted service and an
independent administrator to accept or reject that operational record.

These evidence-observation and strict-proposal endpoints remain
capability-disabled. They are separate from the enabled Service Catalog
metadata workflow and do not alter its approval model.

## Remaining gates for separate operational writes and assessment outputs

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
