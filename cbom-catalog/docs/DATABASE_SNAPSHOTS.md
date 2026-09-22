# Database snapshot sharing

Use a database snapshot to distribute a verified, query-ready copy of the
catalog without forcing every recipient to parse the corpus. Treat it as
sensitive working evidence: it can contain internal paths, component metadata,
tracker ownership, and candidate assessment records.

## Create the snapshot bundle

With the Compose PostgreSQL service running:

```bash
./scripts/export_db_snapshot.sh /secure/path/cbom-catalog.dump
```

The command creates three mode-`0600` files:

- `cbom-catalog.dump` — PostgreSQL custom-format archive;
- `cbom-catalog.dump.sha256` — byte-integrity sidecar; and
- `cbom-catalog.dump.manifest.json` — schema, migration, source collection,
  latest ingest, and key count metadata.

The manifest explicitly says that exact raw source bytes are not included. Keep
the immutable corpus/object-store versions independently.

The `app_auth` schema is deliberately excluded. Shared bundles never contain
user identities, API credential digests, administrator overlays, or access
audit events. After restore, apply migrations and bootstrap administrators in
the destination environment through its own identity provider.

## Publication gate

Before sharing:

1. confirm the latest ingest run is completed and represents the intended
   collection/root;
2. compare manifest counts with `/api/v1/stats` and the dashboard;
3. scan the manifest and restored UI for environment-sensitive paths or owner
   data and obtain the required data-owner approval;
4. store the bundle in a private, versioned, access-logged, encrypted location;
5. record who exported it, why, and the retention/expiry date; and
6. never commit a real dump or secret-bearing `.env` file to source control.

## Restore and validate

Use PostgreSQL 16 and an empty target database:

```bash
DATABASE_URL='postgresql://user:password@host:5432/cbom_catalog' \
  ./scripts/restore_db_snapshot.sh /secure/path/cbom-catalog.dump
```

The restore refuses a database that already contains user tables, verifies the
SHA-256 sidecar, applies the archive without source ownership/ACLs, and prints
post-restore counts. Compare those counts to the manifest. Then start the API
and web console and complete [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).

Do not run migrations before restoring into an empty database: doing so creates
tables and triggers the safety refusal. After a successful restore, apply only
newer repository migrations, if any, and retain both the original dump and a
record of the post-restore migration versions.

## Compatibility and recovery

- Restore to PostgreSQL 16 unless a newer-version migration is tested.
- The archive is an application snapshot, not a substitute for managed RDS
  automated backups, point-in-time recovery, or retained source objects.
- Keep the previous database untouched until health, counts, representative
  document/component queries, Accountability joins, assessment summaries, and
  downloads are accepted.
- A checksum proves the dump was not changed after export; it does not attest to
  source truth, CMVP validation, or an assessor decision.
