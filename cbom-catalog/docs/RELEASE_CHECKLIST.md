# Release and handoff checklist

Run this checklist before sharing a database snapshot, publishing a container,
or handing the repository to another operator.

## Data

- [ ] Confirm the corpus root and stable source collection.
- [ ] Run a checksum-gated authoritative refresh only against a complete corpus.
- [ ] Confirm the latest ingest completed with zero unexpected failures.
- [ ] Reconcile source files, current documents, empty groups, fingerprints, and
      current parse issues with the dashboard and `/api/v1/stats`.
- [ ] Spot-check APIX, FIS/SMA Threatgrid, CNHE, ZTA-CALP, Discovery, SCC-Backend,
      Avengers, PAC-cbom, TAAC-cbom, and App-Control mappings.
- [ ] Confirm the active service-impact import checksum, 20 selected rows, 22
      mapped service groups, and zero retained owner/lead/IL2/IL5/CBOM fields.

## Automated verification

```bash
cd cbom-catalog
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v
cd ../cbom-console
npm run lint
npx tsc --noEmit --incremental false
npm run build
cd ../infra
npm run test
npm run build
```

Confirm API health and representative routes: dashboard, service-group register,
service detail, document components, library inventory/usage, team milestones,
assessment paging, issues, and assessment-export behavior for the active
contract state.

For an assigned-service review, use two different configured principals with
disjoint grants and pass one exact `(source_collection, service_group,
product_scope_id)` triple on
every service-data request. Compare dashboard, register, document, component,
artifact, dependency, fingerprint, FIPS, 20x, and export responses with the
selected triple. Direct IDs from the other principal's group or product must
return 404;
unscoped or ungranted reads and global operational routes must return 403.
Verify all administrator methods reject an assigned-only principal. The live
review may use a temporary read-only database connection and review-only grant
configuration; it must not modify ingestion, planning, assessment, or user data.
The POA&M Planning and Team milestones projections are read-only and shared
across signed dashboard roles. Raw Team Tracker APIs, evidence detail, and
candidate APIs remain restricted by their existing gates.
Before each cloud release, exercise `/api/v1/portfolio/poam-planning` through
an actual summary-only signed session against current managed Service Catalog
rows. Both IL2 and IL5 target dates must return ISO strings, and the Planning
and Team milestones views must load without a 500. A local imported-only
Catalog is insufficient for this check because it can supply string dates where
managed PostgreSQL rows supply `date` objects.
Compare the completed Planning count across Summary, Lead, Engineer, and Admin
modes; the Admin badge must stay pending until its Catalog and register requests
finish instead of displaying a partial tracker count.
Service Catalog shows only exact-grant service rows to assigned roles. The
reviewed Team Tracker baseline applies to `sse-cboms` only; service-impact
values use their recorded collection/group. A same-named group in another
collection cannot inherit SSE planning. Its Admin evidence drawer must not become a path
for assigned roles to fetch planning, candidate, or POA&M detail. Review the
signed role views against live data before service-team release.

### Evidence-only contract gate

For a read-only deployment without an approved complete assessment contract,
verify the assessment returns `assessment_run: null`, explicit missing facts,
and zero candidate/workstream/portfolio rows. Candidate CSV, workstream CSV,
portfolio CSV, and the compliance ZIP must return HTTP 422; the console must
disable those downloads and show the analyst-observation queue. Do not create
credentials or overlays and do not run an ingestion flow during this validation.
When a separately approved complete deployment contract is supplied, repeat the
export checks and reconcile every payload to the run manifest and evidence
fingerprints.

## Browser flows

For Service Catalog, apply migrations 022–024 before enabling
`enableServiceCatalog`. Confirm the table contains the existing 40 service
groups with imported planning context and distinguishes managed
revisions from imported values. Check Add, Edit, approval review, exact scoped
Lead proposals, read-only Engineer mode, and Summary denial. Test create,
publish, proposal, approval, rejection, stale revision, and self-approval
denial and intentional clearing of imported values in an isolated database;
do not add or edit live authored records during
read-only browser validation. A new managed group must have no fabricated
source files or routing and must receive an exact Admin group mapping before a
service role can access it. Verify the Admin evidence drawer opens only where
current files exist and its close button works. Compare source counts and
checksums before and after all three migrations. Planning status and dates are
operational assertions, not ATO or FIPS validation evidence.

