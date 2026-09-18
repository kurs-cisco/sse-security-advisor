# Source-to-catalog mapping

The importer detects content signatures before considering filenames. Every
parsed document keeps its raw JSON/CSV representation (unless disabled), parser
version, SHA-256, source paths, generator metadata, and warnings.

## Common mapping

| Source concept | Catalog representation |
|---|---|
| Corpus/root | Stable `source_collection` and base URI |
| Service folder | Collection-scoped `service_group`; identity is `(source_collection, slug)` |
| Exact file bytes | Current `source_file.content_sha256`, immutable `source_file_fingerprint` history, and `document.sha256`; duplicates share one document |
| File path | A distinct `source_file`, even for duplicate content |
| Scanned image/application/package | `artifact` and `document_artifact` |
| Package/file/crypto item | Global `component` plus document-scoped `document_component` |
| Native identifier | `source_bom_ref`; unique occurrence `bom_ref`; PURL/CPE on component |
| Dependency/relationship | `dependency_edge`, retaining original relationship type |
| Extension/enrichment/assessment | Typed `external_record` with provider and observation time |
| Parse/schema problem | `ingest_issue`; the run continues |

## CycloneDX 1.5, 1.6, and 1.7

| CycloneDX field | Mapping |
|---|---|
| `serialNumber`, `version`, `specVersion` | `document` identity metadata |
| `metadata.timestamp`, `metadata.tools` | Generation provenance |
| `metadata.component` | Subject occurrence plus `artifact` role `bom-subject` |
| `components[]` | `component` + `document_component` |
| `bom-ref` | Document-scoped occurrence key |
| `purl`, `cpe`, name/version/group/type | Canonical component identity candidates |
| `hashes`, `licenses`, `externalReferences`, `evidence` | Occurrence JSONB; licenses also normalized |
| `properties[]` | Occurrence JSONB plus `component_property` rows |
| `cryptoProperties` | Indexed occurrence JSONB, preserving certificate/algorithm shape |
| `dependencies[].dependsOn` | `dependency_edge` with `DEPENDS_ON` |
| `vulnerabilities[]` and `affects[]` | Vulnerability, document evidence, and affected refs |
| `services[]`, `annotations[]` | Typed external records |

The parser does not reject custom fields or later extension objects. Unmapped
component keys are retained in `document_component.raw_extra`, and the complete
document can remain in `document.raw_document`.

`metadata.tools` appears both as an array and as an object containing tool
components. It is therefore preserved as JSON rather than forced into one shape.

Nested CycloneDX components are recursively normalized with `CONTAINS` edges.
Duplicate source `bom-ref` values receive distinct occurrence keys but are marked
ambiguous; relationships using an ambiguous source ref are not silently attached
to one of the duplicates.

## SPDX 2.3

| SPDX field | Mapping |
|---|---|
| Document namespace/name/creation info | `document` metadata and generator |
| `documentDescribes[]` | Subject artifacts and subject component occurrences |
| `packages[]` | Common component model using `SPDXID` as `bom_ref` |
| Package PURL/CPE external references | Canonical identity candidates |
| Declared/concluded licenses | Normalized license records with acknowledgement |
| `relationships[]` | Dependency edges retaining the SPDX relationship type |
| `files[]` | `spdx_file` rows with checksums/licenses and raw data |

CycloneDX and SPDX documents about the same image are not merged destructively.
They remain separate evidence documents that may link to a shared artifact and
shared canonical package identities.

## Crypto and FedRAMP extensions

`fedramp:*`, `cdx:*`, `internal:*`, `bap:*`, and future `snyk:*` properties remain
namespaced. Values stay strings when the producer encoded them as strings; the
catalog does not guess that `"false"`, a certificate identifier, or a newline list
has a different type.

`syft:location:N:path` and `syft:location:N:layerID` are high-cardinality. They are
always retained in occurrence JSONB and are expanded into EAV rows only with
`--include-location-properties`.

## Auxiliary inputs

| Input | Mapping and authority |
|---|---|
| CNHE generation summary | One external record per image; rollup is an observation, not an overwrite |
| ZTA-BAP scan index | One scan result record linked to digest/ref-derived artifacts |
| FIPS tool report | Artifact from image reference plus provider-attributed result record |
| OSCAL assessment results | Result, observation, finding, risk, and attestation records linked to image/digest properties when present; child records link relationally to their result |
| Curated crypto CSV | One record per row linked to a component/service artifact |
| Unknown JSON | Retained as `unknown_json` and raised as an ingest warning |

## Future Snyk data

Load future Snyk data with four explicit dimensions: provider (`snyk`), provider
record ID, observation/retrieval timestamp, and raw evidence. Link it to artifacts
by immutable digest first, then PURL, then an explicitly scored name/version
match. Never use a mutable image tag as proof that two observations describe the
same bytes.
