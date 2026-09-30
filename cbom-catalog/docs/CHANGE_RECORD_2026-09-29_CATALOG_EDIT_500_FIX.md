# Service Catalog edit 500 fix — 2026-09-29

## Failure

Cloud API logs for `PUT /api/v1/admin/service-catalog/sse-cboms/adc` show that
the request reached FastAPI and failed while inserting the append-only Service
Catalog revision snapshot. PostgreSQL returned Python `date` and `datetime`
values in that snapshot; passing them directly to Psycopg `Jsonb` raised
`TypeError: Object of type datetime is not JSON serializable`. The same shared
writer is used for Admin create, Admin update, and approved lead proposals.
The failed requests raised before commit, so their transactions rolled back.

## Correction and verification

The revision writer now converts its database snapshot with FastAPI
`jsonable_encoder` before passing it to `Jsonb`. Dates and timestamps are
recorded as ISO strings in the revision JSON. Current catalog fields,
optimistic locking, approval rules, and the append-only audit model are
unchanged. No migration or authored data correction is required.

A regression test exercises both create and update paths with Python `date`,
naive `datetime`, and UTC `datetime` values. The full API suite passed 177
tests. A read-only local PostgreSQL `SELECT %s::jsonb` using the converted
snapshot passed through Psycopg's actual adapter. Infrastructure tests passed
12 cases, and the CDK diff contained only ECS task image tag changes.

## Deployment

Release `deploy-20260929-8` updates the API image; the web image content is
unchanged from `-7`. The access roster capability remains disabled. No
Service Catalog write was submitted during verification against live authored
records. CloudFormation `cbom-workbench-dev` reached `UPDATE_COMPLETE`; ECS
task revision 58 reached `COMPLETED` with one running task and API/web images
at `-8`. Cloud `/healthz` returned HTTP 200. The signed Admin Service Catalog
view loaded all 40 service groups, and `sse-cboms/adc` still displayed its
pre-edit imported planning values after the failed, rolled-back requests.
