from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from cbom_catalog.access_control import (
    AccessDenied,
    Principal,
    _verified_oidc_groups,
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
    assert read_scope_for_path("/api/v1/admin/ingestion/batches") == "ingestion:read"


def test_token_expiration_is_bounded() -> None:
    now = datetime.now(UTC)
    expiration = token_expiration(999)
    assert 89 <= (expiration - now).days <= 90


def test_noisy_oidc_group_claim_preserves_exact_admin_entitlement() -> None:
    groups = [f"directory-group-{index}" for index in range(250)] + ["fedsse-admins"]

    assert _verified_oidc_groups(json.dumps(groups)) == frozenset({"fedsse-admins"})


def test_irrelevant_empty_whitespace_and_overlong_groups_do_not_block_admin() -> None:
    groups = ["", "   ", "directory-" + "x" * 300, "fedsse-admins"]

    assert _verified_oidc_groups(json.dumps(groups)) == frozenset({"fedsse-admins"})


def test_oidc_group_claim_rejects_more_than_1024_entries() -> None:
    with pytest.raises(AccessDenied) as error:
        _verified_oidc_groups(json.dumps([f"directory-group-{index}" for index in range(1_025)]))

    assert error.value.status_code == 401
    assert error.value.detail == "groups_claim_too_many_entries"


def test_oidc_group_claim_rejects_more_than_128_reserved_entitlements() -> None:
    with pytest.raises(AccessDenied) as error:
        _verified_oidc_groups(json.dumps([f"fedsse-team-{index}" for index in range(129)]))

    assert error.value.status_code == 401
    assert error.value.detail == "groups_claim_too_many_entitlements"


def test_oidc_group_claim_rejects_more_than_32_kib_of_raw_json() -> None:
    with pytest.raises(AccessDenied) as error:
        _verified_oidc_groups(json.dumps(["directory-" + "x" * 32_768]))

    assert error.value.status_code == 401
    assert error.value.detail == "groups_claim_too_large"


@pytest.mark.parametrize(
    "group",
    [" fedsse-admins", "fedsse-", "fedsse-admins ", "fedsse-Admins", "fedsse-admins/extra"],
)
def test_malformed_reserved_oidc_group_is_rejected(group: str) -> None:
    with pytest.raises(AccessDenied) as error:
        _verified_oidc_groups(json.dumps([group]))

    assert error.value.status_code == 401
    assert error.value.detail == "groups_claim_invalid_entitlement"


def test_spoofed_or_unrelated_group_never_becomes_admin_entitlement() -> None:
    entitlements = _verified_oidc_groups(
        json.dumps(["FEDSSE-ADMINS", "fedsse-admins-extra", "directory-admins"])
    )

    assert "fedsse-admins" not in entitlements
    assert entitlements == frozenset({"fedsse-admins-extra"})


def test_non_string_oidc_group_member_is_rejected() -> None:
    with pytest.raises(AccessDenied) as error:
        _verified_oidc_groups(json.dumps(["fedsse-admins", 7]))

    assert error.value.status_code == 401
    assert error.value.detail == "groups_claim_invalid_member"
