# Operations and deployment

## Local Docker workflow

```bash
cp .env.example .env
docker compose up -d postgres
docker compose run --rm migrate
docker compose --profile tools run --rm ingest
docker compose up -d --build api web
```

The source mount is read-only. PostgreSQL data is stored in the named
`postgres-data` volume. `docker compose down` keeps it; `docker compose down -v`
deletes the database and should be used only when a full rebuild is intended.
The host binding defaults to `127.0.0.1:55432`; container-to-container connections
continue to use `postgres:5432`. The API also binds only to loopback, on port 8000
unless `API_PORT` is changed.

To inspect the database:

```bash
docker compose exec postgres psql -U cbom -d cbom_catalog
```

## Re-ingestion

Ingestion is checksum-gated and idempotent by exact SHA-256:

- every discovered file is read and SHA-256 verified against its collection/path
  record before parsing;
- unchanged bytes update only run/verification metadata and increment
  `files_unchanged`; they are not parsed or normalized again;
- changed bytes create a new document and update that path to the new document;
- every checksum observed at a path remains in `source_file_fingerprint`;
- parser failures update the source-file status and add an issue;
- one transaction per file prevents partial documents.

Reading the bytes is deliberate: trusting only size or modification time can miss
content changes and would weaken the integrity guarantee. The optimization removes
JSON parsing and relational normalization, not cryptographic verification.

Normal refresh:

```bash
docker compose --profile tools run --rm ingest
```

Deliberate parser-validation pass over unchanged bytes:

```bash
docker compose --profile tools run --rm ingest \
  cbom-catalog ingest /data/SSE_CBOMS --collection sse-cboms --force-reprocess
```

`CBOM_FORCE_REPROCESS=true` is the environment equivalent. A forced run is stored
on `ingest_run`, so it remains distinguishable from an ordinary data refresh.
It reruns parsing but does not replace an existing normalized document with the
same checksum. For a material mapping change, ingest into a new database/volume
and compare it before promoting the rebuild.

Migration 006 backfills one checksum observation for each source path from the
catalog's then-current state. It cannot reconstruct checksum changes that occurred
before the migration; complete per-path history accumulates from that point on.

If a file cannot be read or a forced reparse fails, the last known checksum and
good document link are preserved where possible; the failure is recorded in
`ingest_issue` instead of erasing prior evidence.

Collection names are stable provenance identities. Service groups are scoped to
their collection, so importing `TEAM/a.json` from two collections does not merge
or overwrite the folder records. Reuse the same `--collection` only when the new
root is intentionally another observation of that logical collection.

Normal refreshes retain unobserved paths. A successful full
`--authoritative-snapshot` refresh marks unobserved collection paths historical
with `is_present=false` while preserving document and fingerprint history. Never
use that option for a partial corpus.

If normalization logic changes materially, use a new database/volume for the
rebuild until migration behavior is defined. The parser version on every document
makes mixed versions detectable.

## Asynchronous cloud ingestion

Cloud corpus additions use the Admin workspace or the supplied
`scripts/submit_ingestion_batch.py` client. The control plane accepts only a
canonical manifest and job-control requests; browser/client bytes go directly
to checksum-bound presigned `PUT` URLs below private
`transfer/ingestion/<batch-id>/` objects. After every expected object exists, a
submit request launches the pinned one-off ECS job task.

Use `dry_run=true` first. The worker downloads to ephemeral storage, verifies
size and SHA-256 for every object, parses an inventory, and compares collection,
path, and checksum with current `source_file` rows without calling
`ingest_root`. A committed job invokes the normal checksum-gated ingester only
after the same validation. Never set `authoritative_snapshot=true` for a partial
collection.

Operational checks:

- confirm the batch reaches `succeeded` and its verified count equals its
  expected count;
- inspect bounded logs/results through the Admin/API status routes rather than
  giving browsers AWS credentials;
- investigate a task that remains `queued`, `validating`, or `running` through
  ECS service/task events and `/cbom-workbench/dev/jobs` CloudWatch logs;
