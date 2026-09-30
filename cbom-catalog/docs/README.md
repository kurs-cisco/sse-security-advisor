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

Keep durable behavior in the current documents above. Git history records code
changes; deployment and migration attestations belong in the organization's
approved change-management system with its retention controls. Git history is
not controlled assessment evidence. Do not add per-release `CHANGE_RECORD_*.md`
files to this directory.

The generated truth remains the database plus the externally retained source bytes. These
documents describe both the pipeline and identified snapshot baselines. Refresh
snapshot-specific counts by rerunning the `inventory` command and exporting a
new database manifest when the corpus changes.
