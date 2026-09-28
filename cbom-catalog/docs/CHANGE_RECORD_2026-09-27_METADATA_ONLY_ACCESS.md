# Metadata-only OIDC service-profile release — 2026-09-27

## Deployment status

The metadata-only access stage is deployed through immutable image tag
`deploy-20260927-7` on ECS task revision 26. CloudFormation reached
`UPDATE_COMPLETE` at 2026-09-27T15:19:16.237Z; ECS reported one desired and one running task with a
completed rollout, and public `/healthz` returned HTTP 200. New web `EACCES`
and API `Traceback` log filters were empty.

Fresh Duo signed-browser verification for revision 25 is complete. It covered
the Reviews placeholder, corrected POA&M heading, role boundaries, and mobile
navigation described below.

`deploy-20260927-6` was an interim UI build and was not deployed. Tag 7 is the
deployed compliance-wording image and its signed Playwright checks are recorded
below.

The image includes a Next.js cache-permission correction. The web runtime must
not attempt to write its `.next` cache using a filesystem identity that lacks
permission. This corrects runtime behavior only; it does not change OIDC policy,
catalog data, source evidence, planning data, assessment data, or POA&M data.

## Intended access policy and capabilities

The deployment-owned OIDC policy is version `2026-09-27.2` and has 83 exact
group entries:

- `fedsse-admins`, `fedsse-external`, and `fedsse-scr2-leads`;
- 80 generated `fedsse-<service>-leads` and
  `fedsse-<service>-engineers` entries for 40 registered services.

The policy uses exact group matches. Service roles receive two product-grant
profiles, one for `secure-access-government` and one for
`secure-access-defense`. A person must choose a valid access mode before the
application releases product-profile metadata. An administrator may choose the
portfolio profile; a person with both a lead and engineer group may choose the
corresponding reduced profile without gaining a new service grant.

This release enables `enableOidcServiceGroups=true`. It keeps all of the
following false:

- `enableProductScopedDetailEvidence`
- `enableAccessRoster`
- `enableOperationalEvidenceNotes`

The resulting service workspace is metadata-only: it may show exact grant cards
and numeric portfolio Overview and POA&M summaries. It does not release
product-scoped evidence, product FIPS detail, candidate exports, roster
revoke/restore, or operational-note writes.

The deployed image presents Reviews as a grant-only placeholder for assigned
product roles. It lists the verified product grants together and states that
review proposals remain unavailable until exact product evidence and the
administrator approval workflow are enabled. The aggregate POA&M page heading
is corrected to **POA&M overview**; its aggregate-only access boundary is
unchanged.

The deployed roster remains read-only. Its current signed-session panel is
sourced from `/auth/me` for that session only; it does not match a row by email,
alter a historical row, or create a roster snapshot. Historical blanks say
**No recorded verified session**, meaning no persisted snapshot is available
rather than that the person lacks IdP access.

The image also contains the Admin users API fix for the prior 500 response. The
endpoint remains a read-only roster view while `enableAccessRoster=false`; its
revoke/restore capability remains disabled.

## Signed browser and API checks

Before the final cache-permission image rollout, a signed session for `kurs`
matched `fedsse-admins`, `fedsse-dlp-leads`, `fedsse-dlp-engineers`, and
`fedsse-scr2-leads`. No SaaS API group was present.

- Admin Inventory listed all 40 services.
- Explicit Product Lead and Product Engineer modes each returned exactly two
  DLP product grants. Engineer cards were read-only.
- Aggregate summary access returned 200.
- Missing or invalid mode selection returned 403.
- Product Admin, product detail, and product FIPS routes returned 403.
- The Admin users API returned 200 with two rows.

The following checks passed before the final rollout: 138 API unit tests, 7
console tests, 9 CDK tests, 8 migrated PostgreSQL tests plus 2 helper checks,
console lint, TypeScript typecheck, and production build.

After revision 24 took traffic, the signed browser still rendered the Product
Engineer grant workspace. A fresh read-only API check returned Admin users
HTTP 200 with two rows, Product Lead and Engineer grant registers HTTP 200 with
two DLP product grants each, summary POA&M HTTP 200, and Engineer Admin and
Lead product-detail requests HTTP 403. The nonroot final web image passed a
container write-permission check for `/app/.next/cache`. CloudWatch showed no
new `EACCES` web event or API `Traceback` during the final live checks.

A fresh Duo session against revision 25 matched exactly `fedsse-admins`,
`fedsse-dlp-leads`, `fedsse-dlp-engineers`, and `fedsse-scr2-leads`; no SaaS
API group was present. Admin Overview, Reviews, and the read-only Admin roster
rendered. Product Lead Reviews showed two DLP Government/Defense grant cards
with no picker or write controls. POA&M rendered **POA&M overview** as its H1
and the assigned section as its H2. Product Engineer cards were read-only; the
API register returned 200 while Admin and FIPS detail returned 403. Summary
access blocked direct `/reviews` navigation and exposed only Overview and
POA&M navigation. At 390 px, page width remained 390 px and the More navigation
remained reachable.

Signed Playwright verification against revision 26 confirmed the Admin roster
current-session panel and historical rows render with the stated boundary. It
also confirmed the corrected Admin ingestion copy, **aggregate portfolio
counts/summaries** wording in Overview, and **evidence observations requiring
review** wording for the Lead POA&M observation count of 594. Lead profile text
describes proposal approval without implying an approved assessment result.
The Lead register returned 200; Admin and FIPS detail remained 403. Normal
navigation produced no JavaScript errors.

The chief-architect and compliance-SME reviews accepted this **metadata-only**
stage after the signed checks. Their review does not authorize product evidence,
FIPS or FedRAMP conclusions, candidate exports, operational writes, roster
changes, or a SaaS API grant absent from the exact signed MyID claim.

The browser emitted only CSS-preload warnings in normal navigation; deliberate
403 negative tests produced expected browser network errors. No ingestion or
migration task ran during this image and policy deployment.

## Remaining gates

- Verify an intended SaaS API group in a fresh signed ALB claim.
- Verify every exact product-triple evidence, direct-ID, assessment, and export
  route before enabling detailed evidence.
- Obtain approved product authorization references and complete product
  contracts before exposing scoped FIPS detail or exports.
- Release roster revoke/restore and operational notes only after their
  separately gated, isolated operational tests pass.

No migration, ingestion, source change, planning change, assessment change,
or POA&M change is part of this release.
