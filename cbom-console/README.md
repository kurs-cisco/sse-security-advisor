# CBOM Workbench console

The console is the Next.js front end for the CBOM Catalog API. It keeps the
FastAPI/PostgreSQL catalog as the source of truth and uses a same-origin server
proxy for `/api/*`, so the browser never connects to PostgreSQL or the internal
API directly. The proxy can attach an internal bearer token at runtime.

## Views

- **Overview** — service-group coverage, pending and empty inputs, fingerprint
  readiness, explicit candidate-crypto totals, and the top five explicitly
  classified crypto libraries.
- **Inventory** — accessible service-group heatmap/table, service evidence
  records with full SHA-256 provenance, per-document component drill-ins, and
  explicitly classified library usage with a service-usage drill-in.
- **Accountability** — owner-grouped service register with lead, IL2/IL5
  planning, CBOM links, crypto inventory, findings, draft POA&M mapping, and a
  service detail drawer.
- **POA&M** — draft FIPS 140-3 candidate register, Team Tracker owner/lead and
  IL2/IL5 planning data, expandable evidence/remediation details, asset and
  workstream CSV exports, and a compliance ZIP.

Light and dark themes share the same semantic color tokens and the selected
theme is retained in local browser storage. Tables remain horizontally scrollable
at narrow breakpoints, while primary navigation moves to the mobile bottom bar.

The UI never treats an SBOM component, version, FIPS label, tracker commitment,
or runtime-mode signal as proof of CMVP validation or FedRAMP compliance.

## Local development

```bash
npm ci
CBOM_AUTH_MODE=dev CBOM_API_ORIGIN=http://127.0.0.1:8000 npm run dev
```

Open <http://127.0.0.1:3000> and select **Continue in local development**. This
sets an HTTP-only cookie and does not create identity claims. If the API cannot be reached, views show a clear
unavailable state; the console never substitutes preview records for live data.

The Docker Compose stack uses a production-built Next.js image on a loopback-only
port, so it explicitly sets `CBOM_ALLOW_INSECURE_DEV_AUTH=true`. Never carry that
override into a cloud deployment.

Inventory and POA&M tables use server-side filtering and pagination. Requests
are bounded by a 25-second client timeout, stale searches are cancelled, and
concurrent identical reads are deduplicated.

For a complete first run, authoritative data refresh, snapshot restore, and
handoff verification, see the catalog [first-run guide](../cbom-catalog/docs/FIRST_RUN.md)
and [release checklist](../cbom-catalog/docs/RELEASE_CHECKLIST.md).

## Verification

```bash
npm run lint
npx tsc --noEmit --incremental false
npm run build
```

## Container

From `cbom-catalog/`, `docker compose up --build web` starts PostgreSQL,
migrations, the API, and this console. The console is published on
<http://127.0.0.1:3000> and proxies API requests to the internal `api` service.

The legacy FastAPI-served `/ui` remains available as a rollback surface until
feature-parity acceptance is complete.

## Production access boundary

Set `CBOM_ENVIRONMENT=production`, `CBOM_API_AUTH_MODE=bearer`, and a random
`CBOM_API_BEARER_TOKEN` of at least 32 characters on the API. Set the same token
only on the Next.js server. Set `CBOM_AUTH_MODE=alb-oidc`, `CBOM_ALB_ARN`, and
`CBOM_OIDC_CLIENT_ID` on the console and configure the HTTPS ALB listener with
the OIDC provider. The console verifies the ALB-signed claim, expected signer,
client ID, expiry, and GovCloud regional signing key. Do not expose PostgreSQL
or the API directly.
The API fails closed in production when authentication is disabled or the token
is missing. `proxy` mode is also available for a trusted identity-aware proxy.

See the catalog's
[cloud authentication and deployment assessment](../cbom-catalog/docs/CLOUD_AUTH_AND_DEPLOYMENT.md)
for the current AWS reuse findings and database snapshot/restore procedure.
