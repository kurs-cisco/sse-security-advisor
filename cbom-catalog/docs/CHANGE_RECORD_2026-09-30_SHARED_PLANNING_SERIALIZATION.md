# Shared Planning response serialization — 2026-09-30

## Incident and cause

The signed Summary viewer showed `Shared planning is unavailable` with HTTP 500. Cloud API logs traced this to `/api/v1/portfolio/poam-planning`: current managed Service Catalog target dates arrived from PostgreSQL as Python `date` objects, and this one route passed its projection directly to `JSONResponse`. The earlier Risk Assessment draft route had the same defect and was corrected separately. Imported-only local planning rows supplied strings, so the previous local check did not reproduce the cloud failure.

## Change

- Encode the complete read-only Shared Planning projection with FastAPI `jsonable_encoder` before `JSONResponse`. The existing summary authorization, projected fields, no-store header, and underlying planning data remain unchanged.
- Exercise both managed IL2 and IL5 `date` objects in the API regression test and assert ISO date strings in the response.
- Add a release gate for a signed Summary viewer against current managed cloud Catalog rows. A local imported-only check is not sufficient.
- Keep the Admin Planning count pending until both the Service Catalog and document register finish loading. The early 39 count came from tracker profiles before the 40th current Catalog group arrived; the final view included all 40.

## Verification

- The full API suite passed 180 tests. Console lint, typecheck, 12 tests, and production build passed. Infrastructure tests (12), build, CDK synth, and an image-tag-only diff passed.
- Local API returned HTTP 200, 40 catalog groups, 38 Team milestone rows, and string dates after the API container update.
- Cloud release `deploy-20260930-06` used ECS web task revision 68. A signed Summary viewer returned Planning 40 and Team milestones 38; both views and aggregate Overview loaded. Cloud API logs recorded HTTP 200 for `/api/v1/portfolio/poam-planning` after rollout. Admin Planning first displayed a transient count of 39, then the complete count of 40.
- A six-hour API-log scan found 500s only on Shared Planning and the previously fixed Risk Assessment draft route. The other direct `JSONResponse` sites contain static error detail or use `jsonable_encoder`; conditional responses also encode data. No source, Service Catalog, assessment, or other app-authored records were changed.
- Follow-up release `deploy-20260930-07` updated the console and retagged the identical catalog image. CDK diff contained only image tags; ECR configuration and layer digests for catalog releases 06 and 07 matched. Local console health returned HTTP 200. CloudFormation completed, ECS web task revision 69 was the sole running PRIMARY task with rollout `COMPLETED`, and the signed Summary Planning request returned HTTP 200.
- Live browser verification showed Summary Planning 40 and Team milestones 38; both views opened without a 500 banner. After returning to Admin, Planning displayed `—` during Catalog/register loading and then 40. API logs after 19:40 UTC had no `Internal Server Error`; the observed shared-planning requests returned 200.
