# Migration 016 change record

Applied 2026-09-25 18:40 UTC to the CBOM Workbench development database in
GovCloud account `135124134289`, region `us-gov-east-1`. This record contains
schema and aggregate verification only; it contains no database dump, user
records, secret, or source document.

| Check | Result |
| --- | --- |
| SQL file | `db/016_lead_review_proposals.sql` |
| Verified SHA-256 | `e1d29c22cea7f8c65955ea8f880d736af0a3a9787c9c1eac6ade7fff73811912` |
| ECS task | `arn:aws-us-gov:ecs:us-gov-east-1:135124134289:task/cbom-workbench-dev/53d56b65c7764185b4964a820dacfb86` |
| CloudWatch log | `/cbom-workbench/dev/jobs`, stream `job/job/53d56b65c7764185b4964a820dacfb86` |
| Task start / stop | 2026-09-25 18:40:24.526Z / 18:40:48.253Z; exit `0` |
| Before | Migrations 001–015; `schema_version=15` |
| After | One migration 016; `schema_version=16`; two review tables and four safeguards/triggers |
| Review records | Zero proposals; zero decisions |

The task decoded the exact migration file, checked its SHA-256, and ran only
`psql -X -v ON_ERROR_STOP=1 -f` for that file. Its log ends with `COMMIT`.
The existing image and web service were not changed. No ingestion or import
command ran.

## Authoritative-data continuity

All values were identical in the isolated preflight and postcheck:

| Measure | Before = after |
| --- | ---: |
| Present source files | 534 |
| Documents (including historical) | 593 |
| Artifacts | 414 |
| Components | 60,552 |
| Component occurrences | 291,121 |
| Fingerprints | 609 |
| Service groups | 40 |
| Active planning imports / team planning rows | 1 / 20 |
| Document checksum fingerprint | `0a88f6fa7f041f2d6f915ea9ab25b7fe` |
| Source checksum fingerprint | `a0b7497d6e1fabd90136e07f6daadc0d` |

The read-only localhost Overview also loaded after migration and displayed 40
service groups, 533 current evidence records, and 534/534 source fingerprint
coverage. That browser session used an older running UI; it does not verify
or release the staged OIDC or dual-product rendering code.
