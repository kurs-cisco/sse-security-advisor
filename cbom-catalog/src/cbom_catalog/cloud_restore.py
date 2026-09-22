"""Restore a checksummed catalog snapshot from a private S3 object."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

import boto3
import psycopg


def _database_url() -> str:
    required = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing database settings: {', '.join(missing)}")
    return psycopg.conninfo.make_conninfo(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        sslmode="require",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def restore(bucket: str, snapshot_key: str) -> None:
    database_url = _database_url()
    checksum_key = f"{snapshot_key}.sha256"
    manifest_key = f"{snapshot_key}.manifest.json"

    with tempfile.TemporaryDirectory(prefix="cbom-restore-") as temporary:
        snapshot_path = Path(temporary) / "catalog.dump"
        checksum_path = Path(temporary) / "catalog.dump.sha256"
        manifest_path = Path(temporary) / "catalog.dump.manifest.json"
        client = boto3.client("s3")
        client.download_file(bucket, snapshot_key, str(snapshot_path))
        client.download_file(bucket, checksum_key, str(checksum_path))
        client.download_file(bucket, manifest_key, str(manifest_path))

        expected = checksum_path.read_text(encoding="utf-8").split()[0]
        actual = _sha256(snapshot_path)
        if actual != expected:
            raise RuntimeError("Snapshot checksum verification failed")

        with psycopg.connect(database_url, password=os.environ["PGPASSWORD"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM pg_catalog.pg_tables "
                    "WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"
                )
                table_count = int(cursor.fetchone()[0])
        if table_count:
            raise RuntimeError(
                f"Refusing to restore into a non-empty database ({table_count} user tables found)"
            )

        sql_path = Path(temporary) / "catalog.sql"
        compatible_sql_path = Path(temporary) / "catalog-compatible.sql"
        subprocess.run(
            [
                "pg_restore",
                "--no-owner",
                "--no-acl",
                "--file",
                str(sql_path),
                str(snapshot_path),
            ],
            check=True,
        )

        # PostgreSQL 17 pg_dump emits this session setting, but PostgreSQL 16
        # does not recognize it. Removing the setting is safe: it controls the
        # restore session only and does not alter any catalog data or DDL.
        with sql_path.open("r", encoding="utf-8") as source, compatible_sql_path.open(
            "w", encoding="utf-8"
        ) as destination:
            for line in source:
                if line.strip() == "SET transaction_timeout = 0;":
                    continue
                destination.write(line)

        restore_environment = os.environ.copy()
        restore_environment["PGSSLMODE"] = "require"
        subprocess.run(
            [
                "psql",
                "--host",
                os.environ["PGHOST"],
                "--port",
                os.environ["PGPORT"],
                "--dbname",
                os.environ["PGDATABASE"],
                "--username",
                os.environ["PGUSER"],
                "--set",
                "ON_ERROR_STOP=on",
                "--single-transaction",
                "--file",
                str(compatible_sql_path),
            ],
            check=True,
            env=restore_environment,
        )
        print(f"Restored {snapshot_key} after SHA-256 verification; manifest={manifest_key}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", default=os.environ.get("CBOM_SNAPSHOT_BUCKET"))
    parser.add_argument("--snapshot-key", required=True)
    args = parser.parse_args()
    if not args.bucket:
        parser.error("--bucket or CBOM_SNAPSHOT_BUCKET is required")
    restore(args.bucket, args.snapshot_key)


if __name__ == "__main__":
    main()
