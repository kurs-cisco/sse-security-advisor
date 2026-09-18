---
name: fedramp-fips-assessor
description: >-
  Assess the CBOM/SBOM catalog for evidence-backed FIPS 140-3 transition gaps,
  service-group coverage, and deduplicated FedRAMP POA&M candidates. Use for
  FIPS 140-2 historical-transition work, CMVP evidence review, cryptographic
  module validation evidence, or auditor-ready FIPS POA&M views. Never treat an
  SBOM component, version, image tag, FIPS label, or FIPS-mode signal as proof
  of module validation or FedRAMP compliance.
---

# FedRAMP FIPS Assessor

Produce a reproducible assessment from the catalog; do not make authorization
decisions. Every machine output is a **candidate** pending review by an
authorized assessor and the Authorizing Official (AO), with system-owner input.

## Required inputs

Before assessment, capture the ATO boundary, source collection, service-group
scope, assessment `as_of` timestamp, accountable owner, and an authoritative
deadline/policy source. If any are absent, continue only with the state
`not_assessable` or `evidence_gap`; do not fill them from filenames or tags.

Read [assessment-contract.md](references/assessment-contract.md),
[evidence-grading.md](references/evidence-grading.md), and
[official-authority-register.md](references/official-authority-register.md)
before classifying results.

## Catalog procedure

1. Establish coverage by querying source fingerprints, documents, artifacts,
   FIPS tool reports, OSCAL records, curated crypto CSV records, CycloneDX
   `cryptoProperties`, and `fedramp:fips:*` properties. Scope every result by
   `(source_collection, service_group)`.
2. Correlate evidence by artifact canonical key and immutable image digest first;
   then by document/source checksum. Similar paths, image tags, and service
   names are hints, not identity proof.
3. Preserve source path, SHA-256, document ID, external-record ID,
   external-record payload SHA-256, provider, JSON/CSV locator, and observed
   time in every evidence reference.
4. Classify observations only as `confirmed_gap`, `likely_gap`, `evidence_gap`,
   `not_assessable`, `validated_pending_review`, or `out_of_scope_candidate`.
   Follow the evidence grade and classification constraints exactly. An
   incomplete contract case, unresolved correlation, or unresolved evidence
   conflict must be emitted as an analyst observation validated by
   `schemas/analyst-observation.schema.json` with `poam_eligibility: false`.
   It cannot become a POA&M candidate yet.
5. Dedupe only findings sharing the same root cause, validated-module or
   cryptographic-boundary identity, remediation strategy, accountable owner,
   and ATO boundary. Put affected services under that POA&M candidate; never
   merge different versions, runtime configurations, owners, or remediations
   merely because a package name matches.
6. Emit an assessment-run record, analyst observations, and only eligible POA&M
   candidate records validated against the schemas in `schemas/`. Generate the
   auditor-facing view from the same evidence manifest, not from inferred prose.

## Current corpus interpretation

- `fips_tool_result` records are tool observations. For example, a detected
  OpenSSL FIPS provider or `fips_enabled: true` can support a runtime signal,
  but does not identify the exact CMVP certificate, module boundary, operational
  environment, approved configuration, or deployed service use.
- An empty module version, inaccessible kernel status, unknown web-server
  configuration, missing dependency data, missing probe output, or missing
  validation evidence is an evidence gap—not a favorable conclusion.
- Curated crypto CSV recommendations (`Validate` or `Review`) are analyst input,
  not an approved control determination. OSCAL and CBOM/SBOM content remains
  provider-attributed evidence.
- The catalog has sparse dependency data. No dependency array means `not
  supplied`, never `no dependencies`.

## Deliverables

Return both:

1. An analyst view: coverage, observations, assertion state, confidence,
   unresolved correlations, and all suppression/out-of-scope decisions.
2. An auditor view: deduplicated candidate POA&M items, affected scoped
   services, evidence manifest, condition, risk rationale, remediation,
   milestones, evidence gaps, and limitations.

Use [evidence-request.md](templates/evidence-request.md) for every missing
fact that prevents a confirmation. Do not mark an item closed; only propose
validation criteria for authorized review.
