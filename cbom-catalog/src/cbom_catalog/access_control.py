from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request

from .api_database import connection as api_connection

TOKEN_PATTERN = re.compile(
    r"^cbw_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})_([A-Za-z0-9_-]{32,})$"
)
ALLOWED_TOKEN_SCOPES = frozenset(
    {
        "catalog:read",
        "assessment:read",
        "poam:read",
        "poam:write",
        "milestones:write",
        "annotations:write",
        "ingestion:read",
        "ingestion:write",
        "users:admin",
        "tokens:admin",
    }
)
_OIDC_GROUPS_MAX_RAW_BYTES = 32_768
_OIDC_GROUPS_MAX_ENTRIES = 1_024
_OIDC_GROUPS_MAX_ENTITLEMENT_ENTRIES = 128
_OIDC_GROUP_MAX_LENGTH = 256
_OIDC_ENTITLEMENT_PREFIX = "fedsse-"
_OIDC_ENTITLEMENT_PATTERN = re.compile(r"fedsse-[a-z0-9]+(?:-[a-z0-9]+)*\Z")


@dataclass(frozen=True)
class Principal:
    kind: str
    subject: str
    role: str
    scopes: frozenset[str]
    user_id: int | None = None
    credential_id: str | None = None
    email: str | None = None
    display_name: str | None = None
    oidc_groups: frozenset[str] = frozenset()

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AccessDenied(Exception):
    def __init__(self, detail: str, status_code: int = 401):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def token_digest(token: str) -> str:
    pepper = os.environ.get("CBOM_API_TOKEN_PEPPER", "")
    if len(pepper) < 32:
        raise AccessDenied("API token verification is not configured", 503)
    return hmac.new(pepper.encode(), token.encode(), hashlib.sha256).hexdigest()


def generate_api_token() -> tuple[str, str, str]:
    credential_id = str(uuid.uuid4())
    token = f"cbw_{credential_id}_{secrets.token_urlsafe(32)}"
    return credential_id, token, token_digest(token)


def _verified_oidc_groups(raw_groups: str) -> frozenset[str]:
    """Keep exact CBOM entitlement candidates from a signed OIDC group claim.

    Unrelated directory groups are not authorization inputs.  They must not
    make a valid CBOM entitlement fail merely by exceeding a small total-group
    limit.  The JSON shape remains strict, parsing remains bounded, and a
    malformed value in the reserved entitlement namespace fails closed.
    """
    if len(raw_groups.encode("utf-8")) > _OIDC_GROUPS_MAX_RAW_BYTES:
        raise AccessDenied("groups_claim_too_large", 401)
    try:
        parsed_groups = json.loads(raw_groups) if raw_groups else []
    except ValueError as error:
        raise AccessDenied("groups_claim_invalid_json", 401) from error
    if not isinstance(parsed_groups, list):
        raise AccessDenied("groups_claim_invalid_shape", 401)
    if len(parsed_groups) > _OIDC_GROUPS_MAX_ENTRIES:
        raise AccessDenied("groups_claim_too_many_entries", 401)
    if any(not isinstance(group, str) for group in parsed_groups):
        raise AccessDenied("groups_claim_invalid_member", 401)

    entitlements: list[str] = []
    for group in parsed_groups:
        # Treat a whitespace-wrapped reserved name as malformed rather than
        # silently downgrading it to an unrelated directory value.  The value
        # itself is never trimmed or otherwise normalized for authorization.
        if (
            not group.startswith(_OIDC_ENTITLEMENT_PREFIX)
            and not group.strip().startswith(_OIDC_ENTITLEMENT_PREFIX)
        ):
            continue
        if len(group) > _OIDC_GROUP_MAX_LENGTH or not _OIDC_ENTITLEMENT_PATTERN.fullmatch(group):
            raise AccessDenied("groups_claim_invalid_entitlement", 401)
        entitlements.append(group)
    if len(entitlements) > _OIDC_GROUPS_MAX_ENTITLEMENT_ENTRIES:
        raise AccessDenied("groups_claim_too_many_entitlements", 401)
    return frozenset(entitlements)


