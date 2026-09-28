"""Operational roster persistence; it never grants cloud authorization."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

_ROLES = frozenset({"admin", "lead", "engineer", "summary", "none"})
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class AccessRosterError(ValueError):
    pass


def record_snapshot(database: Any, *, user_id: int, effective_role: str, grants: list[dict[str, Any]], policy_version: str, policy_fingerprint: str) -> None:
    if effective_role not in _ROLES or not policy_version.strip() or not _FINGERPRINT.fullmatch(policy_fingerprint):
        raise AccessRosterError("Invalid verified access snapshot")
    canonical = json.loads(json.dumps(grants, sort_keys=True))
    latest = database.execute("""SELECT effective_role, exact_grants, policy_version, policy_fingerprint, verified_at
        FROM app_auth.access_roster_snapshot WHERE app_user_id = %s
        ORDER BY verified_at DESC, id DESC LIMIT 1""", (user_id,)).fetchone()
    verified_at = latest.get("verified_at") if latest else None
    if isinstance(verified_at, datetime) and verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=UTC)
    unchanged = latest and latest.get("effective_role") == effective_role and latest.get("exact_grants") == canonical and latest.get("policy_version") == policy_version and latest.get("policy_fingerprint") == policy_fingerprint
    if unchanged and isinstance(verified_at, datetime) and verified_at >= datetime.now(UTC) - timedelta(minutes=15):
        return
    database.execute("""INSERT INTO app_auth.access_roster_snapshot
        (app_user_id,effective_role,exact_grants,policy_version,policy_fingerprint)
        VALUES (%s,%s,%s,%s,%s)""", (user_id, effective_role, Jsonb(canonical), policy_version, policy_fingerprint))


def change_access(database: Any, *, actor_user_id: int, target_user_id: int, action: str, reason: str, request_id: str) -> None:
    """Append revoke/restore action and permanently revoke target tokens on revoke."""
    if action not in {"revoke", "restore"} or actor_user_id == target_user_id or len(reason.strip()) < 8:
        raise AccessRosterError("Invalid access action")
    # Serialize every revoke decision before checking the current roster. A
    # recently verified admin means a
    # snapshot no older than 24 hours whose latest operational action is restore
    # or absent; stored app_user.role is deliberately not considered.
    database.execute("SELECT pg_advisory_xact_lock(hashtext('cbom-user-access-actions'))")
    state = database.execute("""
        WITH latest_snapshot AS (
            SELECT DISTINCT ON (app_user_id) app_user_id, effective_role, verified_at
            FROM app_auth.access_roster_snapshot ORDER BY app_user_id, verified_at DESC, id DESC
        ), latest_action AS (
            SELECT DISTINCT ON (target_user_id) target_user_id, action
            FROM app_auth.user_access_action ORDER BY target_user_id, occurred_at DESC, id DESC
        )
        , active_admins AS (
            SELECT app_user.id
            FROM app_auth.app_user app_user
            JOIN latest_snapshot snapshot ON snapshot.app_user_id = app_user.id
            LEFT JOIN latest_action action ON action.target_user_id = snapshot.app_user_id
            WHERE snapshot.effective_role = 'admin' AND snapshot.verified_at >= now() - interval '24 hours'
              AND coalesce(action.action, 'restore') = 'restore'
            FOR UPDATE OF app_user
        ), target AS (
            SELECT app_user.id, snapshot.effective_role, snapshot.verified_at,
                   coalesce(latest.action, 'restore') AS access_state
            FROM app_auth.app_user app_user
            LEFT JOIN latest_snapshot snapshot ON snapshot.app_user_id = app_user.id
            LEFT JOIN latest_action latest ON latest.target_user_id = app_user.id
            WHERE app_user.id = %s
            FOR UPDATE OF app_user
        )
        SELECT (SELECT count(*) FROM active_admins) AS admins,
               target.id AS target_id, target.effective_role,
               target.verified_at, target.access_state
        FROM target
    """, (target_user_id,)).fetchone()
    if not state or state.get("target_id") is None:
        raise AccessRosterError("Access target does not exist")
    before = {
        "access_state": state.get("access_state"),
        "effective_role": state.get("effective_role"),
        "verified_at": str(state.get("verified_at") or ""),
    }
    if state.get("access_state") == action:
        raise AccessRosterError(f"User access is already {action}d")
    target_is_active_admin = (
        state.get("effective_role") == "admin"
        and state.get("access_state") == "restore"
        and state.get("verified_at") is not None
    )
    if action == "revoke" and target_is_active_admin and int(state.get("admins") or 0) <= 1:
        raise AccessRosterError("Cannot revoke the last recently verified active administrator")
    database.execute("""INSERT INTO app_auth.user_access_action
        (target_user_id,action,reason,actor_user_id,request_id) VALUES (%s,%s,%s,%s,%s)""",
        (target_user_id, action, reason.strip(), actor_user_id, request_id))
    if action == "revoke":
        database.execute("UPDATE app_auth.api_credential SET revoked_at = coalesce(revoked_at, now()) WHERE owner_user_id = %s", (target_user_id,))
    database.execute("""INSERT INTO app_auth.audit_event
        (request_id,actor_user_id,action,resource_type,resource_key,before_state,after_state)
        VALUES (%s,%s,%s,'app_user',%s,%s,%s)""", (request_id, actor_user_id, f"user_access.{action}", str(target_user_id), Jsonb({**before, "reason": reason.strip()}), Jsonb({"access_state": action, "tokens_permanently_revoked": action == "revoke"})))
