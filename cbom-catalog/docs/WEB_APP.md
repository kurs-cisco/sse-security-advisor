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
compliance. Overview is a single page; it has no subtabs. Summary users receive
aggregate totals and allowlisted category distributions, while detailed charts
remain limited to Administrator and exact assigned-product modes.

### Inventory

Inventory supports service, library, and heatmap perspectives with server-side
search, sorting, filtering, and pagination. Service/document drill-downs expose
format, checksum, timestamps, component inventory, explicit crypto signals, and
provenance. Library usage retains version-specific canonical identity and links
back to affected services/documents.

### Service Catalog

Service Catalog is the operational service register. It shows collection/service
rows with imported planning context, managed metadata, and an Admin-only
evidence drawer where current source files exist. Product roles receive only
their exact granted collection/service rows; planning fields remain operational
assertions and do not establish authorization or FIPS validation. The legacy
`/accountability` route redirects to `/service-catalog` and preserves a group
deep link.

Administrators use the Service Catalog and its Approvals workspace to manage
and approve operational metadata. Product Leads may submit exact-scope changes
for independent Administrator approval; Product Engineers are read-only.
Editors open focused dialogs that preserve focus and close with Escape. The
console forwards authorized `PUT` updates to the Service Catalog API.

### Risk Assessment

Risk Assessment includes the legacy POA&M register, Planning, and Team
milestones. Planning and Team milestones are read-only all-service views for
every signed dashboard role. The POA&M register separates non-eligible
coverage/evidence requests from technical candidate findings. With an
incomplete assessment contract, it shows the evidence-only queue and withholds
candidate output and exports. With a complete contract,
portfolio, workstream, and asset-level views retain source, owner, milestone,
and finding traceability. Every merge and disposition remains review-required.
See [POAM_EXPORT.md](POAM_EXPORT.md).

## Primary API contracts

| UI concern | Endpoint |
|---|---|
| Dashboard | `GET /api/v1/dashboard/overview` |
| Documents/components/libraries | `GET /api/v1/inventory/documents`, `GET /api/v1/documents/{id}/components`, `GET /api/v1/inventory/libraries` |
| Service Catalog | `GET /api/v1/service-catalog`; authorized Admin writes, Lead proposals, and Admin proposal decisions use `/api/v1/admin/service-catalog/*` routes |
| Tracker planning metadata | `GET /api/v1/fips/team-milestones` |
| Shared planning | `GET /api/v1/portfolio/poam-planning` |
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

Local `dev` authentication is an eight-hour, HTTP-only click-through cookie. It
requires `CBOM_AUTH_MODE=local-admin`, `CBOM_ENVIRONMENT=local`, and a loopback
host; the legacy insecure override cannot enable it in cloud configuration.
Cloud mode verifies the ALB-signed OIDC token and requires a separate bearer-token
trust boundary between Next.js and FastAPI. Raw document APIs are disabled by default.

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
for the primary read views plus the authorized Admin workspace, drawers,
filters, pagination, themes, responsive navigation, the assessment-contract
export behavior, and a dry-run ingestion job. Production verification must not
show HMR or React development tooling.