def _resolve_human(request: Request) -> Principal:
    issuer = request.headers.get("x-cbom-user-issuer", "").strip()
    subject = request.headers.get("x-cbom-user-sub", "").strip()
    email = request.headers.get("x-cbom-user-email", "").strip().casefold()
    display_name = request.headers.get("x-cbom-user-name", "").strip() or None
    raw_groups = request.headers.get("x-cbom-user-groups", "").strip()
    oidc_groups = _verified_oidc_groups(raw_groups)
    if not issuer or not subject or not email:
        raise AccessDenied("Verified OIDC subject and email are required", 401)

    with api_connection() as database:
        row = database.execute(
            """
            SELECT id, oidc_issuer, oidc_subject, email, display_name, role, status
            FROM app_auth.app_user
            WHERE oidc_issuer = %s AND oidc_subject = %s
            """,
            (issuer, subject),
        ).fetchone()
        if row is None:
            invited = database.execute(
                """
                SELECT id, oidc_issuer, oidc_subject, email, display_name, role, status
                FROM app_auth.app_user WHERE lower(email) = %s FOR UPDATE
                """,
                (email,),
            ).fetchone()
            if invited is not None:
                if invited.get("oidc_subject") and (
                    invited.get("oidc_issuer") != issuer
                    or invited.get("oidc_subject") != subject
                ):
                    raise AccessDenied("This email is already bound to another identity", 403)
                row = database.execute(
                    """
                    UPDATE app_auth.app_user
                    SET oidc_issuer = %s, oidc_subject = %s,
                        display_name = coalesce(%s, display_name),
                        status = CASE WHEN status = 'invited' THEN 'active' ELSE status END,
                        last_login_at = now(), updated_at = now()
                    WHERE id = %s
                    RETURNING id, oidc_issuer, oidc_subject, email, display_name, role, status
                    """,
                    (issuer, subject, display_name, invited["id"]),
                ).fetchone()
            else:
                row = database.execute(
                    """
                    INSERT INTO app_auth.app_user
                        (oidc_issuer, oidc_subject, email, display_name, role, status, last_login_at)
                    VALUES (%s, %s, %s, %s, 'viewer', 'active', now())
                    RETURNING id, oidc_issuer, oidc_subject, email, display_name, role, status
                    """,
                    (issuer, subject, email, display_name),
                ).fetchone()
        else:
            row = database.execute(
                """
                UPDATE app_auth.app_user
                SET email = %s, display_name = coalesce(%s, display_name),
                    last_login_at = now(), updated_at = now()
                WHERE id = %s
                RETURNING id, oidc_issuer, oidc_subject, email, display_name, role, status
                """,
                (email, display_name, row["id"]),
            ).fetchone()
        if row is None:
            raise AccessDenied("Unable to provision application user", 503)
        if row["status"] != "active":
            raise AccessDenied("Application access is disabled", 403)
        database.commit()

    return Principal(
        kind="human",
        subject=f"oidc:{subject}",
        # Cloud authorization is derived by the deployment-owned OIDC group
        # policy in api.py.  The legacy stored role is deliberately not used
        # here: it remains only for existing API credential ownership.
        role="viewer",
        scopes=frozenset(),
        user_id=int(row["id"]),
        email=row["email"],
        display_name=row.get("display_name"),
        oidc_groups=oidc_groups,
    )