For Admin group-to-service mapping, apply migration 021 before deploying with
`enableAdminGroupMapping=true`. Confirm the Admin view starts from the exact
40-service deployment seed and shows both product contexts, including the five
registered services with no source evidence. Confirm that every mapping target
renders its current-source-file and fingerprinted-source-file counts; a zero
fingerprinted count must render **Evidence gap** and coverage unknown, without
implying compliance, validation, authorization, product evidence, FIPS
evidence, or absence of risk. These are catalog inventory counts only. Confirm
the inventory-only disclaimer, no “CBOM source evidence” label, and Evidence
gap treatment for configured services with no source evidence. Confirm a direct
API fetch without an active-mode header returns 403 and the same API returns
200 with the proper Admin mode header. Confirm the disposable PostgreSQL count
test covers invalid, empty, historical, and separate-collection inputs. The
disposable PostgreSQL policy-lifecycle test
passed add, stale-revision denial, remap, retire, audit-chain, and immediate
next-request grant checks. With disposable policy revisions
only, verify an Admin can add, remap, and retire a paired exact Lead/Engineer
group with a reason; the audit event records actor, request ID, old/new mapping,
and revision. Concurrent stale revisions, unknown catalog groups, duplicate
targets, wildcard names, unsupported products, and a token or non-Admin caller
must be denied. A published change must affect the next signed request without
altering MyID memberships. Restore the original policy through a new audited
revision after the exercise; never delete revision history. Mapping and routing
labels must not appear as ATO, CMVP, or FIPS validation evidence.

For the staged OIDC group rollout, verify exact `fedsse-admins`,
`fedsse-external`, `fedsse-scr2-leads`, service lead, and service engineer
claims with separate Chrome sessions or Playwright fixtures. An unmatched
signed-in user must see no catalog data. External and SCR2 users may see
all-service Overview and POA&M summaries plus read-only POA&M Planning and
Team milestones. Direct Inventory, Service Catalog, candidate details,
exports, and raw tracker APIs must deny access.
Leads and engineers may see the same aggregates and their verified grant cards;
when the product-detail capability is enabled, detail must stay within their
exact collection/service/ATO grants. Check mixed memberships and direct ID
tampering.
For an identity with multiple exact access categories, verify `/auth/me`
offers only verified modes, blocks data routes until a mode is selected, and
shows the verified identity, active mode, and complete grant union in the
profile. Changing the browser mode must not add an unverified entitlement.
Admin must open all portfolio and Admin views without a product picker; Product
Lead and Product Engineer must see every verified service grant together in
their workspace without a product picker. Check that engineer mode is read
only even when the same identity also has lead or admin groups. With the
product-detail capability disabled, those workspaces may show verified grant
placeholders but must not fetch or imply evidence counts for a product.
Test revoke/restore and token persistence against isolated test data only. The
operational schemas in migrations 016–021 are applied and verified live.
Product-scoped catalog detail is enabled for exact grants; roster, lead review
proposals, and operational evidence notes remain disabled. Product candidate
output and exports still require a complete verified assessment contract. Test a lead's exact product-scoped
evidence-observation submission, engineer and cross-pair denial, a distinct
human administrator's approval/rejection, stale-item conflict, and the
append-only audit trail. These observations must remain separate from
assessment and POA&M conclusions. Local admin login must work on loopback and
fail in cloud configuration. Do not enable detailed evidence or writes while
exact service grants, MyID claim checks, or the operational access workflow
remain incomplete.

- [ ] Unauthenticated navigation redirects to login; local login returns safely
      to an internal path.
- [ ] Overview counts/charts load, refresh works, and light/dark modes remain
      legible.
- [ ] In a signed Summary session, Overview shows aggregate Catalog processing
      and component-category counts without service, document, component, or
      library identifiers. The former identifier-withholding panels must not
      appear. Summary attention rows must not link to restricted Inventory.
      A failed Overview or shared Planning request shows a retry message rather
      than a raw API, IdP, or load-balancer response, and a failed refresh does
      not leave stale counts presented as current.
- [ ] Inventory service, library, and heatmap views filter, sort, page, and open
      document/component drawers.
- [ ] Service Catalog lists all collection/service rows in Admin mode and only
      exact-grant rows in Lead/Engineer mode. Check search, owner/profile,
      IL2/IL5 status and date, impact risk, comments, publication state, and
      Add/Edit/proposal controls by role. Imported Team Tracker fields appear
      only for exact `sse-cboms` grants, and impact values match the exact
      collection/group. Approved managed values override imported fields.
- [ ] The Admin-only evidence drawer opens for rows with source files, pages
      documents and libraries without skipping rows, and closes by button,
      Escape, and backdrop. Assigned roles cannot reach its planning,
      candidate, or POA&M detail APIs through the Service Catalog.
