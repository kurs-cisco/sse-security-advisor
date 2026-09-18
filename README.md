# SSE CBOM/SBOM workspace

This workspace contains the retained 2026-09-17 corpus in
[`SSE_CBOMS/`](SSE_CBOMS/), the current 2026-09-18 corpus in
[`OneDrive_1_9-18-2026/`](OneDrive_1_9-18-2026/), a queryable catalog in
[`cbom-catalog/`](cbom-catalog/), and the primary Next.js console in
[`cbom-console/`](cbom-console/).

New operators should start with the [first-run guide](cbom-catalog/docs/FIRST_RUN.md).
The catalog [README](cbom-catalog/README.md) explains the architecture, API, and
data model, while the
[ingestion and assessment contract](cbom-catalog/docs/INGESTION_AND_ASSESSMENT.md)
preserves approved mappings and evidence rules.
After starting the stack, the Next.js CBOM Workbench is available at
<http://localhost:3000> with portfolio charts, service/library inventory,
SHA-256 provenance, Team Tracker milestones, and a scoped FIPS 140-3
transition/POA&M candidate view. The legacy workbench remains at
<http://localhost:8000/ui/> as a rollback surface.

See the console [README](cbom-console/README.md) for its development,
verification, and container workflow.
Cloud OIDC configuration, the read-only NOTA/AWS reuse assessment, and the
checksummed local-to-RDS migration workflow are in
[CLOUD_AUTH_AND_DEPLOYMENT.md](cbom-catalog/docs/CLOUD_AUTH_AND_DEPLOYMENT.md).
Secure database export/restore and handoff instructions are in
[DATABASE_SNAPSHOTS.md](cbom-catalog/docs/DATABASE_SNAPSHOTS.md), with the final
acceptance gate in [RELEASE_CHECKLIST.md](cbom-catalog/docs/RELEASE_CHECKLIST.md).

The catalog workflow does not rewrite the source folders and mounts them read-only
during container ingestion. A source path is treated as provenance, while exact
file contents are deduplicated by SHA-256 in the database.

For the FIPS transition workflow, start with the catalog’s
[FIPS 140-3 assessment guide](cbom-catalog/docs/FIPS_140_3_ASSESSMENT.md). It
uses the September 21, 2026 last new-system acceptance date and September 22
Historical List transition as review context, while keeping every result a
candidate pending authorized assessor/AO review.
