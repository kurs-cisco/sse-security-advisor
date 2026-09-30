# OIDC scope and workspace release — 2026-09-29

## Released behavior

- Cloud browser authorization uses signed, exact `fedsse-` group matches. The
  bounded parser accepts a larger valid signed group claim, ignores unrelated
  groups, and rejects malformed `fedsse-` entitlements. A historic seeded
  roster row does not grant current cloud access.
- `/auth/me` reports distinct service groups separately from product-context
  grants. The profile and Admin Users view distinguish active verified modes
  from historical session observations. Admin, Product Lead, Product Engineer,
  and Summary remain independently selectable only when present in verified
  claims.
- Summary Overview and POA&M contain aggregate data without detailed
  identifiers. Admin and assigned workspaces load detailed Overview charts
  only for the current mode and exact grants. The POA&M aggregate now reports
  605 noneligible evidence observations, matching the detailed register; 594
  is the review-only finding subset.
- Migration 025 records a verified Admin entitlement separately from the
  selected workspace role for the access-roster last-admin safeguard. It
  changes `app_auth` metadata and migration bookkeeping only.

## Deployment and verification

- Local Compose project `cbom-catalog-final`: API, web, and PostgreSQL healthy;
  localhost one-click Admin and Overview/POA&M browser flows passed.
- GovCloud stack `cbom-workbench-dev`: CloudFormation `UPDATE_COMPLETE`, ECS
  service `cbom-workbench-web` rollout `COMPLETED` with one healthy task on
  revision 54. API and web images use `deploy-20260929-4`. Cloud `/healthz`
  returned 200.
- A mixed-role signed cloud test identity exposed four verified modes. Admin
  loaded detailed Overview charts; Engineer loaded only its DLP and SaaS API
  detail read-only; Summary denied direct Service Catalog navigation and showed
  aggregate POA&M data. A separate signed Admin profile also exposed Admin.
- Admin Service mappings loaded the active deployment baseline with all 40
  services mapped to exact Lead and Engineer groups in both product contexts.
  Admin Users loaded recorded identities without an API error.
- Automated checks passed: 176 API unit tests, 7 console tests, 12
  infrastructure tests, console lint/typecheck/build, infrastructure build and
  strict synth, and `git diff --check`. Disposable PostgreSQL integration tests
  for the roster and access middleware passed earlier in this release sequence.
- Read-only local row counts after deployment match the recorded pre-release
  counts: 40 service groups, 593 documents, 608 source files, and 60,552
  components. No authored catalog, evidence, assessment, planning, or POA&M
  records were changed.

## Operational gate

`CBOM_ACCESS_ROSTER_ENABLED` remains `false` in the deployed API. The roster
schema and code are staged, but live revoke/restore requires a separate,
explicit activation approval. No live user was revoked or restored. Before
service-team rollout, test disjoint service identities; a single mixed-role
test identity cannot prove cross-user isolation. `fedsse-scr2-leads`
remains a summary-only exception under the approved policy.
