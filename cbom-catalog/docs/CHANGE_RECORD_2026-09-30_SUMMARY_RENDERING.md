# Summary rendering correction — 2026-09-30

## Change

- Replaced Overview's identifier-withholding panels for Summary users with
  catalog processing totals and an allowlisted component-category distribution.
  The Summary API still excludes service, document, component, and library
  identities; detailed Overview charts remain limited to authorized roles.
- Removed raw API/IdP/proxy error bodies from Overview, Risk Assessment, and the
  access gate. Failed Summary and POA&M draft refreshes clear stale counts and
  show a retry message.
- Kept the existing read-only, all-service Planning and Team milestones access
  for signed Summary users. No author-maintained catalog, planning, or
  assessment data was changed.

## Verification

- API: 199 unit tests passed, including the aggregate projection contract.
- Console: 16 tests, lint, TypeScript check, and production build passed.
- Infrastructure: 12 tests and build passed; CDK diff contained image tags only.
- Local web container rebuilt; Chrome showed Overview and Risk Assessment
  loading against the local catalog.
- Cloud release tag: `deploy-20260930-12`; CloudFormation reached
  `UPDATE_COMPLETE`. ECS web task revision 74 is the sole running deployment,
  web and API target groups are healthy, and public `/healthz` returned 200.
- The local aggregate Overview API returned 40 service groups, 534 source
  files, and only `scope`, numeric `counts`, format families, and allowlisted
  component-category totals. Chrome confirmed the rebuilt local Admin Overview
  and Risk Assessment load; the local Admin login cannot impersonate Summary.

The signed Summary-mode browser flow requires a user with the Summary entitlement
and remains an explicit release-checklist validation.
