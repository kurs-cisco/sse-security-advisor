"""Read-only SQL building blocks for product-scoped evidence visibility.

Product routing is an operational decision attached to an exact, current
source-file checksum.  These helpers deliberately deny legacy, unassigned,
removed, and changed source files.  Callers compose the returned SQL with
parameterized database queries; product scope values are never interpolated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .product_scopes import PRODUCT_SCOPES

_SQL_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class ProductScopeQueryError(ValueError):
    """Raised when a caller asks for an unsupported product or SQL alias."""


@dataclass(frozen=True)
class SqlFragment:
    """A parameterized SQL fragment and its positional bind values."""

    sql: str
    params: tuple[str, ...]


@dataclass(frozen=True)
class ProductScopeCtes(SqlFragment):
    """Names exposed by :func:`product_scope_ctes` for downstream joins."""

    source_files: str
    documents: str
    components: str
    artifacts: str


def _scope_id(product_scope_id: str) -> str:
    if not isinstance(product_scope_id, str) or product_scope_id not in PRODUCT_SCOPES:
        raise ProductScopeQueryError("Unsupported product scope")
    return product_scope_id


def _identifier(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not _SQL_IDENTIFIER.fullmatch(value):
        raise ProductScopeQueryError(f"Invalid SQL {label}")
    return value


def source_file_scope_predicate(
    product_scope_id: str, *, source_file_alias: str = "sf"
) -> SqlFragment:
    """Return a default-deny predicate for a ``source_file`` table alias.

    The current source checksum is part of the decision identity.  The nested
    query chooses the most recent append-only decision for that exact identity
    before checking membership, so an older decision cannot expose a file
    after a later owner/uploader decision changes its product selection.
    """
    scope_id = _scope_id(product_scope_id)
    alias = _identifier(source_file_alias, label="source-file alias")
    return SqlFragment(
        sql=f"""
            {alias}.is_present
            AND {alias}.content_sha256 IS NOT NULL
            AND EXISTS (
                SELECT 1
                FROM (
                    SELECT decision.product_scope_ids
                    FROM app_auth.evidence_product_scope_decision AS decision
                    WHERE decision.source_collection_id = {alias}.source_collection_id
                      AND decision.service_group_id = {alias}.service_group_id
                      AND decision.source_path = {alias}.source_path
                      AND decision.source_sha256 = {alias}.content_sha256
                    ORDER BY decision.attributed_at DESC, decision.id DESC
                    LIMIT 1
                ) AS latest_decision
                WHERE %s = ANY(latest_decision.product_scope_ids)
            )
        """.strip(),
        params=(scope_id,),
    )


def product_scope_ctes(
    product_scope_id: str, *, prefix: str = "product_scoped"
) -> ProductScopeCtes:
    """Return CTEs for current source files and evidence derived from them.

    Append ``result.sql`` after ``WITH`` (or after existing CTEs with a comma),
    then join the named CTEs from ``result``.  Source-file identity drives every
    downstream evidence type, preventing a document, component, or artifact
    with shared global identity from bypassing product attribution.
    """
    safe_prefix = _identifier(prefix, label="CTE prefix")
    source_files = f"{safe_prefix}_source_files"
    documents = f"{safe_prefix}_documents"
    components = f"{safe_prefix}_components"
    artifacts = f"{safe_prefix}_artifacts"
    predicate = source_file_scope_predicate(product_scope_id, source_file_alias="sf")
    return ProductScopeCtes(
        sql=f"""
            {source_files} AS (
                SELECT sf.id, sf.source_collection_id, sf.service_group_id,
                       sf.document_id, sf.source_path, sf.source_uri,
                       sf.content_sha256, sf.is_present, sf.parse_status
                FROM source_file AS sf
                WHERE {predicate.sql}
            ),
            {documents} AS (
                SELECT DISTINCT sf.document_id
                FROM {source_files} AS sf
                WHERE sf.document_id IS NOT NULL
            ),
            {components} AS (
                SELECT DISTINCT dc.component_id
                FROM document_component AS dc
                JOIN {documents} AS document_scope ON document_scope.document_id = dc.document_id
            ),
            {artifacts} AS (
                SELECT DISTINCT da.artifact_id
                FROM document_artifact AS da
                JOIN {documents} AS document_scope ON document_scope.document_id = da.document_id
            )
        """.strip(),
        params=predicate.params,
        source_files=source_files,
        documents=documents,
        components=components,
        artifacts=artifacts,
    )
