"""Execute staged product-scoped API SQL against a disposable PostgreSQL catalog.

This is intentionally separate from the unit tests.  It uses synthetic rows in
one transaction in a database that already has migrations 001--017, then rolls
the transaction back.  It never connects to a shared or production catalog.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from cbom_catalog import api
from cbom_catalog.access_control import Principal

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row


@pytest.fixture()
def database() -> Iterator[object]:
    dsn = os.environ.get("CBOM_INTEGRATION_DATABASE_URL")
    if not dsn:
        pytest.skip("CBOM_INTEGRATION_DATABASE_URL is required for disposable PostgreSQL tests")
    connection = psycopg.connect(dsn, row_factory=dict_row)
    try:
        if not connection.execute(
            "SELECT to_regclass('app_auth.evidence_product_scope_decision') AS relation"
        ).fetchone()["relation"]:
            pytest.skip("migration 017 is not applied to the disposable PostgreSQL database")
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _fetchers(connection: object):
    def fetch_all(sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
        return list(connection.execute(sql, params).fetchall())

    def fetch_one(sql: str, params: tuple[object, ...] = ()) -> dict[str, object] | None:
        return connection.execute(sql, params).fetchone()

    return fetch_all, fetch_one


def _seed(connection: object) -> dict[str, object]:
    suffix = uuid.uuid4().hex[:12]
    collection = connection.execute(
        "INSERT INTO source_collection (slug, display_name, root_uri) VALUES (%s, %s, %s) RETURNING id",
        (f"api-scope-{suffix}", "API product scope SQL", "s3://scope-test.invalid"),
    ).fetchone()
    group = connection.execute(
        "INSERT INTO service_group (source_collection_id, slug, display_name, source_path) VALUES (%s, %s, %s, %s) RETURNING id",
        (collection["id"], f"brain-{suffix}", "Brain", "brain"),
    ).fetchone()
    document = connection.execute(
        "INSERT INTO document (sha256, byte_size, document_kind, format_name, spec_version, parser_version) VALUES (%s, 1, 'cyclonedx', 'JSON', '1.5', 'scope-test') RETURNING id",
        ("d" * 52 + suffix,),
    ).fetchone()
    component = connection.execute(
        "INSERT INTO component (identity_hash, component_type, name, version) VALUES (%s, 'library', 'shared-crypto', '1.0') RETURNING id",
        ("c" * 52 + suffix,),
    ).fetchone()
    occurrence = connection.execute(
        "INSERT INTO document_component (document_id, component_id, bom_ref, source_bom_ref, is_subject, crypto_properties) VALUES (%s, %s, 'subject', 'subject', true, '{}'::jsonb) RETURNING id",
        (document["id"], component["id"]),
    ).fetchone()
    connection.execute(
        "INSERT INTO component_property (occurrence_id, ordinal, property_name, property_value) VALUES (%s, 1, 'fedramp:fips:crypto-relevant', 'true')",
        (occurrence["id"],),
    )
    artifact = connection.execute(
        "INSERT INTO artifact (canonical_key, artifact_type, name, version, digest) VALUES (%s, 'container', 'shared-image', '1.0', 'sha256:test') RETURNING id",
        (f"scope-artifact-{suffix}",),
    ).fetchone()
    connection.execute(
        "INSERT INTO document_artifact (document_id, artifact_id, role) VALUES (%s, %s, 'primary')",
        (document["id"], artifact["id"]),
    )
    connection.execute(
        "INSERT INTO dependency_edge (document_id, from_occurrence_id, to_occurrence_id, from_ref, to_ref, relationship_type, resolution_status) VALUES (%s, %s, %s, 'subject', 'subject', 'DEPENDS_ON', 'resolved')",
        (document["id"], occurrence["id"], occurrence["id"]),
    )
    connection.execute(
        "INSERT INTO external_record (document_id, artifact_id, record_type, external_id, provider, payload_sha256, data) VALUES (%s, %s, 'fips_tool_result', 'scope-test', 'test', %s, '{}'::jsonb)",
        (document["id"], artifact["id"], "e" * 64),
    )
    current = {
        "government": "1" * 64,
        "defense": "2" * 64,
        "unassigned": "3" * 64,
        "stale": "4" * 64,
    }
    for label, checksum in current.items():
        connection.execute(
            """INSERT INTO source_file (
                    source_collection_id, service_group_id, document_id, source_path,
                    filename, media_type, byte_size, content_sha256, parse_status, is_present
                ) VALUES (%s, %s, %s, %s, %s, 'application/json', 1, %s, 'linked', true)""",
            (collection["id"], group["id"], document["id"], f"brain/{label}.json", f"{label}.json", checksum),
        )
    for label, product in (("government", "secure-access-government"), ("defense", "secure-access-defense")):
        connection.execute(
            """INSERT INTO app_auth.evidence_product_scope_decision (
                    source_collection_id, service_group_id, source_path, source_sha256,
                    product_scope_ids, decision_basis, decision_reference
                ) VALUES (%s, %s, %s, %s, %s, 'owner default both', 'scope execution')""",
            (collection["id"], group["id"], f"brain/{label}.json", current[label], [product]),
        )
    # This decision does not match the current file checksum and must be ignored.
    connection.execute(
        """INSERT INTO app_auth.evidence_product_scope_decision (
                source_collection_id, service_group_id, source_path, source_sha256,
                product_scope_ids, decision_basis, decision_reference
            ) VALUES (%s, %s, 'brain/stale.json', %s, ARRAY['secure-access-government'], 'owner default both', 'stale')""",
        (collection["id"], group["id"], "5" * 64),
    )
    return {
        "collection": f"api-scope-{suffix}", "group": f"brain-{suffix}",
        "document_id": document["id"], "component_id": component["id"],
        "artifact_id": artifact["id"],
    }


def test_product_scoped_api_handler_sql_executes_and_hides_other_product_paths(database: object) -> None:
    seed = _seed(database)
    fetch_all, fetch_one = _fetchers(database)
    common = {
        "source_collection": seed["collection"], "service_group": seed["group"],
        "product_scope_id": "secure-access-government", "limit": 100, "offset": 0,
    }
    with patch.object(api, "_fetch_all", side_effect=fetch_all), patch.object(api, "_fetch_one", side_effect=fetch_one):
        documents = api.documents(path_query="government", kind=None, spec_version=None, **common)
        assert len(documents) == 1
        assert documents[0]["source_paths"] == ["brain/government.json"]
        assert api.documents(path_query="defense", kind=None, spec_version=None, **common) == []
        defense = {**common, "product_scope_id": "secure-access-defense"}
        defense_documents = api.documents(path_query="defense", kind=None, spec_version=None, **defense)
        assert len(defense_documents) == 1
        assert defense_documents[0]["source_paths"] == ["brain/defense.json"]
        assert api.documents(path_query="government", kind=None, spec_version=None, **defense) == []
        page = api.paged_documents(query="government", kind=None, spec_version=None, **common)
        assert page["total"] == 1 and page["items"][0]["source_paths"] == ["brain/government.json"]


def test_product_scoped_non_inventory_handler_sql_executes(database: object) -> None:
    seed = _seed(database)
    fetch_all, fetch_one = _fetchers(database)
    common = {
        "source_collection": seed["collection"], "service_group": seed["group"],
        "product_scope_id": "secure-access-government", "limit": 100, "offset": 0,
    }
    with patch.object(api, "_fetch_all", side_effect=fetch_all), patch.object(api, "_fetch_one", side_effect=fetch_one):
        assert api.components(query=None, purl=None, component_type=None, crypto_only=False, **common)[0]["component_id"] == seed["component_id"]
        assert api.artifacts(query=None, digest=None, **common)[0]["id"] == seed["artifact_id"]
        assert api.dependency_documents(**common)[0]["source_paths"] == ["brain/government.json"]
        detail = api.document_detail(seed["document_id"], include_raw=False, **{key: common[key] for key in ("source_collection", "service_group", "product_scope_id")})
        assert [row["source_path"] for row in detail["source_files"]] == ["brain/government.json"]
        graph = api.dependency_graph(seed["document_id"], relationship_type=["DEPENDS_ON"], node_limit=10, edge_limit=10, **{key: common[key] for key in ("source_collection", "service_group", "product_scope_id")})
        assert graph["document"]["source_paths"] == ["brain/government.json"] and len(graph["edges"]) == 1
        closure = api.dependency_closure(
            seed["document_id"], "subject", max_depth=3, limit=100,
            relationship_type=["DEPENDS_ON"],
            **{key: common[key] for key in ("source_collection", "service_group", "product_scope_id")},
        )
        assert len(closure) == 1
        records = api.external_records(record_type=None, provider=None, **common)
        assert len(records) == 1 and records[0]["record_type"] == "fips_tool_result"


def test_fips_scope_cte_executes_with_current_sha_product_visibility(database: object) -> None:
    seed = _seed(database)
    cte, params = api._fips_scope_cte(seed["collection"], seed["group"], "secure-access-government")
    rows = database.execute(
        cte + " SELECT source_path FROM scoped_source_files ORDER BY source_path",
        params,
    ).fetchall()
    assert [row["source_path"] for row in rows] == ["brain/government.json"]
    relevance = database.execute(
        cte + " SELECT explicitly_true, explicitly_false FROM occurrence_relevance",
        params,
    ).fetchone()
    assert relevance == {"explicitly_true": True, "explicitly_false": False}


def test_operational_observation_queues_execute_and_keep_product_history_separate(database: object) -> None:
    if not database.execute(
        "SELECT to_regclass('app_auth.operational_evidence_note') AS relation"
    ).fetchone()["relation"]:
        pytest.skip("migration 020 is required for observation queue SQL")
    suffix = uuid.uuid4().hex[:12]
    users = [
        database.execute(
            "INSERT INTO app_auth.app_user (email, status) VALUES (%s, 'active') RETURNING id",
            (f"{role}-{suffix}@test.invalid",),
        ).fetchone()["id"]
        for role in ("lead", "admin")
    ]
    note_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    for note_id, product in zip(
        note_ids, ("secure-access-government", "secure-access-defense"), strict=True
    ):
        database.execute(
            """INSERT INTO app_auth.operational_evidence_note
               (id,source_collection,service_group,product_scope_id,finding_id,
                source_tuple_digest,finding_observation_digest,policy_fingerprint,
                assessment_revision,note,lead_rationale,submitted_by_user_id)
               VALUES (%s,'sse-cboms','brain',%s,'FIPSF-EXAMPLE',%s,%s,%s,
                       'revision-1','Evidence requires review.','Lead checked the evidence.',%s)""",
            (note_id, product, "a" * 64, "b" * 64, "c" * 64, users[0]),
        )
    database.execute(
        """INSERT INTO app_auth.operational_evidence_note_decision
           (note_id,decision,reason,decided_by_user_id)
           VALUES (%s,'approved','Evidence note reviewed.',%s)""",
        (note_ids[0], users[1]),
    )
    fetch_all, _ = _fetchers(database)
    admin = Principal(kind="human", subject="test-admin", role="admin", scopes=frozenset(), user_id=users[1])
    with (
        patch.object(api, "_operational_evidence_notes_enabled", return_value=True),
        patch.object(api, "_evidence_note_scope_grant", return_value=(None, None, None)),
        patch.object(api, "_admin_principal", return_value=admin),
        patch.object(api, "_fetch_all", side_effect=fetch_all),
    ):
        lead_history = api.operational_evidence_notes(
            object(), "sse-cboms", "brain", "secure-access-government", limit=100
        )
        assert lead_history["total"] == 1
        assert lead_history["items"][0]["id"] == uuid.UUID(note_ids[0])
        assert lead_history["items"][0]["status"] == "approved"
        assert lead_history["items"][0]["decision_reason"] == "Evidence note reviewed."
        queue = api.admin_operational_evidence_notes(object(), limit=100)
        assert queue["total"] == 2
        assert {row["product_scope_id"] for row in queue["items"]} == {
            "secure-access-government", "secure-access-defense"
        }
