# Operational access schema change record

This record describes the schema application at that time. The later
[diagnostic-stage application release](CHANGE_RECORD_2026-09-26_OIDC_DIAGNOSTIC_DEPLOYMENT.md)
kept service access disabled.

Applied 2026-09-26 to the CBOM Workbench GovCloud development database
(`135124134289`, `us-gov-east-1`). The owner authorized operational access,
lead review, and audit schema changes while keeping authored catalog,
assessment, and planning data unchanged. This record covers schema only; the
staged API and console have not been deployed and their product-detail access
switch remains off.

| Migration | SHA-256 | Scope |
| --- | --- | --- |
| `db/018_product_scoped_lead_review_proposals.sql` | `1610e91b55cf5e4ac5dd311b384bf58a34386b3f0a7ec245c8ba720d7f1a4df6` | Require exact product and authorization reference on future strict proposals; live proposal count was zero. |
| `db/019_operational_access_roster.sql` | `a8592f35f02368d388bc321ae68499d8767746bc35dda4d9f6de25cabde9cd54` | Append-only verified-role snapshots and revoke/restore decisions. |
| `db/020_operational_evidence_notes.sql` | `4e996809a07a602c69428a278096207f2e08e113b9170db2ff6e7bbaedd5e8d8` | Append-only product-scoped finding observations and separate-administrator decisions. |

The files were tested in order against disposable PostgreSQL 16. A private
one-off ECS job using the existing named database secret references decoded
and checked each exact file SHA-256, asserted the schema-17 and source baseline,
applied 018–020 in order, and checked schema 20, all five append-only/separate
decision triggers, and the authoritative continuity measures. It exited 0:

- Task: `arn:aws-us-gov:ecs:us-gov-east-1:135124134289:task/cbom-workbench-dev/c74067d59c534840bb8d86f2affb5904`
- Log: `/cbom-workbench/dev/jobs`, `job/job/c74067d59c534840bb8d86f2affb5904`

A second read-only one-off ECS task independently checked schema 20, all four
new operational tables, empty roster/action/note/decision and proposal tables,
five triggers, 534 routing decisions, and unchanged source/document/planning
measures. It exited 0:

- Task: `arn:aws-us-gov:ecs:us-gov-east-1:135124134289:task/cbom-workbench-dev/2abf5ab7e47b43e69b7fb6d3a475815b`
- Log: `/cbom-workbench/dev/jobs`, `job/job/2abf5ab7e47b43e69b7fb6d3a475815b`

| Continuity measure | Before = after |
| --- | ---: |
| Present files / product routing decisions | 534 / 534 |
| Source checksum fingerprint | `a0b7497d6e1fabd90136e07f6daadc0d` |
| Document checksum fingerprint | `0a88f6fa7f041f2d6f915ea9ab25b7fe` |
| Team service-impact rows | 20 |
| Lead proposals / decisions | 0 / 0 |
| New roster snapshots / access actions / evidence notes / note decisions | 0 / 0 / 0 / 0 |

No source corpus, document, planning import, assessment, candidate, or POA&M
record was changed. Schema availability does not activate OIDC service grants,
product detail, roster mutation, or lead observation submission. Those remain
subject to application tests, live read-only role/view verification, and the
actual MyID `fedsse-` claim before deployment.
