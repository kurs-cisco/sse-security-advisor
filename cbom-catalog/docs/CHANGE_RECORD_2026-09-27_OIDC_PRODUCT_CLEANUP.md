# OIDC product cleanup — 2026-09-27

## Product contract

The cloud ALB requests `openid email groups`. The Next.js server verifies the
ALB-signed identity, forwards the verified `groups` claim to FastAPI, and the
API authorizes only exact group names in the deployment-owned `fedsse-` policy.
`fedsse-admins` takes precedence when a person also belongs to a summary or
service group. The custom MyID `memberships` scope and claim were diagnostic
only and are not consumed by this application.

Keep the MyID `groups` scope and claim. Configure its group selector to emit
only names beginning with `fedsse-` (or an exact allowlist of those names), then
complete a fresh CBOM sign-in and check the resolved role and matched groups.
The unused custom `memberships` mapping can then be removed from this MyID app.
This release did not change MyID configuration.

## Removed temporary application paths

- Removed both temporary OIDC claim diagnostic HTTP routes, their helpers,
  tests, ECS environment switches, and CDK expiry gates.
- Removed the temporary internal FastAPI diagnostic authorization bypass.
- Kept the signed ALB token verification, exact group policy, read-only
  portfolio summaries, product routing, and localhost-only admin login.
- Kept the earlier diagnostic deployment record as historical audit context;
  it does not describe a live application endpoint.

## Verification and deployment

The API suite passed 126 tests. Console lint, typecheck, and production build
passed. The CDK tests (9), build, synth, and final template diff passed. The
diff contained only the application image tag and diagnostic environment
removals in the web task, plus the dormant job task image pointer.

Immutable catalog and web images tagged `deploy-20260927-1` were deployed to
the `cbom-workbench-dev` GovCloud stack. The ECS service stabilized on task
revision 21 with one desired and one running task. Existing migrations 001–020
were skipped on startup; no migration or ingestion job ran. `/healthz` returned
200. A fresh signed-in browser session resolved the owner to portfolio admin
with both the administrator and summary group matched. The removed diagnostic
routes returned 404. The authenticated portfolio stats endpoint returned 200
and retained the prior baseline: 40 service groups, 534 source files, 533
documents, 341 artifacts, 59,263 unique components, 282,688 occurrences, and
609 fingerprint versions.

No source evidence, authored planning, assessment data, or MyID configuration
was changed by this cleanup.

## Remaining rollout gate

The Admin users endpoint still returned 500 in the live browser. Service group
detail grants and operational roster mutations remain disabled by deployment
capability flags pending their separate role-matrix and endpoint verification.
Do not treat this cleanup as service-role activation.
