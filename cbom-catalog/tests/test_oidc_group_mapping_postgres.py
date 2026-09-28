"""Disposable PostgreSQL coverage for the Admin OIDC mapping publish lifecycle.

Set ``CBOM_INTEGRATION_DATABASE_URL`` to a disposable database migrated through
021. This test commits only synthetic policy, user, and catalog rows. It
restores the prior active-policy pointer, but append-only revision and audit
records remain for the disposable database to preserve the real publish path.
Never point this test at an authoritative catalog.
"""
from __future__ import annotations

import ipaddress
import json
import os
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from cbom_catalog import api
from cbom_catalog.oidc_group_mapping import policy_sha256, service_rows

psycopg = pytest.importorskip("psycopg")
DSN = os.environ.get("CBOM_INTEGRATION_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="requires disposable migrated PostgreSQL DSN")


def _require_disposable_database(dsn: str) -> None:
    """Fail before fixture writes unless the DSN names a local disposable DB."""
    try:
        connection = conninfo_to_dict(dsn)
    except Exception as error:
        pytest.fail(f"CBOM_INTEGRATION_DATABASE_URL is invalid: {error}")
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
            "CBOM_INTEGRATION_DATABASE_URL must use a loopback host (and, if "
            "specified, loopback hostaddr) and a database named cbom_test_*; "
            "this test commits synthetic rows."
        )


def _groups(*, service_key: str, collection: str, service_group: str) -> dict:
    grant = {
        "source_collection": collection,
        "service_group": service_group,
        "product_scope_id": "secure-access-government",
        "boundary_name": "FedRAMP High/IL2",
    }
    return {
        "fedsse-admins": {"access": "admin"},
        "fedsse-external": {"access": "summary"},
        "fedsse-scr2-leads": {"access": "summary"},
        f"fedsse-{service_key}-leads": {
            "access": "lead", "service_key": service_key, "grants": [grant],
        },
        f"fedsse-{service_key}-engineers": {
            "access": "engineer", "service_key": service_key, "grants": [dict(grant)],
        },
    }