- retain audit/job rows in the environment-local `app_auth` schema, while the
  temporary S3 lifecycle expires uploaded objects; and
- revoke short-lived automation credentials after verification.

See [INGESTION_AND_ASSESSMENT.md](INGESTION_AND_ASSESSMENT.md) for endpoint and
manifest details and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for the API
and browser dry-run acceptance flow.

## Raw data policy

For the current ~305 MiB corpus, storing raw JSONB is convenient. At larger scale:

1. store immutable source objects in S3-compatible object storage;
2. keep SHA-256, object URI, byte size, format, and normalized facts in Postgres;
3. set `CBOM_STORE_RAW_JSON=false` and `CBOM_SOURCE_URI` to that immutable prefix;
4. use Parquet snapshots for large analytical scans.

Do not discard exact source bytes solely because JSONB exists: JSONB normalizes
whitespace and object ordering and is not a byte-for-byte archive.

## Cloud/container mapping

| Local component | Cloud equivalent |
|---|---|
| PostgreSQL container | Managed PostgreSQL such as RDS/Aurora or Cloud SQL |
| Read-only bind mount | Versioned object-storage prefix or read-only persistent volume |
| One-shot ingest service | Kubernetes Job, ECS task, or scheduled batch job |
| FastAPI container | Kubernetes Deployment, ECS service, Cloud Run, or App Service |
| Docker secret values | Secret manager plus workload identity |

Set `DATABASE_HOST`/`DATABASE_PORT` plus the `POSTGRES_*` credentials for a managed
database, or provide `DATABASE_URL` when running the CLI outside Compose. Apply all
ordered `db/NNN_*.sql` migrations through `db/migrate.sh` before starting a new API
image.

`PYTHON_IMAGE`, `POSTGRES_IMAGE`, and `CBOM_CATALOG_IMAGE` are overrideable. Use
digest-pinned values in a production deployment.

## Security baseline

- Replace the example credentials; never publish port 5432 to the internet.
- Put the web service behind the organization's TLS and OIDC/SSO ingress. Run
  the API with `CBOM_ENVIRONMENT=production`, `CBOM_API_AUTH_MODE=bearer`, and a
  random `CBOM_API_BEARER_TOKEN` of at least 32 characters shared only with the
  Next.js server. The API fails closed if production authentication is absent.
  Trusted identity-aware proxies may instead use `CBOM_API_AUTH_MODE=proxy`,
  `CBOM_AUTH_PROXY_SECRET`, and `X-Authenticated-User`.
- Configure `CBOM_CORS_ORIGINS` only when a separate browser origin is required;
  the same-origin Next.js proxy does not require CORS. Production requests are
  rate-limited by default and emit request-ID/subject access logs.
- Raw-document API responses are disabled by default. Enabling
  `CBOM_API_ALLOW_RAW=true` should require a privileged upstream route.
- Use separate migration, ingestion, read/write API, and read-only analyst roles.
- Consider row-level security if service groups require tenant isolation.
- Treat paths, registry names, source URLs, and supplier metadata as potentially
  sensitive. Avoid copying raw payloads into general application logs.
- Scan the API image and pin image digests in production.

## Backup and recovery

- Back up the database with the managed-service facility or `pg_dump`.
- Retain the source corpus/object versions independently; the database can then be
  rebuilt and verified by SHA-256.
- Test restore plus a small set of known component/artifact queries.
- Record schema version, application image digest, and parser version with each
  backup or exported analytical snapshot.

Use `scripts/export_db_snapshot.sh` to create a custom-format dump, SHA-256
sidecar, and JSON manifest. Restore only into an empty database with
`scripts/restore_db_snapshot.sh`. See [DATABASE_SNAPSHOTS.md](DATABASE_SNAPSHOTS.md).

## Monitoring

Monitor failed ingest runs, asynchronous batches that fail or stop progressing,
checksum-verification errors, `ingest_issue` counts, temporary-object growth,
API latency, long recursive queries, and autovacuum health. The `/healthz`
endpoint checks database connectivity; `/api/v1/stats` provides catalog-level
counts.
