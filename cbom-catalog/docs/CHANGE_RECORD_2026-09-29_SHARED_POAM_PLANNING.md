# Shared POA&M planning and Chromebook Client label

Released locally and to `cbom-workbench-dev` on 2026-09-29 as catalog and web image tag `deploy-20260929-12` (ECS web task revision 62). The catalog image is byte-identical to the verified `deploy-20260929-11` catalog image; the final web image corrects the scope-gate message.

## Product behavior

- The `sse-cboms/on-prem-clients` identity and evidence links remain unchanged. Migration 026 changes the existing `On Prem / Clients` display name to `Chromebook Client` only when the legacy label is still present. Future ingests and the console use the same label.
- Every signed dashboard role can GET `/api/v1/portfolio/poam-planning`. This read-only projection contains the current SSE Service Catalog planning fields, current document counts, and imported Team milestone data. Admin, Lead, Engineer, External, and SCR2 roles use the shared Planning and Team milestones data. A write to this route is denied.
- The Planning view includes all current catalog groups, including groups without an imported module target. It does not turn a plan or module assertion into a validated certificate or POA&M candidate. Product evidence, raw tracker, Service Catalog management, candidate, and export routes retain their existing authorization gates.
- Planning joins current module-planning assertions to the read-only Service
  Catalog projection by collection and service-group identity. Refresh reloads
  planning inputs before rendering lane and impact totals, so catalog date or
  risk changes are reflected without exposing restricted evidence detail.
- Admin retains its assessment views. Product roles see the all-service Planning and Team milestones views above their exact-grant evidence cards. External and SCR2 see the shared views without product evidence cards.

## Verification

- API suite: 245 passed, 15 skipped; exact role and read-only planning tests passed separately (37 tests).
- Console: lint, typecheck, 12 unit tests, production build. Infrastructure: 12 tests, TypeScript build, CDK synth and diff. The diff changed only catalog and web image tags in the existing task definitions.
- Local Compose: API and web healthy. Migration 026 recorded; `sse-cboms` retained 40 groups, and the renamed group retained zero current source-file records. The shared API returned 40 catalog groups, 40 tracker profiles, 38 milestone rows, and no edit-permission field. Local Playwright showed Planning 40, Team milestones 38, and Chromebook Client in Planning.
- Cloud: migration 026 ran on revision 61; revision 62 skipped it as already applied. CloudFormation reached `UPDATE_COMPLETE`, and ECS revision 62 is the sole primary deployment with one running task and none pending. The final revision uses the same catalog image and the corrected web copy. A signed Summary-role browser validation was not completed as part of this release.
