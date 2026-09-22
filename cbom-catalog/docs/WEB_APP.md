# CBOM Workbench web application

The primary browser interface is the authenticated Next.js application in
`cbom-console/`. It runs as a separate container and proxies `/api/*` to FastAPI
on the server side. Browsers never connect to PostgreSQL or receive the internal
API bearer token. FastAPI `/ui/` is retained only as a legacy rollback surface.

## Start it

Follow [FIRST_RUN.md](FIRST_RUN.md), then open <http://127.0.0.1:3000>. In local
mode, select **Continue in local development**. Cloud mode requires the ALB OIDC
boundary documented in [CLOUD_AUTH_AND_DEPLOYMENT.md](CLOUD_AUTH_AND_DEPLOYMENT.md).

## Information architecture

### Overview

Overview puts Catalog scale first, then Review priorities. It shows service
groups, evidence records, explicit candidate-crypto occurrences/assets, empty
categories, pending inputs, top crypto libraries, format mix, fingerprint
readiness, and service-group coverage. Counts describe evidence scope, not
compliance.

### Inventory

Inventory supports service, library, and heatmap perspectives with server-side
search, sorting, filtering, and pagination. Service/document drill-downs expose
format, checksum, timestamps, component inventory, explicit crypto signals, and
provenance. Library usage retains version-specific canonical identity and links
back to affected services/documents.

### Accountability

Accountability is the operational service register. Rows are grouped by
effective executive owner and expose lead, IL2/IL5 planning, catalog evidence,
candidate crypto assets, findings, draft POA&M candidates, and workstreams.
Filtering covers owner/lead, milestone state, and candidate action. A side drawer
joins Team Tracker source metadata, each service document, crypto libraries,
coverage observations, findings, and POA&M mappings without changing evidence.

### POA&M

POA&M separates non-eligible coverage/evidence requests from technical candidate
findings. Its default view contains two portfolio candidates: migration to a
deployment-matched active FIPS 140-3 certificate and dependency on a module in
CMVP In-Test/In-Progress. Expand either row to follow service, group, library,
owner/lead, group ETA, finding, and source-record links. Issue workstreams and
asset candidates remain available as traceability layers. October, December,
and March delivery-wave cards link to the corresponding accountability drawer.
The page provides portfolio CSV, asset CSV, and compliance ZIP downloads. Every
merge and disposition remains review-required. See [POAM_EXPORT.md](POAM_EXPORT.md).

## Primary API contracts

| UI concern | Endpoint |
|---|---|
| Dashboard | `GET /api/v1/dashboard/overview` |
| Documents/components/libraries | `GET /api/v1/inventory/documents`, `GET /api/v1/documents/{id}/components`, `GET /api/v1/inventory/libraries` |
| Accountability register/detail | `GET /api/v1/inventory/service-groups`, `GET /api/v1/inventory/service-groups/{collection}/{group}` |
| Tracker planning metadata | `GET /api/v1/fips/team-milestones` |
| Assessment | `GET /api/v1/fips/assessment` |
| Exports | `GET /api/v1/fips/portfolio-poam.csv`, `GET /api/v1/fips/poam.csv`, `GET /api/v1/fips/poam-workstreams.csv`, `GET /api/v1/fips/compliance-package.zip` |

List-heavy endpoints are bounded and server-paged. The console cancels stale
searches, deduplicates concurrent identical requests, and shows explicit
unavailable states instead of substituting sample data.

## Interaction and accessibility contract

- Desktop primary navigation remains fixed; narrow layouts use bottom navigation.
- Tables may scroll horizontally without moving the application shell.
- Drawers/dialogs are keyboard operable, focus-visible, and close with Escape.
- Charts have accessible labels and adjacent text values; color is not the only
  status encoding.
- Semantic CSS variables drive both light and dark modes. Reduced-motion,
  browser zoom, narrow viewports, and forced colors must remain usable.
- Candidate-analysis caveats use compact disclosures/tooltips where appropriate
  and do not displace primary work.

## Security boundary

Local `dev` authentication is an eight-hour, HTTP-only click-through cookie and
is blocked in production unless an explicit insecure override is set. Cloud mode
verifies the ALB-signed OIDC token and requires a separate bearer-token trust
boundary between Next.js and FastAPI. Raw document APIs are disabled by default.

Imported evidence remains read-only. The administrator page provides the
checksum-gated asynchronous ingestion workflow plus user management and scoped
API credentials. Corpus bytes upload directly to temporary private S3 objects;
FastAPI receives only manifest metadata and job control requests. The audited
overlay API and data model remain available for future inline editing on the
affected tables and entities; there is no standalone overlay editor. Source
deletion and raw-source distribution remain operator workflows. See
[ACCESS_CONTROL_AND_OVERLAYS.md](ACCESS_CONTROL_AND_OVERLAYS.md) and
[OPERATIONS.md](OPERATIONS.md).

## Verification

Use [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). At minimum, run console lint,
non-incremental typecheck, production build, API tests, and real-browser checks
for all four views, drawers, filters, pagination, themes, responsive navigation,
and exports. Production verification must not show HMR or React development
tooling.
