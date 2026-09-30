# Cryptographic module planning — 2026-09-30

## Why an imported target remained pending

The owner-supplied target-module file names intended libraries and sometimes a
certificate in free text. A public certificate verifies a specific module
identity and version; it does not identify the deployed provider, build,
operational environment, approved mode, service, or ATO boundary. The imported
assertion and public reference therefore remain separate. A pending reason is
not silently replaced by a certificate found for another or ambiguous module.

## Product change

- Migration 027 adds a nullable approved `crypto_module_plans` overlay to the
  Service Catalog. It does not backfill or rewrite imported target assertions,
  public evidence, or existing authored catalog values.
- Admins may record a current module and version, attach an exact immutable
  imported module row, and select a versioned public reference. Leads can
  propose the same change for their exact granted service group; a separate
  admin approves it. A custom target needs its exact module name and version,
  an HTTPS supporting document, and an evidence basis. Engineers and summary
  viewers cannot write it.
- The active public-evidence import supplies the curated choices. Current
  examples are OpenSSL FIPS Provider 3.1.2 / CMVP #4985, Go Cryptographic
  Module v1.0.0 / CMVP #5247, vendor-reported OpenSSL FIPS Object Module
  3.5.4 review, and vendor-reported Go Cryptographic Module v1.26.0 in process.
  The vendor statements are displayed as pipeline evidence without a
  certificate. Generic Python interpreter or package names are not presented
  as CMVP modules; a Python service must identify its underlying provider.
- Approved plans are a read-only overlay in Planning and Team milestones. The
  imported assertion remains visible. The Service Catalog detail projects
  `planning_disposition`, `evidence_state`, and `disposition_basis` from current
  checksum-addressed public evidence. If evidence changes, the saved target
  identity remains visible but its disposition becomes unverified until
  reviewed. A custom target remains user asserted and unverified.
- Exact version matching applies to both certificate and vendor pipeline
  correlation. A build suffix or patch string cannot inherit a base-version
  match. Selecting a public reference never proves deployment or makes a
  POA&M candidate eligible.

## Verification

- API suite: 198 passing tests, including exact-version, evidence-drift,
  imported-row identity, no-mutation, and cross-collection isolation cases.
- Console: lint, TypeScript check, 15 tests, and production build passed.
  Infrastructure: 12 tests, TypeScript build, CDK synth and an image-only diff
  passed. Chief Architect and Compliance SME reviews signed off.
- Local API and console containers rebuilt and returned HTTP 200 at `/healthz`.
  Read-only local browser review found 40 Service Catalog groups, 10 curated
  versioned options, Planning 40, and Team milestones 38. The editor opened,
  attached an imported current module, and showed certificate and vendor
  pipeline labels; the draft was closed without saving.
- Signed cloud browser review before the final display refinement found the
  same 40 catalog groups, curated options, Planning 40, Team milestones 38,
  and no shared-planning 500. Cloud API logs showed HTTP 200 on the relevant
  routes and migration 027 applied. After the final release, the signed browser
  again showed Catalog 40, Planning 40, and Team milestones 38. The editor
  offered the four named OpenSSL/Go choices and was closed without saving.
  In the same signed identity, Summary mode displayed all-service Planning 40
  and Team milestones 38 while denying Service Catalog; Lead mode showed only
  DLP and SAASAPI with **Propose** controls; Engineer mode showed those same
  two groups read-only with no Propose or Edit controls. Admin mode was
  restored and again showed all 40 groups. This verifies the mixed-role
  identity's mode behavior, not isolation between two different users.

## Release and data boundary

- Release `deploy-20260930-08` applied migration 027 and enabled the module
  editor, Planning overlay, and curated choices. It changed no authored
  Service Catalog plan values. Release `deploy-20260930-09` adds the live
  evidence-state display and strict version-correlation fixes; its reviewed
  CloudFormation change set affected only ECS task definitions and references.
  CloudFormation reached `UPDATE_COMPLETE`. ECS web task revision 71 is the
  sole running deployment (`1/1`, rollout `COMPLETED`), and the new API log
  recorded HTTP 200 for Service Catalog and Team milestones. Migration 027
  was already applied and skipped on this restart.
- No Service Catalog module plan was saved during verification. Existing
  pending owner assertions remain pending until an Admin records an approved
  plan or approves a Lead proposal for the exact service group and current
  module. A completed assessment contract and deployment-specific evidence
  are still required before any candidate/POA&M conclusion.
- The controlled public-evidence import does not yet include Cisco FIPS
  Provider 3.1.2 / CMVP #5160, which appears in the DW-VOLT owner assertion.
  Adding that record requires a separately approved, checksum-gated evidence
  intake. Cisco #5160 and OpenSSL #4985 are different certified module
  boundaries despite the shared 3.1.2 version. No generic Cisco Go #5324
  option is offered without an exact version and operational-environment
  record.

Primary references: [OpenSSL #4985](https://csrc.nist.gov/projects/cryptographic-module-validation-program/certificate/4985),
[Go #5247](https://csrc.nist.gov/projects/cryptographic-module-validation-program/certificate/5247),
[Go module guidance](https://go.dev/doc/security/fips140),
[OpenSSL 3.5.4 submission](https://openssl-library.org/post/2025-10-09-ossl3.5.4-fips-submission/),
[Cisco #5160](https://csrc.nist.gov/projects/cryptographic-module-validation-program/certificate/5160).
