from __future__ import annotations

import pytest
from fastapi import HTTPException

from cbom_catalog import api
from cbom_catalog.product_scope_queries import (
    ProductScopeQueryError,
    product_scope_ctes,
    source_file_scope_predicate,
)


def test_source_file_predicate_requires_current_exact_attribution() -> None:
    predicate = source_file_scope_predicate("secure-access-government")

    assert predicate.params == ("secure-access-government",)
    assert "sf.is_present" in predicate.sql
    assert "sf.content_sha256 IS NOT NULL" in predicate.sql
    assert "decision.source_collection_id = sf.source_collection_id" in predicate.sql
    assert "decision.service_group_id = sf.service_group_id" in predicate.sql
    assert "decision.source_path = sf.source_path" in predicate.sql
    assert "decision.source_sha256 = sf.content_sha256" in predicate.sql
    assert "ORDER BY decision.attributed_at DESC, decision.id DESC" in predicate.sql
    assert "LIMIT 1" in predicate.sql
    assert "%s = ANY(latest_decision.product_scope_ids)" in predicate.sql


def test_scope_ctes_keep_shared_document_derived_evidence_scoped() -> None:
    scope = product_scope_ctes("secure-access-defense")

    assert scope.params == ("secure-access-defense",)
    assert scope.source_files == "product_scoped_source_files"
    assert scope.documents == "product_scoped_documents"
    assert scope.components == "product_scoped_components"
    assert scope.artifacts == "product_scoped_artifacts"
    assert "JOIN product_scoped_documents AS document_scope" in scope.sql
    assert "FROM document_component AS dc" in scope.sql
    assert "FROM document_artifact AS da" in scope.sql


@pytest.mark.parametrize("value", ["", "other-product", "FedRAMP High/IL2", None])
def test_scope_helpers_reject_unknown_product_scope(value: object) -> None:
    with pytest.raises(ProductScopeQueryError, match="Unsupported product scope"):
        source_file_scope_predicate(value)  # type: ignore[arg-type]


def test_api_scope_helper_returns_422_for_unknown_product_scope() -> None:
    with pytest.raises(HTTPException) as error:
        api._product_scope_ctes("unknown-product")
    assert error.value.status_code == 422


@pytest.mark.parametrize("alias", ["sf; DROP TABLE source_file", "sf.scope", "1sf", "sf-1"])
def test_scope_predicate_rejects_untrusted_sql_alias(alias: str) -> None:
    with pytest.raises(ProductScopeQueryError, match="Invalid SQL source-file alias"):
        source_file_scope_predicate("secure-access-government", source_file_alias=alias)


@pytest.mark.parametrize("prefix", ["scope; DROP TABLE document", "scope.name", "1scope"])
def test_scope_ctes_reject_untrusted_cte_prefix(prefix: str) -> None:
    with pytest.raises(ProductScopeQueryError, match="Invalid SQL CTE prefix"):
        product_scope_ctes("secure-access-government", prefix=prefix)