- [ ] Target-module planning assertions are visibly labeled as non-findings;
      asserted active-certificate badges reflect verification conflicts instead
      of implying validation.
- [ ] Service Catalog module plans offer only exact module/version public
      references from the active evidence import. Verify certificate-backed and
      vendor-pipeline references, immutable imported-row matching, unverified
      custom targets, Lead proposal, separate Admin approval, and read-only
      Engineer/Summary Planning. Replace active public evidence in an isolated
      test database and confirm a stale approved plan stays visible but no
      longer enters active or pipeline lanes. Confirm a same-named group in
      another source collection cannot receive the plan. Public certificate and
      vendor statements do not establish deployment or service FIPS validation.
- [ ] In Service Catalog detail, confirm an approved plan shows the saved
      current and target module identities, live `evidence_state`, planning
      disposition, basis, and source URL. Replace a preset's public evidence
      in an isolated test database while reusing its key: the saved target must
      remain visible and the old evidence must render as superseded, not as
      the replacement option's module. Missing evidence state remains
      unverified. Certificate and pipeline comparisons require exact module
      versions, including rejection of a `+vendor-patch` suffix.
- [ ] POA&M workstream/candidate views, coverage gaps, filters, paging, drawers,
      and compliance ZIP/workstream CSV/asset CSV downloads follow the active
      assessment-contract gate.
- [ ] Risk Assessment opens its read-only POA&M subtab for each signed dashboard
      role. Confirm its impact chips report Critical, Moderate, and Other
      service-group counts and distinct current catalog document-record counts,
      without exposing group, owner, or lead identities in the POA&M response.
      Changing a Catalog date or risk category must change the counts after
      Refresh; planning windows must not invent a completion date. Every row
      remains noneligible and must not enable candidate exports or writes.
      Planning and Team milestones remain available to summary-only roles.
      Include representative imported and managed planning states with matching
      dates; exclude `not_applicable` and non-date rows even if a stale date
      remains. Verify this against the signed cloud Service Catalog after release.
- [ ] Exact `fedsse-admins` membership enables Admin; unmatched, external, and
      engineer accounts cannot see Admin or mutate catalog state.
- [ ] Product-scoped catalog detail verifies the current source SHA-256 routing
      decision for the requested exact product triple on every evidence query
      and direct ID. Every current file has audited routing;
      disposable PostgreSQL execution tests cover scoped queries. Assessment
      and export routes remain separately gated by a verified product contract.
      The exact 40-service registry supplies grant metadata and Admin mapping.
      Recheck MyID claims and the live role matrix before expanding access.
      Owner-declared labels and routing decisions do not prove authorization.
- [ ] With the applied roster/revoke schema and disabled-by-default application
      capability enabled only in isolated test data, generate a short-lived scoped credential
      in Admin, exercise one permitted read and one temporary overlay
      create/deactivate through the API hostname, then revoke it and confirm
      subsequent access returns `401`.
- [ ] After ingestion approval, create a dry-run ingestion batch through the public API, upload directly
      to its presigned S3 URLs, and confirm the ECS task reaches `succeeded`, all
      checksums verify, and the catalog comparison reports no unexpected delta.
- [ ] After ingestion approval, repeat the dry-run from Admin: folder discovery and browser checksumming
      complete, direct S3 upload succeeds without CORS errors, job state polls,
      and the selected job shows CloudWatch logs and the same comparison result.
- [ ] Primary navigation stays fixed on desktop and the bottom navigation works
      on a narrow viewport. Check keyboard focus, escape-to-close, 200% zoom,
      and reduced motion.
- [ ] No browser console errors, failed network requests, demo fallbacks, or
      stale-development/HMR assets appear in the production container.

## Assessment and release safety

- [ ] Candidate and evidence-gap labels remain visible and distinct.
- [ ] No output claims compliance, validation, closure, acceptance, or an AO
      decision based only on catalog evidence.
- [ ] The active target-module import checksum matches the authoritative PR #1
      planning payload; `done` and `vendor_dependency` remain planning states.
- [ ] Active public-authority and catalog-correlation evidence imports have
      claim links to the active target-module import after every planning refresh.
- [ ] IL2 mitigation dates use the farthest explicit IL2 date; IL5 stays context.
- [ ] Asset-level candidate evidence remains available beneath workstreams.
- [ ] Snapshot checksum and manifest are present and match the restored copy.
- [ ] Secrets, OIDC values, credentials, dumps, and sensitive `.env` files are
      excluded from the repository and logs.
- [ ] Shared snapshots exclude the entire `app_auth` schema.
