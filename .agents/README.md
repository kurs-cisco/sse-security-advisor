# Project agents and assessment guidance

The repository includes one project-local specialist skill:

- [`fedramp-fips-assessor/SKILL.md`](skills/fedramp-fips-assessor/SKILL.md) —
  evidence-backed FIPS 140-3 transition triage, coverage review, and candidate
  FedRAMP POA&M generation/deduplication.

Use it whenever a task interprets FIPS/CMVP evidence, assesses service-group
coverage, or creates/merges POA&M candidates. The skill's reference files and
JSON schemas are normative. Read all required references before classifying
evidence.

The specialist never makes an authorization decision. Inventory presence,
component versions, FIPS labels, runtime mode, tracker dates, and CBOM/SBOM
metadata are evidence inputs, not proof of validation or compliance. Missing or
conflicting required facts stay `evidence_gap` or `not_assessable` and are not
POA&M eligible.

When changing assessment behavior, update together:

1. the specialist skill/references/schemas;
2. `cbom_catalog.fips_assessment` and Team Tracker mappings;
3. automated tests;
4. [ingestion and assessment intelligence](../cbom-catalog/docs/INGESTION_AND_ASSESSMENT.md);
5. POA&M/export documentation and the release checklist.

The administrator ingestion control plane is operational infrastructure, not a
new evidence grade or assessor authority. Changes to manifests, presigned S3
uploads, ECS job execution, or `app_auth` ingestion metadata must preserve the
specialist's read-only evidence assumptions and be reflected in the catalog
ingestion contract, operations/data-model docs, console guidance, tests, and
release checklist. Do not add transport or job-state rules to the FIPS skill
unless they actually change assessment semantics.

General coding and operational instructions remain in the root
[`AGENTS.md`](../AGENTS.md). The Next.js-specific generated guidance remains in
[`cbom-console/AGENTS.md`](../cbom-console/AGENTS.md).
