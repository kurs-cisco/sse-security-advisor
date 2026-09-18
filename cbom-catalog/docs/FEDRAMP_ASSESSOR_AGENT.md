# FedRAMP FIPS assessor specialist

The project includes a reusable specialist instruction set at
[`../../.agents/skills/fedramp-fips-assessor/`](../../.agents/skills/fedramp-fips-assessor/)
for reviewing CBOM/SBOM catalog evidence during the FIPS 140-3 transition. It
is designed to produce reproducible analyst observations and deduplicated draft
POA&M candidates—not autonomous compliance determinations.

## What it requires

Before an assessment, capture the ATO boundary, source collection,
service-group scope, `as_of` timestamp, accountable owner, and authoritative
policy/deadline source. If a required fact is absent, the specialist uses
`not_assessable` or `evidence_gap`; it does not infer it from a filename, image
tag, or service folder.

The instructions require evidence correlation in this order:

1. Exact deployed artifact canonical key and immutable digest.
2. Exact document/source SHA-256 with source collection and service group.
3. Explicit provider linkage to an artifact or assessment subject.
4. Human attestation, retained as user-asserted until independently corroborated.

It preserves conflicting evidence and does not let a component inventory claim
override newer, stronger, or better-correlated primary/runtime evidence.

## Outputs

The specialist emits these decision states:

| State | Meaning |
|---|---|
| `confirmed_gap` | A traceable in-scope deficiency conflicts with the approved policy; authorized review is still required. |
| `likely_gap` | Strong technical indicator, but a required boundary, identity, policy, or configuration fact is incomplete. |
| `evidence_gap` | Needed validation, deployment, configuration, or scope proof is missing or conflicts. |
| `not_assessable` | The supplied corpus cannot support a posture determination. |
| `validated_pending_review` | Correlated validation evidence is present but has not been accepted by the authorized assessor/AO. |
| `out_of_scope_candidate` | Evidence appears outside the production/ATO boundary and needs an authorized scope decision. |

Only an eligible, fully contract-compliant candidate can be rendered as a draft
POA&M row. The agent schema marks incomplete-contract observations as
`poam_eligibility: false`.

The application additionally presents two portfolio planning candidates: one
for mapped active-certificate migration targets and one for mapped CMVP
In-Test/In-Progress dependencies. These summarize eligible asset candidates but
do not override the specialist’s deduplication guard. Historical, unknown, and
ambiguous mappings remain unclassified; all service/library links and group
ETAs stay available so an authorized reviewer can accept or split the grouping.

## Important limits

An SBOM/CBOM component, crypto property, library version, provider name, FIPS
label, image tag, or FIPS-mode signal does not prove FIPS validation. The
reviewer must correlate an exact CMVP certificate and security policy to the
module version, module boundary, operating environment, approved configuration,
deployed artifact, and in-scope use. The specialist never marks an item
compliant, authorized, accepted, remediated, or closed.

The authority register is pinned with a retrieval date and records that FIPS
140-2 remains acceptable for new systems through **2026-09-21** and moves to the
Historical List on **2026-09-22**. Re-check the authority when rerunning an
assessment after the recorded retrieval date or when a policy decision depends
on current guidance. See [NIST CMVP](https://csrc.nist.gov/projects/cryptographic-module-validation-program)
and the [CMVP FAQ](https://csrc.nist.gov/Projects/cryptographic-module-validation-program/faqs).

## Files

- `SKILL.md` — operating instructions and safety constraints.
- `references/assessment-contract.md` — evidence requirements and hard limits.
- `references/evidence-grading.md` — grades, correlation order, conflict
  precedence, and dedupe guard.
- `references/official-authority-register.md` — policy-source register.
- `schemas/` — machine-readable run, evidence, observation, and POA&M schemas.
- `templates/evidence-request.md` — a neutral request for missing evidence.

See [FIPS 140-3 assessment](FIPS_140_3_ASSESSMENT.md) for the workbench and API
workflow.
