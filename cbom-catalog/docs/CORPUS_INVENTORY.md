# Corpus inventory

Current snapshot date: 2026-09-18. Scan root: `OneDrive_1_9-18-2026/`.
The older `SSE_CBOMS/` snapshot remains available for retained provenance and
mixed-format parser fixtures; its 2026-09-17 results are recorded in
`ingestion-validation-2026-09-17.json`.

## Headline results

- 534 JSON source files, 167,557,116 bytes (~160 MiB).
- 35 populated input folders, canonicalized into 35 populated catalog groups.
- Four earlier no-data service categories are retained in the same source
  collection, giving 39 visible service groups.
- 533 CycloneDX 1.6 files and one CycloneDX 1.7 file.
- 282,161 top-level CycloneDX component occurrences.
- One exact duplicate-content pair under OPC and no invalid/empty current input.

The validated database contains 533 unique current documents, 341 artifacts,
59,263 canonical components, 282,688 document-scoped occurrences, 198
relationship edges, and one current external record. Database occurrences also
include BOM subjects, so they do not exactly equal the top-level component count.

The latest authoritative refresh saw all 534 files: 507 were checksum-unchanged,
14 were parsed as new/changed content, 13 paths were linked to already-known
content, and zero failed. Every current source path has SHA-256 provenance.

## Canonical service groups

| Service group | Files | Service group | Files |
|---|---:|---|---:|
| ADC | 1 | ANDROID-NO_CBOM | 0 |
| APIX | 2 | App-Control | 2 |
| Avengers | 1 | BRAIN | 97 |
| CNHE | 9 | CONTRAAST | 46 |
| DATA-PLATFORM | 20 | Discovery | 8 |
| DISTHOST | 4 | DLP | 7 |
| DNS-PLATFORM | 1 | Download Service | 1 |
| DW_VOLT | 6 | FIS/SMA Threatgrid | 11 |
| FROUTER | 2 | IDENTITY-APPS | 6 |
| IDENTITY-CORE | 13 | IOS-NO_CBOM | 0 |
| KNEX | 31 | LANDERS | 12 |
| METERING | 2 | OPC | 7 |
| OVD-APP-Discovery | 19 | PAC-cbom | 6 |
| REPORTING | 19 | RSM-SECURE_CLIENT-NO_CBOM | 0 |
| SAASAPI | 27 | SCC-Backend | 1 |
| SFCN-FIREWALL | 60 | SFCN-RAVPN | 26 |
| SWG-PROXY | 5 | SWG-ROAMING-CLIENT-NO_CBOM | 0 |
| TAAC-cbom | 5 | UNIFIED-POLICY | 7 |
| VA | 1 | ZTA-BAP | 18 |
| ZTA-CALP | 51 |  |  |

The database key is `(source_collection, service_group)`, not the display name
alone. Approved folder and Team Tracker aliases are documented in
[INGESTION_AND_ASSESSMENT.md](INGESTION_AND_ASSESSMENT.md).

## CycloneDX profile

| Component type | Top-level occurrences |
|---|---:|
| `file` | 198,086 |
| `library` | 76,948 |
| `cryptographic-asset` | 6,658 |
| `application` | 429 |
| `operating-system` | 40 |

Property occurrences are dominated by `syft` and `fedramp`, followed by `cdx`,
un-namespaced, internal, Aqua Security, and ADC properties. The parser retains
all producer-specific fields and normalizes query-worthy properties without
treating them as validated assertions.

## Naming and quality intelligence

- The first path segment is a service-group observation, not global artifact
  identity.
- `*-source.cdx.json` generally suggests source/repository analysis; registry-
  heavy names generally suggest images. These are hints, not authoritative scope.
- A double underscore often separates a project/workload from a sub-service and
  is preserved rather than promoted to ownership truth.
- A missing dependency array means “not supplied,” not “no dependencies.”
- No populated vulnerability record exists in the current snapshot.
- FIS/SMA Threatgrid is evidence-bearing: its 11 scanner CBOMs contribute
  inventory/FIPS signals but do not prove deployed module identity or validation.
- The OPC duplicate pair remains two source-path observations linked to one exact
  content document.

Rerun the host-only inventory after any corpus change:

```bash
PYTHONPATH=src python -m cbom_catalog.cli inventory ../OneDrive_1_9-18-2026 --pretty
```

