# UI and access hardening — 2026-09-28

## Change

Image `deploy-20260928-1` removes the unused Admin assessment-governance panel and its background assessment/20x preview requests. The console shortens redundant explanatory copy, gives mapping and inventory buttons specific accessible names, improves empty states and table controls, validates token expiry input, and shows Lead review controls only when the API explicitly grants the capability. Follow-up image `deploy-20260928-2` stops Admin Reviews from requesting a disabled review queue and removes stale Lead write wording.

The API now requires `CBOM_LEAD_REVIEW_PROPOSALS_ENABLED` before any Lead proposal or Admin review-queue route can be used. The development stack sets this flag to `false`. Disabled review and operational-note routes deny before database access. The release changes no corpus, authored assessment, planning, POA&M, product-routing, or MyID record.

## Verification

| Check | Result |
| --- | --- |
| API suite | 153 tests passed |
| Console | Lint, TypeScript, production build, and 7 tests passed |
| Infrastructure | 10 tests and TypeScript build passed |
| CDK diff | Web and job task image references; web task also receives the disabled review flag |
| Deployment | CloudFormation `UPDATE_COMPLETE`; follow-up ECS web revision 33 stable at 1/1; `/healthz` 200 |
| Signed Admin browser | Requested panel absent; fresh Admin load made no assessment or 20x preview call; mapping actions have service-specific names; no page console errors before deliberate denial probes |
| Signed Admin API | `/auth/me` reports review and note capabilities `false`; review queue GET returns 403 |
| Signed Reviews browser after follow-up | Disabled state rendered; no review or note API request; zero console errors |

## Remaining release gates

- The available signed test identity has overlapping Admin and DLP grants. Cross-user isolation needs two separate identities with disjoint service grants; SaaS API group rendering remains unverified live.
- Roster revoke/restore and Lead operational writes remain disabled pending isolated workflow and audit verification. Do not infer write readiness from the Lead group alone.
- Product FIPS candidates, POA&M exports, and 20x output remain gated by the product assessment contract. Catalog routing labels do not establish ATO, CMVP, FIPS, or FedRAMP conclusions.
