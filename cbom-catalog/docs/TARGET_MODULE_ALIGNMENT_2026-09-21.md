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
is now registered as `on-prem-clients` with zero documents so its missing
evidence is called out rather than omitted. The obsolete `apix` planning alias
is collapsed into canonical `apix-no-cbom` and does not create a duplicate row.

Source fingerprint:
`158c2d2c82ff1b1e3a7e57bb1e95edad16f1c670e4f9223c4ccffaf847c6d45c`.
The source declares retrieval date `2026-09-24`, 39 teams, and 76 module rows.
Planning values are authoritative from GitHub PR #1 at commit
`a57eaba9`; the superseded engineering milestone tracker document is not used
as planning authority.

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

## Material corrections versus the prior tracker model

- Android now supplies explicit IL2 and IL5 dates of `2026-10-31`; the older row
  treated them as not applicable.
- Avengers / FRUP and SCC no longer supply the October dates present in the
  prior model, so they remain uncommitted until confirmed.
- VA supplies an explicit `2027-03-31` commitment rather than a partial month.
- ZTA-CALP supplies `2026-09-22` without the ignored `+1w lead time` phrase.
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
