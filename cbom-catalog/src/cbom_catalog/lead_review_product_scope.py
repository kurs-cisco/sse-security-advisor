"""Validation helpers for product-scoped lead review proposals.

These helpers only bind a proposal to its access-policy scope.  They do not
change assessment evidence, candidate status, POA&M records, or authorization.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .product_scopes import PRODUCT_SCOPES


class LeadReviewProductScopeError(ValueError):
    pass


def matching_product_grant(
    grants: list[dict[str, Any]], *, source_collection: str,
    service_group: str, product_scope_id: str,
) -> dict[str, str]:
    """Return exactly one lead-capable grant for the requested product triple."""
    matches = [
        grant for grant in grants
        if grant.get("source_collection") == source_collection
        and grant.get("service_group") == service_group
        and grant.get("product_scope_id") == product_scope_id
        and grant.get("access") == "lead"
    ]
    if len(matches) != 1:
        raise LeadReviewProductScopeError("A lead grant for the exact product scope is required")
    grant = matches[0]
    boundary_name = grant.get("boundary_name")
    reference = grant.get("assessment_authorization_reference")
    if (
        product_scope_id not in PRODUCT_SCOPES
        or boundary_name != PRODUCT_SCOPES[product_scope_id]
        or not isinstance(reference, str)
        or not reference.strip()
    ):
        raise LeadReviewProductScopeError("The product grant lacks an immutable assessment authorization reference")
    return {
        "source_collection": source_collection,
        "service_group": service_group,
        "product_scope_id": product_scope_id,
        "boundary_name": boundary_name,
        "assessment_authorization_reference": reference.strip(),
    }


def product_scope_fingerprint(scope: dict[str, str]) -> str:
    """Stable proposal-scope identity including the product and authorization ref."""
    required = (
        "source_collection", "service_group", "product_scope_id",
        "boundary_name", "assessment_authorization_reference",
    )
    if any(not isinstance(scope.get(key), str) or not scope[key].strip() for key in required):
        raise LeadReviewProductScopeError("A complete product scope is required")
    payload = {key: scope[key].strip() for key in required}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
