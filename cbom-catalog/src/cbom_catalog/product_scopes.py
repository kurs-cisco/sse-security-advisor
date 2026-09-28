"""Product routing scopes for evidence uploaded after the dual-product cutover.

These values route evidence visibility only.  They do not establish an ATO,
FedRAMP authorization, a deployment fact, or CMVP/FIPS validation.
"""
from __future__ import annotations

from collections.abc import Iterable

PRODUCT_SCOPES: dict[str, str] = {
    "secure-access-government": "FedRAMP High/IL2",
    "secure-access-defense": "IL5",
}
DEFAULT_PRODUCT_SCOPE_IDS: tuple[str, ...] = tuple(PRODUCT_SCOPES)


class ProductScopeError(ValueError):
    pass


def normalize_product_scope_ids(value: Iterable[object] | None) -> list[str]:
    """Return a canonical, nonempty selection; omitted means both products.

    The caller's selection is intentionally part of the signed manifest.  A
    legacy batch has NULL in the database and is never interpreted as this
    default.
    """
    if value is None:
        return sorted(DEFAULT_PRODUCT_SCOPE_IDS)
    result: list[str] = []
    for raw in value:
        if not isinstance(raw, str) or raw != raw.strip() or raw not in PRODUCT_SCOPES:
            raise ProductScopeError("product_scope_ids contains an unsupported product scope")
        if raw in result:
            raise ProductScopeError("product_scope_ids must not contain duplicates")
        result.append(raw)
    if not result:
        raise ProductScopeError("product_scope_ids must select at least one product scope")
    return sorted(result)
