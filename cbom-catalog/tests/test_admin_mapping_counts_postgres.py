"""Admin mapping inventory counts against an isolated, migrated PostgreSQL DB.

Set CBOM_INTEGRATION_DATABASE_URL to a disposable database. The fixture rolls
back its synthetic rows; this must never be aimed at an authoritative catalog.
"""
from __future__ import annotations

import os
import uuid

import pytest
from psycopg.rows import dict_row

from cbom_catalog import api

psycopg = pytest.importorskip("psycopg")
DSN = os.environ.get("CBOM_INTEGRATION_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="requires disposable migrated PostgreSQL DSN")


def test_mapping_counts_are_exact_catalog_inventory_not_product_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    with psycopg.connect(DSN, row_factory=dict_row) as database:
        suffix = uuid.uuid4().hex[:12]
        ids = []
        for collection_slug in (f"map-a-{suffix}", f"map-b-{suffix}"):
            collection_id = database.execute(
                "INSERT INTO source_collection (slug, display_name) VALUES (%s, 'Mapping count test') RETURNING id",
                (collection_slug,),
            ).fetchone()["id"]
            group_id = database.execute(
                """INSERT INTO service_group (source_collection_id, slug, display_name, source_path)
                   VALUES (%s, 'sample', 'Sample', 'sample') RETURNING id""",
                (collection_id,),
            ).fetchone()["id"]
            ids.append((collection_slug, collection_id, group_id))

        def add_file(collection_id: int, group_id: int, path: str, status: str,
                     checksum: str | None, present: bool) -> None:
            database.execute(
                """INSERT INTO source_file (
                       source_collection_id, service_group_id, source_path, filename,
                       media_type, byte_size, parse_status, content_sha256, is_present
                   ) VALUES (%s, %s, %s, %s, 'application/json', 1, %s, %s, %s)""",
                (collection_id, group_id, path, path, status, checksum, present),
            )

        _, first_collection, first_group = ids[0]
        _, second_collection, second_group = ids[1]
        add_file(first_collection, first_group, "sample/invalid.json", "invalid", None, True)
        add_file(first_collection, first_group, "sample/empty.json", "empty", None, True)
        add_file(first_collection, first_group, "sample/linked.json", "linked", "a" * 64, True)
        add_file(first_collection, first_group, "sample/historical.json", "linked", "b" * 64, False)
        add_file(second_collection, second_group, "sample/other.json", "linked", "c" * 64, True)

        monkeypatch.setattr(api, "_fetch_all", lambda sql, params=(): list(database.execute(sql, params).fetchall()))
        rows = {row["source_collection"]: row for row in api._group_mapping_service_options()
                if row["source_collection"] in {ids[0][0], ids[1][0]}}
        assert rows[ids[0][0]]["current_source_files"] == 3
        assert rows[ids[0][0]]["fingerprinted_source_files"] == 1
        assert rows[ids[1][0]]["current_source_files"] == 1
        assert rows[ids[1][0]]["fingerprinted_source_files"] == 1
        database.rollback()
