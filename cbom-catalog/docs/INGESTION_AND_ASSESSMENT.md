# Ingestion and assessment intelligence

This document is the durable operating contract for converting service-group
folders into queryable evidence and then into candidate FIPS 140-3 assessment
outputs. The source files, database, application, and assessor instructions must
remain consistent with this contract.

## Evidence boundary

A service is represented by a parsed CBOM, SBOM, assessment document, tool
summary, or other retained evidence record. A folder with no current document is
kept as a coverage category, not interpreted as a compliant or non-compliant
service. A component, library version, image tag, FIPS label, or enabled-mode
signal is never proof of CMVP validation or FedRAMP compliance.

## Ingestion pipeline

1. Discover files below the read-only corpus root. The first relative path
   segment is a service-group observation.
2. Canonicalize approved folder aliases before resolving the collection-scoped
   service group.
3. Read the exact bytes and compute SHA-256. Size and modification time are not
   trusted as integrity gates.
4. Compare `(source collection, relative path, SHA-256)` with `source_file` and
   `source_file_fingerprint`.
5. Skip parsing and normalized writes for unchanged bytes. Relink exact content
   already known at another path; otherwise classify, parse, and normalize in a
   single transaction.
6. Preserve the source/document checksum, format, generator metadata, component
   occurrences, properties, artifacts, relationships, external evidence, and
   parsing issues. Canonical components are deduplicated while occurrences retain
   document-specific evidence.
7. On a successful full `--authoritative-snapshot` run, mark paths not observed
   in that collection as historical (`is_present=false`). Do not delete their
   documents or fingerprint history.

For the `sse-cboms` collection, ingestion also registers five approved coverage
categories even when the current source tree has no matching directory:
`ANDROID-NO_CBOM`, `IOS-NO_CBOM`, `RSM-SECURE_CLIENT-NO_CBOM`, and
`SWG-ROAMING-CLIENT-NO_CBOM`, and `ON-PREM-CLIENTS-NO_CBOM`. This makes a clean
source import reproduce the 40-group roster implied by the 39 team rows (the
shared PAC row expands to three groups and the two SCC rows merge) instead of depending on rows inherited from an older
database. These registry entries have zero files and remain evidence gaps until
data is supplied.

The current approved ingestion aliases are:

| Observed input | Canonical catalog group |
| --- | --- |
| `APIX-NO_CBOM`, `APIX` | `APIX` |
| `ZTA CLAP`, `ZTA-CLAP`, `ZTA-CALP` | `ZTA-CALP` |
| `Discovery`, `Resource Discovery`, `DISCOVERY` | `Discovery` |
| `FRUP/MicroApps`, `FRUP/MicroApps/DAPI`, `Avengers` | `Avengers` |
| `SCC`, `SCC-Backend` | `SCC-Backend` |
| `PAC`, `PAC-cbom` | `PAC-cbom` |
| `TAAC`, `TAAC-cbom` | `TAAC-cbom` |
| `APP-CONTROL`, `App-Control` | `App-Control` |
| `FIS_SMA_Threatgrid`, `FIS/SMA Threatgrid` | `FIS/SMA Threatgrid` |

Tracker inheritance is intentionally broader than ingestion identity:
`PAC-cbom`, `TAAC-cbom`, and `App-Control` inherit the tracker row
`PAC/CSC/OVD/TIG`; SCC tracker rows are merged; the spelling aliases above share
one tracker profile. These joins add owner/lead/ETA planning context and never
alter source evidence.

## Refresh modes

Normal checksum-gated refresh:

```bash
docker compose --profile tools run --rm ingest
```

Full authoritative refresh of the selected collection:

```bash
docker compose --profile tools run --rm ingest \
  cbom-catalog ingest /data/SSE_CBOMS \
  --collection sse-cboms --authoritative-snapshot
```

Parser-validation pass over unchanged bytes:

```bash
docker compose --profile tools run --rm ingest \
  cbom-catalog ingest /data/SSE_CBOMS \
  --collection sse-cboms --force-reprocess
```

