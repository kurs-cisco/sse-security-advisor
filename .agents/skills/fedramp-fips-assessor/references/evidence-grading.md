# Evidence grading and correlation

## Grades

| Grade | Examples | What it can support |
|---|---|---|
| `primary` | CMVP certificate/security policy, signed deployment attestation, approved SSP/SAP/SAR extract | Exact identity or approved scope only when the artifact/boundary correlation is explicit. |
| `tool_observation` | `fips_tool_result`, runtime command output, scanner result | A timestamped observed signal; never a validation conclusion by itself. |
| `inventory` | CycloneDX/SPDX component, crypto asset, artifact record, fingerprint | Presence/provenance of inventory data; not runtime use or validated status. |
| `curated_analysis` | Crypto CSV recommendation, analyst enrichment | A triage lead requiring confirmation. |
| `user_asserted` | Manual scope, ownership, deadline, or deployment assertion | Planning input until independently attested and recorded. |

## Correlation order

1. Exact deployed artifact canonical key and digest.
2. Exact document/source SHA-256 and stable source collection/service group.
3. Explicit provider-supplied linkage to an artifact or assessment subject.
4. Human attestation, marked `user_asserted` until independently corroborated.

Names, tags, path adjacency, and sibling files do not correlate evidence.

## Conflict handling and precedence

Retain every contradictory observation; do not collapse it into a single
favorable fact. A conflict exists when evidence correlated to the same artifact
and claimed cryptographic boundary materially disagrees about module identity,
validation applicability, runtime/provider state, or approved configuration.

1. Prefer exact digest/boundary correlation over a weaker correlation.
2. Within the same correlated scope, give a current, admissible primary record
   or runtime/tool observation precedence over a less direct inventory or
   curated assertion about the same fact.
3. A positive inventory assertion (component version, tag, CBOM property, or
   provider listing) must never override newer or stronger primary/runtime
   negative evidence.
4. A primary certificate can establish only its stated module and operational
   environment; it does not erase a newer runtime observation that the deployed
   artifact is misconfigured, outside that boundary, or otherwise unverified.
5. When timing, correlation, applicability, or probe admissibility cannot
   resolve the disagreement, emit `evidence_gap` with each side and its locator
   in the evidence manifest. Do not emit a POA&M candidate or a favorable
   conclusion until the conflict is resolved by authoritative review.

## FIPS tool interpretation

`fips_enabled: true`, `overall_openssl_fips: true`, or a detected provider means
only that the tool observed the reported condition at its observation time.
Missing `fips_module_version`, unknown web-server configuration, inaccessible
kernel state, absent positive controls, or absent completion evidence must be
recorded as limitations. A tool error, missing field, or omitted result is not a
negative test and is never evidence of a blocked or approved cryptographic path.

## Dedupe guard

Create a shared POA&M candidate only when root cause, module/boundary identity,
remediation, accountable owner, and ATO boundary are identical. The stable key
is `sha256(policy_version | finding_type | normalized_root_cause |
module_or_boundary_identity | remediation_strategy | owner_or_unassigned |
ato_boundary)`. Sort normalized fields and affected-service rows before output.