def test_admin_mapping_publish_lifecycle_is_versioned_audited_and_immediately_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish add/remap/retire with CAS and verify the next policy lookup."""
    suffix = uuid.uuid4().hex[:12]
    collection_slug = f"mapping-it-{suffix}"
    base_key, add_key = f"base-{suffix}", f"add-{suffix}"
    request_id = f"mapping-it-{suffix}"
    _require_disposable_database(DSN)
    with psycopg.connect(DSN, row_factory=dict_row) as database:
        if not database.execute(
            "SELECT to_regclass('app_auth.oidc_group_policy_revision') AS relation"
        ).fetchone()["relation"]:
            pytest.skip("migration 021 is required for Admin mapping integration")

        prior_active = database.execute(
            "SELECT revision_id FROM app_auth.oidc_group_policy_active WHERE singleton = 1"
        ).fetchone()
        collection_id = database.execute(
            "INSERT INTO source_collection (slug, display_name) VALUES (%s, %s) RETURNING id",
            (collection_slug, "Admin mapping integration"),
        ).fetchone()["id"]
        groups: dict[str, str] = {}
        for slug in ("base", "added", "remapped"):
            groups[slug] = database.execute(
                """INSERT INTO service_group (source_collection_id, slug, display_name, source_path)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (collection_id, f"{slug}-{suffix}", slug.title(), slug),
            ).fetchone()["id"]
        actor_id = database.execute(
            "INSERT INTO app_auth.app_user (email, display_name, status) VALUES (%s, 'Mapping Admin', 'active') RETURNING id",
            (f"mapping-admin-{suffix}@test.invalid",),
        ).fetchone()["id"]

        base_slug = f"base-{suffix}"
        added_slug = f"added-{suffix}"
        remapped_slug = f"remapped-{suffix}"
        baseline_groups = _groups(
            service_key=base_key, collection=collection_slug, service_group=base_slug,
        )
        baseline_hash = policy_sha256(baseline_groups)
        seed = database.execute(
            """INSERT INTO app_auth.oidc_group_policy_revision
               (policy_sha256, previous_sha256, groups, reason, actor_user_id, request_id)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (baseline_hash, "0" * 64, Jsonb(baseline_groups), "Synthetic initial policy.", actor_id, f"{request_id}-seed"),
        ).fetchone()
        database.execute(
            """INSERT INTO app_auth.oidc_group_policy_active (singleton, revision_id)
               VALUES (1, %s) ON CONFLICT (singleton) DO UPDATE SET revision_id = EXCLUDED.revision_id""",
            (seed["id"],),
        )
        database.commit()

        @contextmanager
        def connection():
            yield database

        principal = api.Principal(
            kind="human", subject="oidc:mapping-admin", role="admin", scopes=frozenset(),
            user_id=actor_id, email=f"mapping-admin-{suffix}@test.invalid",
        )
        request = SimpleNamespace(state=SimpleNamespace(request_id=request_id))
        deployment_policy = {"version": "integration", "groups": baseline_groups}
        monkeypatch.setenv("CBOM_ADMIN_GROUP_MAPPING_ENABLED", "true")
        monkeypatch.setenv("CBOM_OIDC_GROUP_SCOPE_JSON", json.dumps(deployment_policy))

        with monkeypatch.context() as scoped:
            scoped.setattr(api, "api_connection", connection)
            _, source, initial_revision = api._oidc_policy_document(database)
            assert source == "admin"

            added = api._publish_service_group_mapping(
                request, principal, action="add", service_key=add_key,
                reason="Add a synthetic service mapping.", expected_revision=initial_revision,
                source_collection=collection_slug, service_group=added_slug,
                product_scope_ids=["secure-access-defense"],
            )
            added_principal = api.Principal(
                kind="human", subject="oidc:added", role="viewer", scopes=frozenset(),
                oidc_groups=frozenset({f"fedsse-{add_key}-leads"}),
            )
            added_scope = api._assigned_scope_for(added_principal)
            assert added_scope["role"] == "lead"
            assert added_scope["grants"] == [{
                "source_collection": collection_slug,
                "service_group": added_slug,
                "product_scope_id": "secure-access-defense",
                "boundary_name": "IL5",
                "access": "lead",
            }]

            # A stale editor must not create a competing revision.
            with pytest.raises(api.HTTPException) as stale:
                api._publish_service_group_mapping(
                    request, principal, action="replace", service_key=add_key,
                    reason="Attempt a stale synthetic remap.", expected_revision=initial_revision,
                    source_collection=collection_slug, service_group=remapped_slug,
                    product_scope_ids=["secure-access-government"],
                )
            assert stale.value.status_code == 409

            remapped = api._publish_service_group_mapping(
                request, principal, action="replace", service_key=add_key,
                reason="Remap the synthetic service exactly.", expected_revision=added["revision"],
                source_collection=collection_slug, service_group=remapped_slug,
                product_scope_ids=["secure-access-government", "secure-access-defense"],
            )
            remapped_scope = api._assigned_scope_for(added_principal)
            assert remapped_scope["role"] == "lead"
            assert {
                (grant["service_group"], grant["product_scope_id"])
                for grant in remapped_scope["grants"]
            } == {
                (remapped_slug, "secure-access-government"),
                (remapped_slug, "secure-access-defense"),
            }
            assert not any(
                grant["service_group"] == added_slug
                for grant in remapped_scope["grants"]
            )
            retired = api._publish_service_group_mapping(
                request, principal, action="retire", service_key=add_key,
                reason="Retire the synthetic service mapping.", expected_revision=remapped["revision"],
            )

            policy, source, active_revision = api._oidc_policy_document(database)
            assert source == "admin"
            assert active_revision == retired["revision"]
            assert [row["service_key"] for row in service_rows(policy["groups"])] == [base_key]

            # The next request resolves from the active DB revision, not the
            # deployment seed. The retired group no longer grants access.
            retired_principal = api.Principal(
                kind="human", subject="oidc:retired", role="viewer", scopes=frozenset(),
                oidc_groups=frozenset({f"fedsse-{add_key}-leads"}),
            )
            effective = api._assigned_scope_for(retired_principal)
            assert effective["mode"] == "denied"

        revisions = database.execute(
            """SELECT policy_sha256, previous_sha256 FROM app_auth.oidc_group_policy_revision
               WHERE request_id = %s ORDER BY id""",
            (request_id,),
        ).fetchall()
        assert len(revisions) == 3
        assert revisions[1]["previous_sha256"] == revisions[0]["policy_sha256"]
        assert revisions[2]["previous_sha256"] == revisions[1]["policy_sha256"]
        actions = database.execute(
            """SELECT action FROM app_auth.audit_event
               WHERE request_id = %s ORDER BY id""",
            (request_id,),
        ).fetchall()
        assert [row["action"] for row in actions] == [
            "oidc_group_mapping.add", "oidc_group_mapping.replace", "oidc_group_mapping.retire",
        ]
        active = database.execute(
            """SELECT revision.id, revision.policy_sha256
               FROM app_auth.oidc_group_policy_active active
               JOIN app_auth.oidc_group_policy_revision revision ON revision.id = active.revision_id
               WHERE active.singleton = 1""",
        ).fetchone()
        assert retired["policy_version"].split(":")[1] == str(active["id"])

        # Leave a reusable disposable DB's active policy as it was. The test's
        # append-only records intentionally remain as a real audit trail.
        if prior_active is None:
            database.execute("DELETE FROM app_auth.oidc_group_policy_active WHERE singleton = 1")
        else:
            database.execute(
                "UPDATE app_auth.oidc_group_policy_active SET revision_id = %s, activated_at = now() WHERE singleton = 1",
                (prior_active["revision_id"],),
            )
        database.commit()
