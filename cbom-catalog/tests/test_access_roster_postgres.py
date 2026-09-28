from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from psycopg.rows import dict_row

from cbom_catalog.access_roster import AccessRosterError, change_access, record_snapshot
from cbom_catalog import api

psycopg = pytest.importorskip("psycopg")
DSN = os.environ.get("CBOM_ACCESS_ROSTER_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires disposable migrated PostgreSQL DSN")


@pytest.fixture()
def database():  # type: ignore[no-untyped-def]
    with psycopg.connect(DSN, row_factory=dict_row) as connection:
        connection.execute("TRUNCATE app_auth.audit_event, app_auth.user_access_action, app_auth.access_roster_snapshot, app_auth.api_credential, app_auth.app_user RESTART IDENTITY CASCADE")
        connection.execute("INSERT INTO app_auth.app_user (email,status) VALUES ('a@test','active'),('b@test','active'),('c@test','active')")
        yield connection
        connection.rollback()


def test_roster_state_machine(database) -> None:  # type: ignore[no-untyped-def]
    for user_id, role in ((1, "admin"), (2, "admin"), (3, "engineer")):
        record_snapshot(database, user_id=user_id, effective_role=role, grants=[], policy_version="v1", policy_fingerprint=(str(user_id) * 64)[:64])
    record_snapshot(database, user_id=1, effective_role="admin", grants=[], policy_version="v1", policy_fingerprint=("1" * 64))
    assert database.execute("SELECT count(*) AS count FROM app_auth.access_roster_snapshot WHERE app_user_id=1").fetchone()["count"] == 1
    database.execute("INSERT INTO app_auth.api_credential (id,owner_user_id,name,token_prefix,token_digest,scopes,expires_at) VALUES (gen_random_uuid(),3,'t','pref','a' || repeat('b',63),ARRAY['catalog:read'],now()+interval '1 day')")
    change_access(database, actor_user_id=1, target_user_id=3, action="revoke", reason="Operational access revocation.", request_id="r1")
    assert database.execute("SELECT revoked_at IS NOT NULL AS revoked FROM app_auth.api_credential WHERE owner_user_id=3").fetchone()["revoked"]
    change_access(database, actor_user_id=1, target_user_id=3, action="restore", reason="Operational access restored.", request_id="r2")
    assert database.execute("SELECT revoked_at IS NOT NULL AS revoked FROM app_auth.api_credential WHERE owner_user_id=3").fetchone()["revoked"]
    with pytest.raises(AccessRosterError):
        change_access(database, actor_user_id=1, target_user_id=3, action="restore", reason="Operational access restored.", request_id="r3")
    change_access(database, actor_user_id=1, target_user_id=2, action="revoke", reason="Second administrator revoked.", request_id="r4")
    with pytest.raises(AccessRosterError, match="last recently verified"):
        change_access(database, actor_user_id=2, target_user_id=1, action="revoke", reason="Last administrator revoked.", request_id="r5")
    assert database.execute("SELECT count(*) AS count FROM app_auth.audit_event WHERE resource_type='app_user'").fetchone()["count"] == 3


def test_admin_users_query_handles_joined_actor_identity(database, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(api, "_admin_principal", lambda request, scope: None)
    monkeypatch.setattr(
        api, "_fetch_all", lambda sql, params=(): list(database.execute(sql, params).fetchall()),
    )
    result = api.admin_users(None)
    assert result["total"] == 3
    assert {row["email"] for row in result["items"]} == {"a@test", "b@test", "c@test"}