### Asynchronous cloud ingestion API

Cloud corpus uploads use the administrator API; raw files never pass through
FastAPI. Create a manifest containing the stable source collection and, for
each `.json` or `.csv` file, its normalized relative path, byte size, SHA-256,
and optional timezone-qualified modification time. Canonicalize the manifest
with `cbom_catalog.ingestion_jobs.normalize_manifest`, then hash the canonical
JSON with `manifest_sha256`.

1. `POST /api/v1/admin/ingestion/batches` with the manifest and its checksum.
   The API validates paths, limits, modes, and checksum, persists operational
   metadata, and returns checksum-bound presigned S3 `PUT` URLs.
2. Upload every file directly to its URL with the returned content type,
   content length, and `x-amz-checksum-sha256` headers. S3 validates the upload.
3. `POST /api/v1/admin/ingestion/batches/{id}/submit` with the same manifest
   checksum. The API launches a one-off ECS/Fargate task and returns immediately.
4. Poll `GET /api/v1/admin/ingestion/batches/{id}`. The worker downloads to
   ephemeral storage, recomputes every byte-level SHA-256, builds an inventory,
   and only then invokes the existing checksum-gated ingester.
5. Read the selected task's newest CloudWatch events from
   `GET /api/v1/admin/ingestion/batches/{id}/logs`. The API resolves the log
   stream from the batch's recorded ECS task ARN; browsers receive no AWS
   credentials.

The administrator page implements this protocol end to end. Choose the corpus
folder, confirm the stable source collection, leave **Dry run** selected for a
non-mutating comparison, and start the batch. Browser-side hashing and direct
S3 upload progress are shown first; the job history then polls validation and
ingestion state. Selecting a job displays checksum progress, timestamps,
CloudWatch task output, inventory totals, comparison counts and sample paths,
or the committed ingest result. Local click-through authentication may inspect
history but cannot launch a cloud task because it is not a provisioned audit
identity.

Use an administrator credential with `ingestion:write` to create and submit a
batch and `ingestion:read` to inspect status. Uploaded objects live below the
private `transfer/ingestion/` prefix and inherit its temporary-object lifecycle.

For a non-mutating end-to-end verification, use `dry_run=true`. It validates
all uploads, parses the corpus inventory, and compares `(source collection,
relative path, SHA-256)` against current `source_file` rows. It does not invoke
`ingest_root` or modify normalized catalog/evidence tables; only private
`app_auth` job/audit records change. Non-dry-run jobs store no raw JSON in
PostgreSQL and use the S3 URI as source provenance.

The supplied client performs the protocol without printing the API token or
presigned URLs:

```bash
cd cbom-catalog
CBOM_ADMIN_API_TOKEN='set-outside-shell-history' \
  PYTHONPATH=src python scripts/submit_ingestion_batch.py \
  ../OneDrive_1_9-18-2026 --collection sse-cboms --dry-run
```

Do not use `--authoritative-snapshot` for a partial download. Do not reuse a
collection name for an unrelated corpus. When normalization semantics change,
rebuild into a separate database and compare before promotion.

### Target-module planning import

Per-team module plans are a separate, checksum-gated input so a planning refresh
does not rewrite catalog evidence:

```bash
CBOM_TARGET_MODULES_FILE=../FIPS-140-3-21-sept.json \
  docker compose --profile tools run --rm target-modules
```

`target_module_import` retains the exact JSON, source filename, SHA-256,
retrieval date, and immutable import history. Importing the same checksum is a
no-op. `team_target_module` retains every raw module row and its record checksum;
one import is marked active for current views. A database snapshot therefore
contains both the catalog and the planning-data provenance.

### Service-impact planning import

The service-impact spreadsheet export is a separate checksum-gated planning
input. The importer reads the team identity only to map rows to service groups
and retains exactly three source columns: `Impact on POA&M`, `Risk Category`,
and `Comments`.

```bash
CBOM_SERVICE_IMPACT_FILE=../service_impact.csv \
  docker compose --profile tools run --rm service-impact
```