def _resolve_api_token(token: str) -> Principal:
    match = TOKEN_PATTERN.fullmatch(token)
    if not match:
        raise AccessDenied("Invalid API credential", 401)
    credential_id = match.group(1)
    digest = token_digest(token)
    with api_connection() as database:
        row = database.execute(
            """
            SELECT credential.id AS credential_id, credential.token_digest,
                   credential.scopes, credential.expires_at, credential.revoked_at,
                   app_user.id AS user_id, app_user.email, app_user.display_name,
                   app_user.role, app_user.status
            FROM app_auth.api_credential credential
            JOIN app_auth.app_user ON app_user.id = credential.owner_user_id
            WHERE credential.id = %s
            """,
            (credential_id,),
        ).fetchone()
        if row is None or not hmac.compare_digest(row["token_digest"], digest):
            raise AccessDenied("Invalid API credential", 401)
        if row["revoked_at"] is not None or row["expires_at"] <= datetime.now(UTC):
            raise AccessDenied("API credential is expired or revoked", 401)
        if row["status"] != "active":
            raise AccessDenied("API credential owner is not active", 403)
        database.execute(
            """
            UPDATE app_auth.api_credential
            SET last_used_at = now()
            WHERE id = %s AND (last_used_at IS NULL OR last_used_at < now() - interval '15 minutes')
            """,
            (credential_id,),
        )
        database.commit()
    return Principal(
        kind="token",
        subject=f"token:{credential_id}",
        # API credentials are never browser administrators.  Their explicit
        # credential scopes are enforced independently of the retired user
        # role column, preventing a legacy database role from granting cloud
        # authorization after the OIDC group cutover.
        role="viewer",
        scopes=frozenset(row["scopes"]),
        user_id=int(row["user_id"]),
        credential_id=str(row["credential_id"]),
        email=row["email"],
        display_name=row.get("display_name"),
    )


def authenticate_request(request: Request, *, production: bool) -> Principal:
    mode = os.environ.get("CBOM_API_AUTH_MODE", "disabled").strip().casefold()
    if mode in {"disabled", "local-admin"}:
        if production:
            raise AccessDenied("Local administrator authentication is unavailable in production", 503)
        if mode == "disabled" and os.environ.get("CBOM_API_AUTH_MODE", "").strip():
            raise AccessDenied("Use CBOM_API_AUTH_MODE=local-admin for local access", 503)
        return Principal(
            kind="local",
            subject="local-development",
            role="admin",
            scopes=frozenset(ALLOWED_TOKEN_SCOPES),
            email="local@development.invalid",
        )
    if mode != "bearer":
        raise AccessDenied(f"Unsupported auth mode: {mode}", 503)

    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    if scheme.casefold() != "bearer" or not supplied:
        raise AccessDenied("Authentication required", 401)
    internal = os.environ.get("CBOM_API_BEARER_TOKEN", "")
    if internal and hmac.compare_digest(supplied, internal):
        if request.headers.get("x-cbom-user-sub"):
            return _resolve_human(request)
        return Principal(
            kind="service",
            subject="bearer-client",
            role="viewer",
            scopes=frozenset({"catalog:read", "assessment:read", "poam:read"}),
        )
    return _resolve_api_token(supplied)


def require_admin(principal: Principal) -> None:
    if not principal.is_admin:
        raise AccessDenied("Administrator access is required", 403)


def require_scope(principal: Principal, scope: str) -> None:
    if principal.kind == "human" and principal.is_admin:
        return
    if scope not in principal.scopes:
        raise AccessDenied(f"API credential lacks required scope: {scope}", 403)


def read_scope_for_path(path: str) -> str:
    if path.startswith("/api/v1/admin/service-group-mappings"):
        return "__human_admin_group_policy_only__"
    if path.startswith("/api/v1/admin/ingestion"):
        return "ingestion:read"
    if path.startswith("/api/v1/admin/users"):
        return "users:admin"
    if path.startswith("/api/v1/admin/tokens"):
        return "tokens:admin"
    if path.startswith("/api/v1/admin/overlays"):
        return "annotations:write"
    if path.startswith("/api/v1/admin/audit"):
        return "__administrative_audit_not_available_to_tokens__"
    if path.startswith("/api/v1/fips/poam") or path.endswith("compliance-package.zip"):
        return "poam:read"
    if path.startswith("/api/v1/fips/"):
        return "assessment:read"
    return "catalog:read"


def token_expiration(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=max(1, min(days, 90)))
