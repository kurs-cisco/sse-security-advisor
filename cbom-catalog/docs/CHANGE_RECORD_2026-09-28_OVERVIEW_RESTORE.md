# Overview layout restoration — 2026-09-28

## Change

Overview is a single page again. It shows the original four catalog metrics,
review priorities, transition checkpoint, service-footprint chart, data
readiness, evidence formats, and crypto-library chart without subtabs.

The portfolio metrics and format/readiness widgets use the aggregate-only
summary API. The identifier-bearing charts use the detailed dashboard API only
in Admin or an assigned product mode. Assigned modes request each verified
collection/service/product grant and show only those service groups. Summary
viewers receive no detailed chart identifiers. No authoritative catalog or
assessment data was changed.

## Verification and release

Console lint, non-incremental TypeScript check, seven console tests, and the
production build passed. Infra tests (10), TypeScript build, CDK synth, and
CDK diff passed. The diff contained only catalog/web ECS task image tags; the
catalog image config and layers were reused from the preceding release.

Local web was rebuilt and restarted without restarting the API or database.
GovCloud dev release `deploy-20260928-12` reached CloudFormation
`UPDATE_COMPLETE`; ECS web task revision 43 completed its rollout. Local and
cloud `/healthz` both returned HTTP 200.

Browser checks on both deployments showed 40 service groups, 533 evidence
records, 6,169 crypto occurrences, and 717 unique crypto assets. In cloud,
Admin saw both detailed charts, Summary viewer saw only aggregate widgets,
and Product Lead saw the assigned SaaS API and DLP footprint chart. The
Overview refresh control reloaded catalog status and both Admin charts.
