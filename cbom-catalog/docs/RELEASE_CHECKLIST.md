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
```

Confirm API health and representative routes: dashboard, service-group register,
service detail, document components, library inventory/usage, team milestones,
assessment paging, issues, and all three exports.

## Browser flows

- [ ] Unauthenticated navigation redirects to login; local login returns safely
      to an internal path.
- [ ] Overview counts/charts load, refresh works, and light/dark modes remain
      legible.
- [ ] Inventory service, library, and heatmap views filter, sort, page, and open
      document/component drawers.
- [ ] Accountability groups by executive owner; owner/lead/IL2/IL5 filters and
      sorting work; POA&M impact, risk category, and comments render without
      changing those planning values; the service drawer shows import
      provenance, evidence, libraries, findings, and POA&M mappings.
- [ ] POA&M workstream/candidate views, coverage gaps, filters, paging, drawers,
      and compliance ZIP/workstream CSV/asset CSV downloads work.
- [ ] The invited administrator activates on first OIDC login; viewers do not
      see the Admin navigation or mutate catalog state.
- [ ] Generate a short-lived scoped credential in Admin, exercise one permitted
      read and one temporary overlay create/deactivate through the API hostname,
      then revoke it and confirm subsequent access returns `401`.
- [ ] Primary navigation stays fixed on desktop and the bottom navigation works
      on a narrow viewport. Check keyboard focus, escape-to-close, 200% zoom,
      and reduced motion.
- [ ] No browser console errors, failed network requests, demo fallbacks, or
      stale-development/HMR assets appear in the production container.

## Assessment and release safety

- [ ] Candidate and evidence-gap labels remain visible and distinct.
- [ ] No output claims compliance, validation, closure, acceptance, or an AO
      decision based only on catalog evidence.
- [ ] Team Tracker source checksum and mapping exceptions are current.
- [ ] IL2 mitigation dates use the farthest explicit IL2 date; IL5 stays context.
- [ ] Asset-level candidate evidence remains available beneath workstreams.
- [ ] Snapshot checksum and manifest are present and match the restored copy.
- [ ] Secrets, OIDC values, credentials, dumps, and sensitive `.env` files are
      excluded from the repository and logs.
- [ ] Shared snapshots exclude the entire `app_auth` schema.
