"""Validation and normalization for managed Service Catalog metadata.

The catalog record is operational metadata.  It is intentionally separate
from imported CBOM evidence and Team Tracker/service-impact source records.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit


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
    "il5_status", "il5_target_date", "service_impact_risk", "comments", "attributes", "crypto_module_plans",
})
CRYPTO_PLAN_FIELDS = frozenset({
    "source_record_sha256", "current_module", "current_version", "target_preset_id",
    "custom_target_module", "custom_target_version", "supporting_url", "evidence_basis", "note",
})
CUSTOM_EVIDENCE_BASES = frozenset({"cmvp_certificate", "cmvp_in_process", "vendor_recommendation", "other"})


def _bounded_text(value: Any, field: str, *, required: bool = False, limit: int = 240) -> str | None:
    if value is None:
        if required:
            raise ServiceCatalogError(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise ServiceCatalogError(f"{field} must be text")
    clean = value.strip()
    if required and not clean:
        raise ServiceCatalogError(f"{field} is required")
    if len(clean) > limit:
        raise ServiceCatalogError(f"{field} is too long")
    return clean or None


def _crypto_module_plans(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 16:
        raise ServiceCatalogError("crypto_module_plans must contain at most 16 rows")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) - CRYPTO_PLAN_FIELDS:
            raise ServiceCatalogError(f"crypto_module_plans[{index}] has unsupported fields")
        current = _bounded_text(raw.get("current_module"), "current_module", required=True)
        current_version = _bounded_text(raw.get("current_version"), "current_version", limit=120)
        source_hash = _bounded_text(raw.get("source_record_sha256"), "source_record_sha256", limit=64)
        if source_hash and not re.fullmatch(r"[0-9a-fA-F]{64}", source_hash):
            raise ServiceCatalogError("source_record_sha256 must be a SHA-256 digest")
        preset = _bounded_text(raw.get("target_preset_id"), "target_preset_id", limit=120)
        custom = _bounded_text(raw.get("custom_target_module"), "custom_target_module")
        custom_version = _bounded_text(raw.get("custom_target_version"), "custom_target_version", limit=120)
        supporting_url = _bounded_text(raw.get("supporting_url"), "supporting_url", limit=2_048)
        evidence_basis = _bounded_text(raw.get("evidence_basis"), "evidence_basis", limit=40)
        note = _bounded_text(raw.get("note"), "note", limit=2_000)
        if bool(preset) == bool(custom):
            raise ServiceCatalogError("Choose one curated target or one custom target per module plan")
        if preset:
            if not re.fullmatch(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", preset):
                raise ServiceCatalogError("target_preset_id is invalid")
            if custom_version or evidence_basis:
                raise ServiceCatalogError("Custom target fields cannot be combined with a curated target")
        elif not custom_version or evidence_basis not in CUSTOM_EVIDENCE_BASES or not supporting_url:
            raise ServiceCatalogError("Custom targets require a version, evidence basis, and supporting HTTPS URL")
        if supporting_url:
            parsed = urlsplit(supporting_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ServiceCatalogError("supporting_url must be an HTTPS URL without credentials")
        identity = (source_hash or "", current.casefold(), preset or f"{custom.casefold()}@{custom_version}")
        if identity in seen:
            raise ServiceCatalogError("Duplicate crypto-module plan")
        seen.add(identity)
        result.append({
            "source_record_sha256": source_hash.lower() if source_hash else None,
            "current_module": current, "current_version": current_version,
            "target_preset_id": preset, "custom_target_module": custom,
            "custom_target_version": custom_version, "supporting_url": supporting_url,
            "evidence_basis": evidence_basis, "note": note,
        })
    return result


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
        elif key == "crypto_module_plans":
            result[key] = _crypto_module_plans(value)
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
