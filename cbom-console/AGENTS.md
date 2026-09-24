<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## CBOM Workbench rules

- Catalog and assessment evidence remains read-only. All browser API requests,
  including authorized Admin mutations, must use the same-origin `/api/*`
  proxy; do not expose PostgreSQL, the internal FastAPI origin, AWS credentials,
  or application bearer tokens to the browser.
- Preserve the four primary read views—Overview, Inventory, Accountability, and
  POA&M—and the administrator-only Admin workspace. Candidate findings and
  evidence requests must remain visually and semantically distinct.
- Admin corpus ingestion must send only manifest/job-control requests through
  the proxy. File bytes upload directly to checksum-bound presigned private-S3
  URLs, and job status/logs/results are read through scoped API endpoints.
- Keep cloud task launch disabled for local click-through identities that do
  not map to a provisioned, auditable application user.
- Do not add demo/sample fallbacks when the API is unavailable.
- Keep desktop navigation fixed, mobile navigation reachable, tables horizontally
  scrollable, drawers keyboard operable, and light/dark tokens accessible.
- Read the installed Next.js documentation named above before framework changes,
  then run lint, non-incremental typecheck, production build, and the browser
  checks in `../cbom-catalog/docs/RELEASE_CHECKLIST.md`.
