# FIPS 140-3 assessment evidence request

**POA&M candidate:** `{{poam_candidate_id}}`  
**Service scope:** `{{source_collection}} / {{service_group}}`  
**Artifact / deployed digest:** `{{artifact_name_or_key}} / {{digest_or_unknown}}`  
**Assertion state:** `{{assertion_state}}`  
**Requested by:** `{{assessment_run_id}}`

## Why this is needed

The catalog currently supports this limited condition:

> {{technical_condition}}

This is a candidate assessment finding, not a compliance conclusion. The
available record cannot establish the cryptographic module’s FIPS 140-3
validation, approved operational environment, or in-scope deployment linkage.

## Please provide

- Exact deployed image/artifact digest and release/build provenance.
- Cryptographic module vendor, name, version/build, CMVP certificate number,
  and applicable security policy.
- Evidence that the module boundary and operational environment match the
  certificate/security policy.
- Approved configuration/provider settings and a timestamped admissible runtime
  verification with positive control and completion evidence.
- ATO-boundary and service-owner attestation, including whether the service is
  production, inherited, test-only, or otherwise out of scope.
- The organization-approved control mapping and remediation owner/milestones.

## Evidence handling

For each response, provide a stable URL or repository path, retrieval/observation
time, artifact digest, and content checksum where available. The assessment will
preserve the response as `primary`, `tool_observation`, or `user_asserted`
evidence and will not replace the original CBOM/SBOM/tool observations.
