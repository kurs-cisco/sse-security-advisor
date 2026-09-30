# Internal rollout plan

## Current review package

The Next.js console remains the primary UI. Its FIPS view separates authored
planning assertions, catalog-backed evidence requests, and eligible POA&M
candidates. The default deployment has no assessment contract, so it shows
evidence requests with candidate exports disabled. Selected-pair planning
context is marked unavailable while imported records lack collection
provenance. A
complete contract still does not create a candidate unless a primary,
checksum-addressed deployment attestation links the exact artifact digest,
cryptographic module and boundary, certificate, ATO boundary, and service group.
FedRAMP 20x output is an incomplete evaluation preview, not a VDR/VER report.

## Assigned-scope review behavior

Cloud human access comes from exact verified OIDC group values. The synthesized
deployment baseline `CBOM_OIDC_GROUP_SCOPE_JSON` contains 83 exact groups: the
three protected global groups `fedsse-admins`, `fedsse-external`, and
`fedsse-scr2-leads`, plus paired Lead and Engineer groups for 40 registered
services. Migration 021 adds an append-only Administrator-maintained policy
registry. Until its first signed human Administrator publish, the deployment
baseline is effective. Afterwards, the active audited revision is effective;
a missing, corrupt, or ambiguous active revision fails closed rather than
restoring a retired deployment grant.

`fedsse-admins` has portfolio and Admin access. `fedsse-external` and
`fedsse-scr2-leads` receive aggregate Overview and POA&M summaries plus the
read-only all-service POA&M Planning and Team milestones views. Every
service Lead or Engineer mapping holds one or two exact
`(source_collection, service_group, product_scope_id)` grants. The current
product scope IDs are `secure-access-government` with label `FedRAMP High/IL2`
and `secure-access-defense` with label `IL5`. These labels route application
access only; they do not prove ATO authorization, deployment, or FIPS/CMVP
validation. The API checks each selected triple and direct-record provenance;
unknown groups, unscoped detailed reads, and out-of-scope exports fail closed.
API credentials retain a separate explicit subject-to-grant mapping and
endpoint scopes; they never inherit a human group.

The Admin mapping editor may add, remap, or retire a paired service mapping.
It validates an existing catalog collection/service target, one or both product
scope IDs, a change reason, and a compare-and-swap revision token. Each publish
records the signed human actor, request ID, old and new mapping, and policy
content hash in the audit trail. It cannot change MyID memberships, source
evidence, planning data, assessment data, or an authorization conclusion.
Protected global groups cannot be edited through this workflow, and API tokens
cannot read or publish mappings. Localhost development remains loopback-only
local Administrator mode.

The Admin mapping view reports current and fingerprinted **catalog inventory**
counts. A zero fingerprinted count is an **Evidence gap** with unknown coverage;
it does not establish compliance, validation, authorization, product evidence,
or FIPS evidence. Product detail requires an exact verified
collection/service/product triple and a current-file routing decision. The API
keeps roster changes, evidence observations, strict proposals, FIPS detail,
candidate exports, and reporting output closed until their independent gates
are complete.

The [Admin mapping deployment record](CHANGE_RECORD_2026-09-27_ADMIN_GROUP_MAPPING.md)
and [product-detail activation record](CHANGE_RECORD_2026-09-27_PRODUCT_DETAIL_ACTIVATION.md)
preserve the dated deployment and signed-browser evidence. The
[UI/UX rollout record](CHANGE_RECORD_2026-09-28_UI_UX_ROLLOUT.md) identifies
the latest reviewed source snapshot and deployed image artifacts.

## Decisions required before service-team rollout

1. **Verify the live role matrix.** Review exact `fedsse-` values in MyID and
   use two separate signed identities with disjoint service grants, plus
   external, engineer, lead, and admin identities. Confirm selected triple and
   direct-ID denial across every detailed route before exposing evidence to
   service teams.
2. **Release operational access records only after isolated tests.** Migrations
   019 and 020 provide the append-only roster and evidence-observation schemas,
   but their capability switches remain off. Test revoke, restore, active
   session denial, permanent token revocation, self-revoke and last-admin
   protection, stale observations, and a separate human Administrator decision.
   The roster remains read only until those checks pass.
3. **Approve assessment contracts and attestations.** Define who can issue and
   supersede a versioned contract, its authority-register checksum and
   checksum-addressed currency review, and a primary deployment attestation.
   Keep source corpora and user-produced
   planning imports immutable. A contract or Team Tracker owner alone does not
   establish deployed cryptographic use. This requires a separately approved
   administrative workflow and storage decision.
4. **Complete both reporting adapters.** Keep the Rev. 5 candidate package
   traceable to one assessment run and authorized review. The 20x readiness
   preview enumerates unsupplied vulnerability detail, assessment impact, and
   reporting governance facts. A reportable VDR/VER adapter still requires
   authoritative observations and a separately approved data workflow. Do not
   treat the current preview as a submission.

## Release gates

- Run the API suite, console lint/typecheck/build, and the read-only browser
  flows in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
- Reconcile scoped group, document, fingerprint, observation, and candidate
  totals against the API and Chrome dashboards. Verify no out-of-scope record
  appears in direct routes or exports.
- Keep ingestion, migrations, overlay mutations, and shared database snapshots
  out of the evidence-only review run. A later release with approved contracts
  must exercise candidate export and schema validation against its exact run
  manifest.

**Go/no-go:** the read-only product-detail release and the Administrator
mapping registry are available after migration 021 and its isolated mapping
audit checks. Keep roster actions, evidence observations, strict proposals,
FIPS detail, candidate exports, and reportable 20x output closed until the
respective live identity, data-provenance, and evidence contracts above are
satisfied. An approved ATO contract and deployment attestations are required
for candidate POA&M reporting; the evidence-only view remains available without
them.
