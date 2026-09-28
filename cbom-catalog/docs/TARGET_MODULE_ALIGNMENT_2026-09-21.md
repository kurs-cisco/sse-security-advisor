# Target-module alignment — updated 2026-09-24

## Result

`FIPS-140-3-21-sept.json` aligns to the canonical portfolio roster: all 39
source teams map to a known team key and service-group inheritance rule, yielding
40 canonical service categories after the shared PAC row expands and SCC rows
merge. The one
name-only exception, `DW / VOLT (Dashweb)`, is explicitly mapped to `DW-VOLT`.
The older `Resource Discovery` tracker row remains intentionally merged into
`Discovery`; it is not a missing fortieth team.

The comparison identified one catalog coverage miss: `On Prem / Clients` had a
planning row but no source folder and was not retained as an empty category. It
was registered as `on-prem-clients` with zero documents so its missing
evidence is called out rather than omitted. The obsolete `apix` planning alias
is collapsed into canonical `apix-no-cbom` and does not create a duplicate row.

Source fingerprint:
`d113d40fc5d722fda1611b70b207aa38fe978989486d63e5de7935ba3e2478e8`.
The source declares retrieval date `2026-09-24`, 39 teams, and 76 module rows.
Planning values are authoritative from GitHub PR #1 at commit
`a57eaba9`; the superseded engineering milestone tracker document is not used
as planning authority.

The superseded root Confluence export
`FIPS+140-3+Engineering+Milestone+Tracker.doc` has SHA-256
`88079a7b6ea1659effe45637dce850e2e8eeba6a15df718c68c70ff3a439ed62` and was
introduced in historical Git commit `faae781`. It is removed from the current
tracked tree and is not a current planning source or shipped artifact.

## Status reconciliation

The 76 source assertions normalize as follows:

| Source-status interpretation | Module rows |
| --- | ---: |
| Asserted not compliant | 35 |
| Asserted compliant | 16 |
| Pending certification | 13 |
| Not determined / blank | 11 |
| Not applicable | 1 |

The target dimension used for the candidate POA&M view is deliberately separate:

| Target disposition | Module rows | Teams represented |
| --- | ---: | ---: |
| Active-certificate target | 21 | 14 |
| CMVP in test / progress | 13 | 7 |
| Planned target without certificate evidence | 9 | 8 |
| Target not supplied | 21 | 12 |
| Not determined | 11 | 11 |
| Not applicable | 1 | 1 |

Eleven teams supply at least one explicit target-module value. A team can appear
in more than one disposition because its module rows may have different plans.
This is expected and must not be collapsed into a single team-level compliance
status.

## Material corrections versus the prior imported module snapshot

PR #1 was the approved authority for planning fields even when the
module-inventory JSON contained an older value. The then-current API contract
applied these approved corrections:

- Android IL2 and IL5 are `NA (Play Store)`, not October dates.
- Avengers / FRUP IL2 and IL5 are `2026-10-12`.
- SCC IL2 and IL5 are `2026-10-31`; its two source rows remain one planning row.
- VA IL5 remains the partial-month commitment `March 2027`; it is not promoted
  to an exact March 31 date.
- ZTA-CALP retains `2026-09-22 + 1w lead time`; the explicit date is usable for
  scheduling while the complete owner-supplied phrase remains visible.
- Resource Discovery remains merged with Discovery, preserving Ashok and Rakesh
  Muthusamy in the effective planning context without inventing a module row.
- SWG Proxy is no longer one generic pipeline mapping: its rows include three
  asserted active-certificate records and a separate non-compliant OpenSSL /
  Bouncy Castle record.
- OPC includes asserted certificate records plus a separate pending-
  certification record. It therefore participates in both portfolio dimensions.
- Data Platform has a pending-certification OpenSSL row that names certificate
  `#4794` while stating that the deployed build differs from the tested build.
  It correctly remains `cmvp_in_process`, not an active deployment match.

## Evidence limitations and review actions

The import is internally aligned, but it does not independently validate any
CMVP certificate or deployed cryptographic module. `Compliant`, `Active`, and a
certificate number remain user assertions. Before an auditor-facing POA&M merge
or closure, confirm the exact module/security policy, version and build,
cryptographic boundary, operational environment, artifact digest, approved
mode/configuration, ATO boundary, accountable owner, and remediation plan.

Eleven blank module placeholders remain `not_determined`; 21 module rows do not
supply a target. Those records should stay visible as evidence requests rather
than being inferred into either portfolio POA&M. Mixed-disposition teams should
retain module-level rows and may require separate milestones or POA&M scope if
their root cause, boundary, owner, or remediation differs.

The independent current-version and public-authority audit is documented in
`CLAIM_EVIDENCE_AND_PROVENANCE_2026-09-21.md`. Its evidence is exposed per
module as separate CBOM-inventory, public-status, and deployment-applicability
states. No public certificate or inventory match upgrades deployment
applicability; that state remains not assessable without runtime and boundary
evidence.

## Historical cloud reconciliation baseline — 2026-09-24

This section preserves a dated reconciliation snapshot. It is not a statement
of the current catalog, assessment, or deployment state.

The reconciliation used the refreshed 76-row target-module correlation set.
Its separate 2026-09-22 service-impact planning input had SHA-256
`5c481b5941d081b537c8f88805b78820fddfbe8d42af6bc9138d2dedce055ecc`.
That source remains a private transfer object and is not committed to Git; the
import retained only POA&M impact, risk category, and comments. The public
evidence and service-impact checksums were unchanged by this reconciliation.

Overview, Inventory/Accountability, POA&M, and milestone profiles had no
group-set or document-count mismatch. The historical output contained 195
deduplicated asset candidates, 218 candidate findings, 376 review-only
findings, 13 proposed workstreams, and 11 coverage requests. These are
machine-generated candidates or review observations, not FIPS validation,
FedRAMP compliance, POA&M closure, or an authorization decision. The retained
empty `on-prem-clients` planning category was not assessable because it had no
catalog evidence; that absence did not establish either a failure or favorable
posture.
