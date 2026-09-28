# Dual-product routing operational change record

Applied 2026-09-26 in the CBOM Workbench GovCloud development database
(`135124134289`, `us-gov-east-1`). The owner directed that existing and new
`sse-cboms` files default to both Secure Access for Government (`FedRAMP
High/IL2`) and Secure Access for Defense (`IL5`), while a later authorized
uploader may select one or both. These are routing labels, not authorization
package, assessment, CMVP, or compliance evidence.

| Check | Result |
| --- | --- |
| Schema file | `db/017_product_scoped_evidence.sql` |
| Schema file SHA-256 | `61c7d623800cd480aba6000b238364c84cadc12b294b7eb07208ee8479b86f0f` |
| Schema ECS task | `arn:aws-us-gov:ecs:us-gov-east-1:135124134289:task/cbom-workbench-dev/c8044bbbf80f465183d21760fc16898c` |
| Schema log | `/cbom-workbench/dev/jobs`, `job/job/c8044bbbf80f465183d21760fc16898c` |
| Schema outcome | Exit 0; version 16 → 17; 017 recorded once; routing decisions 0; legacy batch selections NULL |
| Backfill file | `ops/backfill_existing_product_scopes_20260926.sql` |
| Backfill file SHA-256 | `70d3fcfaa40d331d875945a8476b19c03c9a8e11f944e02aabe191b20c5f06a1` |
| Canonical current-file manifest SHA-256 | `3cfb938f667f165cb980090f5371fdfa724d488f4e8672e09fa2301c4e34771a` |
| Backfill ECS task | `arn:aws-us-gov:ecs:us-gov-east-1:135124134289:task/cbom-workbench-dev/8f4af0ee305648cd9421df063958d1e8` |
| Backfill log | `/cbom-workbench/dev/jobs`, `job/job/8f4af0ee305648cd9421df063958d1e8` |
| Backfill transaction | Committed 534 exact `(collection, service group, path, current source SHA-256)` routing decisions and audit event 15 |
| Independent verification task | `arn:aws-us-gov:ecs:us-gov-east-1:135124134289:task/cbom-workbench-dev/e6aac49e96fc4a219b295bcda4edf810` |
| Independent verification log | `/cbom-workbench/dev/jobs`, `job/job/e6aac49e96fc4a219b295bcda4edf810`; exit 0 |

The backfill script ran with an exact file SHA-256 check and the separately
measured canonical manifest digest. It locked current source identities and
routing decisions from preflight through commit, preserved any valid later
uploader selection, and wrote only `app_auth` operational records. Audit event
15 records the owner instruction, the declared on-behalf-of user, manifest
digest, and database executor (`cbom_admin` as `session_user` and
`current_user`). No ingestion, deployment, source update, planning import, or
assessment write ran.

The backfill ECS task exited 3 **after its transaction committed and its
postcondition block passed**: a subsequent read-only audit print query used
an invalid SQL operator precedence. The independent read-only task corrected
that query, asserted exact-file coverage and unchanged authoritative-data
measures, and exited 0. The backfill was not rerun live.

| Measure | Before = after |
| --- | ---: |
| Present source files / service groups | 534 / 40 |
| Documents / artifacts / components | 593 / 414 / 60,552 |
| Active service-impact imports / team rows | 1 / 20 |
| Source checksum fingerprint | `a0b7497d6e1fabd90136e07f6daadc0d` |
| Document checksum fingerprint | `0a88f6fa7f041f2d6f915ea9ab25b7fe` |
| Lead review proposals / decisions | 0 / 0 |
| Legacy batches with a product selection | 0 |

The checked-in OIDC service-group deployment switch remains off. The staged
API's product-detail capability also remains off: product attribution alone
does not make pair-scoped catalog queries, direct IDs, review proposals, FIPS
assessments, or exports safe for an assigned product scope. Chief Architect
and Compliance signoff covered only schema 017 and this routing backfill.
