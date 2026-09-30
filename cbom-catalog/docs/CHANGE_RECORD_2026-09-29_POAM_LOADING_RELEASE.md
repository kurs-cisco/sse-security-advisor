# POA&M loading release — 2026-09-29

## Cause and change

The detailed POA&M component assumed candidate output was available until its
assessment API response arrived. On an incomplete contract, it briefly showed
an SC-13 draft-candidate heading and then switched to evidence collection.
It also started the assessment, team-milestone, and full Service Catalog reads
together when opening the evidence view.

The heading is now consistently **POA&M**. Candidate controls stay withheld
until the assessment contract is known, and a loading state appears while the
assessment is pending. Team-milestone data starts after the assessment, and the
full Service Catalog register loads when Planning is selected. The selected
view URL is not rewritten before the assessment response arrives. No source,
planning, assessment, authorization, or other authoritative app data changed.

## Verification and deployment

- Console lint, TypeScript typecheck, optimized build, and 8 tests passed.
- API virtual-environment suite: 243 passed, 15 skipped, 48 subtests passed.
- Infrastructure tests: 12 passed; build and CDK synthesis passed.
- CDK diff changed only catalog/web image references in ECS task definitions.
- Local Compose web container updated without restarting the API; `/healthz`
  returned 200. Local Chrome showed the POA&M title, 605 evidence observations,
  and the Planning lanes after selecting Planning.
- Cloud image tag `deploy-20260929-9` deployed to stack `cbom-workbench-dev`;
  ECS task definition revision 59 reached steady state and `/healthz` returned
  200. Signed Chrome showed the same 605 evidence observations, Planning 39,
  no old draft-candidate heading, and no candidate export button.

The assessment contract remains incomplete in the live environment, so the
evidence requests are noneligible observations and candidate exports remain
withheld. This release addresses the misleading intermediate screen and
removes two competing reads from the initial evidence path. It does not
establish an end-to-end backend latency service-level target.
