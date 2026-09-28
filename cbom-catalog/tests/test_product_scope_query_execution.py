"""Disposable PostgreSQL execution coverage for product evidence scope CTEs.

Set ``CBOM_PRODUCT_SCOPE_TEST_DSN`` to a disposable PostgreSQL database.  The
fixture creates and drops a dedicated schema, so it never targets application
data.  CI may opt in with a temporary postgres service.
"""
from __future__ import annotations

import ipaddress
import os
import uuid

import pytest
from psycopg.conninfo import conninfo_to_dict

from cbom_catalog.product_scope_queries import product_scope_ctes

psycopg = pytest.importorskip("psycopg")
DSN = os.environ.get("CBOM_PRODUCT_SCOPE_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires disposable PostgreSQL DSN")


def _require_empty_disposable_database(dsn: str) -> None:
    """Protect the self-contained DDL fixture from shared catalog databases."""
    try:
        connection = conninfo_to_dict(dsn)
    except Exception as error:
        pytest.fail(f"CBOM_PRODUCT_SCOPE_TEST_DSN is invalid: {error}")
    host = str(connection.get("host") or "").casefold()
    hostaddr = str(connection.get("hostaddr") or "")
    database = str(connection.get("dbname") or connection.get("database") or "")
    try:
        hostaddr_is_loopback = not hostaddr or ipaddress.ip_address(hostaddr).is_loopback
    except ValueError:
        hostaddr_is_loopback = False
    if (
        host not in {"localhost", "127.0.0.1", "::1"}
        or not hostaddr_is_loopback
        or not database.startswith("cbom_test_")
    ):
        pytest.fail(
            "CBOM_PRODUCT_SCOPE_TEST_DSN must use a loopback host (and, if "
            "specified, loopback hostaddr) and a database named cbom_test_*; "
            "this fixture creates schema objects."
        )


@pytest.fixture()
def database():  # type: ignore[no-untyped-def]
    schema = f"scope_exec_{uuid.uuid4().hex}"
    _require_empty_disposable_database(DSN)
    with psycopg.connect(DSN, autocommit=True) as connection:
        if connection.execute("SELECT to_regnamespace('app_auth') AS schema").fetchone()[0]:
            pytest.skip(
                "test_product_scope_query_execution requires an empty disposable database; "
                "use the migrated-catalog integration suites for a migrated database"
            )
        connection.execute(f'CREATE SCHEMA "{schema}"')
        connection.execute(f'SET search_path TO "{schema}", public')
        connection.execute("CREATE SCHEMA app_auth")
        connection.execute("CREATE TABLE source_file (id bigint primary key, source_collection_id bigint, service_group_id bigint, document_id bigint, source_path text, source_uri text, content_sha256 char(64), is_present boolean, parse_status text)")
        connection.execute("CREATE TABLE document_component (id bigint primary key, document_id bigint, component_id bigint)")
        connection.execute("CREATE TABLE document_artifact (document_id bigint, artifact_id bigint)")
        connection.execute("CREATE TABLE app_auth.evidence_product_scope_decision (id bigint primary key, source_collection_id bigint, service_group_id bigint, source_path text, source_sha256 char(64), product_scope_ids text[], attributed_at timestamptz)")
        try:
            yield connection
        finally:
            connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
            connection.execute("DROP SCHEMA app_auth CASCADE")


def _seed(connection) -> None:  # type: ignore[no-untyped-def]
    government_sha, defense_sha = "a" * 64, "b" * 64
    connection.execute("INSERT INTO source_file VALUES (1, 10, 20, 100, 'shared.json', NULL, %s, true, 'loaded'), (2, 10, 20, 101, 'stale.json', NULL, %s, true, 'loaded'), (3, 10, 20, 102, 'missing.json', NULL, %s, true, 'loaded')", (government_sha, defense_sha, government_sha))
    connection.execute("INSERT INTO document_component VALUES (1, 100, 500), (2, 101, 501), (3, 102, 502)")
    connection.execute("INSERT INTO document_artifact VALUES (100, 600), (101, 601), (102, 602)")
    connection.execute("INSERT INTO app_auth.evidence_product_scope_decision VALUES (1,10,20,'shared.json',%s,ARRAY['secure-access-government'],now()), (2,10,20,'shared.json',%s,ARRAY['secure-access-defense'],now() + interval '1 second'), (3,10,20,'stale.json',%s,ARRAY['secure-access-government'],now())", (government_sha, government_sha, government_sha))


def _visible(connection, scope_id: str) -> tuple[list[int], list[int], list[int], list[int]]:  # type: ignore[no-untyped-def]
    scope = product_scope_ctes(scope_id)
    rows = connection.execute(
        f"WITH {scope.sql} SELECT (SELECT array_agg(id ORDER BY id) FROM {scope.source_files}), (SELECT array_agg(document_id ORDER BY document_id) FROM {scope.documents}), (SELECT array_agg(component_id ORDER BY component_id) FROM {scope.components}), (SELECT array_agg(artifact_id ORDER BY artifact_id) FROM {scope.artifacts})",
        scope.params,
    ).fetchone()
    return tuple(list(value or []) for value in rows)  # type: ignore[return-value]


def test_latest_exact_decision_isolates_shared_evidence_and_direct_ids(database) -> None:  # type: ignore[no-untyped-def]
    _seed(database)
    # The newer decision for the same current SHA supersedes the older one.
    assert _visible(database, "secure-access-government") == ([], [], [], [])
    assert _visible(database, "secure-access-defense") == ([1], [100], [500], [600])


def test_stale_and_missing_decisions_fail_closed(database) -> None:  # type: ignore[no-untyped-def]
    _seed(database)
    scope = product_scope_ctes("secure-access-government")
    # `stale.json` has a decision for a different checksum; `missing.json` has none.
    rows = database.execute(
        f"WITH {scope.sql} SELECT source_path FROM {scope.source_files} ORDER BY source_path",
        scope.params,
    ).fetchall()
    assert rows == []
