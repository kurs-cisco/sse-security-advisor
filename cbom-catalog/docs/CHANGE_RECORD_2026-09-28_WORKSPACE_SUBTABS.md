# Workspace subtabs — 2026-09-28

## Change

The Next.js console separates long pages into focused, accessible sections:

- Admin: Service mappings, Data ingestion, Users, Scoped tokens. Inactive sections do not mount their data-heavy panels or fetch their section-specific API data. On narrow screens, all four tabs remain visible in a two-row grid.
- Overview: Summary, Evidence readiness, Guidance.
- POA&M: Review queue, Candidates, Planning, Migration dimensions, Evidence requests, Team milestones. The existing assessment-contract gate still withholds candidate views and exports when required facts are missing. Assessment provenance is expandable so the active view remains easy to reach on mobile.
- Scoped Accountability: Summary, Documents, Libraries, Observations. When one assigned service has multiple product contexts, the same selected view applies across its rendered contexts; each tab panel has a unique accessible ID.
- Reviews: Decision queue and Audit trail. The existing disabled workflow state is preserved.
- Inventory: its existing Coverage, Services, and Libraries tabs now restore correctly with browser Back and Forward while keeping each table's paging and sorting state.

Tab selection is reflected in URL state where applicable. Tabs change presentation only; signed identity, exact service grants, API authorization, assessment eligibility, and source data are unchanged. No mapping revision, user access action, token action, ingestion, review decision, or authored-data mutation was submitted during validation.

## Verification

- API suite: 206 passed, 12 skipped, 37 subtests passed. Infrastructure: 10 tests passed and TypeScript build passed. Console: seven tests passed; lint, non-incremental TypeScript, and production build passed after the final code change.
- CDK diffs for the UI releases contained only catalog/web image tag updates in ECS task definitions. The catalog image config and layers were reused unchanged.
- Signed browser checks covered Admin mappings, ingestion history, Users, and Scoped tokens; Overview tabs and Back navigation; Inventory Services/Libraries and Back navigation; Reviews Queue/Audit; and POA&M evidence-only gating, Planning, and Team milestones. Mobile screenshots at 390 pixels confirmed the Admin two-row tabs and POA&M collapsed provenance.
- Final deployed scoped Accountability synchronization, unique tab IDs, deployment health, and ECS stability are recorded in the release outcome below.

## Release outcome

Image `deploy-20260928-10` reached CloudFormation `UPDATE_COMPLETE`. ECS web task revision 41 uses that tag for both containers and the service reached steady state; `/healthz` returned HTTP 200. The catalog tag carries the same image config and layers as the preceding catalog release.

A fresh signed `kurs@cisco.com` Product Lead session showed two service groups and four verified product grants. Opening DLP evidence loaded its Defense and Government contexts. Selecting Documents in Defense selected Documents in both panels, with unique tab/panel IDs; browser Back restored Summary in both panels. The browser reported zero errors. Five warnings were Next.js CSS preload timing notices, with no failed UI flow observed.
