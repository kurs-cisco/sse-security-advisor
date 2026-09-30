from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from cbom_catalog.access_roster import AccessRosterError, change_access, record_snapshot


def test_snapshot_is_policy_observation_not_a_role_grant() -> None:
    database = MagicMock()
    record_snapshot(database, user_id=7, effective_role="admin", verified_admin=True, grants=[{"service_group": "brain"}], policy_version="v1", policy_fingerprint="a" * 64)
    sql = database.execute.call_args.args[0]
    assert "access_roster_snapshot" in sql and "app_user.role" not in sql


def test_unchanged_recent_snapshot_does_not_append() -> None:
    database = MagicMock()
    database.execute.return_value.fetchone.return_value = {"effective_role": "admin", "verified_admin": True, "exact_grants": [], "policy_version": "v1", "policy_fingerprint": "a" * 64, "verified_at": datetime.now(UTC)}
    record_snapshot(database, user_id=7, effective_role="admin", verified_admin=True, grants=[], policy_version="v1", policy_fingerprint="a" * 64)
    assert database.execute.call_count == 1


def test_revoke_is_self_and_last_admin_safe_and_revokes_tokens() -> None:
    database = MagicMock()
    database.execute.return_value.fetchone.return_value = {"admins": 2, "target_id": 2, "effective_role": "engineer", "access_state": "restore", "verified_at": "2026-09-26"}
    change_access(database, actor_user_id=1, target_user_id=2, action="revoke", reason="Approved operational revocation.", request_id="r1")
    sql = "\n".join(call.args[0] for call in database.execute.call_args_list)
    assert "user_access_action" in sql and "api_credential SET revoked_at" in sql and "audit_event" in sql
    with pytest.raises(AccessRosterError):
        change_access(database, actor_user_id=1, target_user_id=1, action="revoke", reason="Approved operational revocation.", request_id="r1")


def test_last_recently_verified_admin_is_denied() -> None:
    database = MagicMock()
    database.execute.return_value.fetchone.return_value = {"admins": 1, "target_id": 2, "effective_role": "admin", "verified_admin": True, "access_state": "restore", "verified_at": "2026-09-26", "recently_verified": True}
    with pytest.raises(AccessRosterError, match="last recently verified"):
        change_access(database, actor_user_id=1, target_user_id=2, action="revoke", reason="Approved operational revocation.", request_id="r1")


def test_last_admin_protection_uses_verified_entitlement_not_selected_workspace() -> None:
    database = MagicMock()
    # The identity selected Product Lead, but its signed groups also contained
    # fedsse-admins. It remains protected as the final active administrator.
    database.execute.return_value.fetchone.return_value = {
        "admins": 1, "target_id": 2, "effective_role": "lead",
        "verified_admin": True, "access_state": "restore", "verified_at": "2026-09-26", "recently_verified": True,
    }
    with pytest.raises(AccessRosterError, match="last recently verified"):
        change_access(database, actor_user_id=1, target_user_id=2, action="revoke", reason="Last administrator revoked.", request_id="r1")


def test_non_admin_revoke_is_allowed_when_one_admin_remains() -> None:
    database = MagicMock()
    database.execute.return_value.fetchone.return_value = {"admins": 1, "target_id": 2, "effective_role": "engineer", "access_state": "restore", "verified_at": "2026-09-26"}
    change_access(database, actor_user_id=1, target_user_id=2, action="revoke", reason="Approved operational revocation.", request_id="r1")


def test_stale_admin_snapshot_does_not_block_revocation() -> None:
    database = MagicMock()
    database.execute.return_value.fetchone.return_value = {
        "admins": 1, "target_id": 2, "effective_role": "admin",
        "verified_admin": True, "access_state": "restore", "verified_at": "2026-09-24",
        "recently_verified": False,
    }
    change_access(database, actor_user_id=1, target_user_id=2, action="revoke", reason="Stale administrator revocation.", request_id="r1")


def test_duplicate_action_and_missing_target_are_rejected() -> None:
    database = MagicMock()
    database.execute.return_value.fetchone.return_value = {"admins": 2, "target_id": 2, "effective_role": "admin", "access_state": "revoke", "verified_at": "2026-09-26"}
    with pytest.raises(AccessRosterError, match="already revoked"):
        change_access(database, actor_user_id=1, target_user_id=2, action="revoke", reason="Approved operational revocation.", request_id="r1")
