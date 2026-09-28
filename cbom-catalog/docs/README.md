# Documentation map

- [FIRST_RUN.md](FIRST_RUN.md) is the new-operator path for starting from source
  files or a database snapshot.
- [INGESTION_AND_ASSESSMENT.md](INGESTION_AND_ASSESSMENT.md) is the durable
  contract for local checksum refreshes, asynchronous Admin/S3/ECS ingestion,
  approved service-group aliases, evidence classification, Team Tracker
  enrichment, and candidate POA&M creation.
- [DATABASE_SNAPSHOTS.md](DATABASE_SNAPSHOTS.md) covers secure export, manifest,
  distribution, restore, and acceptance.
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) is the automated and browser
  verification gate for releases and handoffs.
- [CORPUS_INVENTORY.md](CORPUS_INVENTORY.md) is the dated 2026-09-18 corpus
  inventory baseline; refresh it from a new inventory run when the corpus changes.
- [FORMAT_MAPPING.md](FORMAT_MAPPING.md) maps each source schema into the common
  model and explains how extensions are retained.
- [DATA_MODEL.md](DATA_MODEL.md) defines identity, provenance, deduplication, and
  the PostgreSQL tables.
- [QUERY_COOKBOOK.md](QUERY_COOKBOOK.md) contains common security, ownership,
  crypto, dependency, and quality queries.
- [OPERATIONS.md](OPERATIONS.md) covers local use, containers, cloud deployment,
  administrator ingestion jobs, security, backups, and lifecycle concerns.
- [CLOUD_AUTH_AND_DEPLOYMENT.md](CLOUD_AUTH_AND_DEPLOYMENT.md) records the live
  AWS reuse assessment, OIDC trust boundary, and checksummed database
  snapshot/restore workflow.
- [ACCESS_CONTROL_AND_OVERLAYS.md](ACCESS_CONTROL_AND_OVERLAYS.md) defines OIDC
  invitation binding, viewer/admin RBAC, scoped API credentials, versioned
  evidence overlays, audit records, and snapshot exclusions.
- [OIDC_SERVICE_GROUP_MAPPING.md](OIDC_SERVICE_GROUP_MAPPING.md) is the
  human-review projection of the deployed service-group mapping baseline.
- [WEB_APP.md](WEB_APP.md) documents the workbench information architecture,
  UI/API contracts, accessibility behavior, deployment boundary, and verification.
- [FIPS_140_3_ASSESSMENT.md](FIPS_140_3_ASSESSMENT.md) explains the deterministic
  FIPS transition triage, evidence limits, reviewer workflow, and policy context.
- [POAM_EXPORT.md](POAM_EXPORT.md) documents the deduplicated draft POA&M CSV,
  evidence fingerprints, and required authorized-review gates.
- [FEDRAMP_ASSESSOR_AGENT.md](FEDRAMP_ASSESSOR_AGENT.md) describes the
  project-local FIPS assessment specialist and its schemas.
- [ingestion-validation-2026-09-17.json](ingestion-validation-2026-09-17.json)
  is the retained validation record for the earlier 2026-09-17 source snapshot;
  it is not the current baseline.

## Historical change records

The `CHANGE_RECORD_*.md` files are immutable operational provenance: they record
the particular migration, deployment artifact, verification result, and known
limitations at the time of a release. They are not current-state runbooks.
Use the durable documents above for operating instructions, and the change
records for evidence about a dated event:

- Schema and routing: [migration 016](CHANGE_RECORD_2026-09-25_MIGRATION_016.md),
  [dual-product routing](CHANGE_RECORD_2026-09-26_DUAL_PRODUCT_ROUTING.md), and
  [operational-access schema](CHANGE_RECORD_2026-09-26_OPERATIONAL_ACCESS_SCHEMA.md).
- OIDC and scoped access: [diagnostic deployment](CHANGE_RECORD_2026-09-26_OIDC_DIAGNOSTIC_DEPLOYMENT.md),
  [product cleanup](CHANGE_RECORD_2026-09-27_OIDC_PRODUCT_CLEANUP.md),
  [metadata-only release](CHANGE_RECORD_2026-09-27_METADATA_ONLY_ACCESS.md),
  [Admin mapping](CHANGE_RECORD_2026-09-27_ADMIN_GROUP_MAPPING.md), and
  [product-detail activation](CHANGE_RECORD_2026-09-27_PRODUCT_DETAIL_ACTIVATION.md).
- UI and deployment: [UI/access hardening](CHANGE_RECORD_2026-09-28_UI_ACCESS_HARDENING.md),
  [mapping usability](CHANGE_RECORD_2026-09-28_MAPPING_USABILITY.md),
  [workspace subtabs](CHANGE_RECORD_2026-09-28_WORKSPACE_SUBTABS.md),
  [local/cloud deployment](CHANGE_RECORD_2026-09-28_LOCAL_CLOUD_DEPLOYMENT.md),
  [Overview restoration](CHANGE_RECORD_2026-09-28_OVERVIEW_RESTORE.md),
  [Service Catalog](CHANGE_RECORD_2026-09-28_SERVICE_CATALOG.md), and
  [UI/UX rollout](CHANGE_RECORD_2026-09-28_UI_UX_ROLLOUT.md).

The generated truth remains the database plus the externally retained source bytes. These
documents describe both the pipeline and identified snapshot baselines. Refresh
snapshot-specific counts by rerunning the `inventory` command and exporting a
new database manifest when the corpus changes.
