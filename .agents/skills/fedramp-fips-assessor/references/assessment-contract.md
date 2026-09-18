# Assessment contract

## Purpose and status

This specialist identifies FIPS 140-3 transition **POA&M candidates** from the
CBOM catalog. It is an evidence-management and triage aid, not a substitute for
an authorized FedRAMP assessor, system owner, or AO. Every generated finding
has `status: candidate` and requires authorized assessor/AO review.

## Authority baseline

NIST states that FIPS 140-2 active modules can be used for new systems through
**2026-09-21** and that FIPS 140-2 validation certificates move to the
Historical List on **2026-09-22**. NIST also states that historical modules may
continue to be used for existing systems. This establishes a transition risk
context; it does not, by itself, decide the organization’s FedRAMP boundary,
control implementation, procurement decision, or POA&M disposition.

For this assessment, historical FIPS 140-2 use or pre-validation FIPS 140-3
use is treated as an **open risk requiring review** whenever it is in the ATO
boundary or cannot yet be excluded from it. It is not automatically a finding
until the deployed module identity, boundary, applicable policy, and evidence
are evaluated. SC-13 is the primary candidate control mapping; any additional
control mapping remains `analyst-proposed` unless supplied by the organization’s
approved SSP/SAP/SAR or control crosswalk.

## Decision states

| State | Permitted conclusion |
|---|---|
| `confirmed_gap` | A traceable, in-scope deficiency conflicts with the approved assessment policy. Cite primary evidence and authorized review is still required. |
| `likely_gap` | Strong technical indicator exists, but a boundary, module identity, policy, or configuration fact is incomplete. |
| `evidence_gap` | Required proof of module validation, deployment identity, approved configuration, or scope is missing. |
| `not_assessable` | The available corpus cannot support a posture determination. |
| `validated_pending_review` | Validation evidence is present and correlated, but an authorized assessor/AO has not accepted the conclusion. |
| `out_of_scope_candidate` | Evidence appears non-production/test-only or outside the boundary; retain it until an authorized scope decision exists. |

## Hard constraints

- Never claim FIPS 140-3 validation from a package version, SBOM/CBOM, image
  label, `cryptoProperties`, `fedramp:fips:*` property, provider listing, or
  FIPS-mode signal.
- Never infer production deployment, ATO membership, owner, impact, inheritance,
  or risk acceptance from source paths, folder names, or image tags.
- Never turn absent tool output, an inaccessible kernel, a failed probe, absent
  dependency data, or unknown configuration into favorable evidence.
- Never state an item is compliant, authorized, accepted, remediated, or closed.
- Never overwrite or collapse raw evidence. Use immutable source and payload
  checksums, and retain contradictory observations.
- Do not use the transition dates without the authority record below. If the
  authority is superseded or the assessment time differs, preserve both the
  quoted authority and the assessment `as_of` timestamp.

## Required confirmation evidence

A move from `likely_gap` or `evidence_gap` to `confirmed_gap` or
`validated_pending_review` requires, as applicable: exact module/version/build
identity; CMVP certificate and security policy; operational environment and
module boundary; deployed artifact digest; approved configuration/mode; runtime
verification using an admissible probe; ATO-boundary linkage; and authorized
assessor/AO review.
