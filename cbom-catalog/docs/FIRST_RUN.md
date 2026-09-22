# First run

This is the shortest supported path from a new checkout to the authenticated
CBOM Workbench. It starts PostgreSQL, applies all ordered migrations, ingests the
current corpus through a read-only mount, and starts the FastAPI and Next.js
containers.

## Prerequisites

- Docker Desktop or Docker Engine with Compose v2
- at least 4 GB of free memory and enough disk for the source corpus, indexes,
  and the PostgreSQL volume
- the source corpus directory, or a compatible database snapshot
- PostgreSQL 16 `psql` and `pg_restore` clients only when using the host-side
  snapshot restore script

No host Python or Node.js installation is required for either container path.

## Start from source files

From `cbom-catalog/`:

```bash
cp .env.example .env
docker compose up -d postgres
docker compose run --rm migrate
docker compose --profile tools run --rm ingest
docker compose --profile tools run --rm target-modules
docker compose --profile tools run --rm target-public-evidence
docker compose --profile tools run --rm target-catalog-evidence
docker compose up -d --build api web
docker compose ps
```

The example environment points `CBOM_CORPUS_ROOT` at
`../OneDrive_1_9-18-2026` and mounts it read-only as `/data/SSE_CBOMS`. Change
that value when the corpus lives elsewhere. Keep `CBOM_SOURCE_COLLECTION`
stable across refreshes of the same logical dataset.

Open <http://127.0.0.1:3000>, then select **Continue in local development**.
Useful operational endpoints are:

- web health: <http://127.0.0.1:3000/healthz>
- API health: <http://127.0.0.1:8000/healthz>
- OpenAPI: <http://127.0.0.1:8000/docs>
- legacy rollback UI: <http://127.0.0.1:8000/ui/>

If a local tunnel or another project owns a default port, use loopback-only
overrides consistently:

```bash
POSTGRES_PORT=55433 API_PORT=8011 WEB_PORT=3015 docker compose up -d postgres
POSTGRES_PORT=55433 API_PORT=8011 WEB_PORT=3015 docker compose run --rm migrate
POSTGRES_PORT=55433 API_PORT=8011 WEB_PORT=3015 docker compose --profile tools run --rm ingest
POSTGRES_PORT=55433 API_PORT=8011 WEB_PORT=3015 docker compose --profile tools run --rm target-modules
POSTGRES_PORT=55433 API_PORT=8011 WEB_PORT=3015 docker compose --profile tools run --rm target-public-evidence
POSTGRES_PORT=55433 API_PORT=8011 WEB_PORT=3015 docker compose --profile tools run --rm target-catalog-evidence
POSTGRES_PORT=55433 API_PORT=8011 WEB_PORT=3015 docker compose up -d --build api web
```

Then open <http://127.0.0.1:3015>. Container-to-container addresses remain
`postgres:5432` and `api:8000`; only host ports change.

## Start from a database snapshot

Create an empty PostgreSQL 16 database, keep the supplied `.dump`, `.sha256`,
and `.manifest.json` together, then restore before starting the API:

```bash
DATABASE_URL='postgresql://cbom:password@127.0.0.1:55433/cbom_catalog' \
  ./scripts/restore_db_snapshot.sh /secure/path/cbom-catalog.dump
docker compose up -d --build api web
```

The restore script verifies SHA-256, refuses a non-empty target, and prints
post-restore counts. Compare them with the manifest before accepting the copy.
A database snapshot contains normalized catalog and assessment working data; it
does not replace retention of the exact source bytes.

## Confirm the first run

```bash
curl --fail http://127.0.0.1:8000/healthz
curl --fail http://127.0.0.1:8000/api/v1/stats
curl --fail http://127.0.0.1:8000/api/v1/fips/target-modules
docker compose logs --no-color --tail=100 api web
```

In the browser, verify login, Overview, Inventory, Accountability, POA&M,
service/document drawers, filters, pagination, theme switching, and all three
POA&M downloads. Use [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for the full
acceptance pass.

## Stop and reset

`docker compose down` stops the application but preserves the named database
volume. `docker compose down -v` permanently deletes that local volume; use it
only when a rebuild or tested restore is intended.
