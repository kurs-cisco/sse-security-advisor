from __future__ import annotations

import pytest

from cbom_catalog.lead_review_product_scope import (
    LeadReviewProductScopeError,
    matching_product_grant,
    product_scope_fingerprint,
)


def _grant(**overrides: str) -> dict[str, str]:
    return {
        "source_collection": "sse-cboms",
        "service_group": "brain",
        "product_scope_id": "secure-access-government",
        "boundary_name": "FedRAMP High/IL2",
        "assessment_authorization_reference": "package-gov-immutable-1",
        "access": "lead",
        **overrides,
    }


def test_exact_product_triple_and_authorization_reference_are_required() -> None:
    scope = matching_product_grant(
        [_grant()], source_collection="sse-cboms", service_group="brain",
        product_scope_id="secure-access-government",
    )
    assert scope["assessment_authorization_reference"] == "package-gov-immutable-1"
    with pytest.raises(LeadReviewProductScopeError):
        matching_product_grant(
            [_grant(product_scope_id="secure-access-defense")],
            source_collection="sse-cboms", service_group="brain",
            product_scope_id="secure-access-government",
        )
    with pytest.raises(LeadReviewProductScopeError):
        matching_product_grant(
            [_grant(assessment_authorization_reference="")],
            source_collection="sse-cboms", service_group="brain",
            product_scope_id="secure-access-government",
        )


def test_scope_fingerprint_changes_by_product_or_authorization_reference() -> None:
    scope = matching_product_grant(
        [_grant()], source_collection="sse-cboms", service_group="brain",
        product_scope_id="secure-access-government",
    )
    changed_reference = {**scope, "assessment_authorization_reference": "package-gov-immutable-2"}
    assert product_scope_fingerprint(scope) != product_scope_fingerprint(changed_reference)
