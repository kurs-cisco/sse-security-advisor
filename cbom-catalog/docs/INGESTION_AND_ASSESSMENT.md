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

For the `sse-cboms` collection, ingestion also registers four approved coverage
categories even when the current source tree has no matching directory:
`ANDROID-NO_CBOM`, `IOS-NO_CBOM`, `RSM-SECURE_CLIENT-NO_CBOM`, and
`SWG-ROAMING-CLIENT-NO_CBOM`. This makes a clean source import reproduce the
39-group inventory instead of depending on rows inherited from an older
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

Do not use `--authoritative-snapshot` for a partial download. Do not reuse a
collection name for an unrelated corpus. When normalization semantics change,
rebuild into a separate database and compare before promotion.

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
8. creates two portfolio review dimensions for active-certificate migrations
   and CMVP In-Test/In-Progress dependencies; and
9. enriches the view with Team Tracker owner, lead, IL2, and IL5 metadata.

IL2 is the POA&M planning milestone. All explicit IL2 dates mapped to an item are
retained and the farthest explicit date becomes its proposed mitigation date.
IL5 remains visible planning context. Non-date phrases such as “FedRAMP Cycle,”
“next week,” and “+1w lead time” are not converted into dates.

Group IL2 commitments are also organized into October 2026, December 2026, and
March 2027 delivery waves. The wave is an aggregation label only: service and
library records keep their mapped group’s own ETA, and candidate mitigation
dates continue to use the farthest explicit linked IL2 date. Missing or relative
dates remain uncommitted.

The Team Tracker `CMVP Mapping (Active/Historical/Testing)` field is normalized
into `active_certificate`, `cmvp_in_process`, `historical_or_legacy`, or
`not_determined`. It is user-asserted planning metadata. Only the first two
states feed the requested two-row portfolio view; nothing is forced into those
dimensions. Exact deployment-to-certificate correlation remains an assessor
review gate.

Coverage states (`not_assessable`, `evidence_gap`) request evidence and are not
POA&M eligible. Candidate findings remain machine-generated until the system
owner, authorized assessor, and AO confirm the deployed artifact, module and
boundary, CMVP certificate/security policy, operating environment, approved
mode, ATO scope, impact, owner, dates, and disposition.

## Provenance and change control

- `source_file` is the current path state; `source_file_fingerprint` is immutable
  checksum observation history; `document.sha256` is exact-content identity.
- `ingest_run` records parser version, refresh mode, counts, and outcome.
- Tracker data is pinned to its source filename/URL and source SHA-256.
- Assessment results include a policy version, run ID, evidence fingerprints,
  scope, limitations, and explicit review requirements.
- POA&M IDs and workstream IDs are derived from stable deduplication inputs.

The normative specialist instructions are in
[`../../.agents/skills/fedramp-fips-assessor/`](../../.agents/skills/fedramp-fips-assessor/).
Changes to evidence grading, merge rules, authority, or candidate eligibility
must update those files, the deterministic engine, tests, and this document in
the same change.
