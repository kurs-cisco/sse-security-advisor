"""Validation and normalization for managed Service Catalog metadata.

The catalog record is operational metadata.  It is intentionally separate
from imported CBOM evidence and Team Tracker/service-impact source records.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any


class ServiceCatalogError(ValueError):
    pass


SERVICE_GROUP_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PLANNING_STATUSES = frozenset({
    "not_supplied", "planned", "in_progress", "complete", "blocked", "not_applicable",
})
RISK_VALUES = frozenset({"low", "moderate", "high", "critical"})
MANAGED_FIELDS = frozenset({
    "display_name", "owner", "owner_profile_email", "lead", "lead_profile_email", "il2_status", "il2_target_date",
    "il5_status", "il5_target_date", "service_impact_risk", "comments", "attributes",
})


def normalized_change(payload: dict[str, Any], *, allow_empty: bool = False) -> dict[str, Any]:
    """Accept only the managed metadata fields and normalize nullable values."""
    unsupported = sorted(set(payload) - MANAGED_FIELDS)
    if unsupported:
        raise ServiceCatalogError("Unsupported Service Catalog fields: " + ", ".join(unsupported))
    if not payload and not allow_empty:
        raise ServiceCatalogError("At least one Service Catalog field is required")
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"display_name", "owner", "lead", "il2_target_date", "il5_target_date", "service_impact_risk", "comments"}:
            if value is None:
                if key == "display_name":
                    raise ServiceCatalogError("display_name cannot be blank")
                result[key] = None
                continue
            if not isinstance(value, str):
                raise ServiceCatalogError(f"{key} must be text or null")
            clean = value.strip()
            if key == "display_name" and not clean:
                raise ServiceCatalogError("display_name cannot be blank")
            if len(clean) > (4_000 if key == "comments" else 240):
                raise ServiceCatalogError(f"{key} is too long")
            result[key] = clean or None
        elif key in {"il2_status", "il5_status"}:
            if value is None:
                result[key] = "not_supplied"
            elif isinstance(value, str) and value in PLANNING_STATUSES:
                result[key] = value
            else:
                raise ServiceCatalogError(f"{key} is invalid")
        elif key in {"owner_profile_email", "lead_profile_email"}:
            if value is None:
                result[key] = None
            elif isinstance(value, str) and not value.strip():
                result[key] = None
            elif isinstance(value, str) and EMAIL.fullmatch(value.strip()) and len(value.strip()) <= 320:
                result[key] = value.strip().casefold()
            else:
                raise ServiceCatalogError(f"{key} must be an email address or null")
        elif key == "attributes":
            if value is None:
                result[key] = {}
            elif isinstance(value, dict):
                reserved = {"source_collection", "service_group", "slug", "group", "product_scope_id", "access", "role", "grant", "grants", "entitlement", "status", "approval_status", "revision"}
                if reserved.intersection(value):
                    raise ServiceCatalogError("attributes cannot contain identity or access-control fields")
                if any(isinstance(item, (dict, list)) for item in value.values()):
                    raise ServiceCatalogError("attributes values must be simple display values")
                encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
                if len(encoded) > 16_000:
                    raise ServiceCatalogError("attributes are too large")
                result[key] = value
            else:
                raise ServiceCatalogError("attributes must be an object")
    risk = result.get("service_impact_risk")
    if risk is not None and risk.casefold() not in RISK_VALUES:
        raise ServiceCatalogError("service_impact_risk must be low, moderate, high, or critical")
    if isinstance(risk, str):
        result["service_impact_risk"] = risk.casefold()
    for boundary in ("il2", "il5"):
        date_key, status_key = f"{boundary}_target_date", f"{boundary}_status"
        if result.get(date_key) is not None:
            try:
                date.fromisoformat(str(result[date_key]))
            except ValueError as error:
                raise ServiceCatalogError(f"{date_key} must be an ISO calendar date") from error
        if result.get(status_key) == "not_applicable" and result.get(date_key):
            raise ServiceCatalogError(f"{date_key} cannot be set when {status_key} is not_applicable")
        if result.get(status_key) == "not_applicable" and date_key not in result:
            result[date_key] = None
    return result
