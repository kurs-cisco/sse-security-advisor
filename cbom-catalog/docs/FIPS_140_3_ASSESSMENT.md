# FIPS 140-3 transition assessment

This catalog provides a deterministic, provenance-preserving triage view for the
FIPS 140-2 to FIPS 140-3 transition. It is intended to help the CSP, 3PAO, and
AO organize evidence and identify possible POA&M work across service groups. It
does **not** determine FedRAMP compliance, prove that a module is CMVP
validated, or authorize a system or POA&M disposition.

## Transition context

NIST states that FIPS 140-2 validated modules may be used for new systems
through **September 21, 2026**. On **September 22, 2026**, FIPS 140-2
certificates move to the CMVP Historical List and FIPS 140-3 validations are the
only active validations. Historical status is not the same as revoked status:
NIST permits continued use of a historical module by an existing system, while a
revoked module is not permitted for use. The applicable ATO boundary, system
status, and disposition remain decisions for the organization and its authorized
assessor/AO. See the [NIST CMVP program](https://csrc.nist.gov/projects/cryptographic-module-validation-program)
and [CMVP FAQ](https://csrc.nist.gov/Projects/cryptographic-module-validation-program/faqs).

FedRAMP guidance says residual risk from historical FIPS 140-2 use or early use
of a FIPS 140-3 module before validation completes should be tracked as an open
vulnerability while the migration is addressed. Its review guidance uses SC-13
as the principal control and expects evidence for each in-scope data flow and
data-at-rest location. See [FedRAMP sunset guidance](https://help.fedramp.gov/hc/en-us/articles/53386638354843-Q-Will-FedRAMP-provide-guidance-on-the-sunsetting-of-FIPS-140-2-What-do-I-do-if-our-planned-140-3-Module-is-not-yet-approved)
and [FedRAMP RFC-0003](https://www.fedramp.gov/rfcs/0003/).

## Use the assessment

The workbench’s **FIPS / POA&M** view and the API use the selected source
collection and service group as a provenance scope. The assessment is rebuilt
from normalized, immutable catalog evidence on each request:

```text
GET /api/v1/fips/assessment
GET /api/v1/fips/assessment?source_collection=<collection>&service_group=<group>
```

The result records the policy version, assessment date, transition dates, scope,
summary counts, service-group rollups, coverage-gap analyst observations,
findings, candidate POA&M rows, source
links, SHA-256 evidence fingerprints, limitations, and the authoritative source
register used by the rule set. Use the same scoped query for the browser view and
CSV export so an exported row can be traced back to the rendered assessment.
Service-group rollups include catalog groups with zero parsed documents. The
`coverage_gaps` collection turns zero-document, zero-FIPS-evidence, and partial
FIPS-evidence coverage into schema-shaped analyst observations. These records
are explicitly `not_assessable` or `evidence_gap`, have
`poam_eligibility: false`, and include the missing facts needed for an evidence
request. They are not inferred vulnerabilities and do not generate POA&M
candidates by themselves. FIS/SMA Threatgrid is a normal evidence-bearing
catalog group when source files are present. Its scanner CBOMs contribute
inventory coverage and candidate-crypto signals, but do not prove a deployed
module identity, CMVP validation, approved mode, ATO scope, or compliance.
The container defaults `CBOM_ASSESSMENT_TIMEZONE` to `Asia/Kolkata`; set that
environment variable to the organization-approved assessment timezone in other
deployments. The resolved timezone is returned with the assessment date.

## What the rules do

The rule engine has a deliberately narrow purpose: turn normalized inventory and
tool observations into reviewable states. It does not use an LLM to make a
compliance conclusion.

Coverage observations are evaluated before technical POA&M review:

| Coverage condition | Output state | POA&M candidate? |
|---|---|---|
| Registered service group with zero parsed documents | `not_assessable` | No |
| Parsed documents but zero usable FIPS/CMVP evidence | `evidence_gap` | No |
| Only part of the service group has usable FIPS/CMVP evidence | `evidence_gap` | No |

The Workbench shows these in **Coverage gaps / evidence requests**, joined to
Team Tracker owner, lead, IL2, and IL5 planning metadata. It never substitutes
demo CNHE or other sample records when the live assessment API is unavailable;
an explicit unavailable state is shown instead.

| Rule | Signal | Output state | POA&M candidate? |
|---|---|---|---|
| `FIPS1403-001` | Affirmative FIPS 140-2 use evidence without an accepted FIPS 140-3 deployment match | `likely_gap` | Yes |
| `FIPS1403-002` | Explicit FIPS 140-3 negative/not-validated assertion | `likely_gap` | Yes |
| `FIPS1403-003` | Negative runtime FIPS observation for an identified library | `likely_gap` | Yes |
| `FIPS1403-004` | Conflicting positive and negative evidence | `evidence_gap` | No |
| `FIPS1403-005` | Inconclusive runtime probe, such as a missing library | `evidence_gap` | No |
| `FIPS1403-006` | Unknown, pending, or incomplete validation evidence | `evidence_gap` | No |

`likely_gap` means a strong technical indicator requires boundary, policy, and
deployment confirmation. `evidence_gap` means the available corpus cannot prove
the needed fact. Neither is an authorized assessor conclusion. An explicit
`fedramp:fips:crypto-relevant=false` component is excluded unless the same
occurrence also has a conflicting explicit true assertion.

## Evidence and provenance

The assessment reads document properties, component properties, associated
artifacts, and preserved `fips_tool_result` records. Every finding retains its
document ID, occurrence/property identifier where applicable, source document
SHA-256, provider-record payload SHA-256, observation time, source collection,
service group, and source path.

These facts are evidence of inventory presence or a point-in-time observation,
not validation proof. A component name/version, image tag, library/provider
listing, SBOM/CBOM crypto property, FIPS label, or enabled-mode result cannot by
itself establish a CMVP validation. Confirmation requires the exact module,
version/build, CMVP certificate and security policy, cryptographic boundary,
operational environment, deployed artifact digest, approved configuration/mode,
runtime evidence, ATO-boundary linkage, and authorized review.

Evidence is partitioned by document-level subject or component occurrence before
classification. Assertions about two different component boundaries are not
collapsed into a false conflict. When positive and negative evidence does
conflict for the same subject, the engine keeps both inputs and emits an evidence
gap. A weaker inventory assertion never overrides a newer or better-correlated
runtime or primary record.

## Review workflow

1. Set the source collection, service-group scope, assessment `as_of` date,
   ATO boundary, and accountable owner outside the automated inference path.
2. Review service-group rollups to identify coverage gaps and candidate findings.
3. Correlate each candidate to the deployed artifact digest and cryptographic
   boundary; do not correlate by folder name, tag, or package name alone.
4. Obtain CMVP certificate/security-policy, approved configuration, runtime,
   data-flow/data-store, and boundary evidence.
5. Have the system owner and authorized assessor set risk, owner, milestones,
   significant-change path, and final POA&M disposition. The AO retains the
   authorization decision.

The project-local specialist instructions and schemas are in
[`../../.agents/skills/fedramp-fips-assessor/`](../../.agents/skills/fedramp-fips-assessor/).
They define the evidence grades, conflict handling, required assessment contract,
and output schemas used for a reproducible review.

## Related material

- [POA&M export workflow](POAM_EXPORT.md)
- [Specialist assessor agent](FEDRAMP_ASSESSOR_AGENT.md)
- [Web application guide](WEB_APP.md)
- [NIST SP 800-53 Rev. 5](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final)
