# CBOM Workbench UI/UX and assessment-view rollout — 2026-09-28

## Scope and approval

The user approved deployment of the reviewed UI/UX, catalog interpretation, and
evidence-only assessment changes. This was a code-only update to the existing
GovCloud development stack `cbom-workbench-dev`. No ingestion, source rewrite,
planning import, authored Service Catalog change, mapping revision, or access
roster change was initiated. The data-importing `infra/deploy-latest.sh` was not
used.

The release uses immutable tag `deploy-20260928-19` in both ECR repositories:

| Image | ECR digest |
| --- | --- |
| `cbom-workbench/catalog` | `sha256:e5d1f72a37e836b94d7a5706219dab52c759536717a73239e4c7d47bde5c6042` |
| `cbom-workbench/web` | `sha256:89be5e20768c422e4e763be3f816b67ff1628cd6ba3c7ea219b892121615aca6` |

The prior known-good pair is immutable tag `deploy-20260928-18` (catalog
`sha256:b69e6b8e8450540f67919f2657ae810630c29aeaf0a94dc612cc589357801fe3`,
web `sha256:c78d868e71c680a1bdda578ae11c47437156ec1f4d79b143a18855de27742d02`).
These image digests define the deployed artifacts. The source workspace had
uncommitted changes at build time; Git HEAD `f43b43f` alone does not reproduce
the images. A reviewed source snapshot should be committed before the next
release.

## Later source snapshot

After the rollout, the reviewed source state was committed as `1c25401` on
`release/deploy-20260928-19-source` and tagged
`source-snapshot/deploy-20260928-19`. It preserves the reviewed files for
handoff, while the immutable ECR digests above remain the authoritative
identity of the deployed images: the snapshot was created after the build and
does not establish byte-for-byte image reproducibility.

## Change review

- Before rollout, CloudFormation was `UPDATE_COMPLETE`, ECS web revision 49 was
  steady at 1/1, public `/healthz` returned 200, and both ECR repositories
  enforced immutable tags.
- The live API task startup log showed migrations 022, 023, and 024 already
  applied. No separate migration was run. The new task startup skipped 024.
- CDK synth passed. The template diff changed only the catalog and web image
  references in the web task and the catalog image reference in the job task.
- The actual CloudFormation change set additionally listed the web service's
  task-definition pointer and its existing IAM policy reference to the new job
  task ARN. The old and new IAM policy documents were identical; there was no
  new action, resource pattern, or condition.
- The API and web remain in the same ECS task. The unchanged web
  `CBOM_API_ORIGIN=http://127.0.0.1:8000` points to the API sidecar on port
  8000; web startup depends on API health.

## Verification

- API: 225 tests passed, 12 environment-dependent tests skipped, 42 subtests
  passed. Console lint, nonincremental TypeScript check, and production build
  passed. Infrastructure build and all 11 policy tests passed.
- CloudFormation reached `UPDATE_COMPLETE`; ECS web task revision 50 reached
  steady 1/1 with both containers healthy. Public HTTPS `/healthz` returned
  200. New API and web task logs had zero matching error lines in the checked
  startup/request window.
- Signed Admin browser: Overview showed 40 catalog service groups, 533 catalog
  records, 6,169 explicit crypto occurrences, and 717 distinct candidate
  crypto assets. Service Catalog showed 40 rows with 12-row paging; a
  no-evidence service opened an operational-summary dialog. POA&M showed the
  incomplete-contract evidence queue: 605 noneligible source observations in
  53 display groups, with candidate output and exports withheld. Admin group
  mappings showed 40 rows and the compact policy/revision disclosure.
- Signed Summary mode showed only aggregate Overview/POA&M navigation and
  denied a direct Service Catalog visit. Product Lead showed only DLP and
  SAASAPI, with proposal actions. Product Engineer showed the same two rows
  without proposal/edit actions. Both product modes showed four exact product
  grants across those two services. Admin mode was restored afterward.

## Remaining acceptance boundary

The live product grants do not currently carry an immutable product assessment
authorization reference. The product UI therefore shows verification pending
and does not call the product-scoped FIPS assessment endpoint. The new
exact-reference, incomplete-contract evidence-only API path and its export
denials passed automated regression tests, but that specific path cannot be
exercised with the current signed live grants. Do not invent a reference or
enable candidate/export output to force this check. A future authorized
product contract and verified grant reference are needed for live acceptance.

The earlier local/cloud source-path metadata drift for 14 service groups
remains recorded in the Service Catalog change record. This rollout did not
reconcile or rewrite source evidence.
