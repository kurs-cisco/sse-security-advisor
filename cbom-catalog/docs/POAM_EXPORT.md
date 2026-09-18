# Draft FIPS POA&M export

The FIPS transition view creates deduplicated **draft candidates** for analyst
review. It is an evidence-management export, not an authoritative FedRAMP
POA&M, a 3PAO conclusion, or an AO decision. Before any row is entered into the
system of record, an authorized reviewer must confirm scope, control mapping,
risk, owner, dates, milestones, and supporting evidence.

## Export

Use the workbench’s **Download draft CSV** action, or request the same scoped
endpoint directly:

```text
GET /api/v1/fips/poam.csv
GET /api/v1/fips/poam.csv?source_collection=<collection>&service_group=<group>
```

The portfolio review has exactly two requested candidate dimensions:

```text
GET /api/v1/fips/portfolio-poam.csv
```

- `FIPS3-PORTFOLIO-ACTIVE-CERT` links candidate assets whose mapped Team
  Tracker row names an active FIPS 140-3 certificate or active module target.
- `FIPS3-PORTFOLIO-CMVP-PIPELINE` links candidate assets whose mapped target is
  described as CMVP In-Test, Testing, or In-Progress.

These are portfolio planning candidates, not two automatically accepted POA&M
records. Unknown, historical-only, and ambiguous module mappings remain
unclassified and visible for evidence collection. An active certificate does
not establish that the deployed service uses the validated module, boundary,
operational environment, or approved mode.

The proposed issue-workstream review export is separate so it cannot be
mistaken for the asset-level candidate register:

```text
GET /api/v1/fips/poam-workstreams.csv
```

The response is RFC 4180 CSV with a date-stamped attachment name. It contains
only findings that are eligible draft candidates; unresolved conflict,
inconclusive probe, and missing-evidence results stay in the assessment view and
are not silently converted into POA&M rows.

The compliance ZIP contains the portfolio, issue-workstream, and asset-level
CSVs plus the assessment summary and manifest. This preserves the two-row
management view without discarding the evidence needed to split a candidate.

## Candidate fields and review gates

The export proposes SC-13 as the primary control and includes conditional
SC-8(1) and SC-28(1) mapping in the assessment payload for analyst review. It
does not assert that the conditional controls apply. Each CSV row includes:

- stable draft candidate ID and rule/policy version;
- weakness, proposed risk, detection source, remediation plan, and planned
  transition checkpoint;
- affected scoped service groups and known artifacts;
- evidence and source SHA-256 fingerprints plus source paths;
- unassigned owner, empty detection/completion dates, and vendor-dependency
  fields that must be supplied or confirmed; and
- an explicit `Assessor Review Required` value of `Yes`.

The source SHA-256 values link the candidate to the immutable catalog documents.
They support repeatability across refreshes; they do not prove a deployed
module/certificate match.

## Deduplication policy

The automated pass uses a deliberately provisional key: normalized gap code,
exact subject identity, remediation strategy, and source-collection boundary.
A stable SHA-256 dedupe key is generated from those fields, then affected service
groups are aggregated under the shared candidate. The CSV labels the ATO
boundary as unassigned and records that this consolidation still needs review.

This is not sufficient to accept a merge in the authoritative POA&M. The
reviewer must confirm that the cryptographic module/boundary, deployed version
and environment, accountable owner, root cause, remediation strategy, and actual
ATO boundary are the same. Split the candidate if any of those facts differ.

Do not merge findings merely because package names, image tags, paths, or service
names are similar. Different versions, deployed environments, accountable owners,
boundaries, or remediation strategies remain separate candidates. This preserves
the evidence needed to defend an auditor review and prevents an apparent fix in
one service from closing another service’s work.

## Issue workstreams and asset candidates

The workbench presents a second, operational grouping above the asset-level
candidates. A proposed issue workstream shares the issue code, proposed risk,
accountable owner, remediation strategy, provisional ATO boundary, and explicit
IL2 mitigation date. Each workstream retains the linked candidate IDs, subject
identities, service groups, and evidence fingerprints.

This workstream is a triage and planning construct, not an automatic POA&M
merge. Before one workstream can become one authoritative POA&M item, an
authorized reviewer must confirm a single technical root cause, cryptographic
module/boundary and operational environment, accountable owner, ATO boundary,
remediation/validation plan, and impact assessment. The UI therefore labels
every workstream `review_required` and keeps all asset candidates available for
drill-down and export.

This two-level model reconciles two relevant FedRAMP approaches:

- The November 2025 [Continuous Monitoring Playbook](https://www.fedramp.gov/resources/documents/Continuous_Monitoring_Playbook.pdf) requires each unique
  scanner vulnerability ID to remain an individual POA&M item and prohibits
  grouping different unique scanner vulnerabilities.
- The Consolidated Rules for 2026 [Managing POA&Ms](https://www.fedramp.gov/2026/agencies/use/ongoing/poams/)
  guidance distinguishes vulnerability records from
  agency POA&Ms and focus POA&Ms on actions an agency owns, manages, or accepts.
  FIPS migration observations are not scanner CVE IDs, but consolidation still
  requires authorized review of whether they are truly one weakness and one
  corrective action.

The draft [RFC-0012](https://www.fedramp.gov/rfcs/0012/) grouping language is useful design context but is explicitly
non-binding and is not used as authority for an accepted merge.

## Service, library, and milestone traceability

Each portfolio or asset candidate retains links to the service-group reference,
catalog document/service record, source path and checksum, component/library
identity and version, finding IDs, executive owner, lead, and the mapped Team
Tracker row. UI links open the filtered service or library inventory and the
service accountability drawer.

Every service record and library inherits its planning context only from its
mapped service group. The October 2026, December 2026, and March 2027 waves are
portfolio delivery views. The group’s own raw IL2 values remain visible, and the
proposed POA&M completion date is the farthest explicit IL2 date among linked
groups. Relative phrases and missing dates are never synthesized into dates.

## Recommended handling before 22 September 2026

For each candidate, confirm whether the system and exact cryptographic use are
inside the ATO boundary and whether the system is an existing system. NIST’s
transition date is **September 21, 2026** for new-system use of FIPS 140-2;
FIPS 140-2 certificates become Historical on **September 22, 2026**. Historical
does not mean revoked: historical modules may remain usable by existing systems,
whereas revoked modules must not be used. See [NIST CMVP](https://csrc.nist.gov/projects/cryptographic-module-validation-program).

For an in-scope candidate, attach the exact CMVP certificate/security policy,
module/version/boundary, deployed image digest, operational environment,
approved-mode configuration, runtime verification, and relevant data
flow/data-store mapping. Confirm risk, owner, dates, vendor responsibility, and
significant-change treatment with the authorized assessor and AO. FedRAMP’s
[sunset guidance](https://help.fedramp.gov/hc/en-us/articles/53386638354843-Q-Will-FedRAMP-provide-guidance-on-the-sunsetting-of-FIPS-140-2-What-do-I-do-if-our-planned-140-3-Module-is-not-yet-approved)
describes tracking the residual risk as an open vulnerability during migration.

## Suggested evidence request

Use the project’s [evidence request template](../../.agents/skills/fedramp-fips-assessor/templates/evidence-request.md)
when the catalog cannot establish a candidate’s deployment match. It asks for
the information required to move from an inventory signal to an assessor-reviewable
record; it must not be used to imply the item has been closed.