Owner, lead, CBOM availability/validity, IL2, IL5, and every other spreadsheet
column are deliberately ignored and cannot overwrite Team Tracker or catalog
values. Imported fields are `user_asserted` planning context with review
required; they are not validation evidence, accepted risk, an assessor
conclusion, or an authorization decision. The active import retains the exact
source filename and SHA-256 plus row-level checksums and selected-field payloads.

## Assessment pipeline

The assessment engine is deterministic and scoped by source collection and,
optionally, service group. It:

1. loads current documents and provider-attributed evidence;
2. partitions evidence by document/component subject so unrelated boundaries do
   not become a false conflict;
3. applies the versioned FIPS rules described in
   [FIPS_140_3_ASSESSMENT.md](FIPS_140_3_ASSESSMENT.md);
4. emits coverage observations separately from technical candidate findings;
5. creates asset-level draft POA&M candidates only from eligible `likely_gap`
   findings;
6. aggregates operational workstreams without discarding asset candidates;
7. joins every eligible candidate back to its service record, service group,
   source checksum, component/library identity, finding, owner, lead, and ETA;
8. joins the active target-module import by canonical team/service-group mapping;
9. creates two portfolio review dimensions for active-certificate targets and
   CMVP In-Test/In-Progress dependencies; and
10. enriches the view with owner, lead, IL2, IL5, module status, certificate
    assertion, and target-module provenance.

IL2 is the POA&M planning milestone. All explicit IL2 dates mapped to an item are
retained and the farthest explicit date becomes its proposed mitigation date.
IL5 remains visible planning context. Non-date phrases such as “FedRAMP Cycle,”
“next week,” and “+1w lead time” are not converted into dates.

Group IL2 commitments are also organized into October 2026, December 2026, and
March 2027 delivery waves. The wave is an aggregation label only: service and
library records keep their mapped group’s own ETA, and candidate mitigation
dates continue to use the farthest explicit linked IL2 date. Missing or relative
dates remain uncommitted.

Target-module rows are normalized separately from the source status. Supported
target dispositions are `active_certificate`, `cmvp_in_process`,
`planned_unverified`, `not_supplied`, `not_applicable`, and `not_determined`.
`Pending Certification` always remains `cmvp_in_process`, even if the row names
a certificate, because the deployed build may differ from the tested build.
Only `active_certificate` and `cmvp_in_process` feed the requested two-row
portfolio view; nothing is forced into either dimension.

Every source status—including `Compliant`—is retained as a user assertion.
Certificate text is a correlation lead, not validation evidence. Exact module
name, security policy, version/build, cryptographic boundary, operational
environment, artifact digest, approved mode, deployed configuration, and ATO
scope remain assessor review gates.

Coverage states (`not_assessable`, `evidence_gap`) request evidence and are not
POA&M eligible. Candidate findings remain machine-generated until the system
owner, authorized assessor, and AO confirm the deployed artifact, module and
boundary, CMVP certificate/security policy, operating environment, approved
mode, ATO scope, impact, owner, dates, and disposition.

## Provenance and change control

- `source_file` is the current path state; `source_file_fingerprint` is immutable
  checksum observation history; `document.sha256` is exact-content identity.
- `ingest_run` records parser version, refresh mode, counts, and outcome.
- Target-module planning data is pinned to its source filename, source SHA-256,
  raw JSON, immutable import ID, and record SHA-256 values.
- Service-impact planning data is pinned to its source filename and SHA-256;
  only the three selected fields and mapping identity are retained per row.
- Assessment results include a policy version, run ID, evidence fingerprints,
  scope, limitations, and explicit review requirements.
- POA&M IDs and workstream IDs are derived from stable deduplication inputs.

The normative specialist instructions are in
[`../../.agents/skills/fedramp-fips-assessor/`](../../.agents/skills/fedramp-fips-assessor/).
Changes to evidence grading, merge rules, authority, or candidate eligibility
must update those files, the deterministic engine, tests, and this document in
the same change.
