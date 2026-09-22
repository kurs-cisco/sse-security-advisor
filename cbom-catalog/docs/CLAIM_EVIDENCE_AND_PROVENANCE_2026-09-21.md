# Claim evidence and corpus provenance — 2026-09-21

## Why the dashboard briefly showed mixed formats

The mixed chart was real database state, but it was not the current September
18 corpus. Docker Compose had no local `.env`, so the ingest service used its
old fallback `../SSE_CBOMS`. That older 582-file root contains CycloneDX,
SPDX, OSCAL, FipsChecker, CSV, summary, and scan-index documents. A later
non-authoritative refresh of the 534-file September 18 root did not mark paths
missing from the older root as historical. A subsequent refresh against the old
fallback made those paths current again.

The Compose fallback now points to `../OneDrive_1_9-18-2026`. Authoritative run
6 processed 534 files with zero failures and left 74 prior paths retained but
inactive. The current dashboard contract is therefore:

| Current format | Source paths | Unique documents |
| --- | ---: | ---: |
| CycloneDX 1.6 | 533 | 532 |
| CycloneDX 1.7 | 1 | 1 |

Do not switch physical snapshot roots under one collection using a partial or
non-authoritative run. Use `CBOM_AUTHORITATIVE_SNAPSHOT=true` for a complete
replacement snapshot. Use distinct collection identifiers and stable source
URIs when roots are not successive snapshots of the same logical collection.

## Evidence layers

Target-module data is evaluated in three independent layers:

1. **Team assertion** — owner, current module/version, target, status,
   certificate, and dates from `FIPS-140-3-21-sept.json`. This remains
   `user_asserted` planning metadata.
2. **Scoped CBOM observation** — a same-service-group component/version
   correlation with source path and document SHA-256. This establishes
   inventory presence only.
3. **Public authority evidence** — a NIST CMVP certificate or primary vendor
   lifecycle source. This can establish public certificate or pipeline status,
   but not service deployment applicability.

The overall claim remains `not_assessable` until exact artifact digest,
cryptographic boundary, operational environment, approved mode/configuration,
and ATO-boundary deployment evidence are supplied. A valid certificate and a
matching SBOM component are not by themselves proof that the deployed service
uses the validated module.

## Current-version correlation result

The checksum-addressed correlation matrix is
`evidence/current-version-correlation-2026-09-21.json`. It contains all 76
module assertions and a representative source path/document checksum wherever
an observation was possible.

| CBOM correlation | Claim rows |
| --- | ---: |
| Exact component name and claimed version observed | 21 |
| Normalized package family and claimed version observed | 6 |
| Package family observed, claimed version not observed | 17 |
| Package family observed, claim unpinned | 5 |
| Claimed module not found in mapped-group CBOMs | 15 |
| Blank or explicit no-evidence claim | 12 |

These categories are inventory correlations, not compliance outcomes. The
matrix importer rejects a record if its team/module position or asserted current
module/version no longer matches the active planning import.

## Material public-evidence corrections

- CMVP certificate `#4985` is active for the OpenSSL FIPS Provider 3.1.2. It
  does not validate arbitrary OpenSSL 3.5.x or 3.6.x builds.
- OpenSSL's primary announcement is specific to 3.5.4 in CMVP review. Claims
  for 3.5.5, 3.5.6, 3.5.7, 3.5.8, or 3.6.2 must not inherit that pipeline state.
- CMVP certificate `#4794` lists Canonical package
  `3.0.5-0ubuntu0.1+Fips2.1`; the asserted DP build
  `3.0.5-0ubuntu0.2+Fips1` is a version mismatch.
- CMVP certificate `#4735` lists BoringCrypto `2022061300`; generic
  Envoy/BoringSSL labels are not exact matches.
- CMVP certificate `#5247` covers Go Cryptographic Module v1.0.0. Official Go
  guidance identifies module v1.26.0 as in process; a Go 1.26 patch version is
  not itself the module identity.
- CMVP certificate `#4943` covers BC-FJA 2.1.x. `bctls-fips-2.1.24` is a
  separate TLS/JSSE artifact version and must not be used as the provider
  version.
- Certificates `#3514`, `#4036`, and `#4282` are historical FIPS 140-2
  evidence, not active FIPS 140-3 evidence.

The primary-source manifest is
`evidence/fips-module-public-evidence-2026-09-21.json`. Both evidence sets are
checksum-gated and retained in `target_module_evidence_import`; field-level
links are append-only in `target_module_claim_evidence`.

## Refresh sequence

```bash
docker compose --profile tools run --rm ingest
docker compose --profile tools run --rm target-modules
docker compose --profile tools run --rm target-public-evidence
docker compose --profile tools run --rm target-catalog-evidence
```

The public and catalog evidence artifacts must be regenerated when their source
content or the underlying team assertion changes. Never carry evidence to a
changed assertion solely by team name.
