from __future__ import annotations

import re
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from cbom_catalog.access_control import (
    AccessDenied,
    Principal,
    generate_api_token,
    read_scope_for_path,
    require_scope,
    token_digest,
    token_expiration,
)


def test_generated_token_is_self_identifying_and_only_digest_is_persistable() -> None:
    with patch.dict("os.environ", {"CBOM_API_TOKEN_PEPPER": "p" * 64}):
        credential_id, token, digest = generate_api_token()

    assert token.startswith(f"cbw_{credential_id}_")
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert token not in digest


def test_digest_requires_a_real_secret_pepper() -> None:
    with (
        patch.dict("os.environ", {"CBOM_API_TOKEN_PEPPER": "short"}),
        pytest.raises(AccessDenied) as error,
    ):
        token_digest("cbw_invalid")
    assert error.value.status_code == 503


def test_token_scope_is_enforced_and_paths_map_to_least_privilege() -> None:
    principal = Principal(
        kind="token",
        subject="token:test",
        role="admin",
        scopes=frozenset({"catalog:read"}),
    )
    require_scope(principal, "catalog:read")
    with pytest.raises(AccessDenied) as error:
        require_scope(principal, "poam:write")
    assert error.value.status_code == 403
    assert read_scope_for_path("/api/v1/fips/assessment") == "assessment:read"
    assert read_scope_for_path("/api/v1/fips/poam.csv") == "poam:read"


def test_token_expiration_is_bounded() -> None:
    now = datetime.now(UTC)
    expiration = token_expiration(999)
    assert 89 <= (expiration - now).days <= 90
