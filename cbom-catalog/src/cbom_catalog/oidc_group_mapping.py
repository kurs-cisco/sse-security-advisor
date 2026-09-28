"""Versioned, exact OIDC group-to-service mapping policy.

This policy grants application access to signed MyID groups. It never changes
MyID membership, source evidence, product deployment facts, or an ATO decision.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .product_scopes import PRODUCT_SCOPES, ProductScopeError, normalize_product_scope_ids

_SERVICE_KEY = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_GLOBAL_GROUPS = frozenset({"fedsse-admins", "fedsse-external", "fedsse-scr2-leads"})


class GroupMappingError(ValueError):
    pass


def policy_sha256(groups: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(groups, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def service_rows(groups: dict[str, Any]) -> list[dict[str, Any]]:
    """Project paired exact groups into rows that the Admin editor can maintain."""
    pairs: dict[str, dict[str, Any]] = {}
    for name, entry in groups.items():
        if name in _GLOBAL_GROUPS:
            continue
        if not isinstance(entry, dict) or entry.get("access") not in {"lead", "engineer"}:
            raise GroupMappingError("Service mapping policy is invalid")
        key = entry.get("service_key")
        access = entry["access"]
        suffix = "leads" if access == "lead" else "engineers"
        if not isinstance(key, str) or not _SERVICE_KEY.fullmatch(key) or name != f"fedsse-{key}-{suffix}":
            raise GroupMappingError("Service mapping policy is invalid")
        grants = entry.get("grants")
        if not isinstance(grants, list) or not grants:
            raise GroupMappingError("Service mapping policy is invalid")
        if any(not isinstance(grant, dict) for grant in grants):
            raise GroupMappingError("Service mapping policy is invalid")
        scope_pairs = {(grant.get("source_collection"), grant.get("service_group")) for grant in grants}
        if len(scope_pairs) != 1 or len(grants) > len(PRODUCT_SCOPES):
            raise GroupMappingError("A group must map to one catalog service and one or two products")
        collection, group = next(iter(scope_pairs))
        if not isinstance(collection, str) or not collection or not isinstance(group, str) or not group:
            raise GroupMappingError("Service mapping policy is invalid")
        raw_products = [grant.get("product_scope_id") for grant in grants]
        if (any(not isinstance(product, str) or product not in PRODUCT_SCOPES for product in raw_products)
            or len(raw_products) != len(set(raw_products))):
            raise GroupMappingError("Service mapping product policy is invalid")
        products = sorted(raw_products)
        expected = [
            {"source_collection": collection, "service_group": group,
             "product_scope_id": product, "boundary_name": PRODUCT_SCOPES[product]}
            for product in products
        ]
        if sorted(grants, key=lambda grant: grant["product_scope_id"]) != expected:
            # Authorization references are permitted on grants, but they are
            # owner-reviewed evidence contract references, not Admin mapping
            # fields. Preserve them only when the service/product stays exact.
            for grant, target in zip(sorted(grants, key=lambda row: row["product_scope_id"]), expected, strict=True):
                if {key: value for key, value in grant.items() if key != "assessment_authorization_reference"} != target:
                    raise GroupMappingError("Service mapping policy is invalid")
        grant_signature = json.dumps(
            sorted(grants, key=lambda grant: grant["product_scope_id"]), sort_keys=True,
        )
        row = pairs.setdefault(key, {"service_key": key, "source_collection": collection,
                                     "service_group": group, "product_scope_ids": products,
                                     "lead_group": f"fedsse-{key}-leads",
                                     "engineer_group": f"fedsse-{key}-engineers",
                                     "_grant_signature": grant_signature})
        if (row["source_collection"] != collection or row["service_group"] != group
            or row["product_scope_ids"] != products or row["_grant_signature"] != grant_signature
            or row.get(f"_{access}")):
            raise GroupMappingError("Lead and engineer mapping must match exactly")
        row[f"_{access}"] = True
    if any(not row.get("_lead") or not row.get("_engineer") for row in pairs.values()):
        raise GroupMappingError("Every service requires paired lead and engineer groups")
    result: list[dict[str, Any]] = []
    seen_targets: set[tuple[str, str]] = set()
    for key in sorted(pairs):
        row = pairs[key]
        target = (row["source_collection"], row["service_group"])
        if target in seen_targets:
            raise GroupMappingError("Two MyID group stems cannot map to the same catalog service")
        seen_targets.add(target)
        result.append({field: value for field, value in row.items() if not field.startswith("_")})
    return result


def changed_service_groups(
    groups: dict[str, Any], *, action: str, service_key: str,
    source_collection: str | None = None, service_group: str | None = None,
    product_scope_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return a full replacement policy without mutating its input."""
    if not _SERVICE_KEY.fullmatch(service_key) or service_key in {"admins", "external", "scr2"}:
        raise GroupMappingError("Invalid service group key")
    rows = {row["service_key"]: row for row in service_rows(groups)}
    present = service_key in rows
    if action not in {"add", "replace", "retire"}:
        raise GroupMappingError("Unsupported mapping action")
    if (action == "add" and present) or (action != "add" and not present):
        raise GroupMappingError("Mapping existence conflicts with requested action")
    changed = json.loads(json.dumps(groups))
    lead = f"fedsse-{service_key}-leads"
    engineer = f"fedsse-{service_key}-engineers"
    if action == "retire":
        changed.pop(lead)
        changed.pop(engineer)
        return changed
    if not isinstance(source_collection, str) or not source_collection or source_collection != source_collection.strip():
        raise GroupMappingError("Choose an exact source collection")
    if not isinstance(service_group, str) or not service_group or service_group != service_group.strip():
        raise GroupMappingError("Choose an exact catalog service group")
    try:
        products = normalize_product_scope_ids(product_scope_ids)
    except ProductScopeError as error:
        raise GroupMappingError(str(error)) from error
    grants = [
        {"source_collection": source_collection, "service_group": service_group,
         "product_scope_id": product, "boundary_name": PRODUCT_SCOPES[product]}
        for product in products
    ]
    # An Admin mapping edit cannot manufacture an assessment authorization.
    # References remain only on unchanged exact triples; new/moved grants
    # require the separate accountable assessment workflow.
    if present:
        for name in (lead, engineer):
            old_by_product = {row["product_scope_id"]: row for row in changed[name]["grants"]}
            for grant in grants:
                old = old_by_product.get(grant["product_scope_id"])
                if old and all(old.get(field) == grant[field] for field in grant):
                    reference = old.get("assessment_authorization_reference")
                    if isinstance(reference, str) and reference.strip():
                        grant["assessment_authorization_reference"] = reference
    for name, access in ((lead, "lead"), (engineer, "engineer")):
        changed[name] = {"access": access, "service_key": service_key,
                         "grants": json.loads(json.dumps(grants))}
    service_rows(changed)
    return changed
