# Service group mapping usability — 2026-09-28

## Change

Image `deploy-20260928-7` fixes the Administrator service-group mapping table. Edit and Retire open focused, scrollable dialogs next to the current task instead of placing an editor after all 40 rows or using browser prompts. The table shows 10 rows per page, resets pagination on search, keeps actions in a real table cell, and removes repeated row copy. Mobile action buttons and the dialog surface are legible at narrow widths. Admin user access, API token revoke, and catalog ingestion actions also use in-app confirmation dialogs. The existing typed collection check remains required for an authoritative snapshot.

The live cross-page check found that Admin Inventory Components and library Usage dialogs sent no scope pair while their API routes required one, producing HTTP 422. The read-only API now accepts an unscoped portfolio detail request for the verified Admin mode. Assigned product modes continue to require an exact granted collection, service group, and product context at the authorization middleware. Validation errors render as readable field messages instead of `[object Object]`.

The API mapping policy, MyID groups, source evidence, and all authored app data are unchanged. Browser verification opens and cancels mapping dialogs only; it does not submit a policy revision.

## Verification

- Full API suite: 206 passed, 12 skipped, 37 subtests passed. Console lint, non-incremental TypeScript check, production build, and seven console tests passed.
- The CDK diff contains only catalog/web image references in ECS task definitions.
- CloudFormation `cbom-workbench-dev` reached `UPDATE_COMPLETE`; ECS web task revision 38 references tag `deploy-20260928-7` for both containers and the service reached steady state. Application `/healthz` returned HTTP 200.
- Signed Admin browser checks: Edit opens an in-viewport dialog; Escape returns focus to its row; Retire opens a reason form with its action disabled until a reason is supplied, and Cancel closes it; page 2 shows rows 11–20; search for DLP returns only DLP.
- Final signed Admin check: the Edit dialog focused Catalog service, Save remained disabled without a reason, Escape canceled it, and the browser console reported zero errors and warnings.
- Signed Admin Inventory checks after the API fix: the Components dialog loaded page 1 of 6,149 real components; the Usage dialog loaded 3 of 3 explicit usages. Accountability uses a fixed detail drawer and POA&M expands details adjacent to their rows; neither had the after-the-table editor pattern.
- Signed route smoke checks rendered Overview, Inventory (coverage, services, libraries), Accountability, POA&M, and Reviews. Reviews displayed its configured disabled state; no review workflow was enabled.
- No mapping save, user access action, token revoke, ingestion, assessment change, or authored-data mutation was performed during browser verification.
