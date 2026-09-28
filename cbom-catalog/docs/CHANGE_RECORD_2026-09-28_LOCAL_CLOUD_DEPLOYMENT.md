# Local and cloud deployment — 2026-09-28

## Release

- Cloud development stack `cbom-workbench-dev`: image tag `deploy-20260928-11`, ECS web task revision 42, CloudFormation `UPDATE_COMPLETE`, ECS steady at 1/1, and public `/healthz` HTTP 200. The CDK diff changed only ECS task definition image references. The catalog image has the same config and layer digests as image 10; the web image includes the local-login host check fix.
- Local Compose project `cbom-catalog-final`: rebuilt API and web images, applied schema migrations 016–021, and recreated the canonical API and web containers on localhost ports 8000 and 3000. Both health checks return HTTP 200. A private pre-migration database backup was kept outside the repository at `/tmp/cbom-local-predeploy-20260928.dump`.
- The local API receives the exact 83-group deployment policy through an ignored `cbom-catalog/.env` file. `docker-compose.yml` passes the nonsecret policy and Admin mapping capability to the API. Local login remains a one-click administrator mode; it does not create MyID claims or permit a local login in cloud configuration. The local mapping view is read-only for the local principal.

## Verification

- Local browser: localhost one-click login succeeds; Overview and Admin navigation load; Admin Service mappings shows policy `2026-09-27.2` and 1–10 of 40 mappings. The URL host check accepts localhost in the production-built local container and denies a non-loopback host. Console tests (7), lint, typecheck, and production Docker builds pass.
- Local database: schema version 21 with 21 migration records. Before and after deployment: 40 service groups, 534 source files, 534 fingerprinted source files, 533 unique documents, 282,688 component occurrences, and zero ingest errors. No ingestion or authored-data action was run.
- Cloud browser: signed Overview shows 40 service groups, 533 evidence records, 6,169 crypto occurrences, and 717 unique crypto assets. Signed Admin Service mappings shows 1–10 of 40 mappings at policy revision `b7457030cbbd499650362e5dbd22f2a3bf1d6ea0b94103c175524458d36265b0`. Infrastructure tests (10) and build pass.

Access-roster actions, Lead review proposals, and operational evidence notes remain disabled in the cloud configuration. No source corpus, planning, assessment, POA&M, mapping revision, or user-access record was changed by this release.
