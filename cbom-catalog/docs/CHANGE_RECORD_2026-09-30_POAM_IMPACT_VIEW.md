# POA&M impact view — 2026-09-30

## Product behavior

- The shared read-only POA&M projection derives Critical, Moderate, Other/unset, and total impact from current Service Catalog rows. High maps to Critical and Medium maps to Moderate, matching Planning rollups.
- Each bucket reports service-group count and distinct current catalog document-record count. A document record is not a unique deployed service.
- The shared POA&M response no longer returns linked service-group, display-name, owner, or lead lists. No Service Catalog or source record was edited for this release.
- October, December, and March drafts use current IL2 planning months. They no longer invent month-end completion dates. DNSCrypt remains unrated and awaiting assessment.
- The read-only register contains three transition-planning drafts and one
  DNSCrypt draft with two technical topics. All four remain noneligible
  observations; the display creates no approved POA&M or assessment finding.
- The Risk Assessment POA&M table displays impact counts and neutral planning language. Page Refresh also reloads the POA&M register. Planning and Team milestones retain their previously approved read-only content.

## Verification

- API unit suite: 198 tests passed, including date/risk changes moving impact counts on the next request.
- Console: lint, typecheck, production build, and 15 unit tests passed.
- Infrastructure: 12 tests and TypeScript build passed. CDK diff and CloudFormation change set showed image-tag updates to ECS task definitions and dependent references only.
- Local production containers: API and web healthy. Local admin browser rendered four POA&M drafts against current local catalog data with Critical/Moderate/Other counts, no group or owner names in those rows, proposed SC-13 mapping, and month-only planning windows. Planning cards rendered the same risk bucket rules and catalog-record terminology.
- Cloud release: `deploy-20260930-11` completed. CloudFormation is `UPDATE_COMPLETE`; ECS task definition 73 is the sole deployment with both containers healthy, and the API and web load-balancer targets are healthy. A signed cloud UI review remained pending at release close.
- Architecture and compliance reviewers signed off on the aggregate response, risk buckets, refresh behavior, customer-facing wording, and assessment limitations. March 2027 currently has two service groups and zero catalog records; that is the derived count from current data.

These rows remain planning drafts, not approved POA&M findings, CMVP validation conclusions, or authorization decisions.
