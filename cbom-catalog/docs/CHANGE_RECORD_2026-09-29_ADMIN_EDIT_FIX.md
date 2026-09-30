# Admin edit and review release — 2026-09-29

## Cause and change

The console sent Service Catalog updates with `PUT`, but its Next.js catch-all
API route did not export a `PUT` handler. Next.js returned HTTP 405 before the
request reached the existing FastAPI update route. The proxy now forwards PUT
with the same verified OIDC identity, selected access mode, request body, and
response handling as the other supported methods. A route-level test covers
the Service Catalog PUT path and upstream response.

Admin now has an **Approvals** subtab for Service Catalog lead proposals. It
loads the pending queue and recent decision history from the existing audited
API and provides a reasoned approve/reject dialog. This queue concerns service
ownership and planning metadata. It does not make an assessment, POA&M, ATO,
CMVP, FIPS, deployment, or access decision. The separate operational evidence
review capability remains disabled by its existing feature flags.

The Admin **Users** view separates the current signed session from historical
application snapshots, summarizes recorded service and product-context scope,
and displays compact rows at narrow widths. Desktop table margins and
responsive status badges no longer clip or stretch the rows. Roster revoke and
restore remain disabled in this deployment.

## Verification

- 176 API tests, 8 console tests, and 12 infrastructure tests passed. Console
  lint, typecheck, and production build passed; CDK strict synth and diff
  passed. The final CloudFormation diff changed ECS task image tags only.
- Local Compose web returned HTTP 200 from `/healthz`. Chrome opened and
  closed the `sse-cboms/adc` editor without saving, showed Admin Approvals,
  and visually checked the Users view at a narrow viewport.
- The signed cloud Admin session showed 40 Service Catalog rows, 40 active
  service mappings, the new Approvals subtab with zero pending proposals, and
  two historical Users rows. Chrome screenshots confirmed that the final
  desktop Users table fits inside its card, while the local narrow view uses
  readable stacked rows.
- No live Service Catalog update, approval, mapping, or user access action was
  submitted. Automatic approval review rejected a PUT against a real local
  catalog row even with an empty payload, because it could modify authoritative
  data. The safe route-level test verifies the 405 fix without a data mutation.

## Final deployment

Release `deploy-20260929-7` uses the same API image content as the preceding
release and the final web image with the API proxy and Admin UI fixes. The
`CBOM_ACCESS_ROSTER_ENABLED` capability remains false. No catalog or evidence
data migration accompanies this release. The GovCloud stack
`cbom-workbench-dev` reached `UPDATE_COMPLETE`; ECS web task revision 57
reached `COMPLETED` with one running task, both containers use the `-7` tag,
and cloud `/healthz` returned HTTP 200.
