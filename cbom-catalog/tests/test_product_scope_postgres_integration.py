"""PostgreSQL integration coverage for exact-SHA product routing.

Set ``CBOM_INTEGRATION_DATABASE_URL`` to a disposable database with migrations
001–017 applied.  The fixture keeps all synthetic rows in one transaction and
rolls it back, so it never changes a shared test or live catalog.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from cbom_catalog.product_scope_queries import product_scope_ctes, source_file_scope_predicate

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - project dependency is normally installed
    psycopg = None


@pytest.fixture()
def database() -> Iterator[object]:
    url = os.environ.get("CBOM_INTEGRATION_DATABASE_URL")
    if not url or psycopg is None:
        pytest.skip("CBOM_INTEGRATION_DATABASE_URL is required for PostgreSQL integration tests")
    connection = psycopg.connect(url, row_factory=dict_row)
    try:
        if not connection.execute(
            "SELECT to_regclass('app_auth.evidence_product_scope_decision') AS relation"
        ).fetchone()["relation"]:
            pytest.skip("migration 017 is not applied to the disposable integration database")
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _seed(database: object) -> dict[str, int | str]:
    suffix = uuid.uuid4().hex[:12]
    collection = database.execute(
        """INSERT INTO source_collection (slug, display_name, root_uri)
           VALUES (%s, %s, %s) RETURNING id""",
        (f"scope-it-{suffix}", "Product scope integration", "s3://integration.invalid"),
    ).fetchone()
    collection_id = int(collection["id"])
    group = database.execute(
        """INSERT INTO service_group (source_collection_id, slug, display_name, source_path)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (collection_id, "brain", "Brain", "brain"),
    ).fetchone()
    group_id = int(group["id"])
    document = database.execute(
        """INSERT INTO document (sha256, byte_size, document_kind, parser_version)
           VALUES (%s, 1, 'cyclonedx', 'integration') RETURNING id""",
        ("d" * 52 + suffix[:12],),
    ).fetchone()
    document_id = int(document["id"])
    component = database.execute(
        """INSERT INTO component (identity_hash, name, version)
           VALUES (%s, 'shared-component', '1.0') RETURNING id""",
        ("c" * 52 + suffix[:12],),
    ).fetchone()
    component_id = int(component["id"])
    database.execute(
        """INSERT INTO document_component (document_id, component_id, bom_ref, source_bom_ref)
           VALUES (%s, %s, 'shared', 'shared')""",
        (document_id, component_id),
    )
    paths = {}
    for key, checksum in (("government", "1" * 64), ("defense", "2" * 64), ("missing", "3" * 64), ("stale", "4" * 64)):
        row = database.execute(
            """INSERT INTO source_file (
                    source_collection_id, service_group_id, document_id,
                    source_path, filename, media_type, byte_size,
                    content_sha256, parse_status, is_present
                ) VALUES (%s, %s, %s, %s, %s, 'application/json', 1, %s, 'linked', true)
                RETURNING id""",
            (collection_id, group_id, document_id, f"brain/{key}.json", f"{key}.json", checksum),
        ).fetchone()
        paths[key] = (int(row["id"]), checksum)
    for key, scopes in (("government", ["secure-access-government"]), ("defense", ["secure-access-defense"])):
        _, checksum = paths[key]
        database.execute(
            """INSERT INTO app_auth.evidence_product_scope_decision (
                    source_collection_id, service_group_id, source_path, source_sha256,
                    product_scope_ids, decision_basis, decision_reference
                ) VALUES (%s, %s, %s, %s, %s, 'owner default both', 'integration')""",
            (collection_id, group_id, f"brain/{key}.json", checksum, scopes),
        )
    # A stale exact-SHA decision must never expose a changed current source.
    stale_id, stale_checksum = paths["stale"]
    database.execute(
        """INSERT INTO app_auth.evidence_product_scope_decision (
                source_collection_id, service_group_id, source_path, source_sha256,
                product_scope_ids, decision_basis, decision_reference
            ) VALUES (%s, %s, 'brain/stale.json', %s, %s, 'owner default both', 'integration')""",
        (collection_id, group_id, stale_checksum, ["secure-access-government"]),
    )
    database.execute("UPDATE source_file SET content_sha256 = %s WHERE id = %s", ("5" * 64, stale_id))
    return {"collection_id": collection_id, "group_id": group_id, "document_id": document_id, "component_id": component_id, "slug": f"scope-it-{suffix}"}


def _source_paths(database: object, product_scope_id: str) -> list[str]:
    scope = product_scope_ctes(product_scope_id)
    return [
        row["source_path"]
        for row in database.execute(
            f"WITH {scope.sql} SELECT source_path FROM {scope.source_files} ORDER BY source_path",
            scope.params,
        ).fetchall()
    ]


def test_current_exact_sha_isolates_shared_document_component_and_lists(database: object) -> None:
    seed = _seed(database)
    assert _source_paths(database, "secure-access-government") == ["brain/government.json"]
    assert _source_paths(database, "secure-access-defense") == ["brain/defense.json"]

    for product_scope_id in ("secure-access-government", "secure-access-defense"):
        scope = product_scope_ctes(product_scope_id)
        direct = database.execute(
            f"""WITH {scope.sql}
                SELECT d.id FROM document d
                JOIN {scope.documents} sd ON sd.document_id = d.id
                WHERE d.id = %s""",
            (*scope.params, seed["document_id"]),
        ).fetchall()
        components = database.execute(
            f"WITH {scope.sql} SELECT component_id FROM {scope.components}", scope.params
        ).fetchall()
        assert [row["id"] for row in direct] == [seed["document_id"]]
        assert [row["component_id"] for row in components] == [seed["component_id"]]


def test_missing_and_stale_decisions_are_denied_for_direct_id_and_inventory_sql(database: object) -> None:
    seed = _seed(database)
    government = product_scope_ctes("secure-access-government")
    direct = database.execute(
        f"""WITH {government.sql}
            SELECT d.id FROM document d
            WHERE d.id = %s AND EXISTS (
                SELECT 1 FROM {government.source_files} sf WHERE sf.document_id = d.id
            )""",
        (*government.params, seed["document_id"]),
    ).fetchall()
    assert [row["id"] for row in direct] == [seed["document_id"]]
    # The list/inventory CTE remains syntactically executable and only includes
    # the current, granted file; missing and stale files are absent.
    inventory = database.execute(
        f"""WITH {government.sql}
            SELECT sf.source_path, d.id AS document_id
            FROM {government.source_files} sf
            JOIN document d ON d.id = sf.document_id
            ORDER BY sf.source_path""",
        government.params,
    ).fetchall()
    assert [(row["source_path"], row["document_id"]) for row in inventory] == [
        ("brain/government.json", seed["document_id"])
    ]
    predicate = source_file_scope_predicate("secure-access-government")
    assert database.execute(
        f"SELECT count(*) AS count FROM source_file sf WHERE {predicate.sql}", predicate.params
    ).fetchone()["count"] == 1
