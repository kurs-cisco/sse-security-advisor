from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import time
import uuid
import zipfile
from collections import OrderedDict, defaultdict, deque
from dataclasses import replace
from datetime import date
from pathlib import Path
from threading import RLock
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .access_control import (
    ALLOWED_TOKEN_SCOPES,
    AccessDenied,
    Principal,
    authenticate_request,
    generate_api_token,
    read_scope_for_path,
    require_admin,
    require_scope,
    token_expiration,
)
from .api_database import close_pool
from .api_database import connection as api_connection
from .access_roster import AccessRosterError, change_access, record_snapshot
from .oidc_group_mapping import (
    GroupMappingError, changed_service_groups, policy_sha256, service_rows,
)
from .fedramp_20x import build_20x_readiness_preview
from .fips_assessment import (
    build_assessment,
    build_poam_workstreams,
    render_poam_csv,
    render_portfolio_poam_csv,
    render_workstream_csv,
)
from .ingestion_jobs import (
    IngestionConfigurationError,
    IngestionManifestError,
    IngestionStateError,
    create_ingestion_batch,
    get_ingestion_batch,
    get_ingestion_batch_logs,
    list_ingestion_batches,
    normalize_manifest,
    submit_ingestion_batch,
)
from .product_scopes import PRODUCT_SCOPES
from .product_fips_contract import suppress_product_candidates, validate_product_fips_contract
from .lead_review_product_scope import (
    LeadReviewProductScopeError,
    matching_product_grant,
    product_scope_fingerprint,
)
from .product_scope_queries import (
    ProductScopeCtes, ProductScopeQueryError, product_scope_ctes,
    source_file_scope_predicate,
)
from .operational_evidence_notes import (
    OperationalEvidenceNoteError, canonical_source_tuple_digest,
    validate_current as validate_evidence_note_current,
    validate_submission as validate_evidence_note_submission,
)
from .service_impact import load_active_service_impacts
from .service_catalog import SERVICE_GROUP_SLUG, ServiceCatalogError, normalized_change
from .target_modules import load_active_target_modules
from .team_milestones import (
    TRACKER_SOURCE,
    build_portfolio_poam_items,
    enrich_poam_items,
    portfolio_delivery_waves,
    team_milestones,
)

LOGGER = logging.getLogger("cbom_catalog.access")

# Deployment must explicitly enable assigned detail after the complete scoped
# query and role matrix has been checked. The checked-in cloud context keeps
# this off. The UI capability is informational; this API gate is authoritative.
_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED = os.environ.get(
    "CBOM_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED", "false"
).strip().casefold() in {"1", "true", "yes", "on"}


class AssignedScopeError(Exception):
    pass


def _validate_scope_grants(grants: Any) -> list[dict[str, str]]:
    """Validate explicit collection/group/product grants and reject ambiguity."""
    if not isinstance(grants, list) or not grants:
        raise AssignedScopeError("Assigned service scope configuration is invalid")
    normalized: list[dict[str, str]] = []
    pairs: set[tuple[str, str]] = set()
    for grant in grants:
        if not isinstance(grant, dict) or not all(
            isinstance(grant.get(key), str) and grant[key].strip()
            for key in ("source_collection", "service_group", "product_scope_id", "boundary_name")
        ):
            raise AssignedScopeError("Assigned service scope configuration is invalid")
        clean = {key: grant[key].strip() for key in ("source_collection", "service_group", "product_scope_id", "boundary_name")}
        if clean["product_scope_id"] not in PRODUCT_SCOPES or clean["boundary_name"] != PRODUCT_SCOPES[clean["product_scope_id"]]:
            raise AssignedScopeError("Assigned service scope configuration is invalid")
        reference = grant.get("assessment_authorization_reference")
        if reference is not None:
            if not isinstance(reference, str) or not reference.strip():
                raise AssignedScopeError("Assigned service scope configuration is invalid")
            clean["assessment_authorization_reference"] = reference.strip()
        pair = (clean["source_collection"], clean["service_group"], clean["product_scope_id"])
        if pair in pairs:
            raise AssignedScopeError("Assigned service scope configuration is ambiguous")
        pairs.add(pair)
        normalized.append(clean)
    return normalized


def _token_assigned_scope_for(principal: Principal) -> dict[str, Any]:
    """Resolve explicit service-credential grants, never OIDC group grants."""
    raw = os.environ.get("CBOM_PRINCIPAL_SCOPE_JSON", "").strip()
    if not raw:
        raise AssignedScopeError("No assigned service scope is configured")
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AssignedScopeError("Assigned service scope configuration is invalid") from error
    entry = mapping.get(principal.subject) if isinstance(mapping, dict) else None
    if not isinstance(entry, dict):
        raise AssignedScopeError("No assigned service scope is configured for this principal")
    grants = _validate_scope_grants(entry.get("grants"))
    return {
        "mode": "portfolio" if entry.get("portfolio") is True else "assigned",
        "grants": grants,
        "fingerprint": hashlib.sha256(json.dumps(grants, sort_keys=True).encode()).hexdigest(),
    }


def _admin_group_mapping_enabled() -> bool:
    return os.environ.get("CBOM_ADMIN_GROUP_MAPPING_ENABLED", "false").strip().casefold() in {
        "1", "true", "yes", "on",
    }


def _baseline_oidc_policy_document() -> dict[str, Any]:
    raw = os.environ.get("CBOM_OIDC_GROUP_SCOPE_JSON", "").strip()
    if not raw:
        raise AssignedScopeError("OIDC group access policy is not configured")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AssignedScopeError("OIDC group access policy is invalid") from error
    if not isinstance(value, dict):
        raise AssignedScopeError("OIDC group access policy is invalid")
    return value


def _oidc_policy_document(database: Any | None = None) -> tuple[dict[str, Any], str, str]:
    """Use the active Admin revision, or the deployment seed before first publish.

    Every request reads the active revision. A redeploy cannot overwrite a
    published Admin mapping, and a corrupt/missing registry fails closed.
    """
    baseline = _baseline_oidc_policy_document()
    baseline_groups = baseline.get("groups")
    if not isinstance(baseline_groups, dict):
        raise AssignedScopeError("OIDC group access policy is invalid")
    if not _admin_group_mapping_enabled():
        return baseline, "deployment", policy_sha256(baseline_groups)
    sql = """
        SELECT revision.id, revision.policy_sha256, revision.groups
        FROM app_auth.oidc_group_policy_active active
        JOIN app_auth.oidc_group_policy_revision revision ON revision.id = active.revision_id
        WHERE active.singleton = 1
    """
    try:
        if database is None:
            with api_connection() as connection:
                row = connection.execute(sql).fetchone()
        else:
            row = database.execute(sql).fetchone()
    except Exception as error:
        LOGGER.exception("Administrator group mapping registry is unavailable")
        raise AssignedScopeError("Administrator group mapping registry is unavailable") from error
    if row is None:
        # Before the first publish the deployment policy is the validated
        # seed. After a publish, a missing pointer is corruption: falling back
        # would silently resurrect mappings an Admin intentionally retired.
        exists_sql = "SELECT EXISTS (SELECT 1 FROM app_auth.oidc_group_policy_revision) AS has_revisions"
        try:
            if database is None:
                with api_connection() as connection:
                    history = connection.execute(exists_sql).fetchone()
            else:
                history = database.execute(exists_sql).fetchone()
        except Exception as error:
            LOGGER.exception("Administrator group mapping history is unavailable")
            raise AssignedScopeError("Administrator group mapping registry is unavailable") from error
        if history is None or history.get("has_revisions") is not False:
            raise AssignedScopeError("Active administrator group mapping revision is missing")
        return baseline, "deployment", policy_sha256(baseline_groups)
    groups = row.get("groups")
    if not isinstance(groups, dict) or policy_sha256(groups) != row.get("policy_sha256"):
        raise AssignedScopeError("Active group mapping revision is invalid")
    for name in ("fedsse-admins", "fedsse-external", "fedsse-scr2-leads"):
        if groups.get(name) != baseline_groups.get(name):
            raise AssignedScopeError("Protected OIDC group mapping was changed")
    try:
        if not service_rows(groups):
            raise GroupMappingError("At least one exact service mapping is required")
    except GroupMappingError as error:
        raise AssignedScopeError(str(error)) from error
    revision = hashlib.sha256(f"{row['id']}:{row['policy_sha256']}".encode()).hexdigest()
    return {**baseline, "version": f"admin:{row['id']}:{row['policy_sha256'][:12]}", "groups": groups}, "admin", revision


def _oidc_group_policy() -> tuple[str, dict[str, dict[str, Any]]]:
    """Load and validate exact signed-group grants from the active policy."""
    value, _, _ = _oidc_policy_document()
    return _normalize_oidc_policy(value)


def _normalize_oidc_policy(value: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    if (not isinstance(value, dict)
        or not isinstance(value.get("version"), str)
        or not value["version"].strip()
        or not isinstance(value.get("groups"), dict)):
        raise AssignedScopeError("OIDC group access policy is invalid")
    groups = value["groups"]
    normalized: dict[str, dict[str, Any]] = {}
    for name, entry in groups.items():
        if (not isinstance(name, str)
            or not re.fullmatch(r"fedsse-[a-z0-9]+(?:-[a-z0-9]+)*", name)
            or not isinstance(entry, dict)):
            raise AssignedScopeError("OIDC group access policy is invalid")
        access = entry.get("access")
        if access not in {"admin", "summary", "lead", "engineer"}:
            raise AssignedScopeError("OIDC group access policy is invalid")
        if access == "admin" and name != "fedsse-admins":
            raise AssignedScopeError("Only fedsse-admins can grant administrator access")
        if access == "summary" and name not in {"fedsse-external", "fedsse-scr2-leads"}:
            raise AssignedScopeError("OIDC summary group policy is invalid")
        if name in {"fedsse-external", "fedsse-scr2-leads"} and access != "summary":
            raise AssignedScopeError("OIDC summary group policy is invalid")
        if access in {"lead", "engineer"} and not name.endswith(
            "-leads" if access == "lead" else "-engineers"
        ):
            raise AssignedScopeError("OIDC service group policy is invalid")
        if access in {"lead", "engineer"}:
            service_key = entry.get("service_key")
            suffix = "leads" if access == "lead" else "engineers"
            if (
                not isinstance(service_key, str)
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", service_key)
                or name != f"fedsse-{service_key}-{suffix}"
            ):
                raise AssignedScopeError("OIDC service group policy is invalid")
        grants = entry.get("grants", [])
        if access in {"lead", "engineer"}:
            grants = _validate_scope_grants(grants)
        elif grants:
            raise AssignedScopeError("OIDC group access policy is invalid")
        normalized[name] = {"access": access, "grants": grants}
    if normalized.get("fedsse-admins", {}).get("access") != "admin":
        raise AssignedScopeError("OIDC policy must define fedsse-admins as admin")
    return str(value.get("version", "unversioned")), normalized


def _assigned_scope_for(principal: Principal) -> dict[str, Any]:
    """Resolve one effective access profile from verified OIDC groups.

    Browser roles never come from app_auth.app_user.role.  Service credentials
    retain their explicit, independently configured scopes and grants.
    """
    if principal.kind == "local":
        return {
            "mode": "portfolio", "role": "admin", "summary_access": True,
            "grants": [], "matched_groups": ["local-admin"],
            "policy_version": "local", "fingerprint": "local",
            "available_modes": ["admin"], "default_mode": "admin",
        }
    if principal.kind != "human":
        token_scope = _token_assigned_scope_for(principal)
        return {
            **token_scope, "role": "viewer", "summary_access": False,
            "matched_groups": [], "policy_version": "token", "token_access": True,
            "available_modes": [], "default_mode": None,
        }

    version, policy = _oidc_group_policy()
    matched_groups = sorted(set(principal.oidc_groups).intersection(policy))
    matched_entries = [policy[name] for name in matched_groups]
    is_admin = any(entry["access"] == "admin" for entry in matched_entries)
    summary_access = is_admin or any(
        entry["access"] in {"summary", "lead", "engineer"}
        for entry in matched_entries
    )
    by_pair: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in matched_entries:
        if entry["access"] not in {"lead", "engineer"}:
            continue
        for grant in entry["grants"]:
            pair = (grant["source_collection"], grant["service_group"], grant["product_scope_id"])
            previous = by_pair.get(pair)
            if previous is None or entry["access"] == "lead":
                by_pair[pair] = {**grant, "access": entry["access"]}
    grants = [by_pair[pair] for pair in sorted(by_pair)]
    # A mode is available only when an exact matched group establishes it.
    # In particular, a lead group does not manufacture an engineer choice.
    # The role selected later may reduce authority, but it never adds a grant.
    available_modes: list[str] = []
    if is_admin:
        available_modes.append("admin")
    if any(entry["access"] == "lead" for entry in matched_entries):
        available_modes.append("product_lead")
    if any(entry["access"] == "engineer" for entry in matched_entries):
        available_modes.append("product_engineer")
    if any(entry["access"] == "summary" for entry in matched_entries):
        available_modes.append("summary")
    role = (
        "admin" if is_admin else "lead" if any(row["access"] == "lead" for row in grants)
        else "engineer" if grants else "summary" if summary_access else "none"
    )
    fingerprint = hashlib.sha256(
        json.dumps({"version": version, "matched": matched_groups, "grants": grants}, sort_keys=True).encode()
    ).hexdigest()
    return {
        "mode": "portfolio" if is_admin else "assigned" if grants else "summary" if summary_access else "denied",
        "role": role, "summary_access": summary_access, "grants": grants,
        "matched_groups": matched_groups, "policy_version": version,
        "fingerprint": fingerprint, "available_modes": available_modes,
        "default_mode": available_modes[0] if available_modes else None,
    }


_ACCESS_MODE_HEADER = "x-cbom-access-mode"
_ACCESS_MODE_VALUES = frozenset({"admin", "product_lead", "product_engineer", "summary"})


def _apply_access_mode(assigned: dict[str, Any], requested: str | None) -> dict[str, Any]:
    """Apply a verified, caller-selected presentation mode without adding authority.

    The mode is carried by a request header and must be revalidated on every
    request.  There is deliberately no stored application role or mutable
    session selection that could outlive a group change at the identity
    provider. Product Lead keeps the exact per-pair access values; Product
    Engineer can see the verified union only after each pair is reduced to
    read-only. Admin remains the only portfolio mode.
    """
    available = list(assigned.get("available_modes") or [])
    default = assigned.get("default_mode")
    if requested is not None and requested not in _ACCESS_MODE_VALUES:
        raise AssignedScopeError("Requested access mode is invalid")
    if requested is not None and requested not in available:
        raise AssignedScopeError("Requested access mode is not granted by verified groups")
    selected = requested or default
    if selected is None:
        return {**assigned, "active_mode": None}
    if selected == "admin":
        # This condition is redundant with the exact group policy check above,
        # but keeps this reducer safe if its caller changes.
        if "admin" not in available:
            raise AssignedScopeError("Requested access mode is not granted by verified groups")
        return {**assigned, "mode": "portfolio", "role": "admin", "summary_access": True, "active_mode": selected}
    if selected == "product_lead":
        if "product_lead" not in available:
            raise AssignedScopeError("Requested access mode is not granted by verified groups")
        return {**assigned, "mode": "assigned", "role": "lead", "summary_access": True, "active_mode": selected}
    if selected == "product_engineer":
        if "product_engineer" not in available:
            raise AssignedScopeError("Requested access mode is not granted by verified groups")
        # A person who has both group categories receives the union already
        # present in grants, with every pair reduced to read-only.  A lead-only
        # membership cannot select this mode.
        grants = [{**grant, "access": "engineer"} for grant in assigned.get("grants", [])]
        return {**assigned, "mode": "assigned", "role": "engineer", "summary_access": True, "grants": grants, "active_mode": selected}
    # Summary is aggregate-only, even when the caller also has a service role.
    if selected == "summary":
        return {**assigned, "mode": "summary", "role": "summary", "summary_access": True, "grants": [], "active_mode": selected}
    raise AssignedScopeError("Requested access mode is invalid")


def _request_access_mode(request: Request) -> str | None:
    raw = request.headers.get(_ACCESS_MODE_HEADER)
    if raw is None:
        return None
    value = raw.strip()
    if not value or value != raw:
        raise AssignedScopeError("Requested access mode is invalid")
    return value


def _request_within_assigned_scope(request: Request, assigned: dict[str, Any]) -> bool:
    """Fail closed unless an assigned caller names one exact granted pair."""
    if request.url.path == "/api/v1/auth/me":
        return True
    # Administrative operational reads are global by design and are therefore
    # available only to an explicitly configured portfolio principal.  An
    # application role or an assigned-service grant is never portfolio access.
    if request.url.path.startswith("/api/v1/admin/"):
        return assigned.get("mode") == "portfolio" and (
            assigned.get("role") == "admin" or assigned.get("token_access") is True
        )
    if request.url.path == "/api/v1/portfolio/product-scope-status":
        return request.method in {"GET", "HEAD"} and (
            (assigned.get("mode") == "portfolio" and assigned.get("role") == "admin")
            or (assigned.get("mode") == "assigned" and bool(assigned.get("grants")))
        )
    if request.url.path == "/api/v1/portfolio/assigned-service-groups":
        # This is a bounded union register, not a portfolio query.  It returns
        # rows only for exact verified grants and uses the evidence-only
        # projection below so unprovenanced planning and candidate data remain
        # unavailable to product roles.
        return request.method in {"GET", "HEAD"} and (
            assigned.get("mode") == "assigned" and bool(assigned.get("grants"))
        )
    if request.url.path == "/api/v1/service-catalog":
        # Service Catalog rows include operational owner and planning metadata.
        # They are available to an administrator or to a product principal,
        # filtered to its exact groups by the endpoint. Summary access remains
        # aggregate-only and cannot enumerate this register.
        return request.method in {"GET", "HEAD"} and (
            (assigned.get("mode") == "portfolio" and assigned.get("role") == "admin")
            or (assigned.get("mode") == "assigned" and bool(assigned.get("grants")))
        )
    if request.url.path == "/api/v1/service-catalog/proposals":
        return request.method == "POST" and (
            assigned.get("mode") == "assigned" and assigned.get("role") == "lead"
        )
    if request.url.path in {
        "/api/v1/portfolio/overview-summary",
        "/api/v1/portfolio/poam-summary",
    }:
        return request.method in {"GET", "HEAD"} and bool(assigned.get("summary_access"))
    if assigned.get("mode") == "portfolio" and assigned.get("role") == "admin":
        return True
    # Only these routes apply the exact pair to their catalog query.  A granted
    # pair must never turn an unrelated global route into an authorized read.
    pair_aware_paths = {
        "/api/v1/dashboard/overview",
        "/api/v1/fingerprints",
        "/api/v1/documents",
        "/api/v1/inventory/documents",
        "/api/v1/components",
        "/api/v1/inventory/libraries",
        "/api/v1/artifacts",
        "/api/v1/dependency-documents",
        "/api/v1/dependency-closure",
        "/api/v1/external-records",
        "/api/v1/inventory/service-groups",
        "/api/v1/fips/assessment",
        "/api/v1/fips/reporting/20x-preview",
        "/api/v1/fips/poam.csv",
        "/api/v1/fips/poam-workstreams.csv",
        "/api/v1/fips/portfolio-poam.csv",
        "/api/v1/fips/compliance-package.zip",
        "/api/v1/review-proposals",
        "/api/v1/operational-evidence-notes",
    }
    pair_aware_patterns = (
        r"/api/v1/inventory/service-groups/[^/]+/[^/]+",
        r"/api/v1/documents/\d+",
        r"/api/v1/documents/\d+/components",
        r"/api/v1/documents/\d+/dependency-graph",
        r"/api/v1/components/\d+/usage",
    )
    if request.url.path not in pair_aware_paths and not any(
        re.fullmatch(pattern, request.url.path) for pattern in pair_aware_patterns
    ):
        return False
    collection = request.query_params.get("source_collection")
    group = request.query_params.get("service_group")
    product_scope_id = request.query_params.get("product_scope_id")
    match = re.fullmatch(r"/api/v1/inventory/service-groups/([^/]+)/([^/]+)", request.url.path)
    if match:
        collection, group = match.groups()
    matched = next((grant for grant in assigned.get("grants", []) if
        collection == grant.get("source_collection") and group == grant.get("service_group")
        and product_scope_id == grant.get("product_scope_id")
    ), None)
    if matched is None:
        return False
    if not _PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED:
        return False
    if request.url.path == "/api/v1/review-proposals" and not _lead_review_proposals_enabled():
        return False
    if request.url.path == "/api/v1/operational-evidence-notes" and not _operational_evidence_notes_enabled():
        return False
    if request.url.path.startswith("/api/v1/fips/"):
        # A product routing decision and boundary label are insufficient for
        # scoped FIPS detail. Every request needs an exact service/product
        # contract whose immutable authorization reference agrees with the
        # verified group-policy grant. An incomplete but exactly scoped
        # assessment may return evidence-only observations and missing facts;
        # exports and reporting previews still require a complete contract.
        validation = _product_fips_validation(collection, group, product_scope_id)
        reference = matched.get("assessment_authorization_reference")
        reference_matches = (
            isinstance(reference, str)
            and bool(reference.strip())
            and validation is not None
            and validation.get("authorization_reference") == reference.strip()
        )
        if not reference_matches:
            return False
        if request.url.path == "/api/v1/fips/assessment" and request.method in {"GET", "HEAD"}:
            # The supplied contract must still name this exact triple. Missing
            # scope or conflicting scope facts cannot authorize a product view.
            scope_fields = {"source_collection", "service_group", "product_scope_id"}
            missing_scope = scope_fields.intersection(validation.get("missing_required_facts") or [])
            conflicting_scope = scope_fields.intersection(validation.get("conflicting_facts") or [])
            if not missing_scope and not conflicting_scope:
                return True
        return validation.get("complete") is True
    return True


def _fips_assessment_contract() -> dict[str, Any] | None:
    """Read an optional deployment configuration; never derive contract facts from catalog data."""
    raw = os.environ.get("CBOM_FIPS_ASSESSMENT_CONTRACT_JSON", "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        LOGGER.warning("CBOM_FIPS_ASSESSMENT_CONTRACT_JSON is not valid JSON")
        return None
    return value if isinstance(value, dict) else None


def _unavailable_planning_context() -> dict[str, Any]:
    """Represent planning data withheld for lack of collection provenance."""
    return {
        "source": None,
        "groups": [],
        "all_tracker_rows": [],
        "disclaimer": (
            "Planning metadata is unavailable for this assigned scope because "
            "the active planning import has no source-collection provenance."
        ),
    }


app = FastAPI(
    title="CBOM Catalog API",
    version=__version__,
    description="Search normalized CycloneDX, SPDX, OSCAL, FIPS, and enrichment records.",
)

app.add_middleware(GZipMiddleware, minimum_size=1_000, compresslevel=5)

_cors_origins = [
    origin.strip()
    for origin in os.environ.get("CBOM_CORS_ORIGINS", "").split(",")
    if origin.strip()
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "HEAD", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "If-None-Match", "X-Request-ID"],
        expose_headers=["ETag", "X-Request-ID", "X-Catalog-Revision"],
        max_age=600,
    )

STATIC_DIRECTORY = Path(__file__).with_name("static")

_rate_lock = RLock()
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)
_cache_lock = RLock()
_data_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
_cache_revision: int | None = None
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class UserAccessUpdate(BaseModel):
    role: str | None = None
    status: str | None = None


class UserAccessActionCreate(BaseModel):
    action: str = Field(pattern=r"^(revoke|restore)$")
    reason: str = Field(min_length=8, max_length=2_000)


class GroupMappingSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_key: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)
    source_collection: str = Field(min_length=1, max_length=80)
    service_group: str = Field(min_length=1, max_length=120)
    product_scope_ids: list[str] = Field(min_length=1, max_length=2)
    reason: str = Field(min_length=8, max_length=500)
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class GroupMappingRetire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=8, max_length=500)
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class ApiCredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=10)
    expires_in_days: int = Field(default=30, ge=1, le=90)


class OverlayCreate(BaseModel):
    resource_type: str
    resource_key: str = Field(min_length=1, max_length=240)
    payload: dict[str, Any]
    rationale: str = Field(min_length=8, max_length=2_000)


class LeadReviewProposalCreate(BaseModel):
    """A service lead's non-authoritative review request.

    This deliberately models a proposal, not a catalog finding disposition or
    an overlay.  An administrator's later decision does not rewrite source
    evidence, planning records, or candidate assessment output.
    """

    source_collection: str = Field(min_length=1, max_length=80)
    service_group: str = Field(min_length=1, max_length=120)
    product_scope_id: str = Field(min_length=1, max_length=80)
    resource_type: str
    resource_key: str = Field(min_length=1, max_length=240)
    proposed_note: str = Field(min_length=8, max_length=4_000)
    rationale: str = Field(min_length=8, max_length=2_000)


class LeadReviewDecisionCreate(BaseModel):
    decision: str
    decision_reason: str = Field(min_length=8, max_length=2_000)


class OperationalEvidenceNoteCreate(BaseModel):
    # Reject client-supplied routing or finding snapshots rather than silently
    # discarding them before the server derives its own current evidence state.
    model_config = ConfigDict(extra="forbid")

    source_collection: str = Field(min_length=1, max_length=80)
    service_group: str = Field(min_length=1, max_length=120)
    product_scope_id: str = Field(min_length=1, max_length=80)
    finding_id: str = Field(min_length=1, max_length=240)
    note: str = Field(min_length=8, max_length=4_000)
    lead_rationale: str = Field(min_length=8, max_length=2_000)


class OperationalEvidenceNoteDecisionCreate(BaseModel):
    decision: str = Field(pattern=r"^(approved|rejected)$")
    reason: str = Field(min_length=8, max_length=2_000)


class ServiceCatalogChange(BaseModel):
    """Managed operational metadata; omitted fields retain their prior value."""
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=240)
    owner: str | None = Field(default=None, max_length=240)
    owner_profile_email: str | None = Field(default=None, max_length=320)
    lead: str | None = Field(default=None, max_length=240)
    lead_profile_email: str | None = Field(default=None, max_length=320)
    il2_status: str | None = None
    il2_target_date: date | None = None
    il5_status: str | None = None
    il5_target_date: date | None = None
    service_impact_risk: str | None = Field(default=None, max_length=32)
    comments: str | None = Field(default=None, max_length=4_000)
    attributes: dict[str, Any] | None = None


class ServiceCatalogCreate(ServiceCatalogChange):
    source_collection: str = Field(min_length=1, max_length=80)
    service_group: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=240)
    reason: str = Field(min_length=8, max_length=2_000)


class ServiceCatalogUpdate(ServiceCatalogChange):
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=8, max_length=2_000)


class ServiceCatalogProposalCreate(ServiceCatalogChange):
    source_collection: str = Field(min_length=1, max_length=80)
    service_group: str = Field(min_length=1, max_length=120)
    expected_revision: int = Field(ge=0)
    rationale: str = Field(min_length=8, max_length=2_000)


class ServiceCatalogProposalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(pattern=r"^(approved|rejected)$")
    decision_reason: str = Field(min_length=8, max_length=2_000)


class IngestionManifestFile(BaseModel):
    path: str = Field(min_length=1, max_length=1_024)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    size_bytes: int = Field(ge=0, le=5 * 1024 * 1024 * 1024)
    modified_at: str | None = None


class IngestionBatchCreate(BaseModel):
    source_collection: str = Field(min_length=1, max_length=80)
    dry_run: bool = False
    authoritative_snapshot: bool = False
    manifest_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    files: list[IngestionManifestFile] = Field(min_length=1, max_length=5_000)


class IngestionBatchSubmit(BaseModel):
    manifest_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


def _production_mode() -> bool:
    return os.environ.get("CBOM_ENVIRONMENT", "local").strip().casefold() in {
        "production",
        "prod",
        "cloud",
    }


def _security_headers(response: Response, request_id: str) -> Response:
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'; object-src 'none'"
    )
    if "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "private, no-cache"
    if _env_bool("CBOM_ENABLE_HSTS"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def _authentication_error(request_id: str, detail: str, status_code: int) -> Response:
    response = JSONResponse({"detail": detail}, status_code=status_code)
    if status_code == 401:
        response.headers["WWW-Authenticate"] = "Bearer"
    return _security_headers(response, request_id)


def _client_key(request: Request) -> str:
    if _env_bool("CBOM_TRUST_PROXY_HEADERS"):
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


def _rate_limited(request: Request) -> bool:
    configured = os.environ.get("CBOM_API_RATE_LIMIT_PER_MINUTE")
    try:
        limit = int(configured) if configured is not None else (600 if _production_mode() else 0)
    except ValueError:
        LOGGER.warning("Invalid CBOM_API_RATE_LIMIT_PER_MINUTE; using the safe default")
        limit = 600 if _production_mode() else 0
    if limit <= 0:
        return False
    now = time.monotonic()
    key = _client_key(request)
    with _rate_lock:
        if len(_rate_buckets) > 2_048:
            stale_keys = [
                bucket_key
                for bucket_key, values in _rate_buckets.items()
                if not values or now - values[-1] >= 60
            ]
            for bucket_key in stale_keys:
                _rate_buckets.pop(bucket_key, None)
        bucket = _rate_buckets[key]
        while bucket and now - bucket[0] >= 60:
            bucket.popleft()
        if len(bucket) >= limit:
            return True
        bucket.append(now)
    return False


@app.middleware("http")
async def access_controls(request: Request, call_next):  # type: ignore[no-untyped-def]
    supplied_request_id = request.headers.get("x-request-id", "").strip()
    request_id = (
        supplied_request_id
        if _REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
        else str(uuid.uuid4())
    )
    request.state.request_id = request_id
    started = time.perf_counter()
    subject = "health-check"
    if request.url.path not in {"/healthz", "/api/v1/health"}:
        try:
            principal = authenticate_request(request, production=_production_mode())
            request.state.principal = principal
            subject = principal.subject
            if _access_is_revoked(principal.user_id):
                return _authentication_error(request_id, "Access has been revoked by an administrator", 403)
            if request.method in {"GET", "HEAD"} and principal.kind in {"token", "service"}:
                require_scope(principal, read_scope_for_path(request.url.path))
            # A signed-in caller may always retrieve their own application role
            # and assigned-scope status.  This is the bootstrap endpoint for a
            # deployment before its first principal grant exists; it exposes no
            # catalog data and cannot be used to select a scope.
            if request.url.path == "/api/v1/auth/me" and request.method in {"GET", "HEAD"}:
                # Preserve the effective grant for an already-configured user.
                # Only a missing or malformed grant is non-fatal here, so an
                # administrator can complete the deployment bootstrap.
                try:
                    request.state.assigned_scope = _assigned_scope_for(principal)
                    if principal.kind in {"human", "local"}:
                        requested_mode = _request_access_mode(request)
                        if (
                            principal.kind == "human"
                            and len(request.state.assigned_scope.get("available_modes") or []) > 1
                            and requested_mode is None
                        ):
                            request.state.assigned_scope = {
                                **request.state.assigned_scope,
                                # Profile metadata may show available grants,
                                # but an unselected profile never gives the UI
                                # an effective role to use for page gating.
                                "mode": "selection_required", "role": "none",
                                "summary_access": False, "active_mode": None,
                                "selection_required": True,
                            }
                        else:
                            request.state.assigned_scope = _apply_access_mode(
                                request.state.assigned_scope, requested_mode
                            )
                except AssignedScopeError:
                    request.state.assigned_scope = None
            elif (
                request.url.path.startswith("/api/v1/admin/")
                or (request.method in {"GET", "HEAD"} and request.url.path.startswith("/api/"))
                # These are the only non-admin write routes that accept a
                # product-scoped human action. Keep the allowlist explicit so
                # resolving a selected product mode cannot broaden unrelated
                # POST handlers or service-credential behavior.
                or (
                    request.method == "POST"
                    and request.url.path in {
                        "/api/v1/review-proposals",
                        "/api/v1/operational-evidence-notes",
                        "/api/v1/service-catalog/proposals",
                    }
                )
            ):
                try:
                    request.state.assigned_scope = _assigned_scope_for(principal)
                    if principal.kind in {"human", "local"}:
                        base_scope = request.state.assigned_scope
                        requested_mode = _request_access_mode(request)
                        # A person entitled to more than one category must
                        # explicitly choose before catalog or write data is
                        # released. /auth/me remains available to render that
                        # choice and has no catalog payload.
                        if (
                            principal.kind == "human"
                            and len(base_scope.get("available_modes") or []) > 1
                            and requested_mode is None
                        ):
                            return _authentication_error(
                                request_id, "Choose an access mode before accessing application data", 403,
                            )
                        request.state.assigned_scope = _apply_access_mode(base_scope, requested_mode)
                except AssignedScopeError as error:
                    return _authentication_error(request_id, str(error), 403)
                if not _request_within_assigned_scope(request, request.state.assigned_scope):
                    direct_id = bool(re.search(r"/(documents|components|artifacts)/\d+(?:/|$)", request.url.path))
                    return _authentication_error(
                        request_id, "Resource not found" if direct_id else "Requested resource is outside assigned scope",
                        404 if direct_id else 403,
                    )
            assigned = getattr(request.state, "assigned_scope", None)
            if isinstance(assigned, dict):
                _record_access_roster_snapshot(principal, assigned)
            if principal.kind in {"human", "local"} and isinstance(assigned, dict):
                principal = replace(principal, role=str(assigned.get("role") or "viewer"))
                request.state.principal = principal
        except AccessDenied as error:
            return _authentication_error(request_id, error.detail, error.status_code)
    if request.url.path not in {"/healthz", "/api/v1/health"} and _rate_limited(request):
        response = JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        response.headers["Retry-After"] = "60"
        return _security_headers(response, request_id)
    response = await call_next(request)
    _security_headers(response, request_id)
    elapsed_ms = (time.perf_counter() - started) * 1_000
    LOGGER.info(
        "request_id=%s subject=%s method=%s path=%s status=%s elapsed_ms=%.1f",
        request_id,
        subject,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.on_event("shutdown")
def shutdown_database_pool() -> None:
    close_pool()


@app.on_event("startup")
def prewarm_catalog_caches() -> None:
    """Build the expensive unscoped views before the first interactive request."""
    if not _env_bool("CBOM_API_PREWARM"):
        return
    started = time.perf_counter()
    try:
        _cached_catalog_value(
            "dashboard-overview",
            (None, None),
            lambda: _build_dashboard_overview(None, None),
        )
        _cached_fips_assessment(None, None)
    except Exception:
        # A transient database problem must not keep health checks from starting;
        # the normal request path can retry and will expose the actual error.
        LOGGER.exception("catalog cache prewarm failed")
    else:
        LOGGER.info(
            "catalog cache prewarm completed elapsed_ms=%.1f",
            (time.perf_counter() - started) * 1_000,
        )


def _database_url() -> str | None:
    return os.environ.get("DATABASE_URL")


def _max_page_size() -> int:
    try:
        configured = int(os.environ.get("CBOM_API_PAGE_SIZE", "100"))
    except ValueError:
        LOGGER.warning("Invalid CBOM_API_PAGE_SIZE; using 100")
        configured = 100
    return max(1, min(configured, 1000))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _access_roster_enabled() -> bool:
    """Enable operational revocation only after migration 019 is present."""
    return _env_bool("CBOM_ACCESS_ROSTER_ENABLED")


def _operational_evidence_notes_enabled() -> bool:
    """Separate default-deny switch for the append-only observation workflow."""
    return _env_bool("CBOM_OPERATIONAL_EVIDENCE_NOTES_ENABLED") and _PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED


def _lead_review_proposals_enabled() -> bool:
    """Keep lead proposal writes off until their operational workflow is enabled."""
    return _env_bool("CBOM_LEAD_REVIEW_PROPOSALS_ENABLED") and _PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED


def _review_proposals_enabled_for_access(principal: Principal, access: dict[str, Any]) -> bool:
    """Report whether the selected profile may read its exact lead review queue.

    This mirrors the route's feature and grant prerequisites for UI fetch
    suppression.  It is informational only: middleware and the route still
    resolve and validate the exact triple on every request.
    """
    if (
        not _lead_review_proposals_enabled()
        or principal.kind != "human"
        or access.get("mode") != "assigned"
        or access.get("role") != "lead"
        or access.get("active_mode") != "product_lead"
    ):
        return False
    for grant in access.get("grants", []):
        if not isinstance(grant, dict) or grant.get("access") != "lead":
            continue
        try:
            matching_product_grant(
                [grant],
                source_collection=str(grant.get("source_collection") or ""),
                service_group=str(grant.get("service_group") or ""),
                product_scope_id=str(grant.get("product_scope_id") or ""),
            )
        except LeadReviewProductScopeError:
            continue
        return True
    return False


def _access_is_revoked(user_id: int | None) -> bool:
    if not _access_roster_enabled() or user_id is None:
        return False
    row = _fetch_one(
        """
        SELECT action FROM app_auth.user_access_action
        WHERE target_user_id = %s
        ORDER BY occurred_at DESC, id DESC LIMIT 1
        """,
        (user_id,),
    )
    return bool(row and row.get("action") == "revoke")


def _record_access_roster_snapshot(principal: Principal, assigned: dict[str, Any]) -> None:
    """Persist verified OIDC policy telemetry; it never grants access."""
    if (
        not _access_roster_enabled()
        or principal.kind != "human"
        or principal.user_id is None
        or assigned.get("selection_required") is True
    ):
        return
    with api_connection() as database:
        record_snapshot(
            database,
            user_id=principal.user_id,
            effective_role=str(assigned.get("role") or "none"),
            grants=list(assigned.get("grants") or []),
            policy_version=str(assigned.get("policy_version") or "unconfigured"),
            policy_fingerprint=str(assigned.get("fingerprint") or ""),
        )
        database.commit()


def _fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with api_connection() as connection:
        return list(connection.execute(sql, params).fetchall())


def _fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with api_connection() as connection:
        return connection.execute(sql, params).fetchone()


def _catalog_revision() -> int:
    row = _fetch_one(
        """
        SELECT coalesce((SELECT max(id) FROM ingest_run), 0) AS ingest_revision,
               coalesce((SELECT max(id) FROM target_module_import), 0) AS target_revision,
               coalesce((SELECT max(id) FROM target_module_evidence_import), 0) AS evidence_revision,
               coalesce((SELECT max(id) FROM service_impact_import), 0) AS service_impact_revision,
               coalesce((SELECT max(id) FROM app_auth.admin_overlay), 0) AS overlay_revision,
               coalesce((SELECT max(id) FROM app_auth.evidence_product_scope_decision), 0) AS routing_revision
        """
    )
    # Keep one numeric revision for cache and ETag compatibility while ensuring
    # a planning-data import invalidates assessment and register responses.
    base_revision = (
        int((row or {}).get("ingest_revision") or 0) * 1_000_000_000_000_000_000_000_000
        + int((row or {}).get("target_revision") or 0) * 1_000_000_000_000_000_000
        + int((row or {}).get("evidence_revision") or 0) * 1_000_000_000_000
        + int((row or {}).get("service_impact_revision") or 0) * 1_000_000
        + int((row or {}).get("overlay_revision") or 0)
    )
    # Product routing is append-only and can change independently of an ingest
    # run. Invalidate cached scoped assessments before an admin decides whether
    # a lead's frozen evidence observation is still current.
    return base_revision * 1_000_000_000_000 + int((row or {}).get("routing_revision") or 0)


def _active_target_module_contract() -> dict[str, Any] | None:
    with api_connection() as connection:
        return load_active_target_modules(connection)


def _active_service_impact_map() -> dict[str, dict[str, Any]]:
    with api_connection() as connection:
        return load_active_service_impacts(connection)


def _active_overlay_map(resource_type: str) -> dict[str, dict[str, Any]]:
    rows = _fetch_all(
        """
        SELECT resource_key, version, payload, rationale, created_at
        FROM app_auth.admin_overlay
        WHERE resource_type = %s AND is_active
        """,
        (resource_type,),
    )
    return {str(row["resource_key"]): row for row in rows}


def _apply_candidate_overlays(
    items: list[dict[str, Any]],
    overlays: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Apply review metadata to response copies without mutating cached evidence."""
    overlays = overlays or {}
    result = []
    for source in items:
        item = dict(source)
        overlay = overlays.get(str(item.get("poam_candidate_id") or ""))
        if overlay:
            item.update(overlay.get("payload") or {})
            item["admin_overlay"] = overlay
        result.append(item)
    return result


def _cached_catalog_value(
    namespace: str,
    parts: tuple[Any, ...],
    builder,  # type: ignore[no-untyped-def]
) -> tuple[Any, int, bool]:
    global _cache_revision
    revision = _catalog_revision()
    key = (namespace, revision, *parts)
    with _cache_lock:
        if _cache_revision != revision:
            _data_cache.clear()
            _cache_revision = revision
        if key in _data_cache:
            value = _data_cache.pop(key)
            _data_cache[key] = value
            return value, revision, True

    # Aggregates can take several seconds on a cold catalog. Never hold the
    # global LRU lock while querying: unrelated dashboard, inventory, and FIPS
    # requests should be able to build concurrently.
    value = builder()

    with _cache_lock:
        # Another request may have completed the same key while this one was
        # building. Prefer its canonical cached object and report a cache hit.
        if key in _data_cache:
            cached = _data_cache.pop(key)
            _data_cache[key] = cached
            return cached, revision, True
        # An import may have advanced the catalog while the builder ran. Return
        # the internally consistent result for its revision, but do not retain
        # it in the new revision's cache.
        if _cache_revision == revision:
            _data_cache[key] = value
            while len(_data_cache) > 32:
                _data_cache.popitem(last=False)
        return value, revision, False


def _conditional_json_response(
    request: Request,
    data: Any,
    *,
    namespace: str,
    revision: int,
    cache_hit: bool,
    parts: tuple[Any, ...] = (),
) -> Response:
    digest = hashlib.sha256(
        json.dumps([namespace, revision, *parts], separators=(",", ":"), default=str).encode()
    ).hexdigest()
    etag = f'"{digest}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=0, must-revalidate",
        "Vary": "Authorization, Accept-Encoding",
        "X-Catalog-Revision": str(revision),
        "X-Cache": "HIT" if cache_hit else "MISS",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(jsonable_encoder(data), headers=headers)


def _scope_sql(
    source_collection: str | None,
    service_group: str | list[str] | None,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if source_collection:
        clauses.append("sc.slug = %s")
        params.append(source_collection)
    if isinstance(service_group, list):
        clauses.append("sg.slug = ANY(%s)")
        params.append(service_group)
    elif service_group:
        clauses.append("sg.slug = %s")
        params.append(service_group)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, tuple(params)


def _product_scope_ctes(product_scope_id: str | None) -> ProductScopeCtes | None:
    """Build current-SHA evidence CTEs only for an assigned product view.

    Portfolio administrators omit ``product_scope_id`` and retain their
    deliberately unpartitioned inventory view.  Assigned callers must supply
    an exact ID at the middleware boundary before this helper is reachable.
    """
    if not product_scope_id:
        return None
    try:
        return product_scope_ctes(product_scope_id)
    except ProductScopeQueryError as error:
        raise HTTPException(status_code=422, detail="Unsupported product_scope_id") from error


def _scope_cte_prefix(product_scope_id: str | None) -> tuple[str, tuple[Any, ...], ProductScopeCtes | None]:
    scope = _product_scope_ctes(product_scope_id)
    if scope is None:
        return "", (), None
    return f"WITH {scope.sql},", scope.params, scope


def _fips_scope_cte(
    source_collection: str | None, service_group: str | list[str] | None,
    product_scope_id: str | None = None,
) -> tuple[str, tuple[Any, ...]]:
    where, params = _scope_sql(source_collection, service_group)
    scoped_filters = where.replace(" WHERE ", " AND ", 1)
    product_ctes = _product_scope_ctes(product_scope_id)
    prefix = f"WITH {product_ctes.sql}," if product_ctes else "WITH"
    source_files = product_ctes.source_files if product_ctes else "source_file"
    return (
        f"""
        {prefix} scoped_source_files AS (
            SELECT sf.*, sc.slug AS collection_slug, sg.slug AS group_slug,
                   sg.display_name AS group_name
            FROM {source_files} sf
            JOIN source_collection sc ON sc.id = sf.source_collection_id
            JOIN service_group sg ON sg.id = sf.service_group_id
            WHERE sf.is_present
            {scoped_filters}
        ),
        scoped_documents AS (
            SELECT DISTINCT document_id
            FROM scoped_source_files
            WHERE document_id IS NOT NULL
        ),
        scoped_document_groups AS (
            SELECT DISTINCT document_id, service_group_id
            FROM scoped_source_files
            WHERE document_id IS NOT NULL
        ),
        occurrence_relevance AS (
            SELECT cp.occurrence_id,
                   bool_or(
                       lower(trim(cp.property_value)) IN
                       ('0', 'false', 'no', 'off', 'disabled', 'not-validated', 'not validated')
                   ) AS explicitly_false,
                   bool_or(
                       lower(trim(cp.property_value)) IN
                       ('1', 'true', 'yes', 'on', 'enabled', 'validated')
                   ) AS explicitly_true
            FROM component_property cp
            JOIN document_component dc ON dc.id = cp.occurrence_id
            JOIN scoped_documents sd ON sd.document_id = dc.document_id
            WHERE lower(cp.property_name) = 'fedramp:fips:crypto-relevant'
            GROUP BY cp.occurrence_id
        )
        """,
        (*(product_ctes.params if product_ctes else ()), *params),
    )


def _load_fips_assessment(
    source_collection: str | None,
    service_group: str | None,
    contract: dict[str, Any] | None = None,
    product_scope_id: str | None = None,
) -> dict[str, Any]:
    # The SQL evidence universe must be no broader than a deployment contract.
    # Multi-group contracts fail closed until the query layer has an explicit
    # list predicate; never build a manifest from a portfolio-wide fallback.
    effective_collection = source_collection
    effective_group = service_group
    effective_contract = contract
    if isinstance(contract, dict) and contract.get("source_collection"):
        groups = contract.get("service_groups")
        if effective_collection not in (None, contract["source_collection"]):
            effective_group = "__contract_scope_mismatch__"
        else:
            effective_collection = contract["source_collection"]
            if effective_group is None and isinstance(groups, list) and len(groups) == 1:
                effective_group = groups[0]
            elif effective_group is None and isinstance(groups, list) and len(groups) != 1:
                effective_group = groups
            elif isinstance(groups, list) and effective_group not in groups:
                effective_group = "__contract_scope_mismatch__"
    # Target-module planning records are keyed by group only.  They cannot be
    # safely joined into a selected collection/group response until their own
    # immutable source collection is recorded.
    target_module_contract = (
        None
        if effective_collection is not None and effective_group is not None
        else _active_target_module_contract()
    )
    scoped_cte, scope_params = _fips_scope_cte(effective_collection, effective_group, product_scope_id)
    scope_where, inventory_params = _scope_sql(effective_collection, effective_group)
    inventory_product_ctes = _product_scope_ctes(product_scope_id)
    inventory_source_files = (
        inventory_product_ctes.source_files if inventory_product_ctes else "source_file"
    )
    inventory_prefix = f"WITH {inventory_product_ctes.sql}" if inventory_product_ctes else ""
    service_group_inventory = _fetch_all(
        f"""
        {inventory_prefix}
        SELECT sc.slug AS source_collection, sg.slug AS service_group,
               sg.display_name AS service_group_name,
               count(DISTINCT sf.id) AS source_files,
               count(*) FILTER (
                   WHERE sf.parse_status IN ('empty', 'invalid', 'unsupported', 'error')
               ) AS ingest_issues
        FROM service_group sg
        JOIN source_collection sc ON sc.id = sg.source_collection_id
        LEFT JOIN {inventory_source_files} sf ON sf.service_group_id = sg.id
            AND sf.is_present
        {scope_where}
        GROUP BY sc.id, sg.id
        ORDER BY sc.slug, sg.slug
        """,
        (*(inventory_product_ctes.params if inventory_product_ctes else ()), *inventory_params),
    )
    documents = _fetch_all(
        scoped_cte
        + """
        SELECT d.id AS document_id, d.sha256 AS document_sha256,
               d.document_kind, d.format_name, d.spec_version,
               coalesce(
                   jsonb_agg(
                       DISTINCT jsonb_build_object(
                           'source_collection', ssf.collection_slug,
                           'service_group', ssf.group_slug,
                           'service_group_name', ssf.group_name,
                           'source_path', ssf.source_path,
                           'source_sha256', ssf.content_sha256
                       )
                   ) FILTER (WHERE ssf.id IS NOT NULL),
                   '[]'::jsonb
               ) AS scopes,
               coalesce(
                   jsonb_agg(
                       DISTINCT jsonb_build_object(
                           'artifact_id', a.id,
                           'canonical_key', a.canonical_key,
                           'artifact_type', a.artifact_type,
                           'name', a.name,
                           'version', a.version,
                           'digest', a.digest,
                           'purl', a.purl,
                           'role', da.role
                       )
                   ) FILTER (WHERE a.id IS NOT NULL),
                   '[]'::jsonb
               ) AS artifacts
        FROM scoped_documents sd
        JOIN document d ON d.id = sd.document_id
        JOIN scoped_source_files ssf ON ssf.document_id = d.id
        LEFT JOIN document_artifact da ON da.document_id = d.id
        LEFT JOIN artifact a ON a.id = da.artifact_id
        GROUP BY d.id
        ORDER BY d.id
        """,
        scope_params,
    )
    observations = _fetch_all(
        scoped_cte
        + """
        SELECT dp.document_id, NULL::bigint AS occurrence_id,
               'document_property'::text AS evidence_kind,
               dp.id AS evidence_id, dp.property_name, dp.property_value,
               NULL::text AS component_identity, NULL::text AS component_name,
               NULL::text AS component_version, d.sha256 AS evidence_sha256,
               d.generated_at_text AS observed_at, NULL::jsonb AS details
        FROM document_property dp
        JOIN scoped_documents sd ON sd.document_id = dp.document_id
        JOIN document d ON d.id = dp.document_id
        WHERE lower(dp.property_name) LIKE '%%fips%%'
           OR lower(dp.property_name) LIKE '%%cmvp%%'
           OR lower(dp.property_name) = 'fedramp:nist-certification'
           OR lower(coalesce(dp.property_value, '')) LIKE '%%fips 140-%%'

        UNION ALL

        SELECT dc.document_id, dc.id AS occurrence_id,
               'component_property'::text AS evidence_kind,
               cp.id AS evidence_id, cp.property_name, cp.property_value,
               coalesce(
                   c.canonical_purl,
                   c.cpe,
                   concat_ws(':', c.component_type, c.namespace, c.name, c.version)
               ) AS component_identity,
               c.name AS component_name, c.version AS component_version,
               d.sha256 AS evidence_sha256, d.generated_at_text AS observed_at,
               jsonb_build_object('bom_ref', dc.source_bom_ref) AS details
        FROM component_property cp
        JOIN document_component dc ON dc.id = cp.occurrence_id
        JOIN component c ON c.id = dc.component_id
        JOIN document d ON d.id = dc.document_id
        JOIN scoped_documents sd ON sd.document_id = dc.document_id
        LEFT JOIN occurrence_relevance relevance ON relevance.occurrence_id = dc.id
        WHERE NOT (
                  coalesce(relevance.explicitly_false, false)
                  AND NOT coalesce(relevance.explicitly_true, false)
              )
          AND lower(cp.property_name) <> 'fedramp:fips:crypto-relevant'
          AND (
               lower(cp.property_name) LIKE '%%fips%%'
               OR lower(cp.property_name) LIKE '%%cmvp%%'
               OR lower(cp.property_name) = 'fedramp:nist-certification'
               OR lower(coalesce(cp.property_value, '')) LIKE '%%fips 140-%%'
          )

        UNION ALL

        SELECT er.document_id, NULL::bigint AS occurrence_id,
               'fips_tool_result'::text AS evidence_kind,
               er.id AS evidence_id,
               'fips_tool:overall_openssl_fips'::text AS property_name,
               er.data #>> '{overall_openssl_fips}' AS property_value,
               NULL::text AS component_identity,
               er.data #>> '{crypto_library,library}' AS component_name,
               er.data #>> '{crypto_library,version}' AS component_version,
               er.payload_sha256 AS evidence_sha256,
               er.observed_at_text AS observed_at,
               jsonb_build_object(
                   'crypto_library', er.data #>> '{crypto_library,library}',
                   'crypto_library_details', er.data #>> '{crypto_library,details}',
                   'crypto_version', er.data #>> '{crypto_library,version}',
                   'fips_module_version', er.data #>> '{crypto_library,fips_module_version}',
                   'fips_enabled', er.data #> '{crypto_library,fips_enabled}',
                   'kernel_fips', er.data #> '{kernel_fips}',
                   'web_servers', er.data #> '{web_servers}'
               ) AS details
        FROM external_record er
        JOIN scoped_documents sd ON sd.document_id = er.document_id
        WHERE er.record_type = 'fips_tool_result'

        ORDER BY document_id, evidence_kind, evidence_id
        """,
        scope_params,
    )
    assessment = build_assessment(
        documents,
        observations,
        scope={
            "source_collection": effective_collection,
            "service_group": effective_group,
        },
        service_group_inventory=service_group_inventory,
        contract=effective_contract,
    )
    if assessment.get("assessment_contract", {}).get("complete"):
        assessment["poam_items"] = enrich_poam_items(
            assessment["poam_items"], target_module_contract,
            preserve_accountable_owner=True,
        )
        assessment["poam_workstreams"] = build_poam_workstreams(assessment["poam_items"])
        assessment["portfolio_poam_items"] = build_portfolio_poam_items(
            assessment["poam_items"], target_module_contract
        )
        assessment.setdefault("summary", {})["proposed_remediation_workstreams"] = len(
            assessment["poam_workstreams"]
        )
        assessment["summary"]["portfolio_poam_candidates"] = len(
            assessment["portfolio_poam_items"]
        )
    # The static tracker wave mapping is group-slug-only.  It has no collection
    # provenance, so it cannot be projected into an assigned pair response.
    if effective_collection is not None and effective_group is not None:
        assessment["portfolio_delivery_waves"] = []
        assessment.setdefault("limitations", []).append(
            "Portfolio delivery waves are unavailable for this assigned scope because the active planning mapping has no source-collection provenance."
        )
    else:
        assessment["portfolio_delivery_waves"] = portfolio_delivery_waves(
            [
                str(row.get("service") or "").rsplit("/", 1)[-1]
                for row in assessment.get("service_groups", [])
                if row.get("service")
            ],
            target_module_contract,
        )
    return assessment


@app.get("/", include_in_schema=False)
def application_root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.get("/healthz", tags=["operations"])
@app.get("/api/v1/health", tags=["operations"])
def health() -> dict[str, Any]:
    row = _fetch_one(
        "SELECT current_database() AS database, now() AS checked_at, %s AS version",
        (__version__,),
    )
    return {"status": "ok", **(row or {})}


def _request_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


def _admin_principal(request: Request, scope: str | None = None) -> Principal:
    principal = _request_principal(request)
    return _require_admin(principal, scope)


def _require_admin(principal: Principal, scope: str | None = None) -> Principal:
    try:
        if principal.kind == "token":
            if scope is None:
                raise AccessDenied("API credentials require an explicit administrative scope", 403)
            require_scope(principal, scope)
            return principal
        require_admin(principal)
    except AccessDenied as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    return principal


def _actor_columns(principal: Principal) -> tuple[int | None, str | None]:
    if principal.kind == "token" and principal.credential_id:
        return None, principal.credential_id
    if principal.user_id is not None:
        return principal.user_id, None
    raise HTTPException(status_code=403, detail="A provisioned administrator identity is required")


def _audit_event(
    database,  # type: ignore[no-untyped-def]
    request: Request,
    principal: Principal,
    *,
    action: str,
    resource_type: str,
    resource_key: str,
    before_state: Any = None,
    after_state: Any = None,
    outcome: str = "success",
) -> None:
    if outcome not in {"success", "denied", "failed"}:
        raise ValueError("Unsupported audit outcome")
    user_id, credential_id = _actor_columns(principal)
    database.execute(
        """
        INSERT INTO app_auth.audit_event
            (request_id, actor_user_id, actor_credential_id, action,
             resource_type, resource_key, before_state, after_state, outcome)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            request.state.request_id,
            user_id,
            credential_id,
            action,
            resource_type,
            resource_key,
            Jsonb(jsonable_encoder(before_state)) if before_state is not None else None,
            Jsonb(jsonable_encoder(after_state)) if after_state is not None else None,
            outcome,
        ),
    )


def _service_catalog_enabled() -> bool:
    """Keep managed catalog writes off until migration 022 is deployed."""
    return _env_bool("CBOM_SERVICE_CATALOG_ENABLED")


def _require_service_catalog() -> None:
    if not _service_catalog_enabled():
        raise HTTPException(status_code=403, detail="Managed Service Catalog is not enabled")


def _catalog_change_from_model(model: BaseModel) -> dict[str, Any]:
    payload = model.model_dump(
        mode="json", exclude_unset=True,
        exclude={"source_collection", "service_group", "expected_revision", "reason", "rationale"},
    )
    try:
        return normalized_change(payload)
    except ServiceCatalogError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _resolve_catalog_profiles(database: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve optional owner/lead profile emails without browser-supplied IDs."""
    for profile_field, column in (("owner_profile_email", "owner_user_id"), ("lead_profile_email", "lead_user_id")):
        email = payload.pop(profile_field, None) if profile_field in payload else ...
        if email is ...:
            continue
        if email is None:
            payload[column] = None
            continue
        profile = database.execute(
            """SELECT id FROM app_auth.app_user WHERE lower(email) = %s AND status = 'active'""", (email,)
        ).fetchone()
        if profile is None:
            raise HTTPException(status_code=422, detail=f"{profile_field} is not an active application user")
        payload[column] = int(profile["id"])
    return payload


def _catalog_group(database: Any, source_collection: str, service_group: str) -> dict[str, Any]:
    row = database.execute(
        """SELECT sg.id AS catalog_service_group_id, %s AS service_group,
                  coalesce(sg.display_name, entry.display_name, %s) AS display_name,
                  sc.id AS source_collection_id, sc.slug AS source_collection
           FROM source_collection sc
           LEFT JOIN service_group sg ON sg.source_collection_id=sc.id AND sg.slug=%s
           LEFT JOIN app_auth.service_catalog_entry entry
             ON entry.source_collection_id=sc.id AND entry.service_group=%s
           WHERE sc.slug = %s AND (sg.id IS NOT NULL OR entry.id IS NOT NULL)""",
        (service_group, service_group, service_group, service_group, source_collection),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Service group not found")
    return dict(row)


def _catalog_collection(database: Any, source_collection: str) -> dict[str, Any]:
    row = database.execute(
        "SELECT id AS source_collection_id, slug AS source_collection FROM source_collection WHERE slug=%s",
        (source_collection,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Source collection not found")
    return dict(row)


def _catalog_entry_payload(payload: dict[str, Any]) -> tuple[list[str], list[Any]]:
    """Build a bounded SQL SET clause from the explicit managed field allowlist."""
    allowed = {
        "display_name", "owner", "owner_user_id", "lead", "lead_user_id", "il2_status", "il2_target_date",
        "il5_status", "il5_target_date", "service_impact_risk", "comments", "attributes",
    }
    keys = [key for key in payload if key in allowed]
    return keys, [Jsonb(payload[key]) if key == "attributes" else payload[key] for key in keys]


def _catalog_overridden_fields(payload: dict[str, Any]) -> list[str]:
    """Return physical managed fields explicitly supplied by an approved change."""
    keys, _ = _catalog_entry_payload(payload)
    return keys


def _catalog_base_metadata(
    source_collection: str, service_group: str, *, profiles: dict[str, dict[str, Any]],
    impacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Read the existing user-authored planning imports without changing them."""
    # Team Tracker/target-module planning is reviewed for SSE CBOMs.  It is
    # keyed by service slug inside that source and must never cross into a
    # different collection that happens to use the same slug.  Service-impact
    # imports carry their own collection key and remain safe to resolve below.
    tracker_collection = str(TRACKER_SOURCE["source_collection"])
    profile = profiles.get(service_group, {}) if source_collection == tracker_collection else {}
    impact = impacts.get(f"{source_collection}/{service_group}", {})
    owners = list(profile.get("owners") or [])
    leads = list(profile.get("leads") or [])
    il2 = _planning_summary(profile, "il2")
    il5 = _planning_summary(profile, "il5")
    return {
        "display_name": None,
        "owner": owners[0] if owners else None,
        "lead": leads[0] if leads else None,
        "lead_profile": None,
        "il2": {"status": il2.get("state") or "not_supplied", "date": il2.get("farthest_date")},
        "il5": {"status": il5.get("state") or "not_supplied", "date": il5.get("farthest_date")},
        "service_impact_risk": impact.get("risk_category"),
        "comments": impact.get("comments"),
        "attributes": {},
        "provenance": "imported_planning",
    }


def _catalog_rows(request: Request, source_collection: str | None = None) -> list[dict[str, Any]]:
    _require_service_catalog()
    principal = _request_principal(request)
    assigned = getattr(request.state, "assigned_scope", {})
    rows = _fetch_all(
        """SELECT sc.slug AS source_collection, sg.slug AS service_group,
                  sg.display_name AS catalog_display_name, entry.revision, entry.display_name,
                  entry.owner, entry.lead, entry.il2_status, entry.il2_target_date,
                  entry.il5_status, entry.il5_target_date, entry.service_impact_risk,
                  entry.comments, entry.attributes, entry.overridden_fields, entry.updated_at,
                  owner_user.id AS owner_user_id, owner_user.email AS owner_user_email,
                  owner_user.display_name AS owner_user_display_name,
                  EXISTS (SELECT 1 FROM source_file sf WHERE sf.service_group_id=sg.id AND sf.is_present) AS has_evidence,
                  lead_user.id AS lead_user_id, lead_user.email AS lead_user_email,
                  lead_user.display_name AS lead_user_display_name
           FROM service_group sg
           JOIN source_collection sc ON sc.id = sg.source_collection_id
           -- A control-plane row can predate source evidence.  Its durable
           -- identity is the collection/slug pair, while catalog_service_group_id
           -- is only a convenient link populated on a later catalog update.
           -- Join on that immutable pair so the managed overlay follows the
           -- group when evidence is ingested.
           LEFT JOIN app_auth.service_catalog_entry entry
             ON entry.source_collection_id = sc.id AND entry.service_group = sg.slug
           LEFT JOIN app_auth.app_user owner_user ON owner_user.id = entry.owner_user_id
           LEFT JOIN app_auth.app_user lead_user ON lead_user.id = entry.lead_user_id
           WHERE (%s::text IS NULL OR sc.slug = %s)
           UNION ALL
           SELECT sc.slug AS source_collection, entry.service_group,
                  entry.service_group AS catalog_display_name, entry.revision, entry.display_name,
                  entry.owner, entry.lead, entry.il2_status, entry.il2_target_date,
                  entry.il5_status, entry.il5_target_date, entry.service_impact_risk,
                  entry.comments, entry.attributes, entry.overridden_fields, entry.updated_at,
                  owner_user.id AS owner_user_id, owner_user.email AS owner_user_email,
                  owner_user.display_name AS owner_user_display_name,
                  false AS has_evidence,
                  lead_user.id AS lead_user_id, lead_user.email AS lead_user_email,
                  lead_user.display_name AS lead_user_display_name
           FROM app_auth.service_catalog_entry entry
           JOIN source_collection sc ON sc.id = entry.source_collection_id
           LEFT JOIN app_auth.app_user owner_user ON owner_user.id = entry.owner_user_id
           LEFT JOIN app_auth.app_user lead_user ON lead_user.id = entry.lead_user_id
           -- Only show a standalone managed row while the source catalog has
           -- no matching immutable group identity.  Once evidence arrives the
           -- first branch owns presentation of the same entry.
           WHERE NOT EXISTS (
                     SELECT 1 FROM service_group source_group
                     WHERE source_group.source_collection_id = entry.source_collection_id
                       AND source_group.slug = entry.service_group
                 )
             AND (%s::text IS NULL OR sc.slug = %s)
           ORDER BY source_collection, catalog_display_name""",
        (source_collection, source_collection, source_collection, source_collection),
    )
    grants = [grant for grant in assigned.get("grants", []) if isinstance(grant, dict)]
    allowed_pairs = {(str(grant.get("source_collection")), str(grant.get("service_group"))) for grant in grants}
    is_admin = principal.is_admin and assigned.get("mode") == "portfolio"
    # Exact grants are filtered before response construction.  This allows a
    # scoped Lead or Engineer to review the operational metadata for the
    # collection/group they own, while `_catalog_base_metadata` separately
    # prevents the tracker fallback from crossing collections.
    profiles = {
        str(row.get("service_group")): row
        for row in team_milestones(_active_target_module_contract()).get("groups", [])
    }
    impacts = _active_service_impact_map()
    visible = rows if is_admin else [
        row for row in rows if (str(row["source_collection"]), str(row["service_group"])) in allowed_pairs
    ]
    pending_by_pair: dict[tuple[str, str], int] = {}
    if principal.kind == "human" and principal.user_id is not None and not is_admin:
        pending_rows = _fetch_all(
            """SELECT sc.slug AS source_collection, proposal.service_group, count(*) AS proposal_count
               FROM app_auth.service_catalog_proposal proposal
               JOIN source_collection sc ON sc.id=proposal.source_collection_id
               LEFT JOIN app_auth.service_catalog_proposal_decision decision ON decision.proposal_id=proposal.id
               WHERE proposal.submitted_by_user_id=%s AND decision.proposal_id IS NULL
               GROUP BY sc.slug, proposal.service_group""", (principal.user_id,),
        )
        pending_by_pair = {
            (str(row["source_collection"]), str(row["service_group"])): int(row["proposal_count"])
            for row in pending_rows
        }
    result: list[dict[str, Any]] = []
    for row in visible:
        source = str(row["source_collection"])
        group = str(row["service_group"])
        base = _catalog_base_metadata(source, group, profiles=profiles, impacts=impacts)
        entry_exists = row.get("revision") is not None
        overrides = set(row.get("overridden_fields") or ()) if entry_exists else set()

        def managed_value(field: str, fallback: Any) -> Any:
            """Use imports only until an approved managed field is explicitly set.

            An overridden field may intentionally contain NULL.  This keeps a
            clear distinct from an untouched imported value without mutating
            the Team Tracker or service-impact source records.
            """
            return row.get(field) if field in overrides else fallback

        owner_profile = (
            {"user_id": row["owner_user_id"], "email": row["owner_user_email"], "display_name": row.get("owner_user_display_name")}
            if row.get("owner_user_id") is not None else None
        )
        lead_profile = (
            {"user_id": row["lead_user_id"], "email": row["lead_user_email"], "display_name": row.get("lead_user_display_name")}
            if row.get("lead_user_id") is not None else None
        )
        item = {
            "service_key": f"{source}/{group}", "source_collection": source,
            "service_group": group,
            "display_name": managed_value("display_name", row["catalog_display_name"]),
            "owner": managed_value("owner", base["owner"]),
            "owner_profile": owner_profile,
            "lead": managed_value("lead", base["lead"]),
            "lead_profile": lead_profile,
            "il2": {
                "status": managed_value("il2_status", base["il2"]["status"]),
                "date": managed_value("il2_target_date", base["il2"]["date"]),
            },
            "il5": {
                "status": managed_value("il5_status", base["il5"]["status"]),
                "date": managed_value("il5_target_date", base["il5"]["date"]),
            },
            "service_impact_risk": managed_value("service_impact_risk", base["service_impact_risk"]),
            "comments": managed_value("comments", base["comments"]),
            "attributes": managed_value("attributes", base["attributes"]),
            "revision": int(row.get("revision") or 0),
            "approval_status": "approved" if entry_exists else "imported",
            "pending_proposals": pending_by_pair.get((source, group), 0),
            "updated_at": row.get("updated_at"),
            "provenance": "managed_catalog" if entry_exists else base["provenance"],
            "can_edit": is_admin or any(
                grant.get("access") == "lead" and grant.get("source_collection") == source and grant.get("service_group") == group
                for grant in grants
            ),
            "can_approve": is_admin,
            "has_evidence": bool(row.get("has_evidence")),
        }
        result.append(item)
    return result


@app.get("/api/v1/service-catalog", tags=["Service Catalog"])
def service_catalog(request: Request, source_collection: str | None = None) -> dict[str, Any]:
    """Role-scoped managed catalog view with imported values as its initial state."""
    rows = _catalog_rows(request, source_collection)
    return {"items": rows, "total": len(rows)}


@app.post("/api/v1/service-catalog/proposals", tags=["Service Catalog"], status_code=201)
def create_service_catalog_proposal(body: ServiceCatalogProposalCreate, request: Request) -> dict[str, Any]:
    """A lead can propose a metadata change for one exact granted service group."""
    _require_service_catalog()
    principal = _request_principal(request)
    if principal.kind != "human" or principal.user_id is None:
        raise HTTPException(status_code=403, detail="A signed-in service lead is required")
    source_collection, service_group = body.source_collection.strip(), body.service_group.strip()
    assigned = getattr(request.state, "assigned_scope", {})
    matching_grants = [grant for grant in assigned.get("grants", []) if isinstance(grant, dict)
                       and grant.get("access") == "lead" and grant.get("source_collection") == source_collection
                       and grant.get("service_group") == service_group]
    if not matching_grants:
        raise HTTPException(status_code=403, detail="A lead grant for the exact service group is required")
    change = _catalog_change_from_model(body)
    if any(key in change for key in {"il2_status", "il2_target_date"}) and not any(
        grant.get("product_scope_id") == "secure-access-government" for grant in matching_grants
    ):
        raise HTTPException(status_code=403, detail="An IL2 plan requires the exact Government product lead grant")
    if any(key in change for key in {"il5_status", "il5_target_date"}) and not any(
        grant.get("product_scope_id") == "secure-access-defense" for grant in matching_grants
    ):
        raise HTTPException(status_code=403, detail="An IL5 plan requires the exact Defense product lead grant")
    proposal_id = str(uuid.uuid4())
    with api_connection() as database:
        group = _catalog_group(database, source_collection, service_group)
        current = database.execute(
            """SELECT revision FROM app_auth.service_catalog_entry
               WHERE source_collection_id=%s AND service_group=%s""",
            (group["source_collection_id"], service_group),
        ).fetchone()
        revision = int(current["revision"]) if current else 0
        if revision != body.expected_revision:
            raise HTTPException(status_code=409, detail="Service Catalog entry changed; refresh before proposing an edit")
        change = _resolve_catalog_profiles(database, change)
        row = database.execute(
            """INSERT INTO app_auth.service_catalog_proposal
               (id,source_collection_id,service_group,proposed_payload,rationale,base_revision,submitted_by_user_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               RETURNING id,base_revision,submitted_at""",
            (proposal_id, group["source_collection_id"], service_group, Jsonb(change), body.rationale.strip(), revision, principal.user_id),
        ).fetchone()
        _audit_event(database, request, principal, action="service_catalog.proposal.submit",
                     resource_type="service_catalog", resource_key=f"{source_collection}/{service_group}",
                     before_state={"revision": revision}, after_state={"proposal_id": proposal_id, "payload": change})
        database.commit()
    return {**dict(row or {}), "source_collection": source_collection, "service_group": service_group, "status": "pending"}


def _upsert_catalog_entry(
    database: Any, *, collection: dict[str, Any], service_group: str,
    catalog_service_group_id: int | None, change: dict[str, Any], expected_revision: int,
    actor_user_id: int, operation: str, reason: str,
) -> dict[str, Any]:
    """Write one current authoritative revision after an optimistic-lock check."""
    current = database.execute(
        """SELECT id,revision FROM app_auth.service_catalog_entry
           WHERE source_collection_id=%s AND service_group=%s FOR UPDATE""",
        (collection["source_collection_id"], service_group),
    ).fetchone()
    current_revision = int(current["revision"]) if current else 0
    if current_revision != expected_revision:
        raise HTTPException(status_code=409, detail="Service Catalog entry changed; refresh before saving")
    keys, values = _catalog_entry_payload(change)
    overridden_fields = _catalog_overridden_fields(change)
    if current is None:
        columns = ["source_collection_id", "service_group", "catalog_service_group_id", *keys, "overridden_fields", "updated_by_user_id"]
        params = [collection["source_collection_id"], service_group, catalog_service_group_id, *values, overridden_fields, actor_user_id]
        placeholders = ", ".join(["%s"] * len(columns))
        row = database.execute(
            f"""INSERT INTO app_auth.service_catalog_entry ({', '.join(columns)})
                VALUES ({placeholders})
                RETURNING id,revision,updated_at""", tuple(params),
        ).fetchone()
    else:
        assignments = [f"{key}=%s" for key in keys]
        params = [*values]
        if catalog_service_group_id is not None:
            assignments.append("catalog_service_group_id=coalesce(catalog_service_group_id, %s)")
            params.append(catalog_service_group_id)
        # Keep earlier decisions intact and add only fields this revision
        # explicitly touched.  This lets a NULL represent an approved clear.
        assignments.append("overridden_fields=(SELECT ARRAY(SELECT DISTINCT field FROM unnest(overridden_fields || %s::text[]) AS field ORDER BY field))")
        params.append(overridden_fields)
        assignments.extend(["revision=revision+1", "updated_by_user_id=%s", "updated_at=now()"])
        params.extend([actor_user_id, current["id"]])
        row = database.execute(
            f"""UPDATE app_auth.service_catalog_entry SET {', '.join(assignments)}
                WHERE id=%s RETURNING id,revision,updated_at""", tuple(params),
        ).fetchone()
    result = dict(row or {})
    snapshot = database.execute(
        """SELECT revision,display_name,owner,owner_user_id,lead,lead_user_id,il2_status,il2_target_date,
                  il5_status,il5_target_date,service_impact_risk,comments,attributes,overridden_fields,updated_at
           FROM app_auth.service_catalog_entry WHERE id=%s""", (result["id"],)
    ).fetchone()
    database.execute(
        """INSERT INTO app_auth.service_catalog_entry_revision
           (service_catalog_entry_id,revision,operation,reason,payload,actor_user_id)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (result["id"], result["revision"], operation, reason, Jsonb(dict(snapshot or {})), actor_user_id),
    )
    return result


def _catalog_admin_human(request: Request) -> Principal:
    principal = _admin_principal(request, "annotations:write")
    if principal.kind == "local" and not _production_mode():
        return principal
    if principal.kind != "human" or principal.user_id is None:
        raise HTTPException(status_code=403, detail="A signed-in administrator is required for Service Catalog changes")
    return principal


def _catalog_actor_for(database: Any, principal: Principal) -> Principal:
    """Give localhost's one-click admin a clearly-labelled local audit actor."""
    if principal.kind != "local":
        return principal
    if _production_mode():
        raise HTTPException(status_code=403, detail="Local Service Catalog access is unavailable in cloud deployments")
    row = database.execute(
        """INSERT INTO app_auth.app_user
               (oidc_issuer,oidc_subject,email,display_name,role,status,last_login_at)
           VALUES ('local-development','service-catalog-admin',
                   'local-service-catalog-admin@localhost.invalid','Local Service Catalog Admin','admin','active',now())
           ON CONFLICT ((lower(email))) DO UPDATE
           SET display_name=EXCLUDED.display_name, role='admin', status='active', updated_at=now()
           RETURNING id,email,display_name"""
    ).fetchone()
    return replace(principal, user_id=int(row["id"]), email=str(row["email"]), display_name=row.get("display_name"))


@app.post("/api/v1/admin/service-catalog", tags=["Service Catalog"], status_code=201)
def create_service_catalog_entry(body: ServiceCatalogCreate, request: Request) -> dict[str, Any]:
    """Create a control-plane-only service group; it has no fabricated evidence."""
    _require_service_catalog()
    principal = _catalog_admin_human(request)
    source_collection, service_group = body.source_collection.strip(), body.service_group.strip()
    if not SERVICE_GROUP_SLUG.fullmatch(service_group):
        raise HTTPException(status_code=422, detail="service_group must be a lowercase URL-safe slug")
    change = _catalog_change_from_model(body)
    if not change.get("display_name"):
        raise HTTPException(status_code=422, detail="display_name is required for a new service group")
    with api_connection() as database:
        principal = _catalog_actor_for(database, principal)
        collection = _catalog_collection(database, source_collection)
        if database.execute(
            "SELECT 1 FROM app_auth.service_catalog_entry WHERE source_collection_id=%s AND service_group=%s",
            (collection["source_collection_id"], service_group),
        ).fetchone() is not None or database.execute(
            "SELECT 1 FROM service_group WHERE source_collection_id=%s AND slug=%s",
            (collection["source_collection_id"], service_group),
        ).fetchone() is not None:
            raise HTTPException(status_code=409, detail="Service group already exists")
        change = _resolve_catalog_profiles(database, change)
        row = _upsert_catalog_entry(
            database, collection=collection, service_group=service_group, catalog_service_group_id=None,
            change=change, expected_revision=0, actor_user_id=principal.user_id,
            operation="create", reason=body.reason.strip(),
        )
        _audit_event(database, request, principal, action="service_catalog.create",
                     resource_type="service_catalog", resource_key=f"{source_collection}/{service_group}",
                     after_state={"revision": row.get("revision"), "payload": change, "reason": body.reason.strip(), "control_plane_only": True})
        database.commit()
    return {"source_collection": source_collection, "service_group": service_group, **row, "approval_status": "approved", "has_evidence": False}


@app.put("/api/v1/admin/service-catalog/{source_collection}/{service_group}", tags=["Service Catalog"])
def update_service_catalog_entry(
    source_collection: str, service_group: str, body: ServiceCatalogUpdate, request: Request,
) -> dict[str, Any]:
    """An administrator directly records an authoritative metadata revision."""
    _require_service_catalog()
    principal = _catalog_admin_human(request)
    if not SERVICE_GROUP_SLUG.fullmatch(service_group):
        raise HTTPException(status_code=422, detail="service_group must be a lowercase URL-safe slug")
    change = _catalog_change_from_model(body)
    with api_connection() as database:
        principal = _catalog_actor_for(database, principal)
        collection = _catalog_collection(database, source_collection)
        existing = database.execute(
            "SELECT id FROM service_group WHERE source_collection_id=%s AND slug=%s",
            (collection["source_collection_id"], service_group),
        ).fetchone()
        managed = database.execute(
            "SELECT 1 FROM app_auth.service_catalog_entry WHERE source_collection_id=%s AND service_group=%s",
            (collection["source_collection_id"], service_group),
        ).fetchone()
        if existing is None and managed is None:
            raise HTTPException(status_code=404, detail="Service group not found")
        change = _resolve_catalog_profiles(database, change)
        row = _upsert_catalog_entry(
            database, collection=collection, service_group=service_group,
            catalog_service_group_id=int(existing["id"]) if existing else None,
            change=change, expected_revision=body.expected_revision, actor_user_id=principal.user_id,
            operation="admin_update", reason=body.reason.strip(),
        )
        _audit_event(database, request, principal, action="service_catalog.update",
                     resource_type="service_catalog", resource_key=f"{source_collection}/{service_group}",
                     before_state={"expected_revision": body.expected_revision},
                     after_state={"revision": row.get("revision"), "payload": change, "reason": body.reason.strip()})
        database.commit()
    return {"source_collection": source_collection, "service_group": service_group, **row, "approval_status": "approved"}


@app.get("/api/v1/admin/service-catalog/proposals", tags=["Service Catalog"])
def service_catalog_proposals(request: Request, limit: int = Query(200, ge=1, le=500)) -> dict[str, Any]:
    _require_service_catalog()
    _catalog_admin_human(request)
    rows = _fetch_all(
        """SELECT proposal.id, sc.slug AS source_collection, proposal.service_group,
                  proposal.proposed_payload, proposal.rationale, proposal.base_revision, proposal.submitted_at,
                  submitter.email AS submitted_by_email, decision.decision, decision.decision_reason,
                  decision.decided_at, decider.email AS decided_by_email,
                  coalesce(decision.decision, 'pending') AS status
           FROM app_auth.service_catalog_proposal proposal
           JOIN source_collection sc ON sc.id=proposal.source_collection_id
           JOIN app_auth.app_user submitter ON submitter.id=proposal.submitted_by_user_id
           LEFT JOIN app_auth.service_catalog_proposal_decision decision ON decision.proposal_id=proposal.id
           LEFT JOIN app_auth.app_user decider ON decider.id=decision.decided_by_user_id
           ORDER BY proposal.submitted_at DESC LIMIT %s""", (limit,),
    )
    return {"items": rows, "total": len(rows)}


@app.post("/api/v1/admin/service-catalog/proposals/{proposal_id}/decision", tags=["Service Catalog"])
def decide_service_catalog_proposal(
    proposal_id: str, body: ServiceCatalogProposalDecision, request: Request,
) -> dict[str, Any]:
    """A different administrator approves a lead proposal into the managed record."""
    _require_service_catalog()
    principal = _catalog_admin_human(request)
    with api_connection() as database:
        principal = _catalog_actor_for(database, principal)
        proposal = database.execute(
            """SELECT proposal.id,proposal.source_collection_id,proposal.service_group,proposal.proposed_payload,
                      proposal.base_revision,proposal.submitted_by_user_id,sc.slug AS source_collection,
                      sg.id AS catalog_service_group_id
               FROM app_auth.service_catalog_proposal proposal
               JOIN source_collection sc ON sc.id=proposal.source_collection_id
               LEFT JOIN service_group sg ON sg.source_collection_id=proposal.source_collection_id AND sg.slug=proposal.service_group
               WHERE proposal.id=%s""", (proposal_id,),
        ).fetchone()
        if proposal is None:
            raise HTTPException(status_code=404, detail="Service Catalog proposal not found")
        if int(proposal["submitted_by_user_id"]) == principal.user_id:
            _audit_event(database, request, principal, action="service_catalog.proposal.decision_denied",
                         resource_type="service_catalog", resource_key=f"{proposal['source_collection']}/{proposal['service_group']}",
                         after_state={"reason": "submitter_cannot_approve"}, outcome="denied")
            database.commit()
            raise HTTPException(status_code=403, detail="A different administrator must decide this proposal")
        already = database.execute(
            "SELECT 1 FROM app_auth.service_catalog_proposal_decision WHERE proposal_id=%s", (proposal_id,)
        ).fetchone()
        if already is not None:
            raise HTTPException(status_code=409, detail="Service Catalog proposal already has a decision")
        current = database.execute(
            "SELECT revision FROM app_auth.service_catalog_entry WHERE source_collection_id=%s AND service_group=%s FOR UPDATE",
            (proposal["source_collection_id"], proposal["service_group"]),
        ).fetchone()
        revision = int(current["revision"]) if current else 0
        if body.decision == "approved" and revision != int(proposal["base_revision"]):
            raise HTTPException(status_code=409, detail="Service Catalog proposal is stale; the entry changed after submission")
        decision = database.execute(
            """INSERT INTO app_auth.service_catalog_proposal_decision
               (proposal_id,decision,decision_reason,decided_by_user_id)
               VALUES (%s,%s,%s,%s) RETURNING decision,decision_reason,decided_at""",
            (proposal_id, body.decision, body.decision_reason.strip(), principal.user_id),
        ).fetchone()
        applied = None
        if body.decision == "approved":
            collection = {"source_collection_id": proposal["source_collection_id"], "source_collection": proposal["source_collection"]}
            applied = _upsert_catalog_entry(
                database, collection=collection, service_group=str(proposal["service_group"]),
                catalog_service_group_id=int(proposal["catalog_service_group_id"]) if proposal.get("catalog_service_group_id") else None,
                change=dict(proposal["proposed_payload"]), expected_revision=revision, actor_user_id=principal.user_id,
                operation="proposal_approved", reason=body.decision_reason.strip(),
            )
        _audit_event(database, request, principal, action=f"service_catalog.proposal.{body.decision}",
                     resource_type="service_catalog", resource_key=f"{proposal['source_collection']}/{proposal['service_group']}",
                     before_state={"proposal_id": proposal_id, "base_revision": proposal["base_revision"]},
                     after_state={"decision": body.decision, "applied_revision": applied.get("revision") if applied else None, "reason": body.decision_reason.strip()})
        database.commit()
    return {"proposal_id": proposal_id, **dict(decision or {}), "applied": applied}


@app.get("/api/v1/auth/me", tags=["access control"])
def current_user(request: Request) -> dict[str, Any]:
    principal = _request_principal(request)
    assigned = getattr(request.state, "assigned_scope", None)
    access = assigned if isinstance(assigned, dict) else {}
    grants = access.get("grants", [])
    if access.get("mode") == "portfolio" and access.get("role") == "admin":
        # Portfolio administrators need a selectable UI scope.  This is an
        # inventory read only; it does not turn every catalog pair into an
        # OIDC grant or modify the access policy presented above.
        service_groups = [
            f"{row['source_collection']}/{row['service_group']}"
            for row in _fetch_all(
                """
                SELECT sc.slug AS source_collection, sg.slug AS service_group
                FROM source_collection sc
                JOIN service_group sg ON sg.source_collection_id = sc.id
                ORDER BY sc.slug, sg.slug
                """
            )
        ]
    else:
        service_groups = [
            f"{row['source_collection']}/{row['service_group']}" for row in grants
        ]
    return {
        "kind": principal.kind,
        "email": principal.email,
        "display_name": principal.display_name,
        "role": principal.role,
        "status": "active",
        "scopes": sorted(principal.scopes),
        "can_edit": principal.role == "admin",
        "capabilities": {
            "roster_revoke_restore": bool(
                _access_roster_enabled()
                and principal.kind == "human"
                and access.get("mode") == "portfolio"
                and access.get("role") == "admin"
            ),
            "operational_evidence_notes": bool(
                _operational_evidence_notes_enabled()
                and principal.kind == "human"
                and (
                    access.get("role") == "admin"
                    or any(grant.get("access") == "lead" for grant in access.get("grants", []))
                )
            ),
            "review_proposals": _review_proposals_enabled_for_access(principal, access),
        },
        "access": {
            "policy_version": access.get("policy_version", "unconfigured"),
            "group_fingerprint": access.get("fingerprint"),
            "effective_role": access.get("role", "viewer"),
            "summary_access": bool(access.get("summary_access")),
            "matched_groups": access.get("matched_groups", []),
            "grants": grants,
            "available_modes": access.get("available_modes", []),
            "default_mode": access.get("default_mode"),
            # Null means the person has several verified choices and has not
            # yet selected one. It is intentionally not an authorization
            # decision; middleware requires a choice before data routes.
            "active_mode": access.get("active_mode"),
            "revoked": False,
        },
        "assigned_scope": {
            "mode": assigned.get("mode") if isinstance(assigned, dict) else "unconfigured",
            "service_groups": service_groups,
            "product_scopes": sorted({row["product_scope_id"] for row in grants}),
            "boundary_names": sorted({row["boundary_name"] for row in grants}),
            # Pair-only catalog handlers remain disabled for assigned product
            # scopes until every detail/export query has the exact current-SHA
            # attribution predicate.  The console must use this capability to
            # render the attribution-pending state instead of fetching detail.
            "product_scoped_detail_evidence": _PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED,
            "union_service_register": bool(
                access.get("mode") == "assigned" and grants
            ),
            # The shell may render the verified grant placeholders while
            # scoped catalog detail remains default-deny. This capability is
            # intentionally absent until a product mode is selected.
            "assigned_workspace_placeholders": bool(
                access.get("mode") == "assigned"
                and access.get("active_mode") in {"product_lead", "product_engineer"}
                and grants
            ),
            "enforcement": "active" if isinstance(assigned, dict) else "denied",
        },
    }


@app.get("/api/v1/admin/users", tags=["access control"])
def admin_users(request: Request) -> dict[str, Any]:
    _admin_principal(request, "users:admin")
    rows = _fetch_all(
        """
        WITH latest_snapshot AS (
            SELECT DISTINCT ON (app_user_id)
                   app_user_id, effective_role, exact_grants, policy_version,
                   policy_fingerprint, verified_at
            FROM app_auth.access_roster_snapshot
            ORDER BY app_user_id, verified_at DESC, id DESC
        ), latest_action AS (
            SELECT DISTINCT ON (target_user_id) target_user_id, action, reason,
                   occurred_at, actor_user_id
            FROM app_auth.user_access_action
            ORDER BY target_user_id, occurred_at DESC, id DESC
        )
        SELECT app_user.id, app_user.email, app_user.display_name, app_user.role, app_user.status,
               app_user.oidc_subject IS NOT NULL AS identity_bound,
               app_user.created_at, app_user.updated_at, app_user.last_login_at,
               snapshot.effective_role, snapshot.exact_grants AS grants, snapshot.policy_version,
               snapshot.policy_fingerprint, snapshot.verified_at AS last_verified_at,
               coalesce(action.action, 'restore') AS access_state,
               action.reason AS access_reason, action.occurred_at AS access_changed_at,
               CASE WHEN action.action = 'revoke' THEN action.occurred_at END AS revoked_at,
               CASE WHEN action.action = 'revoke' THEN action.reason END AS revoked_reason,
               actor.email AS access_changed_by_email
        FROM app_auth.app_user app_user
        LEFT JOIN latest_snapshot snapshot ON snapshot.app_user_id = app_user.id
        LEFT JOIN latest_action action ON action.target_user_id = app_user.id
        LEFT JOIN app_auth.app_user actor ON actor.id = action.actor_user_id
        ORDER BY lower(app_user.email)
        """
    )
    return {"items": rows, "total": len(rows)}


def _mapping_admin(request: Request, *, write: bool = False) -> Principal:
    principal = _admin_principal(request, "users:admin")
    if principal.kind not in {"human", "local"}:
        raise HTTPException(status_code=403, detail="Group mappings require an interactive administrator")
    if write and (principal.kind != "human" or principal.user_id is None):
        raise HTTPException(status_code=403, detail="A provisioned signed-in administrator must publish group mappings")
    return principal


def _group_mapping_service_options() -> list[dict[str, Any]]:
    rows = _fetch_all("""
        SELECT sc.slug AS source_collection, sg.slug AS service_group,
               sg.display_name,
               count(sf.id) FILTER (WHERE sf.is_present) AS current_source_files,
               count(sf.id) FILTER (
                   WHERE sf.is_present AND sf.content_sha256 IS NOT NULL
               ) AS fingerprinted_source_files
        FROM service_group sg
        JOIN source_collection sc ON sc.id = sg.source_collection_id
        LEFT JOIN source_file sf ON sf.service_group_id = sg.id
                                AND sf.source_collection_id = sc.id
        GROUP BY sc.slug, sg.slug, sg.display_name
        ORDER BY lower(sc.slug), lower(sg.display_name), lower(sg.slug)
    """)
    # Migration 022 is deliberately enabled only after its schema is present.
    # Keep the established group-mapping editor available in the image-first
    # stage where the feature flag is false and the new relation is absent.
    if not _service_catalog_enabled():
        return rows
    managed = _fetch_all("""
        SELECT sc.slug AS source_collection, entry.service_group,
               coalesce(entry.display_name, entry.service_group) AS display_name,
               0 AS current_source_files, 0 AS fingerprinted_source_files
        FROM app_auth.service_catalog_entry entry
        JOIN source_collection sc ON sc.id = entry.source_collection_id
        WHERE NOT EXISTS (
            SELECT 1 FROM service_group source_group
            WHERE source_group.source_collection_id = entry.source_collection_id
              AND source_group.slug = entry.service_group
        )
        ORDER BY lower(sc.slug), lower(entry.display_name), lower(entry.service_group)
    """)
    return sorted(rows + managed, key=lambda row: (
        str(row["source_collection"]).casefold(), str(row["display_name"]).casefold(), str(row["service_group"]).casefold(),
    ))


@app.get("/api/v1/admin/service-group-mappings", tags=["access control"])
def admin_service_group_mappings(request: Request) -> dict[str, Any]:
    principal = _mapping_admin(request)
    policy, source, revision = _oidc_policy_document()
    _normalize_oidc_policy(policy)
    try:
        rows = service_rows(policy["groups"])
    except GroupMappingError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    options = _group_mapping_service_options()
    services = {(row["source_collection"], row["service_group"]): row for row in options}
    return {
        "revision": revision, "policy_version": policy["version"], "source": source,
        "can_manage": bool(_admin_group_mapping_enabled() and principal.kind == "human" and principal.user_id is not None),
        "products": [
            {"product_scope_id": scope_id, "boundary_name": boundary,
             "product_name": "Secure Access for Government" if scope_id == "secure-access-government" else "Secure Access for Defense"}
            for scope_id, boundary in PRODUCT_SCOPES.items()
        ],
        "service_options": options,
        "rows": [
            {
                **row,
                "display_name": services.get((row["source_collection"], row["service_group"]), {}).get(
                    "display_name", row["service_group"]
                ),
                "current_source_files": services.get((row["source_collection"], row["service_group"]), {}).get(
                    "current_source_files", 0
                ),
                "fingerprinted_source_files": services.get((row["source_collection"], row["service_group"]), {}).get(
                    "fingerprinted_source_files", 0
                ),
            }
            for row in rows
        ],
    }


def _publish_service_group_mapping(
    request: Request, principal: Principal, *, action: str, service_key: str,
    reason: str, expected_revision: str,
    source_collection: str | None = None, service_group: str | None = None,
    product_scope_ids: list[str] | None = None,
) -> dict[str, Any]:
    if not _admin_group_mapping_enabled():
        raise HTTPException(status_code=403, detail="Administrator group mapping registry is not enabled")
    if reason != reason.strip():
        raise HTTPException(status_code=422, detail="A trimmed change reason is required")
    with api_connection() as database:
        database.execute("SELECT pg_advisory_xact_lock(hashtext('cbom-oidc-group-policy'))")
        policy, _, current_revision = _oidc_policy_document(database)
        _normalize_oidc_policy(policy)
        if expected_revision != current_revision:
            raise HTTPException(status_code=409, detail="Group mapping revision changed; refresh before publishing")
        before_rows = {row["service_key"]: row for row in service_rows(policy["groups"])}
        if action != "retire":
            registered = database.execute("""
                SELECT 1 FROM source_collection sc
                JOIN service_group sg ON sg.source_collection_id = sc.id
                WHERE sc.slug = %s AND sg.slug = %s
            """, (source_collection, service_group)).fetchone()
            if not registered and _service_catalog_enabled():
                registered = database.execute("""
                SELECT 1 FROM source_collection sc
                JOIN app_auth.service_catalog_entry entry ON entry.source_collection_id=sc.id
                WHERE sc.slug = %s AND entry.service_group=%s
                """, (source_collection, service_group)).fetchone()
            if not registered:
                raise HTTPException(status_code=422, detail="Choose a registered catalog collection and service group")
        try:
            changed = changed_service_groups(
                policy["groups"], action=action, service_key=service_key,
                source_collection=source_collection, service_group=service_group,
                product_scope_ids=product_scope_ids,
            )
            after_rows = {row["service_key"]: row for row in service_rows(changed)}
            if not after_rows:
                raise GroupMappingError("At least one service mapping must remain active")
            _normalize_oidc_policy({**policy, "groups": changed})
        except (GroupMappingError, AssignedScopeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        content_sha256 = policy_sha256(changed)
        if content_sha256 == policy_sha256(policy["groups"]):
            raise HTTPException(status_code=409, detail="Mapping is unchanged")
        row = database.execute("""
            INSERT INTO app_auth.oidc_group_policy_revision
                (policy_sha256, previous_sha256, groups, reason, actor_user_id, request_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
        """, (content_sha256, policy_sha256(policy["groups"]), Jsonb(changed), reason, principal.user_id,
              request.state.request_id)).fetchone()
        next_revision = hashlib.sha256(f"{row['id']}:{content_sha256}".encode()).hexdigest()
        database.execute("""
            INSERT INTO app_auth.oidc_group_policy_active (singleton, revision_id)
            VALUES (1, %s)
            ON CONFLICT (singleton) DO UPDATE
            SET revision_id = EXCLUDED.revision_id, activated_at = now()
        """, (row["id"],))
        _audit_event(
            database, request, principal, action=f"oidc_group_mapping.{action}",
            resource_type="oidc_group_policy", resource_key=service_key,
            before_state={"revision": current_revision, "mapping": before_rows.get(service_key), "reason": reason},
            after_state={"revision": next_revision, "mapping": after_rows.get(service_key), "reason": reason},
        )
        database.commit()
    return {"revision": next_revision, "policy_version": f"admin:{row['id']}:{next_revision[:12]}",
            "service_key": service_key, "action": action, "effective": True}


@app.post("/api/v1/admin/service-group-mappings", tags=["access control"], status_code=201)
def add_admin_service_group_mapping(body: GroupMappingSave, request: Request) -> dict[str, Any]:
    principal = _mapping_admin(request, write=True)
    return _publish_service_group_mapping(
        request, principal, action="add", service_key=body.service_key,
        reason=body.reason, expected_revision=body.expected_revision,
        source_collection=body.source_collection, service_group=body.service_group,
        product_scope_ids=body.product_scope_ids,
    )


@app.put("/api/v1/admin/service-group-mappings/{service_key}", tags=["access control"])
def update_admin_service_group_mapping(service_key: str, body: GroupMappingSave, request: Request) -> dict[str, Any]:
    principal = _mapping_admin(request, write=True)
    if service_key != body.service_key:
        raise HTTPException(status_code=422, detail="Path and body service keys must match")
    return _publish_service_group_mapping(
        request, principal, action="replace", service_key=service_key,
        reason=body.reason, expected_revision=body.expected_revision,
        source_collection=body.source_collection, service_group=body.service_group,
        product_scope_ids=body.product_scope_ids,
    )


@app.delete("/api/v1/admin/service-group-mappings/{service_key}", tags=["access control"])
def retire_admin_service_group_mapping(service_key: str, body: GroupMappingRetire, request: Request) -> dict[str, Any]:
    principal = _mapping_admin(request, write=True)
    return _publish_service_group_mapping(
        request, principal, action="retire", service_key=service_key,
        reason=body.reason, expected_revision=body.expected_revision,
    )


@app.patch("/api/v1/admin/users/{user_id}", tags=["access control"])
def update_admin_user(user_id: int, body: UserAccessUpdate, request: Request) -> dict[str, Any]:
    """Retired: cloud access is derived from OIDC groups, never this row."""
    raise HTTPException(
        status_code=410,
        detail="Manual user-role changes are retired; access is derived from verified OIDC groups",
    )


@app.post("/api/v1/admin/users/{user_id}/access", tags=["access control"])
def change_admin_user_access(
    user_id: int, body: UserAccessActionCreate, request: Request,
) -> dict[str, Any]:
    """Append an operational revoke/restore without changing OIDC policy."""
    principal = _admin_principal(request, "users:admin")
    if not _access_roster_enabled():
        raise HTTPException(status_code=403, detail="Operational access roster is not enabled")
    if principal.kind != "human" or principal.user_id is None:
        raise HTTPException(status_code=403, detail="A signed-in administrator must change user access")
    with api_connection() as database:
        try:
            change_access(
                database, actor_user_id=principal.user_id, target_user_id=user_id,
                action=body.action, reason=body.reason,
                request_id=request.state.request_id,
            )
        except AccessRosterError as error:
            database.rollback()
            message = str(error)
            status = 404 if message == "Access target does not exist" else 409
            raise HTTPException(status_code=status, detail=message) from error
        database.commit()
    return {
        "user_id": user_id, "access_state": body.action,
        "operational_effect": (
            "Access action recorded; cloud authorization continues to require verified OIDC group policy."
        ),
    }

@app.get("/api/v1/admin/tokens", tags=["access control"])
def admin_tokens(request: Request) -> dict[str, Any]:
    principal = _admin_principal(request, "tokens:admin")
    clauses = "" if principal.kind == "human" else "WHERE credential.owner_user_id = %s"
    params: tuple[Any, ...] = () if principal.kind == "human" else (principal.user_id,)
    rows = _fetch_all(
        f"""
        SELECT credential.id, credential.name, credential.token_prefix, credential.scopes,
               credential.created_at, credential.expires_at, credential.last_used_at,
               credential.revoked_at, app_user.email AS owner_email
        FROM app_auth.api_credential credential
        JOIN app_auth.app_user ON app_user.id = credential.owner_user_id
        {clauses}
        ORDER BY credential.created_at DESC
        """,
        params,
    )
    return {"items": rows, "total": len(rows)}


@app.post("/api/v1/admin/tokens", tags=["access control"], status_code=201)
def create_admin_token(body: ApiCredentialCreate, request: Request) -> dict[str, Any]:
    principal = _admin_principal(request, "tokens:admin")
    if principal.user_id is None:
        raise HTTPException(status_code=403, detail="A provisioned administrator is required")
    scopes = sorted(set(body.scopes))
    unsupported = sorted(set(scopes) - ALLOWED_TOKEN_SCOPES)
    if unsupported:
        raise HTTPException(status_code=422, detail=f"Unsupported scopes: {', '.join(unsupported)}")
    credential_id, token, digest = generate_api_token()
    expires_at = token_expiration(body.expires_in_days)
    prefix = f"cbw_{credential_id[:8]}"
    with api_connection() as database:
        row = database.execute(
            """
            INSERT INTO app_auth.api_credential
                (id, owner_user_id, name, token_prefix, token_digest, scopes, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, name, token_prefix, scopes, created_at, expires_at
            """,
            (credential_id, principal.user_id, body.name.strip(), prefix, digest, scopes, expires_at),
        ).fetchone()
        _audit_event(
            database, request, principal, action="api_credential.create",
            resource_type="api_credential", resource_key=credential_id,
            after_state={"name": body.name.strip(), "prefix": prefix, "scopes": scopes, "expires_at": expires_at},
        )
        database.commit()
    return {**dict(row or {}), "token": token, "shown_once": True}


@app.delete("/api/v1/admin/tokens/{credential_id}", tags=["access control"])
def revoke_admin_token(credential_id: str, request: Request) -> dict[str, Any]:
    principal = _admin_principal(request, "tokens:admin")
    with api_connection() as database:
        before = database.execute(
            "SELECT id, name, token_prefix, scopes, revoked_at, owner_user_id FROM app_auth.api_credential WHERE id = %s FOR UPDATE",
            (credential_id,),
        ).fetchone()
        if before is None:
            raise HTTPException(status_code=404, detail="API credential not found")
        if principal.kind == "token" and int(before["owner_user_id"]) != principal.user_id:
            raise HTTPException(status_code=403, detail="Credential ownership mismatch")
        after = database.execute(
            "UPDATE app_auth.api_credential SET revoked_at = coalesce(revoked_at, now()) WHERE id = %s RETURNING id, name, token_prefix, scopes, revoked_at",
            (credential_id,),
        ).fetchone()
        _audit_event(
            database, request, principal, action="api_credential.revoke",
            resource_type="api_credential", resource_key=credential_id,
            before_state=dict(before), after_state=dict(after or {}),
        )
        database.commit()
    return dict(after or {})


_OVERLAY_FIELDS = {
    "service_group": {"effective_owners", "leads", "il2_date", "il5_date", "admin_notes"},
    "poam_candidate": {"responsible_owner", "scheduled_completion_date", "review_status", "admin_notes"},
    "target_module": {"review_status", "admin_notes", "evidence_url"},
    "finding": {"review_status", "admin_notes", "disposition"},
}

_LEAD_REVIEW_FIELDS = {
    # These are operational annotations only.  They are intentionally kept
    # outside admin_overlay, so neither a lead request nor an approval changes
    # planning inputs, immutable evidence, or a candidate assessment result.
    "poam_candidate",
    "finding",
}


def _lead_scope_grant(
    request: Request,
    source_collection: str,
    service_group: str,
    product_scope_id: str,
) -> tuple[Principal, dict[str, Any], dict[str, Any]]:
    """Require a human lead's exact collection/service-group grant."""
    principal = _request_principal(request)
    if principal.kind != "human":
        raise HTTPException(status_code=403, detail="Service-lead review proposals require a signed-in human")
    assigned = getattr(request.state, "assigned_scope", None)
    if not isinstance(assigned, dict):
        raise HTTPException(status_code=403, detail="Access mode is not resolved")
    try:
        grant = matching_product_grant(
            assigned.get("grants", []), source_collection=source_collection,
            service_group=service_group, product_scope_id=product_scope_id,
        )
    except LeadReviewProductScopeError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    return principal, grant, assigned


def _lead_review_resource_snapshot(
    source_collection: str,
    service_group: str,
    resource_type: str,
    resource_key: str,
    product_scope_id: str,
) -> tuple[int, str] | None:
    """Return a stable fingerprint for an item from one scoped assessment."""
    assessment, revision, _ = _cached_fips_assessment(
        source_collection, service_group, product_scope_id=product_scope_id
    )
    item: dict[str, Any] | None = None
    if resource_type == "poam_candidate":
        item = next(
            (
                candidate for candidate in assessment.get("poam_items", [])
                if str(candidate.get("poam_candidate_id") or "") == resource_key
            ),
            None,
        )
    elif resource_type == "finding":
        item = next(
            (
                finding for finding in assessment.get("findings", [])
                if str(finding.get("finding_id") or "") == resource_key
            ),
            None,
        )
    if item is None:
        return None
    fingerprint = hashlib.sha256(
        json.dumps(jsonable_encoder(item), sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return revision, fingerprint


def _evidence_note_scope_grant(
    request: Request, source_collection: str, service_group: str, product_scope_id: str,
) -> tuple[Principal, dict[str, Any], dict[str, Any]]:
    """Exact human lead triple for a non-authoritative finding observation."""
    principal = _request_principal(request)
    if principal.kind != "human":
        raise HTTPException(status_code=403, detail="Evidence observations require a signed-in human lead")
    if principal.user_id is None:
        raise HTTPException(status_code=403, detail="A provisioned lead identity is required")
    assigned = getattr(request.state, "assigned_scope", None)
    if not isinstance(assigned, dict):
        raise HTTPException(status_code=403, detail="Access mode is not resolved")
    grant = next((row for row in assigned.get("grants", []) if
                  row.get("source_collection") == source_collection
                  and row.get("service_group") == service_group
                  and row.get("product_scope_id") == product_scope_id
                  and row.get("access") == "lead"), None)
    if grant is None:
        raise HTTPException(status_code=403, detail="A lead grant for the exact product scope is required")
    return principal, grant, assigned


def _evidence_note_snapshot(
    source_collection: str, service_group: str, product_scope_id: str, finding_id: str,
) -> dict[str, Any] | None:
    assessment, revision, _ = _cached_fips_assessment(
        source_collection, service_group, product_scope_id=product_scope_id
    )
    finding = next((item for item in assessment.get("findings", [])
                    if str(item.get("finding_id") or "") == finding_id), None)
    if not isinstance(finding, dict):
        return None
    sources = [{
        "source_collection": source_collection, "service_group": service_group,
        "product_scope_id": product_scope_id,
        "source_path": scope.get("source_path"), "source_sha256": scope.get("source_sha256"),
    } for scope in finding.get("scopes", []) if isinstance(scope, dict)]
    try:
        source_tuple_digest = canonical_source_tuple_digest(sources)
    except OperationalEvidenceNoteError:
        return None
    finding_digest = hashlib.sha256(json.dumps(
        jsonable_encoder(finding), sort_keys=True, separators=(",", ":"), default=str
    ).encode()).hexdigest()
    policy_fingerprint = hashlib.sha256(json.dumps(
        assessment.get("policy") or {}, sort_keys=True, separators=(",", ":"), default=str
    ).encode()).hexdigest()
    return {
        "source_tuple_digest": source_tuple_digest,
        "finding_observation_digest": finding_digest,
        "policy_fingerprint": policy_fingerprint,
        "assessment_revision": str(revision),
    }


def _lead_review_rows(
    *,
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
    proposal_id: str | None = None,
    include_actor_email: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if source_collection is not None:
        clauses.append("proposal.source_collection = %s")
        params.append(source_collection)
    if service_group is not None:
        clauses.append("proposal.service_group = %s")
        params.append(service_group)
    if product_scope_id is not None:
        clauses.append("proposal.product_scope_id = %s")
        params.append(product_scope_id)
    if proposal_id is not None:
        clauses.append("proposal.id = %s")
        params.append(proposal_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    actor_fields = (
        ", submitter.email AS submitted_by_email, approver.email AS decided_by_email"
        if include_actor_email else ""
    )
    join_actors = (
        " LEFT JOIN app_auth.app_user submitter ON submitter.id = proposal.submitted_by_user_id"
        " LEFT JOIN app_auth.app_user approver ON approver.id = decision.decided_by_user_id"
        if include_actor_email else ""
    )
    return _fetch_all(
        f"""
        SELECT proposal.id, proposal.source_collection, proposal.service_group,
               proposal.product_scope_id, proposal.assessment_authorization_reference,
               proposal.resource_type, proposal.resource_key, proposal.proposed_note,
               proposal.rationale, proposal.policy_version, proposal.scope_fingerprint,
               proposal.ato_boundary, proposal.assessment_revision,
               proposal.assessment_fingerprint, proposal.submitted_at,
               decision.decision, decision.decision_reason, decision.decided_at,
               coalesce(decision.decision, 'pending') AS status
               {actor_fields}
        FROM app_auth.lead_review_proposal proposal
        LEFT JOIN app_auth.lead_review_decision decision ON decision.proposal_id = proposal.id
        {join_actors}
        {where}
        ORDER BY proposal.submitted_at DESC
        LIMIT %s
        """,
        (*params, limit),
    )


def _overlay_scope(resource_type: str) -> str:
    if resource_type == "service_group":
        return "milestones:write"
    if resource_type == "poam_candidate":
        return "poam:write"
    return "annotations:write"


@app.get("/api/v1/admin/overlays", tags=["access control"])
def admin_overlays(
    request: Request,
    resource_type: str | None = None,
    resource_key: str | None = None,
    include_history: bool = False,
) -> dict[str, Any]:
    _admin_principal(request, "annotations:write")
    clauses: list[str] = [] if include_history else ["overlay.is_active"]
    params: list[Any] = []
    if resource_type:
        clauses.append("overlay.resource_type = %s")
        params.append(resource_type)
    if resource_key:
        clauses.append("overlay.resource_key = %s")
        params.append(resource_key)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = _fetch_all(
        f"""
        SELECT overlay.id, overlay.resource_type, overlay.resource_key, overlay.version,
               overlay.payload, overlay.rationale, overlay.is_active, overlay.created_at,
               app_user.email AS created_by_email,
               overlay.created_by_credential_id AS created_by_credential
        FROM app_auth.admin_overlay overlay
        LEFT JOIN app_auth.app_user ON app_user.id = overlay.created_by_user_id
        {where}
        ORDER BY overlay.created_at DESC
        LIMIT 500
        """,
        tuple(params),
    )
    return {"items": rows, "total": len(rows)}


@app.post("/api/v1/admin/overlays", tags=["access control"], status_code=201)
def create_admin_overlay(body: OverlayCreate, request: Request) -> dict[str, Any]:
    principal = _admin_principal(request, _overlay_scope(body.resource_type))
    allowed = _OVERLAY_FIELDS.get(body.resource_type)
    if allowed is None:
        raise HTTPException(status_code=422, detail="Unsupported overlay resource type")
    unsupported = sorted(set(body.payload) - allowed)
    if unsupported:
        raise HTTPException(status_code=422, detail=f"Unsupported overlay fields: {', '.join(unsupported)}")
    if not body.payload:
        raise HTTPException(status_code=422, detail="Overlay payload cannot be empty")
    user_id, credential_id = _actor_columns(principal)
    with api_connection() as database:
        previous = database.execute(
            """
            SELECT id, version, payload, rationale, created_at
            FROM app_auth.admin_overlay
            WHERE resource_type = %s AND resource_key = %s AND is_active
            FOR UPDATE
            """,
            (body.resource_type, body.resource_key),
        ).fetchone()
        version = int(previous["version"]) + 1 if previous else 1
        if previous:
            database.execute(
                "UPDATE app_auth.admin_overlay SET is_active = false WHERE id = %s",
                (previous["id"],),
            )
        row = database.execute(
            """
            INSERT INTO app_auth.admin_overlay
                (resource_type, resource_key, version, payload, rationale,
                 created_by_user_id, created_by_credential_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, resource_type, resource_key, version, payload,
                      rationale, is_active, created_at
            """,
            (
                body.resource_type, body.resource_key, version, Jsonb(body.payload),
                body.rationale.strip(), user_id, credential_id,
            ),
        ).fetchone()
        _audit_event(
            database, request, principal, action="overlay.create",
            resource_type=body.resource_type, resource_key=body.resource_key,
            before_state=dict(previous) if previous else None,
            after_state=dict(row or {}),
        )
        database.commit()
    global _cache_revision
    with _cache_lock:
        _data_cache.clear()
        _cache_revision = None
    return dict(row or {})


@app.delete("/api/v1/admin/overlays/{overlay_id}", tags=["access control"])
def deactivate_admin_overlay(overlay_id: int, request: Request) -> dict[str, Any]:
    principal = _request_principal(request)
    with api_connection() as database:
        before = database.execute(
            """
            SELECT id, resource_type, resource_key, version, payload, rationale, is_active
            FROM app_auth.admin_overlay
            WHERE id = %s
            FOR UPDATE
            """,
            (overlay_id,),
        ).fetchone()
        if before is None:
            raise HTTPException(status_code=404, detail="Overlay not found")
        _require_admin(principal, _overlay_scope(str(before["resource_type"])))
        after = database.execute(
            """
            UPDATE app_auth.admin_overlay
            SET is_active = false
            WHERE id = %s
            RETURNING id, resource_type, resource_key, version, payload,
                      rationale, is_active, created_at
            """,
            (overlay_id,),
        ).fetchone()
        _audit_event(
            database, request, principal, action="overlay.deactivate",
            resource_type=str(before["resource_type"]), resource_key=str(before["resource_key"]),
            before_state=dict(before), after_state=dict(after or {}),
        )
        database.commit()
    global _cache_revision
    with _cache_lock:
        _data_cache.clear()
        _cache_revision = None
    return dict(after or {})


@app.get("/api/v1/admin/audit", tags=["access control"])
def admin_audit(request: Request, limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    _admin_principal(request)
    rows = _fetch_all(
        """
        SELECT audit.id, audit.request_id, audit.action, audit.resource_type,
               audit.resource_key, audit.before_state, audit.after_state,
               audit.outcome, audit.occurred_at, app_user.email AS actor_email,
               audit.actor_credential_id
        FROM app_auth.audit_event audit
        LEFT JOIN app_auth.app_user ON app_user.id = audit.actor_user_id
        ORDER BY audit.occurred_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    return {"items": rows, "total": len(rows)}


@app.get("/api/v1/review-proposals", tags=["operational review"])
def lead_review_proposals(
    request: Request,
    source_collection: str,
    service_group: str,
    product_scope_id: str,
    limit: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    """Show operational review proposals for one service lead's exact scope."""
    if not _lead_review_proposals_enabled():
        raise HTTPException(status_code=403, detail="Operational review proposals are not enabled")
    _lead_scope_grant(request, source_collection, service_group, product_scope_id)
    rows = _lead_review_rows(
        source_collection=source_collection,
        service_group=service_group,
        product_scope_id=product_scope_id,
        limit=limit,
    )
    return {"items": rows, "total": len(rows)}


@app.post("/api/v1/review-proposals", tags=["operational review"], status_code=201)
def create_lead_review_proposal(
    body: LeadReviewProposalCreate,
    request: Request,
) -> dict[str, Any]:
    """Submit an additive, non-authoritative service-lead review proposal."""
    if not _lead_review_proposals_enabled():
        raise HTTPException(status_code=403, detail="Operational review proposals are not enabled")
    source_collection = body.source_collection.strip()
    service_group = body.service_group.strip()
    resource_type = body.resource_type.strip()
    resource_key = body.resource_key.strip()
    product_scope_id = body.product_scope_id.strip()
    proposed_note = body.proposed_note.strip()
    rationale = body.rationale.strip()
    if not source_collection or not service_group or not resource_key:
        raise HTTPException(status_code=422, detail="Review proposal scope and resource key are required")
    if len(proposed_note) < 8 or len(rationale) < 8:
        raise HTTPException(status_code=422, detail="Review proposal note and rationale must contain meaningful text")
    if resource_type not in _LEAD_REVIEW_FIELDS:
        raise HTTPException(status_code=422, detail="Unsupported operational review resource type")
    query_collection = request.query_params.get("source_collection")
    query_group = request.query_params.get("service_group")
    query_product_scope = request.query_params.get("product_scope_id")
    if query_collection != source_collection or query_group != service_group or query_product_scope != product_scope_id:
        raise HTTPException(
            status_code=400,
            detail="Query source_collection, service_group, and product_scope_id must exactly match the proposal body",
        )
    principal, grant, assigned = _lead_scope_grant(request, source_collection, service_group, product_scope_id)
    snapshot = _lead_review_resource_snapshot(
        source_collection, service_group, resource_type, resource_key, product_scope_id
    )
    if snapshot is None:
        # Do not reveal whether an item exists outside the assigned pair.
        raise HTTPException(status_code=404, detail="Scoped review item not found")
    assessment_revision, assessment_fingerprint = snapshot
    proposal_id = str(uuid.uuid4())
    with api_connection() as database:
        row = database.execute(
            """
            INSERT INTO app_auth.lead_review_proposal
                (id, source_collection, service_group, resource_type, resource_key,
                 proposed_note, rationale, policy_version,
                 scope_fingerprint, ato_boundary, assessment_revision,
                 assessment_fingerprint, submitted_by_user_id, product_scope_id,
                 assessment_authorization_reference)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, source_collection, service_group, resource_type, resource_key,
                      proposed_note, rationale, policy_version,
                      scope_fingerprint, ato_boundary, assessment_revision, product_scope_id,
                      assessment_authorization_reference,
                      assessment_fingerprint, submitted_at
            """,
            (
                proposal_id, source_collection, service_group, resource_type, resource_key,
                proposed_note, rationale,
                str(assigned.get("policy_version") or "unconfigured"),
                product_scope_fingerprint(grant),
                str(grant["assessment_authorization_reference"]), str(assessment_revision),
                assessment_fingerprint, principal.user_id, product_scope_id,
                str(grant["assessment_authorization_reference"]),
            ),
        ).fetchone()
        _audit_event(
            database, request, principal,
            action="lead_review_proposal.submit",
            resource_type="lead_review_proposal", resource_key=proposal_id,
            after_state={
                "source_collection": source_collection,
                "service_group": service_group,
                "resource_type": resource_type,
                "resource_key": resource_key,
                "policy_version": assigned.get("policy_version"),
                "scope_fingerprint": product_scope_fingerprint(grant),
                "product_scope_id": product_scope_id,
                "assessment_authorization_reference": grant["assessment_authorization_reference"],
                "assessment_revision": assessment_revision,
                "assessment_fingerprint": assessment_fingerprint,
                "status": "pending",
            },
        )
        database.commit()
    return {**dict(row or {}), "status": "pending"}


@app.get("/api/v1/admin/review-proposals", tags=["operational review"])
def admin_lead_review_proposals(
    request: Request,
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    """Administrator queue for additive service-lead operational reviews."""
    if not _lead_review_proposals_enabled():
        raise HTTPException(status_code=403, detail="Operational review proposals are not enabled")
    _admin_principal(request, "annotations:write")
    rows = _lead_review_rows(include_actor_email=True, limit=limit)
    return {"items": rows, "total": len(rows)}


@app.post("/api/v1/operational-evidence-notes", tags=["operational review"], status_code=201)
def create_operational_evidence_note(body: OperationalEvidenceNoteCreate, request: Request) -> dict[str, Any]:
    """Submit a product-scoped finding observation; it cannot alter assessment output."""
    if not _operational_evidence_notes_enabled():
        raise HTTPException(status_code=403, detail="Operational evidence observations are not enabled")
    payload = body.model_dump()
    try:
        validate_evidence_note_submission(payload)
    except OperationalEvidenceNoteError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    query = request.query_params
    if any(query.get(key) != payload[key] for key in ("source_collection", "service_group", "product_scope_id")):
        raise HTTPException(status_code=400, detail="Query scope must exactly match the evidence observation body")
    principal, _, assigned = _evidence_note_scope_grant(
        request, payload["source_collection"], payload["service_group"], payload["product_scope_id"]
    )
    snapshot = _evidence_note_snapshot(**{key: payload[key] for key in (
        "source_collection", "service_group", "product_scope_id", "finding_id")})
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Scoped finding evidence is unavailable")
    note_id = str(uuid.uuid4())
    with api_connection() as database:
        row = database.execute(
            """INSERT INTO app_auth.operational_evidence_note
               (id,source_collection,service_group,product_scope_id,finding_id,source_tuple_digest,
                finding_observation_digest,policy_fingerprint,assessment_revision,note,lead_rationale,submitted_by_user_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id,source_collection,service_group,product_scope_id,finding_id,note,lead_rationale,submitted_at""",
            (note_id, payload["source_collection"], payload["service_group"], payload["product_scope_id"], payload["finding_id"],
             snapshot["source_tuple_digest"], snapshot["finding_observation_digest"], snapshot["policy_fingerprint"],
             snapshot["assessment_revision"], payload["note"].strip(), payload["lead_rationale"].strip(), principal.user_id),
        ).fetchone()
        _audit_event(database, request, principal, action="operational_evidence_note.submit",
                     resource_type="operational_evidence_note", resource_key=note_id,
                     after_state={**payload, **snapshot, "policy_version": assigned.get("policy_version")})
        database.commit()
    return {**dict(row or {}), "status": "pending", "operational_effect": "Observation only; no candidate, POA&M, or authorization effect."}


@app.get("/api/v1/operational-evidence-notes", tags=["operational review"])
def operational_evidence_notes(
    request: Request, source_collection: str, service_group: str, product_scope_id: str,
    limit: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    if not _operational_evidence_notes_enabled():
        raise HTTPException(status_code=403, detail="Operational evidence observations are not enabled")
    _evidence_note_scope_grant(request, source_collection, service_group, product_scope_id)
    rows = _fetch_all(
        """SELECT note.id,note.source_collection,note.service_group,note.product_scope_id,note.finding_id,
                  note.note,note.lead_rationale,note.submitted_at,submitter.email AS submitted_by_email,
                  decision.decision AS status,decision.reason AS decision_reason,decision.decided_at,decider.email AS decided_by_email
           FROM app_auth.operational_evidence_note note
           JOIN app_auth.app_user submitter ON submitter.id=note.submitted_by_user_id
           LEFT JOIN app_auth.operational_evidence_note_decision decision ON decision.note_id=note.id
           LEFT JOIN app_auth.app_user decider ON decider.id=decision.decided_by_user_id
           WHERE note.source_collection=%s AND note.service_group=%s AND note.product_scope_id=%s
           ORDER BY note.submitted_at DESC LIMIT %s""",
        (source_collection, service_group, product_scope_id, limit),
    )
    return {"items": [{**row, "status": row.get("status") or "pending"} for row in rows], "total": len(rows)}


@app.get("/api/v1/admin/operational-evidence-notes", tags=["operational review"])
def admin_operational_evidence_notes(request: Request, limit: int = Query(200, ge=1, le=500)) -> dict[str, Any]:
    if not _operational_evidence_notes_enabled():
        raise HTTPException(status_code=403, detail="Operational evidence observations are not enabled")
    principal = _admin_principal(request, "annotations:write")
    if principal.kind != "human":
        raise HTTPException(status_code=403, detail="A signed-in administrator must view evidence observations")
    rows = _fetch_all(
        """SELECT note.id,note.source_collection,note.service_group,note.product_scope_id,note.finding_id,
                  note.note,note.lead_rationale,note.submitted_at,submitter.email AS submitted_by_email,
                  decision.decision AS status,decision.reason AS decision_reason,decision.decided_at,decider.email AS decided_by_email
           FROM app_auth.operational_evidence_note note
           JOIN app_auth.app_user submitter ON submitter.id=note.submitted_by_user_id
           LEFT JOIN app_auth.operational_evidence_note_decision decision ON decision.note_id=note.id
           LEFT JOIN app_auth.app_user decider ON decider.id=decision.decided_by_user_id
           ORDER BY note.submitted_at DESC LIMIT %s""", (limit,),
    )
    return {"items": [{**row, "status": row.get("status") or "pending"} for row in rows], "total": len(rows)}


@app.post("/api/v1/admin/operational-evidence-notes/{note_id}/decision", tags=["operational review"])
def decide_operational_evidence_note(
    note_id: str, body: OperationalEvidenceNoteDecisionCreate, request: Request,
) -> dict[str, Any]:
    """Approve or reject a frozen observation after exact evidence revalidation."""
    if not _operational_evidence_notes_enabled():
        raise HTTPException(status_code=403, detail="Operational evidence observations are not enabled")
    principal = _admin_principal(request, "annotations:write")
    if principal.kind != "human" or principal.user_id is None:
        raise HTTPException(status_code=403, detail="A signed-in administrator must decide evidence observations")
    with api_connection() as database:
        note = database.execute(
            """SELECT id,source_collection,service_group,product_scope_id,finding_id,source_tuple_digest,
                      finding_observation_digest,policy_fingerprint,assessment_revision,submitted_by_user_id
               FROM app_auth.operational_evidence_note WHERE id=%s""", (note_id,)
        ).fetchone()
        if note is None:
            raise HTTPException(status_code=404, detail="Evidence observation not found")
        if int(note["submitted_by_user_id"]) == principal.user_id:
            _audit_event(
                database, request, principal,
                action="operational_evidence_note.decision_denied",
                resource_type="operational_evidence_note", resource_key=note_id,
                before_state={"status": "pending", "submitted_by_user_id": note["submitted_by_user_id"]},
                after_state={"reason": "submitter_cannot_decide"}, outcome="denied",
            )
            database.commit()
            raise HTTPException(status_code=403, detail="A different administrator must decide this observation")
        snapshot = _evidence_note_snapshot(
            str(note["source_collection"]), str(note["service_group"]),
            str(note["product_scope_id"]), str(note["finding_id"]),
        )
        try:
            if snapshot is None:
                raise OperationalEvidenceNoteError("Finding evidence is stale or reassigned")
            validate_evidence_note_current(
                current_sources=[{"source_collection": str(note["source_collection"]), "service_group": str(note["service_group"]), "product_scope_id": str(note["product_scope_id"]), "source_path": scope.get("source_path"), "source_sha256": scope.get("source_sha256")} for scope in next((item for item in _cached_fips_assessment(str(note["source_collection"]), str(note["service_group"]), product_scope_id=str(note["product_scope_id"]))[0].get("findings", []) if str(item.get("finding_id") or "") == str(note["finding_id"])), {}).get("scopes", []) if isinstance(scope, dict)],
                stored_digest=str(note["source_tuple_digest"]),
                current_finding_observation_digest=snapshot["finding_observation_digest"], stored_finding_observation_digest=str(note["finding_observation_digest"]),
                current_policy_fingerprint=snapshot["policy_fingerprint"], stored_policy_fingerprint=str(note["policy_fingerprint"]),
                current_assessment_revision=snapshot["assessment_revision"], stored_assessment_revision=str(note["assessment_revision"]),
            )
        except OperationalEvidenceNoteError:
            _audit_event(database, request, principal, action="operational_evidence_note.stale", resource_type="operational_evidence_note", resource_key=note_id, before_state=dict(note), after_state={"reason": "current scoped evidence differs"})
            database.commit()
            raise HTTPException(status_code=409, detail="Evidence observation is stale or reassigned")
        row = database.execute("""INSERT INTO app_auth.operational_evidence_note_decision (note_id,decision,reason,decided_by_user_id)
                                  VALUES (%s,%s,%s,%s) ON CONFLICT (note_id) DO NOTHING
                                  RETURNING note_id,decision,reason,decided_at""", (note_id, body.decision, body.reason.strip(), principal.user_id)).fetchone()
        if row is None:
            _audit_event(database, request, principal, action="operational_evidence_note.conflict", resource_type="operational_evidence_note", resource_key=note_id, before_state={"status":"pending"}, after_state={"reason":"already_decided"})
            database.commit()
            raise HTTPException(status_code=409, detail="Evidence observation already has a decision")
        _audit_event(database, request, principal, action="operational_evidence_note.decision", resource_type="operational_evidence_note", resource_key=note_id, before_state=dict(note), after_state=dict(row))
        database.commit()
    return {**dict(row), "operational_effect": "Recorded observation decision only; assessment and POA&M outputs are unchanged."}


@app.post(
    "/api/v1/admin/review-proposals/{proposal_id}/decision",
    tags=["operational review"],
)
def decide_lead_review_proposal(
    proposal_id: str,
    body: LeadReviewDecisionCreate,
    request: Request,
) -> dict[str, Any]:
    """Append an administrator decision without changing the submitted proposal."""
    if not _lead_review_proposals_enabled():
        raise HTTPException(status_code=403, detail="Operational review proposals are not enabled")
    if body.decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=422, detail="Decision must be approved or rejected")
    decision_reason = body.decision_reason.strip()
    if len(decision_reason) < 8:
        raise HTTPException(status_code=422, detail="Decision reason must contain meaningful text")
    principal = _admin_principal(request, "annotations:write")
    if principal.kind != "human":
        raise HTTPException(
            status_code=403,
            detail="A signed-in fedsse-admins administrator must decide operational review requests",
        )
    if principal.user_id is None:
        raise HTTPException(status_code=403, detail="A provisioned administrator identity is required")
    with api_connection() as database:
        proposal = database.execute(
            """
            SELECT id, source_collection, service_group, resource_type, resource_key,
                   proposed_note, rationale, submitted_at,
                   policy_version, scope_fingerprint, ato_boundary,
                   assessment_revision, assessment_fingerprint, submitted_by_user_id,
                   product_scope_id, assessment_authorization_reference
            FROM app_auth.lead_review_proposal
            WHERE id = %s
            """,
            (proposal_id,),
        ).fetchone()
        if proposal is None:
            raise HTTPException(status_code=404, detail="Review proposal not found")
        # An administrator must be a separate person from the submitting lead.
        # API credentials retain the owning user ID, so they cannot bypass this
        # separation rule by approving through a token they created.
        if principal.user_id is not None and int(proposal["submitted_by_user_id"]) == principal.user_id:
            _audit_event(
                database, request, principal,
                action="lead_review_proposal.decision_denied",
                resource_type="lead_review_proposal", resource_key=proposal_id,
                before_state={"status": "pending", "submitted_by_user_id": proposal["submitted_by_user_id"]},
                after_state={"reason": "submitter_cannot_decide"},
            )
            database.commit()
            raise HTTPException(status_code=403, detail="A different administrator must decide this review proposal")
        current_product_contract = _product_fips_validation(
            str(proposal["source_collection"]),
            str(proposal["service_group"]),
            str(proposal["product_scope_id"]),
        )
        if (
            current_product_contract is None
            or current_product_contract.get("authorization_reference")
            != proposal.get("assessment_authorization_reference")
        ):
            _audit_event(
                database, request, principal,
                action="lead_review_proposal.decision_stale",
                resource_type="lead_review_proposal", resource_key=proposal_id,
                before_state={
                    "status": "pending",
                    "product_scope_id": proposal.get("product_scope_id"),
                    "assessment_authorization_reference": proposal.get("assessment_authorization_reference"),
                },
                after_state={
                    "reason": "assessment_authorization_reference_changed_or_unavailable",
                    "current_assessment_authorization_reference": (
                        current_product_contract.get("authorization_reference")
                        if current_product_contract else None
                    ),
                },
            )
            database.commit()
            raise HTTPException(
                status_code=409,
                detail="Review proposal is stale because its product authorization reference is unavailable or changed",
            )
        current_snapshot = _lead_review_resource_snapshot(
            str(proposal["source_collection"]),
            str(proposal["service_group"]),
            str(proposal["resource_type"]),
            str(proposal["resource_key"]),
            str(proposal["product_scope_id"]),
        )
        if (
            current_snapshot is None
            or str(current_snapshot[0]) != str(proposal["assessment_revision"])
            or current_snapshot[1] != str(proposal["assessment_fingerprint"])
        ):
            _audit_event(
                database, request, principal,
                action="lead_review_proposal.decision_stale",
                resource_type="lead_review_proposal", resource_key=proposal_id,
                before_state={
                    "status": "pending",
                    "assessment_revision": proposal["assessment_revision"],
                    "assessment_fingerprint": proposal["assessment_fingerprint"],
                },
                after_state={
                    "current_assessment_revision": current_snapshot[0] if current_snapshot else None,
                    "current_assessment_fingerprint": current_snapshot[1] if current_snapshot else None,
                },
            )
            database.commit()
            raise HTTPException(
                status_code=409,
                detail="Review proposal is stale because its scoped assessment item changed or is unavailable",
            )
        decision = database.execute(
            """
            INSERT INTO app_auth.lead_review_decision
                (proposal_id, decision, decision_reason, decided_by_user_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (proposal_id) DO NOTHING
            RETURNING proposal_id, decision, decision_reason, decided_at
            """,
            (proposal_id, body.decision, decision_reason, principal.user_id),
        ).fetchone()
        if decision is None:
            _audit_event(
                database, request, principal,
                action="lead_review_proposal.decision_conflict",
                resource_type="lead_review_proposal", resource_key=proposal_id,
                before_state={"status": "pending"},
                after_state={"reason": "administrator_decision_already_exists"},
            )
            database.commit()
            raise HTTPException(status_code=409, detail="Review proposal already has an administrator decision")
        _audit_event(
            database, request, principal,
            action=f"lead_review_proposal.{body.decision}",
            resource_type="lead_review_proposal", resource_key=proposal_id,
            before_state={"status": "pending", **dict(proposal)},
            after_state={"status": body.decision, **dict(decision)},
        )
        database.commit()
    return {
        **dict(proposal), **dict(decision), "status": body.decision,
        "operational_effect": "Recorded review decision only; candidate and POA&M status are unchanged",
    }


@app.get("/api/v1/admin/ingestion/batches", tags=["admin ingestion"])
def admin_ingestion_batches(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    _admin_principal(request, "ingestion:read")
    rows = list_ingestion_batches(limit=limit)
    return {"items": rows, "total": len(rows)}


@app.get("/api/v1/admin/ingestion/batches/{batch_id}", tags=["admin ingestion"])
def admin_ingestion_batch(batch_id: str, request: Request) -> dict[str, Any]:
    _admin_principal(request, "ingestion:read")
    try:
        uuid.UUID(batch_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Invalid ingestion batch ID") from error
    row = get_ingestion_batch(batch_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ingestion batch not found")
    return row


@app.get("/api/v1/admin/ingestion/batches/{batch_id}/logs", tags=["admin ingestion"])
def admin_ingestion_batch_logs(
    batch_id: str,
    request: Request,
    limit: int = Query(200, ge=1, le=1_000),
) -> dict[str, Any]:
    _admin_principal(request, "ingestion:read")
    try:
        uuid.UUID(batch_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Invalid ingestion batch ID") from error
    try:
        result = get_ingestion_batch_logs(batch_id, limit=limit)
    except (BotoCoreError, ClientError) as error:
        LOGGER.exception("Unable to read ingestion task logs")
        raise HTTPException(status_code=503, detail="Ingestion task logs are unavailable") from error
    if result is None:
        raise HTTPException(status_code=404, detail="Ingestion batch not found")
    return result


@app.post("/api/v1/admin/ingestion/batches", tags=["admin ingestion"], status_code=201)
def create_admin_ingestion_batch(
    body: IngestionBatchCreate,
    request: Request,
) -> dict[str, Any]:
    principal = _admin_principal(request, "ingestion:write")
    user_id, credential_id = _actor_columns(principal)
    try:
        manifest = normalize_manifest(
            source_collection=body.source_collection,
            dry_run=body.dry_run,
            authoritative_snapshot=body.authoritative_snapshot,
            files=[item.model_dump() for item in body.files],
        )
        return create_ingestion_batch(
            manifest=manifest,
            supplied_manifest_sha256=body.manifest_sha256,
            request_id=request.state.request_id,
            actor_user_id=user_id,
            actor_credential_id=credential_id,
        )
    except IngestionManifestError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except IngestionConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (BotoCoreError, ClientError) as error:
        LOGGER.exception("Unable to create presigned ingestion uploads")
        raise HTTPException(status_code=503, detail="S3 upload signing is unavailable") from error


@app.post("/api/v1/admin/ingestion/batches/{batch_id}/submit", tags=["admin ingestion"])
def submit_admin_ingestion_batch(
    batch_id: str,
    body: IngestionBatchSubmit,
    request: Request,
) -> dict[str, Any]:
    principal = _admin_principal(request, "ingestion:write")
    try:
        uuid.UUID(batch_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Invalid ingestion batch ID") from error
    user_id, credential_id = _actor_columns(principal)
    try:
        return submit_ingestion_batch(
            batch_id=batch_id,
            supplied_manifest_sha256=body.manifest_sha256,
            request_id=request.state.request_id,
            actor_user_id=user_id,
            actor_credential_id=credential_id,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Ingestion batch not found") from error
    except IngestionManifestError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except IngestionStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except IngestionConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (BotoCoreError, ClientError) as error:
        LOGGER.exception("Unable to start ingestion task")
        raise HTTPException(status_code=503, detail="ECS ingestion launch is unavailable") from error


@app.get("/api/v1/stats", tags=["catalog"])
def catalog_stats() -> dict[str, Any]:
    row = _fetch_one(
        """
        SELECT
            (SELECT count(*) FROM service_group) AS service_groups,
            (SELECT count(DISTINCT slug) FROM service_group) AS distinct_service_group_slugs,
            (SELECT count(*) FROM source_collection) AS source_collections,
            (SELECT count(*) FROM source_file WHERE is_present) AS source_files,
            (SELECT count(*) FROM source_file WHERE is_present AND content_sha256 IS NOT NULL)
                AS fingerprinted_source_files,
            (SELECT count(*) FROM source_file_fingerprint) AS fingerprint_versions,
            (SELECT count(DISTINCT document_id) FROM source_file
                WHERE is_present AND document_id IS NOT NULL) AS unique_documents,
            (SELECT count(DISTINCT da.artifact_id) FROM document_artifact da
                JOIN source_file sf ON sf.document_id = da.document_id WHERE sf.is_present) AS artifacts,
            (SELECT count(DISTINCT dc.component_id) FROM document_component dc
                JOIN source_file sf ON sf.document_id = dc.document_id WHERE sf.is_present) AS unique_components,
            (SELECT count(DISTINCT dc.id) FROM document_component dc
                JOIN source_file sf ON sf.document_id = dc.document_id WHERE sf.is_present) AS component_occurrences,
            (SELECT count(DISTINCT de.id) FROM dependency_edge de
                JOIN source_file sf ON sf.document_id = de.document_id WHERE sf.is_present) AS dependency_edges,
            (SELECT count(DISTINCT dv.vulnerability_id) FROM document_vulnerability dv
                JOIN source_file sf ON sf.document_id = dv.document_id WHERE sf.is_present) AS vulnerabilities,
            (SELECT count(DISTINCT er.id) FROM external_record er
                JOIN source_file sf ON sf.document_id = er.document_id WHERE sf.is_present) AS external_records,
            (SELECT count(DISTINCT ii.id) FROM ingest_issue ii
                LEFT JOIN source_file sf ON sf.id = ii.source_file_id
                LEFT JOIN source_file dsf ON dsf.document_id = ii.document_id AND dsf.is_present
                WHERE ii.severity = 'error' AND (sf.is_present OR dsf.id IS NOT NULL)) AS ingest_errors
        """
    )
    coverage = _fetch_all(
        """
        SELECT document_kind, format_name, spec_version, unique_documents,
               source_files, component_occurrences
        FROM v_format_coverage
        ORDER BY source_files DESC, document_kind, spec_version
        """
    )
    return {"counts": row or {}, "format_coverage": coverage}


def _build_dashboard_overview(
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
) -> dict[str, Any]:
    """Return a provenance-scoped dashboard summary without client-side overfetching."""
    where, scope_params = _scope_sql(source_collection, service_group)
    product_ctes = _product_scope_ctes(product_scope_id)
    product_prefix = f"WITH {product_ctes.sql}, " if product_ctes else "WITH "
    source_files = product_ctes.source_files if product_ctes else "source_file"
    scoped_cte = f"""
        {product_prefix}scoped_service_groups AS (
            SELECT sg.*
            FROM service_group sg
            JOIN source_collection sc ON sc.id = sg.source_collection_id
            {where}
        ),
        scoped_source_files AS (
            SELECT sf.*
            FROM {source_files} sf
            JOIN source_collection sc ON sc.id = sf.source_collection_id
            JOIN scoped_service_groups sg ON sg.id = sf.service_group_id
            WHERE sf.is_present
        ),
        scoped_documents AS (
            SELECT DISTINCT document_id
            FROM scoped_source_files
            WHERE document_id IS NOT NULL
        ),
        scoped_document_groups AS (
            SELECT DISTINCT document_id, service_group_id
            FROM scoped_source_files
            WHERE document_id IS NOT NULL
        ),
        scoped_occurrences AS (
            SELECT dc.*
            FROM document_component dc
            JOIN scoped_documents sd ON sd.document_id = dc.document_id
        ),
        scoped_crypto_occurrences AS (
            SELECT so.*
            FROM scoped_occurrences so
            WHERE (
                so.crypto_properties IS NOT NULL
                AND so.crypto_properties <> '{{}}'::jsonb
            ) OR EXISTS (
                SELECT 1
                FROM component_property cp
                WHERE cp.occurrence_id = so.id
                  AND lower(cp.property_name) = 'fedramp:fips:crypto-relevant'
                  AND lower(trim(coalesce(cp.property_value, ''))) IN
                      ('1', 'true', 'yes', 'on', 'enabled', 'validated')
            )
        )
    """
    counts = _fetch_one(
        scoped_cte
        + """
        SELECT
            (SELECT count(DISTINCT source_collection_id) FROM scoped_source_files)
                AS source_collections,
            (SELECT count(*) FROM scoped_service_groups)
                AS service_groups,
            (SELECT count(*) FROM scoped_service_groups ssg
                WHERE NOT EXISTS (
                    SELECT 1 FROM scoped_source_files ssf
                    WHERE ssf.service_group_id = ssg.id
                )) AS empty_service_groups,
            (SELECT count(*) FROM scoped_source_files) AS source_files,
            (SELECT count(*) FROM scoped_source_files
                WHERE parse_status IN ('empty', 'invalid', 'unsupported', 'error'))
                AS pending_source_files,
            (SELECT count(*) FROM scoped_source_files WHERE content_sha256 IS NOT NULL)
                AS fingerprinted_source_files,
            (SELECT count(*) FROM source_file_fingerprint history
                JOIN scoped_source_files ssf ON ssf.id = history.source_file_id)
                AS fingerprint_versions,
            (SELECT count(*) FROM scoped_documents) AS unique_documents,
            (SELECT count(DISTINCT da.artifact_id) FROM document_artifact da
                JOIN scoped_documents sd ON sd.document_id = da.document_id) AS artifacts,
            (SELECT count(DISTINCT component_id) FROM scoped_occurrences) AS unique_components,
            (SELECT count(*) FROM scoped_occurrences) AS component_occurrences,
            (SELECT count(DISTINCT component_id) FROM scoped_crypto_occurrences)
                AS unique_crypto_components,
            (SELECT count(*) FROM scoped_crypto_occurrences)
                AS crypto_component_occurrences,
            (SELECT count(*) FROM dependency_edge de
                JOIN scoped_documents sd ON sd.document_id = de.document_id) AS dependency_edges,
            (SELECT count(DISTINCT dv.vulnerability_id) FROM document_vulnerability dv
                JOIN scoped_documents sd ON sd.document_id = dv.document_id) AS vulnerabilities,
            (SELECT count(*) FROM external_record er
                JOIN scoped_documents sd ON sd.document_id = er.document_id) AS external_records,
            (SELECT count(DISTINCT ii.id) FROM ingest_issue ii
                LEFT JOIN scoped_source_files ssf ON ssf.id = ii.source_file_id
                LEFT JOIN scoped_documents sd ON sd.document_id = ii.document_id
                WHERE ii.severity = 'error'
                  AND (ssf.id IS NOT NULL OR sd.document_id IS NOT NULL)) AS ingest_errors
        """,
        (*(product_ctes.params if product_ctes else ()), *scope_params),
    )
    format_coverage = _fetch_all(
        scoped_cte
        + """
        SELECT d.document_kind, coalesce(d.format_name, '') AS format_name,
               coalesce(d.spec_version, '') AS spec_version,
               count(DISTINCT d.id) AS unique_documents,
               count(DISTINCT ssf.id) AS source_files,
               count(DISTINCT dc.id) AS component_occurrences
        FROM scoped_documents sd
        JOIN document d ON d.id = sd.document_id
        JOIN scoped_source_files ssf ON ssf.document_id = d.id
        LEFT JOIN document_component dc ON dc.document_id = d.id
        GROUP BY d.document_kind, d.format_name, d.spec_version
        ORDER BY source_files DESC, d.document_kind, d.spec_version
        """,
        (*(product_ctes.params if product_ctes else ()), *scope_params),
    )
    component_types = _fetch_all(
        scoped_cte
        + """
        SELECT coalesce(c.component_type, 'unknown') AS component_type,
               count(DISTINCT c.id) AS unique_components,
               count(so.id) AS component_occurrences
        FROM scoped_occurrences so
        JOIN component c ON c.id = so.component_id
        GROUP BY c.component_type
        ORDER BY component_occurrences DESC, component_type
        """,
        (*(product_ctes.params if product_ctes else ()), *scope_params),
    )
    top_crypto_libraries = _fetch_all(
        scoped_cte
        + """
        SELECT c.id AS component_id, c.name, c.version, c.canonical_purl,
               count(*) AS occurrence_count,
               count(DISTINCT sco.document_id) AS service_count,
               (
                   SELECT count(DISTINCT ssf.service_group_id)
                   FROM scoped_occurrences related
                   JOIN scoped_source_files ssf ON ssf.document_id = related.document_id
                   WHERE related.component_id = c.id
               ) AS service_group_count,
               'explicit_crypto_metadata'::text AS classification_basis
        FROM scoped_crypto_occurrences sco
        JOIN component c ON c.id = sco.component_id
        WHERE c.component_type IN ('library', 'framework')
        GROUP BY c.id
        ORDER BY service_count DESC, occurrence_count DESC, c.name, c.version
        LIMIT 5
        """,
        (*(product_ctes.params if product_ctes else ()), *scope_params),
    )
    groups = _fetch_all(
        scoped_cte
        + """
        SELECT sc.slug AS source_collection, sg.slug, sg.display_name,
               count(DISTINCT ssf.id) AS source_files,
               count(DISTINCT ssf.document_id) AS unique_documents,
               (
                   SELECT count(*)
                   FROM scoped_crypto_occurrences sco
                   JOIN scoped_document_groups sdg ON sdg.document_id = sco.document_id
                   WHERE sdg.service_group_id = sg.id
               ) AS crypto_component_occurrences,
               (
                   SELECT count(DISTINCT sco.component_id)
                   FROM scoped_crypto_occurrences sco
                   JOIN scoped_document_groups sdg ON sdg.document_id = sco.document_id
                   WHERE sdg.service_group_id = sg.id
               ) AS unique_crypto_components,
               (
                   SELECT count(DISTINCT sco.component_id)
                   FROM scoped_crypto_occurrences sco
                   JOIN component c ON c.id = sco.component_id
                   JOIN scoped_document_groups sdg ON sdg.document_id = sco.document_id
                   WHERE sdg.service_group_id = sg.id
                     AND c.component_type IN ('library', 'framework')
               ) AS unique_crypto_libraries,
               count(DISTINCT ssf.id) FILTER (
                   WHERE ssf.parse_status IN ('empty', 'invalid', 'unsupported', 'error')
               ) AS issues
        FROM scoped_service_groups sg
        JOIN source_collection sc ON sc.id = sg.source_collection_id
        LEFT JOIN scoped_source_files ssf ON ssf.service_group_id = sg.id
        GROUP BY sc.id, sc.slug, sc.display_name, sg.id, sg.slug, sg.display_name
        ORDER BY source_files DESC, sc.display_name, sg.display_name
        """,
        (*(product_ctes.params if product_ctes else ()), *scope_params),
    )
    scope = {
        "source_collection": source_collection,
        "service_group": service_group,
    }
    if product_scope_id is not None:
        scope["product_scope_id"] = product_scope_id
    return {
        "scope": scope,
        "counts": dict(counts or {}),
        "format_coverage": format_coverage,
        "component_types": component_types,
        "top_crypto_libraries": top_crypto_libraries,
        "service_groups": groups,
    }


@app.get("/api/v1/dashboard/overview", tags=["catalog"])
def dashboard_overview(
    request: Request,
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
) -> Response:
    parts = (source_collection, service_group, product_scope_id)
    data, revision, cache_hit = _cached_catalog_value(
        "dashboard-overview",
        parts,
        lambda: _build_dashboard_overview(source_collection, service_group, product_scope_id),
    )
    return _conditional_json_response(
        request,
        data,
        namespace="dashboard-overview",
        revision=revision,
        cache_hit=cache_hit,
        parts=parts,
    )


def _numeric_fields(value: Any) -> dict[str, int | float]:
    """Project a summary without identifiers, prose, evidence, or drilldowns."""
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    }


def _format_family(row: dict[str, Any]) -> str:
    value = " ".join(str(row.get(key) or "") for key in ("document_kind", "format_name")).casefold()
    if "cyclonedx" in value:
        return "CycloneDX"
    if "spdx" in value:
        return "SPDX"
    if "oscal" in value:
        return "OSCAL"
    return "Other"


def _portfolio_overview_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Return an aggregate projection that cannot disclose source identifiers."""
    format_counts: dict[str, int] = defaultdict(int)
    for row in data.get("format_coverage", []):
        if isinstance(row, dict):
            format_counts[_format_family(row)] += int(row.get("source_files") or 0)
    component_counts: dict[str, int] = defaultdict(int)
    allowed_component_types = {
        "application", "library", "framework", "operating-system", "device",
        "file", "firmware", "service", "unknown",
    }
    for row in data.get("component_types", []):
        if not isinstance(row, dict):
            continue
        component_type = str(row.get("component_type") or "unknown").casefold()
        component_counts[component_type if component_type in allowed_component_types else "unknown"] += int(row.get("unique_components") or 0)
    return {
        "scope": "portfolio-summary",
        "counts": _numeric_fields(data.get("counts")),
        "format_coverage": [{"format": name, "count": format_counts.get(name, 0)} for name in ("CycloneDX", "SPDX", "OSCAL", "Other")],
        "component_types": [
            {"component_type": name, "count": count}
            for name, count in sorted(component_counts.items())
        ],
    }


@app.get("/api/v1/portfolio/overview-summary", tags=["portfolio"])
def portfolio_overview_summary(request: Request) -> Response:
    """Aggregate-only catalog counts for summary-authorized users."""
    data, revision, cache_hit = _cached_catalog_value(
        "dashboard-overview", (None, None), lambda: _build_dashboard_overview(None, None)
    )
    payload = _portfolio_overview_summary(data)
    return _conditional_json_response(
        request, payload, namespace="portfolio-overview-summary", revision=revision,
        cache_hit=cache_hit, parts=(),
    )


@app.get("/api/v1/portfolio/assigned-service-groups", tags=["portfolio"])
def assigned_service_group_register(request: Request) -> dict[str, Any]:
    """Return safe placeholders for the caller's union of exact grants.

    This response deliberately has no source-collection or service-group input.
    The middleware derives the set from the verified OIDC policy, preventing a
    browser from widening the union by changing a query string. It does not
    aggregate catalog evidence while the product-scoped detail gate is off:
    catalog rows could belong to one product boundary but not the other.
    """
    assigned = getattr(request.state, "assigned_scope", None)
    if not isinstance(assigned, dict) or assigned.get("mode") != "assigned":
        raise HTTPException(status_code=403, detail="A product access mode is required")
    grants = list(assigned.get("grants") or [])
    if not grants:
        raise HTTPException(status_code=403, detail="No verified product grants are available")
    detail_state = (
        "available" if _PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED else "attribution_pending"
    )
    rows = [
        {
            "source_collection": str(grant.get("source_collection") or ""),
            "service_group": str(grant.get("service_group") or ""),
            "product_scope_id": str(grant.get("product_scope_id") or ""),
            "boundary_name": str(grant.get("boundary_name") or ""),
            "access": str(grant.get("access") or "engineer"),
            "detail_state": detail_state,
            "assessment_authorization_reference": grant.get("assessment_authorization_reference"),
        }
        for grant in grants
    ]
    rows.sort(key=lambda row: (row["source_collection"], row["service_group"], row["product_scope_id"]))
    return {
        "items": rows,
        "total": len(rows),
        "scope": "assigned-service-union",
        "access_mode": assigned.get("active_mode"),
        "evidence_only": True,
        "detail_state": detail_state,
    }


def _planning_summary(profile: dict[str, Any], key: str) -> dict[str, Any]:
    entries = []
    for tracker_row in profile.get("tracker_rows", []):
        milestone = tracker_row.get(key) or {}
        entries.append(
            {
                "team": tracker_row.get("team"),
                "raw_value": milestone.get("raw_value") or "",
                "status": milestone.get("status") or "not_supplied",
                "date": milestone.get("date"),
            }
        )
    dates = sorted({entry["date"] for entry in entries if entry.get("date")})
    statuses = {entry["status"] for entry in entries} or {"not_supplied"}
    if dates:
        state = "dated"
    elif statuses == {"not_applicable"}:
        state = "not_applicable"
    elif "vendor_dependency" in statuses:
        state = "vendor_dependency"
    elif "done" in statuses:
        state = "done"
    elif statuses == {"not_supplied"}:
        state = "not_supplied"
    else:
        state = "non_date"
    return {
        "state": state,
        "farthest_date": dates[-1] if dates else None,
        "explicit_dates": dates,
        "entries": entries,
    }


def _apply_service_group_overlays(
    rows: list[dict[str, Any]],
    overlays: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Apply active planning overlays consistently to register and detail views."""
    overlays = overlays or {}
    for row in rows:
        overlay = overlays.get(str(row.get("service_key"))) or overlays.get(
            str(row.get("service_key") or "").rsplit("/", 1)[-1]
        )
        if not overlay:
            continue
        patch = overlay.get("payload") or {}
        if "effective_owners" in patch:
            row["effective_owners"] = list(patch["effective_owners"] or [])
            row["owner_state"] = (
                "multiple" if len(row["effective_owners"]) > 1
                else "supplied" if row["effective_owners"]
                else "not_supplied"
            )
        if "leads" in patch:
            row["leads"] = list(patch["leads"] or [])
            row["lead_state"] = (
                "multiple" if len(row["leads"]) > 1
                else "supplied" if row["leads"]
                else "not_supplied"
            )
        for milestone_key in ("il2", "il5"):
            date_value = patch.get(f"{milestone_key}_date")
            if date_value:
                row[milestone_key] = {
                    **row[milestone_key],
                    "state": "dated",
                    "farthest_date": date_value,
                    "admin_override": True,
                }
        row["admin_overlay"] = overlay
    return rows


def _service_group_register_rows(
    assessment: dict[str, Any],
    overview: dict[str, Any],
    milestones: dict[str, Any],
    service_impacts: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Join catalog, planning, and candidate-assessment rollups by scoped group key."""
    overview_by_key = {
        (row.get("source_collection"), row.get("slug")): row
        for row in overview.get("service_groups", [])
    }
    profiles = {
        profile.get("service_group"): profile
        for profile in milestones.get("groups", [])
    }
    poam_by_service: dict[str, list[str]] = defaultdict(list)
    for item in assessment.get("poam_items", []):
        for service in item.get("affected_services", []):
            candidate_id = item.get("poam_candidate_id")
            if candidate_id and candidate_id not in poam_by_service[service]:
                poam_by_service[service].append(candidate_id)
    workstreams_by_service: dict[str, list[str]] = defaultdict(list)
    for item in assessment.get("poam_workstreams", []):
        for service in item.get("affected_services", []):
            workstream_id = item.get("workstream_id")
            if workstream_id and workstream_id not in workstreams_by_service[service]:
                workstreams_by_service[service].append(workstream_id)
    portfolio_poams_by_service: dict[str, list[str]] = defaultdict(list)
    for item in assessment.get("portfolio_poam_items", []):
        for service in item.get("affected_service_groups", []):
            portfolio_id = item.get("portfolio_poam_id")
            if portfolio_id and portfolio_id not in portfolio_poams_by_service[service]:
                portfolio_poams_by_service[service].append(portfolio_id)
    coverage_by_service: dict[str, list[str]] = defaultdict(list)
    for observation in assessment.get("coverage_gaps", []):
        scope = observation.get("scope") or {}
        collection = scope.get("source_collection")
        for value in scope.get("service_groups", []):
            service = value if "/" in value else f"{collection}/{value}" if collection else value
            state = observation.get("assertion_state")
            if state and state not in coverage_by_service[service]:
                coverage_by_service[service].append(state)

    rows = []
    for rollup in assessment.get("service_groups", []):
        service_key = str(rollup.get("service") or "")
        collection, separator, group_slug = service_key.partition("/")
        if not separator:
            continue
        inventory = overview_by_key.get((collection, group_slug), {})
        profile = profiles.get(group_slug, {})
        service_impact = (service_impacts or {}).get(service_key, {})
        owners = list(profile.get("owners") or [])
        leads = list(profile.get("leads") or [])
        target_modules = list(profile.get("target_modules") or [])
        asserted_not_compliant = [
            module
            for module in target_modules
            if module.get("normalized_status") == "asserted_not_compliant"
        ]
        verification_conflicts = [
            module
            for module in target_modules
            if ((module.get("verification") or {}).get("overall") or {}).get("state")
            in {"contradicted", "conflicting_evidence"}
        ]
        rows.append(
            {
                "service_key": service_key,
                "source_collection": collection,
                "service_group": group_slug,
                "display_name": rollup.get("service_group_name") or inventory.get("display_name") or group_slug,
                "mapping_status": profile.get("mapping_status") or "not_mapped",
                "effective_owners": owners,
                "owner_state": "multiple" if len(owners) > 1 else "supplied" if owners else "not_supplied",
                "leads": leads,
                "lead_state": "multiple" if len(leads) > 1 else "supplied" if leads else "not_supplied",
                "il2": _planning_summary(profile, "il2"),
                "il5": _planning_summary(profile, "il5"),
                "poam_impact": service_impact.get("poam_impact"),
                "risk_category": service_impact.get("risk_category"),
                "comments": service_impact.get("comments"),
                "service_impact_team": service_impact.get("team"),
                "service_impact_evidence_grade": service_impact.get("evidence_grade"),
                "service_impact_review_required": service_impact.get("review_required", False),
                "service_impact_source": service_impact.get("source"),
                "risk_authority": service_impact.get("risk_authority"),
                "source_files": int(rollup.get("source_files") or inventory.get("source_files") or 0),
                "documents": int(rollup.get("documents") or inventory.get("unique_documents") or 0),
                "documents_with_fips_evidence": int(rollup.get("documents_with_fips_evidence") or 0),
                "documents_without_fips_evidence": int(rollup.get("documents_without_fips_evidence") or 0),
                "evidence_coverage_percent": float(rollup.get("evidence_coverage_percent") or 0),
                "ingest_issues": int(
                    rollup["ingest_issues"]
                    if rollup.get("ingest_issues") is not None
                    else inventory.get("issues") or 0
                ),
                "crypto_component_occurrences": int(inventory.get("crypto_component_occurrences") or 0),
                "candidate_crypto_assets": int(inventory.get("unique_crypto_components") or 0),
                "candidate_crypto_libraries": int(inventory.get("unique_crypto_libraries") or 0),
                "candidate_findings": int(rollup.get("poam_candidate_findings") or 0),
                "review_observations": int(rollup.get("needs_review_findings") or 0),
                "finding_count": int(rollup.get("finding_count") or 0),
                "target_module_review_count": len(target_modules),
                "target_module_asserted_not_compliant_count": len(asserted_not_compliant),
                "target_module_verification_conflict_count": len(verification_conflicts),
                "coverage_gap_states": sorted(coverage_by_service.get(service_key, [])),
                "coverage_gap_count": len(coverage_by_service.get(service_key, [])),
                "poam_candidate_ids": sorted(poam_by_service.get(service_key, [])),
                "poam_candidate_count": len(poam_by_service.get(service_key, [])),
                "workstream_ids": sorted(workstreams_by_service.get(service_key, [])),
                "workstream_count": len(workstreams_by_service.get(service_key, [])),
                "portfolio_poam_ids": sorted(
                    portfolio_poams_by_service.get(service_key, [])
                ),
                "portfolio_poam_count": len(
                    portfolio_poams_by_service.get(service_key, [])
                ),
                "delivery_wave": profile.get("delivery_wave"),
            }
        )
    return rows


def _evidence_only_service_group_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Withhold unprovenanced planning and candidate material from scoped views.

    A catalog pair identifies evidence, but the active Team Tracker and
    service-impact imports do not carry a source-collection key.  Do not use a
    matching group slug as a substitute for that provenance.  This projection
    also prevents a scoped Accountability page from representing a generated
    candidate or an operational overlay as an assigned service's evidence.
    """
    unavailable_plan = {
        "state": "not_supplied",
        "farthest_date": None,
        "explicit_dates": [],
        "entries": [],
    }
    evidence_rows = []
    for row in rows:
        # This is deliberately an allowlist.  Do not copy a register row and
        # override fields: a later planning field added to the base projection
        # must not silently become visible to an assigned service scope.
        evidence_rows.append(
            {
            "service_key": str(row.get("service_key") or ""),
            "source_collection": str(row.get("source_collection") or ""),
            "service_group": str(row.get("service_group") or ""),
            "display_name": str(row.get("display_name") or ""),
            "mapping_status": "not_mapped",
            "effective_owners": [],
            "owner_state": "not_supplied",
            "leads": [],
            "lead_state": "not_supplied",
            "il2": dict(unavailable_plan),
            "il5": dict(unavailable_plan),
            "poam_impact": None,
            "risk_category": None,
            "comments": None,
            "service_impact_team": None,
            "service_impact_evidence_grade": None,
            "service_impact_review_required": False,
            "service_impact_source": None,
            "risk_authority": None,
            "source_files": int(row.get("source_files") or 0),
            "documents": int(row.get("documents") or 0),
            "documents_with_fips_evidence": int(row.get("documents_with_fips_evidence") or 0),
            "documents_without_fips_evidence": int(row.get("documents_without_fips_evidence") or 0),
            "evidence_coverage_percent": float(row.get("evidence_coverage_percent") or 0),
            "ingest_issues": int(row.get("ingest_issues") or 0),
            "crypto_component_occurrences": int(row.get("crypto_component_occurrences") or 0),
            "candidate_crypto_assets": int(row.get("candidate_crypto_assets") or 0),
            "candidate_crypto_libraries": int(row.get("candidate_crypto_libraries") or 0),
            "candidate_findings": 0,
            # The raw finding count may include candidate-capable findings.
            # This view exposes only evidence-review observations.
            "review_observations": int(row.get("review_observations") or 0),
            "finding_count": int(row.get("review_observations") or 0),
            "target_module_review_count": 0,
            "target_module_asserted_not_compliant_count": 0,
            "target_module_verification_conflict_count": 0,
            "coverage_gap_states": list(row.get("coverage_gap_states") or []),
            "coverage_gap_count": int(row.get("coverage_gap_count") or 0),
            "poam_candidate_ids": [],
            "poam_candidate_count": 0,
            "workstream_ids": [],
            "workstream_count": 0,
            "portfolio_poam_ids": [],
            "portfolio_poam_count": 0,
            "delivery_wave": None,
        }
        )
    return evidence_rows


def _is_portfolio_admin_request(request: Request | None) -> bool:
    """Identify the effective admin policy applied by access_controls."""
    state = getattr(request, "state", None)
    assigned = getattr(state, "assigned_scope", None)
    return bool(
        isinstance(assigned, dict)
        and assigned.get("mode") == "portfolio"
        and assigned.get("role") == "admin"
    )


def _filter_service_group_register(
    rows: list[dict[str, Any]],
    *,
    query: str | None,
    owner: str | None,
    lead: str | None,
    il2_state: str | None,
    il5_state: str | None,
    action: str | None,
) -> list[dict[str, Any]]:
    normalized = (query or "").strip().casefold()
    filtered = []
    for row in rows:
        if normalized and normalized not in " ".join(
            [
                row["service_key"], row["display_name"],
                *row["effective_owners"], *row["leads"],
                *row["poam_candidate_ids"], *row["workstream_ids"],
                *row.get("portfolio_poam_ids", []),
                str(row.get("poam_impact") or ""),
                str(row.get("risk_category") or ""),
                str(row.get("comments") or ""),
            ]
        ).casefold():
            continue
        if owner == "__missing__" and row["effective_owners"]:
            continue
        if owner and owner != "__missing__" and owner not in row["effective_owners"]:
            continue
        if lead == "__missing__" and row["leads"]:
            continue
        if lead and lead != "__missing__" and lead not in row["leads"]:
            continue
        if il2_state and il2_state != "all" and row["il2"]["state"] != il2_state:
            continue
        if il5_state and il5_state != "all" and row["il5"]["state"] != il5_state:
            continue
        if action == "has_poam" and not row["poam_candidate_count"]:
            continue
        if action == "has_findings" and not row["finding_count"]:
            continue
        if action == "review_only" and not row["review_observations"]:
            continue
        if action == "no_action" and (row["finding_count"] or row["poam_candidate_count"]):
            continue
        filtered.append(row)
    return filtered


@app.get("/api/v1/inventory/service-groups", tags=["inventory"])
def service_group_register(
    request: Request,
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
    query: str | None = None,
    owner: str | None = None,
    lead: str | None = None,
    il2_state: str | None = None,
    il5_state: str | None = None,
    action: str | None = None,
    sort: str = "effective_owner",
    direction: str = "asc",
    limit: int = Query(50, ge=1, le=250),
    offset: int = Query(0, ge=0),
) -> Response:
    """Accountability register; tracker fields remain planning metadata only."""
    portfolio_admin = _is_portfolio_admin_request(request)
    evidence_only = bool(source_collection and service_group) and not portfolio_admin
    assessment, revision, _ = _cached_fips_assessment(
        source_collection, service_group, product_scope_id=product_scope_id
    )
    overview, _, _ = _cached_catalog_value(
        "dashboard-overview", (source_collection, service_group, product_scope_id),
        lambda: _build_dashboard_overview(source_collection, service_group, product_scope_id),
    )
    milestone_contract = (
        team_milestones(_active_target_module_contract())
        if portfolio_admin else _unavailable_planning_context()
    )
    all_rows = _service_group_register_rows(
        assessment,
        overview,
        milestone_contract,
        # Service-impact and overlay records lack collection provenance.  A
        # caller that names an exact pair receives evidence only.
        None if evidence_only else _active_service_impact_map(),
    )
    if evidence_only:
        all_rows = _evidence_only_service_group_rows(all_rows)
    else:
        _apply_service_group_overlays(all_rows, _active_overlay_map("service_group"))
    rows = _filter_service_group_register(
        all_rows, query=query, owner=owner, lead=lead,
        il2_state=il2_state, il5_state=il5_state, action=action,
    )
    sorters = {
        "service_group": lambda row: row["display_name"].casefold(),
        "effective_owner": lambda row: ((row["effective_owners"] or ["~ Not supplied"])[0].casefold(), row["display_name"].casefold()),
        "lead": lambda row: ((row["leads"] or ["~ Not supplied"])[0].casefold(), row["display_name"].casefold()),
        "il2": lambda row: (row["il2"]["farthest_date"] or "9999-12-31", row["display_name"].casefold()),
        "il5": lambda row: (row["il5"]["farthest_date"] or "9999-12-31", row["display_name"].casefold()),
        "documents": lambda row: row["documents"],
        "libraries": lambda row: row["candidate_crypto_assets"],
        "findings": lambda row: row["finding_count"],
        "poam": lambda row: row["poam_candidate_count"],
    }
    rows.sort(key=sorters.get(sort, sorters["effective_owner"]), reverse=direction.casefold() == "desc")
    page_size = min(limit, _max_page_size())
    payload = {
        "items": rows[offset : offset + page_size],
        "total": len(rows),
        "limit": page_size,
        "offset": offset,
        "filter_options": {
            "owners": sorted({value for row in all_rows for value in row["effective_owners"]}, key=str.casefold),
            "leads": sorted({value for row in all_rows for value in row["leads"]}, key=str.casefold),
        },
        "disclaimer": (
            "This exact-pair register contains scoped catalog evidence only; "
            "Team Tracker, service-impact, overlays, and candidate POA&M "
            "material are withheld until they carry collection provenance."
            if evidence_only else
            "Team Tracker owners and IL2/IL5 values and imported service-impact fields are user-asserted planning metadata. Findings and POA&M mappings are machine-generated candidates requiring authorized review."
        ),
    }
    parts = (
        source_collection, service_group, query, owner, lead, il2_state,
        il5_state, action, sort, direction, page_size, offset,
    )
    return _conditional_json_response(
        request, payload, namespace="service-group-register-v2", revision=revision,
        cache_hit=False, parts=parts,
    )


@app.get("/api/v1/service-groups", tags=["catalog"])
def service_groups(source_collection: str | None = None) -> list[dict[str, Any]]:
    where = "WHERE sc.slug = %s" if source_collection else ""
    params: tuple[Any, ...] = (source_collection,) if source_collection else ()
    return _fetch_all(
        f"""
        SELECT sg.id, sc.slug AS source_collection, sg.slug, sg.display_name,
               count(DISTINCT sf.id) AS source_files,
               count(DISTINCT sf.document_id) AS unique_documents,
               count(*) FILTER (WHERE sf.parse_status IN ('invalid', 'error', 'empty')) AS issues
        FROM service_group sg
        JOIN source_collection sc ON sc.id = sg.source_collection_id
        LEFT JOIN source_file sf ON sf.service_group_id = sg.id AND sf.is_present
        {where}
        GROUP BY sg.id, sc.id
        ORDER BY source_files DESC, sc.display_name, sg.display_name
        """,
        params,
    )


@app.get("/api/v1/source-collections", tags=["catalog"])
def source_collections() -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT sc.id, sc.slug, sc.display_name, sc.root_uri,
               count(DISTINCT sf.id) AS source_files,
               count(DISTINCT sf.document_id) AS unique_documents,
               max(ir.completed_at) AS last_ingested_at
        FROM source_collection sc
        LEFT JOIN source_file sf ON sf.source_collection_id = sc.id AND sf.is_present
        LEFT JOIN ingest_run ir ON ir.source_collection_id = sc.id
        GROUP BY sc.id
        ORDER BY sc.display_name
        """
    )


@app.get("/api/v1/fingerprints", tags=["catalog"])
def fingerprints(
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
    path_query: str | None = None,
    checksum: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    product_ctes = _product_scope_ctes(product_scope_id)
    clauses: list[str] = []
    params: list[Any] = []
    if source_collection:
        clauses.append("source_collection = %s")
        params.append(source_collection)
    if service_group:
        clauses.append("service_group = %s")
        params.append(service_group)
    if path_query:
        clauses.append("source_path ILIKE %s")
        params.append(f"%{path_query}%")
    if checksum:
        clauses.append("current_checksum = %s")
        params.append(checksum.casefold())
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend((min(limit, _max_page_size()), offset))
    prefix = f"WITH {product_ctes.sql}" if product_ctes else ""
    source_join = f"JOIN {product_ctes.source_files} psf ON psf.id = status.source_file_id" if product_ctes else ""
    return _fetch_all(
        f"""
        {prefix}
        SELECT *
        FROM v_source_fingerprint_status status
        {source_join}
        {where}
        ORDER BY source_collection, source_path
        LIMIT %s OFFSET %s
        """,
        (*(product_ctes.params if product_ctes else ()), *params),
    )


@app.get("/api/v1/ingest-runs", tags=["operations"])
def ingest_runs(
    source_collection: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    where = "WHERE sc.slug = %s" if source_collection else ""
    params: list[Any] = [source_collection] if source_collection else []
    params.extend((min(limit, _max_page_size()), offset))
    return _fetch_all(
        f"""
        SELECT ir.id, sc.slug AS source_collection, ir.root_path,
               ir.parser_version, ir.fingerprint_algorithm, ir.force_reprocess,
               ir.status, ir.files_seen, ir.files_loaded, ir.files_linked,
               ir.files_unchanged, ir.files_failed,
               ir.started_at, ir.completed_at
        FROM ingest_run ir
        LEFT JOIN source_collection sc ON sc.id = ir.source_collection_id
        {where}
        ORDER BY ir.id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )


@app.get("/api/v1/documents", tags=["documents"])
def documents(
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
    kind: str | None = None,
    spec_version: str | None = None,
    path_query: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    rows, _ = _document_inventory_rows(
        source_collection=source_collection,
        service_group=service_group,
        product_scope_id=product_scope_id,
        kind=kind,
        spec_version=spec_version,
        path_query=path_query,
        limit=limit,
        offset=offset,
        sort="document_id",
        direction="asc",
        include_total=False,
    )
    return rows


def _document_inventory_filters(
    *,
    source_collection: str | None,
    service_group: str | None,
    kind: str | None,
    spec_version: str | None,
    path_query: str | None,
    product_source_files: str | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if source_collection or service_group or path_query:
        provenance_clauses = ["sf.document_id = inventory.document_id", "sf.is_present"]
        if source_collection:
            provenance_clauses.append("sc.slug = %s")
            params.append(source_collection)
        if service_group:
            provenance_clauses.append("sg.slug = %s")
            params.append(service_group)
        if path_query:
            provenance_clauses.append("sf.source_path ILIKE %s")
            params.append(f"%{path_query}%")
        source_table = product_source_files or "source_file"
        clauses.append(
            f"EXISTS (SELECT 1 FROM {source_table} sf "
            "JOIN source_collection sc ON sc.id = sf.source_collection_id "
            "JOIN service_group sg ON sg.id = sf.service_group_id WHERE "
            + " AND ".join(provenance_clauses)
            + ")"
        )
    if kind:
        clauses.append("inventory.document_kind = %s")
        params.append(kind)
    if spec_version:
        clauses.append("inventory.spec_version = %s")
        params.append(spec_version)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def _document_inventory_rows(
    *,
    source_collection: str | None,
    service_group: str | None,
    product_scope_id: str | None = None,
    kind: str | None,
    spec_version: str | None,
    path_query: str | None,
    limit: int,
    offset: int,
    sort: str,
    direction: str,
    include_total: bool,
) -> tuple[list[dict[str, Any]], int | None]:
    # The inventory view aggregates provenance across every service group. Build
    # that aggregation from the selected pair before paging so shared document
    # aliases and their paths cannot escape through a scoped response.
    product_ctes = _product_scope_ctes(product_scope_id)
    scoped_inventory = bool((source_collection and service_group) or product_ctes)
    inventory_cte = ""
    inventory_params: tuple[Any, ...] = ()
    if product_ctes:
        inventory_cte = f"""
        WITH {product_ctes.sql},
        inventory AS MATERIALIZED (
            SELECT d.id AS document_id, d.sha256, d.document_kind,
                   d.format_name, d.spec_version, d.serial_number,
                   d.generated_at_text, count(sf.id) AS source_alias_count,
                   array_agg(DISTINCT sc.slug ORDER BY sc.slug) AS source_collections,
                   array_agg(DISTINCT sc.slug || '/' || sg.display_name
                             ORDER BY sc.slug || '/' || sg.display_name) AS service_groups,
                   array_agg(sf.source_path ORDER BY sc.slug, sf.source_path) AS source_paths,
                   array_remove(array_agg(sf.source_uri ORDER BY sc.slug, sf.source_path), NULL) AS source_uris
            FROM document d
            JOIN {product_ctes.source_files} sf ON sf.document_id = d.id
            JOIN source_collection sc ON sc.id = sf.source_collection_id
            JOIN service_group sg ON sg.id = sf.service_group_id
            WHERE (%s::text IS NULL OR sc.slug = %s) AND (%s::text IS NULL OR sg.slug = %s)
            GROUP BY d.id
        ),
        """
        inventory_params = (*product_ctes.params, source_collection, source_collection, service_group, service_group)
    elif scoped_inventory:
        inventory_cte = """
        WITH inventory AS MATERIALIZED (
            SELECT d.id AS document_id, d.sha256, d.document_kind,
                   d.format_name, d.spec_version, d.serial_number,
                   d.generated_at_text, count(sf.id) AS source_alias_count,
                   array_agg(DISTINCT sc.slug ORDER BY sc.slug) AS source_collections,
                   array_agg(DISTINCT sc.slug || '/' || sg.display_name
                             ORDER BY sc.slug || '/' || sg.display_name) AS service_groups,
                   array_agg(sf.source_path ORDER BY sc.slug, sf.source_path) AS source_paths,
                   array_remove(array_agg(sf.source_uri ORDER BY sc.slug, sf.source_path), NULL) AS source_uris
            FROM document d
            JOIN source_file sf ON sf.document_id = d.id AND sf.is_present
            JOIN source_collection sc ON sc.id = sf.source_collection_id
            JOIN service_group sg ON sg.id = sf.service_group_id
            WHERE sc.slug = %s AND sg.slug = %s
            GROUP BY d.id
        ),
        """
        inventory_params = (source_collection, service_group)
    else:
        inventory_cte = "WITH "
    where, filter_params = _document_inventory_filters(
        source_collection=source_collection,
        service_group=service_group,
        kind=kind,
        spec_version=spec_version,
        path_query=path_query,
        product_source_files=product_ctes.source_files if product_ctes else None,
    )
    sort_columns = {
        "document_id": "document_id",
        "service": "source_paths[1]",
        "group": "service_groups[1]",
        "kind": "document_kind",
        "format": "format_name",
        "observed_at": "generated_at_text",
    }
    order_column = sort_columns.get(sort, "document_id")
    order_direction = "DESC" if direction.casefold() == "desc" else "ASC"
    page_size = min(max(1, limit), _max_page_size())
    rows = _fetch_all(
        f"""
        {inventory_cte} page AS MATERIALIZED (
            SELECT inventory.*
            FROM {"inventory" if scoped_inventory else "v_document_inventory"} inventory
            {where}
            ORDER BY {order_column} {order_direction} NULLS LAST, document_id
            LIMIT %s OFFSET %s
        )
        SELECT page.*,
               crypto.crypto_component_occurrences,
               crypto.unique_crypto_components,
               crypto.unique_crypto_libraries
        FROM page
        LEFT JOIN LATERAL (
            SELECT count(*) AS crypto_component_occurrences,
                   count(DISTINCT dc.component_id) AS unique_crypto_components,
                   count(DISTINCT dc.component_id) FILTER (
                       WHERE c.component_type IN ('library', 'framework')
                   ) AS unique_crypto_libraries
            FROM document_component dc
            JOIN component c ON c.id = dc.component_id
            WHERE dc.document_id = page.document_id
              AND (
                  (dc.crypto_properties IS NOT NULL AND dc.crypto_properties <> '{{}}'::jsonb)
                  OR EXISTS (
                      SELECT 1
                      FROM component_property cp
                      WHERE cp.occurrence_id = dc.id
                        AND lower(cp.property_name) = 'fedramp:fips:crypto-relevant'
                        AND lower(trim(coalesce(cp.property_value, ''))) IN
                            ('1', 'true', 'yes', 'on', 'enabled', 'validated')
                  )
              )
        ) crypto ON TRUE
        ORDER BY page.{order_column} {order_direction} NULLS LAST, page.document_id
        """,
        (*inventory_params, *filter_params, page_size, offset),
    )
    total: int | None = None
    if include_total:
        count_cte = inventory_cte.rstrip().removesuffix(",") if scoped_inventory else ""
        count_row = _fetch_one(
            f"{count_cte} SELECT count(*) AS total FROM "
            f"{('inventory' if scoped_inventory else 'v_document_inventory')} inventory {where}",
            (*inventory_params, *filter_params),
        )
        total = int((count_row or {}).get("total") or 0)
    return rows, total


@app.get("/api/v1/inventory/documents", tags=["inventory"])
def paged_documents(
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
    kind: str | None = None,
    spec_version: str | None = None,
    query: str | None = None,
    sort: str = "document_id",
    direction: str = "asc",
    limit: int = Query(25, ge=1, le=250),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    rows, total = _document_inventory_rows(
        source_collection=source_collection,
        service_group=service_group,
        product_scope_id=product_scope_id,
        kind=kind,
        spec_version=spec_version,
        path_query=query,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
        include_total=True,
    )
    return {
        "items": rows,
        "total": total,
        "limit": min(limit, _max_page_size()),
        "offset": offset,
    }


def _scoped_document_exists(
    document_id: int, source_collection: str, service_group: str,
    product_scope_id: str | None = None,
) -> bool:
    product_ctes = _product_scope_ctes(product_scope_id)
    if product_ctes:
        return bool(_fetch_one(
            f"""
            WITH {product_ctes.sql}
            SELECT d.id FROM document d
            JOIN {product_ctes.source_files} sf ON sf.document_id = d.id
            JOIN source_collection sc ON sc.id = sf.source_collection_id
            JOIN service_group sg ON sg.id = sf.service_group_id
            WHERE d.id = %s AND sc.slug = %s AND sg.slug = %s
            """,
            (*product_ctes.params, document_id, source_collection, service_group),
        ))
    return bool(_fetch_one(
        """
        SELECT d.id FROM document d
        WHERE d.id = %s AND EXISTS (
            SELECT 1 FROM source_file sf
            JOIN source_collection sc ON sc.id = sf.source_collection_id
            JOIN service_group sg ON sg.id = sf.service_group_id
            WHERE sf.document_id = d.id AND sf.is_present
              AND sc.slug = %s AND sg.slug = %s
        )
        """,
        (document_id, source_collection, service_group),
    ))


@app.get("/api/v1/documents/{document_id}", tags=["documents"])
def document_detail(
    document_id: int,
    source_collection: str = Query(..., min_length=1),
    service_group: str = Query(..., min_length=1),
    product_scope_id: str | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    if include_raw and not _env_bool("CBOM_API_ALLOW_RAW"):
        raise HTTPException(status_code=403, detail="Raw document responses are disabled")
    raw_column = ", d.raw_document" if include_raw else ""
    product_ctes = _product_scope_ctes(product_scope_id)
    evidence_from = product_ctes.source_files if product_ctes else "source_file"
    evidence_prefix = f"WITH {product_ctes.sql}" if product_ctes else ""
    evidence_params: tuple[Any, ...] = product_ctes.params if product_ctes else ()
    row = _fetch_one(
        f"""
        {evidence_prefix}
        SELECT d.id, d.sha256, d.byte_size, d.document_kind, d.format_name,
               d.spec_version, d.serial_number, d.document_version,
               d.generated_at_text, d.generator, d.metadata, d.warnings,
               d.parser_version, d.created_at{raw_column},
               (SELECT count(*) FROM document_component dc WHERE dc.document_id = d.id)
                   AS component_count,
               (SELECT count(*) FROM dependency_edge de WHERE de.document_id = d.id)
                   AS dependency_count,
               (SELECT count(*) FROM external_record er WHERE er.document_id = d.id)
                   AS external_record_count
        FROM document d
        WHERE d.id = %s AND EXISTS (
            SELECT 1 FROM {evidence_from} sf
            JOIN source_collection sc ON sc.id = sf.source_collection_id
            JOIN service_group sg ON sg.id = sf.service_group_id
            WHERE sf.document_id = d.id {'' if product_ctes else 'AND sf.is_present'}
              AND sc.slug = %s AND sg.slug = %s
        )
        """,
        (*evidence_params, document_id, source_collection, service_group),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    row["source_files"] = _fetch_all(
        f"""
        {evidence_prefix}
        SELECT sc.slug AS source_collection, sf.source_path, raw.source_uri,
               raw.parse_status, raw.byte_size, sg.slug AS service_group
        FROM {product_ctes.source_files if product_ctes else 'source_file'} sf
        JOIN source_file raw ON raw.id = sf.id
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        WHERE sf.document_id = %s {'' if product_ctes else 'AND sf.is_present'}
          AND sc.slug = %s AND sg.slug = %s
        ORDER BY sf.source_path
        """,
        (*evidence_params, document_id, source_collection, service_group),
    )
    row["artifacts"] = _fetch_all(
        """
        SELECT a.*, da.role, da.confidence, da.evidence
        FROM document_artifact da
        JOIN artifact a ON a.id = da.artifact_id
        WHERE da.document_id = %s
        ORDER BY da.role, a.name
        """,
        (document_id,),
    )
    return row


@app.get("/api/v1/documents/{document_id}/components", tags=["documents"])
def document_components(
    document_id: int,
    source_collection: str | None = Query(None, min_length=1),
    service_group: str | None = Query(None, min_length=1),
    product_scope_id: str | None = None,
    query: str | None = None,
    crypto_only: bool = False,
    include_total: bool = False,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]] | dict[str, Any]:
    if (source_collection is None) != (service_group is None):
        raise HTTPException(status_code=422, detail="Source collection and service group must be supplied together")
    if source_collection is not None and service_group is not None:
        exists = _scoped_document_exists(document_id, source_collection, service_group, product_scope_id)
    else:
        exists = bool(_fetch_one(
            """SELECT d.id FROM document d WHERE d.id = %s AND EXISTS (
                SELECT 1 FROM source_file sf WHERE sf.document_id = d.id AND sf.is_present
            )""",
            (document_id,),
        ))
    if not exists:
        raise HTTPException(status_code=404, detail="Document not found")
    clauses = ["dc.document_id = %s"]
    params: list[Any] = [document_id]
    if query:
        clauses.append(
            "(c.name ILIKE %s OR coalesce(c.version, '') ILIKE %s "
            "OR coalesce(c.canonical_purl, '') ILIKE %s)"
        )
        pattern = f"%{query}%"
        params.extend((pattern, pattern, pattern))
    crypto_predicate = """
        (
            (dc.crypto_properties IS NOT NULL AND dc.crypto_properties <> '{}'::jsonb)
            OR EXISTS (
                SELECT 1
                FROM component_property cp
                WHERE cp.occurrence_id = dc.id
                  AND lower(cp.property_name) = 'fedramp:fips:crypto-relevant'
                  AND lower(trim(coalesce(cp.property_value, ''))) IN
                      ('1', 'true', 'yes', 'on', 'enabled', 'validated')
            )
        )
    """
    if crypto_only:
        clauses.append(crypto_predicate)
    page_size = min(limit, _max_page_size())
    params.extend((page_size, offset))
    rows = _fetch_all(
        f"""
        SELECT dc.id AS occurrence_id, c.id AS component_id, c.component_type,
               c.namespace, c.name, c.version, c.canonical_purl, c.cpe,
               dc.bom_ref, dc.scope, dc.is_subject, dc.crypto_properties,
               {crypto_predicate} AS explicit_crypto
        FROM document_component dc
        JOIN component c ON c.id = dc.component_id
        WHERE {' AND '.join(clauses)}
        ORDER BY explicit_crypto DESC, c.name, c.version, dc.id
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )
    # Preserve the established list response unless a consumer explicitly asks
    # for pagination metadata.  Detail dialogs need a total so that a full
    # page does not incorrectly imply that another page exists.
    if not include_total:
        return rows
    count_params = params[:-2]
    count_row = _fetch_one(
        f"""
        SELECT count(*) AS total
        FROM document_component dc
        JOIN component c ON c.id = dc.component_id
        WHERE {' AND '.join(clauses)}
        """,
        tuple(count_params),
    )
    return {"items": rows, "total": int((count_row or {}).get("total") or 0), "limit": page_size, "offset": offset}


@app.get("/api/v1/components", tags=["components"])
def components(
    query: str | None = None,
    purl: str | None = None,
    component_type: str | None = None,
    crypto_only: bool = False,
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    rows, _ = _component_inventory_rows(
        query=query,
        purl=purl,
        component_type=component_type,
        crypto_only=crypto_only,
        source_collection=source_collection,
        service_group=service_group,
        product_scope_id=product_scope_id,
        limit=limit,
        offset=offset,
        sort="document_count",
        direction="desc",
        include_total=False,
    )
    return rows


def _component_inventory_filters(
    *,
    query: str | None,
    purl: str | None,
    component_type: str | None,
    crypto_only: bool,
    source_collection: str | None,
    service_group: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = ["sf.is_present"]
    params: list[Any] = []
    if query:
        clauses.append("(c.name ILIKE %s OR c.canonical_purl ILIKE %s OR c.cpe ILIKE %s)")
        pattern = f"%{query}%"
        params.extend((pattern, pattern, pattern))
    if purl:
        clauses.append("c.canonical_purl = %s")
        params.append(purl)
    if component_type:
        clauses.append("c.component_type = %s")
        params.append(component_type)
    if crypto_only:
        clauses.append(
            """(
                (dc.crypto_properties IS NOT NULL AND dc.crypto_properties <> '{}'::jsonb)
                OR EXISTS (
                    SELECT 1 FROM component_property cp
                    WHERE cp.occurrence_id = dc.id
                      AND lower(cp.property_name) = 'fedramp:fips:crypto-relevant'
                      AND lower(trim(coalesce(cp.property_value, ''))) IN
                          ('1', 'true', 'yes', 'on', 'enabled', 'validated')
                )
            )"""
        )
    if source_collection:
        clauses.append("sc.slug = %s")
        params.append(source_collection)
    if service_group:
        clauses.append("sg.slug = %s")
        params.append(service_group)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def _component_inventory_rows(
    *,
    query: str | None,
    purl: str | None,
    component_type: str | None,
    crypto_only: bool,
    source_collection: str | None,
    service_group: str | None,
    product_scope_id: str | None = None,
    limit: int,
    offset: int,
    sort: str,
    direction: str,
    include_total: bool,
) -> tuple[list[dict[str, Any]], int | None]:
    product_ctes = _product_scope_ctes(product_scope_id)
    cte_prefix = f"WITH {product_ctes.sql}" if product_ctes else ""
    source_files = product_ctes.source_files if product_ctes else "source_file"
    where, filter_params = _component_inventory_filters(
        query=query,
        purl=purl,
        component_type=component_type,
        crypto_only=crypto_only,
        source_collection=source_collection,
        service_group=service_group,
    )
    sort_columns = {
        "library": "c.name",
        "version": "c.version",
        "document_count": "document_count",
        "occurrence_count": "occurrence_count",
    }
    order_column = sort_columns.get(sort, "document_count")
    order_direction = "ASC" if direction.casefold() == "asc" else "DESC"
    page_size = min(max(1, limit), _max_page_size())
    rows = _fetch_all(
        f"""
        {cte_prefix}
        SELECT c.id AS component_id, c.component_type, c.namespace, c.name,
               c.version, c.canonical_purl, c.cpe,
               count(DISTINCT dc.document_id) AS document_count,
               count(DISTINCT dc.id) AS occurrence_count,
               array_agg(
                   DISTINCT sc.slug || '/' || sg.display_name
                   ORDER BY sc.slug || '/' || sg.display_name
               ) AS service_groups,
               array_agg(DISTINCT sc.slug ORDER BY sc.slug) AS source_collections
        FROM component c
        JOIN document_component dc ON dc.component_id = c.id
        JOIN {source_files} sf ON sf.document_id = dc.document_id
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        {where}
        GROUP BY c.id
        ORDER BY {order_column} {order_direction} NULLS LAST, c.name, c.version
        LIMIT %s OFFSET %s
        """,
        (*(product_ctes.params if product_ctes else ()), *filter_params, page_size, offset),
    )
    total: int | None = None
    if include_total:
        count_row = _fetch_one(
            f"""
            {cte_prefix}
            SELECT count(DISTINCT c.id) AS total
            FROM component c
            JOIN document_component dc ON dc.component_id = c.id
            JOIN {source_files} sf ON sf.document_id = dc.document_id
            JOIN source_collection sc ON sc.id = sf.source_collection_id
            JOIN service_group sg ON sg.id = sf.service_group_id
            {where}
            """,
            (*(product_ctes.params if product_ctes else ()), *filter_params),
        )
        total = int((count_row or {}).get("total") or 0)
    return rows, total


@app.get("/api/v1/inventory/libraries", tags=["inventory"])
def paged_crypto_libraries(
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
    query: str | None = None,
    sort: str = "document_count",
    direction: str = "desc",
    limit: int = Query(25, ge=1, le=250),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    rows, total = _component_inventory_rows(
        query=query,
        purl=None,
        component_type="library",
        crypto_only=True,
        source_collection=source_collection,
        service_group=service_group,
        product_scope_id=product_scope_id,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
        include_total=True,
    )
    return {
        "items": rows,
        "total": total,
        "limit": min(limit, _max_page_size()),
        "offset": offset,
    }


@app.get(
    "/api/v1/inventory/service-groups/{source_collection}/{service_group}",
    tags=["inventory"],
)
def service_group_register_detail(
    source_collection: str,
    service_group: str,
    product_scope_id: str | None = None,
    document_limit: int = Query(50, ge=1, le=250),
    document_offset: int = Query(0, ge=0),
    library_limit: int = Query(50, ge=1, le=250),
    library_offset: int = Query(0, ge=0),
    request: Request = None,
) -> dict[str, Any]:
    """Detail for one provenance-scoped group.

    The selected collection/group pair is mandatory at the route level.  The
    scoped response intentionally excludes planning imports, administrative
    overlays, and POA&M candidate dimensions unless the effective access policy
    is a portfolio administrator.
    """
    portfolio_admin = _is_portfolio_admin_request(request)
    scoped_assessment, _, _ = _cached_fips_assessment(
        source_collection, service_group, product_scope_id=product_scope_id
    )
    # A selected pair is the complete visibility boundary for this endpoint.
    # Do not enrich it from an unscoped assessment or dashboard cache.
    canonical_assessment = scoped_assessment
    canonical_overview, _, _ = _cached_catalog_value(
        "dashboard-overview",
        (source_collection, service_group, product_scope_id),
        lambda: _build_dashboard_overview(source_collection, service_group, product_scope_id),
    )
    milestone_contract = (
        team_milestones(_active_target_module_contract())
        if portfolio_admin else _unavailable_planning_context()
    )
    register_rows = _service_group_register_rows(
        canonical_assessment,
        canonical_overview,
        milestone_contract,
        _active_service_impact_map() if portfolio_admin else None,
    )
    if portfolio_admin:
        _apply_service_group_overlays(register_rows, _active_overlay_map("service_group"))
    else:
        register_rows = _evidence_only_service_group_rows(register_rows)
    service_key = f"{source_collection}/{service_group}"
    register_row = next(
        (row for row in register_rows if row.get("service_key") == service_key),
        None,
    )
    if register_row is None:
        raise HTTPException(status_code=404, detail="Service group not found")
    profile = next(
        (
            row for row in milestone_contract.get("groups", [])
            if row.get("service_group") == service_group
        ),
        {
            "service_group": service_group,
            "mapping_status": "not_mapped",
            "owners": [],
            "leads": [],
            "tracker_rows": [],
        },
    )
    documents, document_total = _document_inventory_rows(
        source_collection=source_collection,
        service_group=service_group,
        product_scope_id=product_scope_id,
        kind=None,
        spec_version=None,
        path_query=None,
        limit=document_limit,
        offset=document_offset,
        sort="observed_at",
        direction="desc",
        include_total=True,
    )
    libraries, library_total = _component_inventory_rows(
        query=None,
        purl=None,
        component_type="library",
        crypto_only=True,
        source_collection=source_collection,
        service_group=service_group,
        product_scope_id=product_scope_id,
        limit=library_limit,
        offset=library_offset,
        sort="document_count",
        direction="desc",
        include_total=True,
    )
    if portfolio_admin:
        poam_items = _apply_candidate_overlays(
            [
                item for item in canonical_assessment.get("poam_items", [])
                if service_key in item.get("affected_services", [])
            ],
            _active_overlay_map("poam_candidate"),
        )
        poam_by_finding: dict[str, list[str]] = defaultdict(list)
        for item in poam_items:
            for finding_id in item.get("linked_finding_ids", []):
                candidate_id = item.get("poam_candidate_id")
                if candidate_id:
                    poam_by_finding[finding_id].append(candidate_id)
        findings = [
            {**finding, "poam_candidate_ids": sorted(poam_by_finding.get(finding.get("finding_id"), []))}
            for finding in scoped_assessment.get("findings", [])
        ]
        workstreams = [
            dict(item) for item in canonical_assessment.get("poam_workstreams", [])
            if service_key in item.get("affected_services", [])
        ]
        portfolio_items = [
            dict(item) for item in canonical_assessment.get("portfolio_poam_items", [])
            if service_key in item.get("affected_service_groups", [])
        ]
        assessment_summary = scoped_assessment.get("summary")
        disclaimer = scoped_assessment.get("disclaimer")
    else:
        findings = _evidence_only_findings(scoped_assessment.get("findings", []))
        poam_items = []
        workstreams = []
        portfolio_items = []
        assessment_summary = {
            "evidence_observations": len(findings),
            "coverage_gaps": len(scoped_assessment.get("coverage_gaps", [])),
            "candidate_dimensions": 0,
        }
        disclaimer = (
            "Scoped catalog evidence and noneligible observations only. "
            "Planning metadata, overlays, and POA&M candidate output are "
            "withheld because they do not have source-collection provenance."
        )
    return {
        "profile": register_row,
        "tracker": {
            "profile": profile,
            "source": milestone_contract.get("source", {}),
            "disclaimer": milestone_contract.get("disclaimer"),
        },
        "documents": {
            "items": documents,
            "total": document_total,
            "limit": min(document_limit, _max_page_size()),
            "offset": document_offset,
        },
        "libraries": {
            "items": libraries,
            "total": library_total,
            "limit": min(library_limit, _max_page_size()),
            "offset": library_offset,
        },
        "assessment": {
            "assessment_run_id": scoped_assessment.get("assessment_run_id"),
            "canonical_assessment_run_id": (
                (canonical_assessment.get("assessment_run") or {}).get("assessment_run_id")
            ),
            "policy": scoped_assessment.get("policy"),
            "assessment_contract": scoped_assessment.get("assessment_contract"),
            "summary": assessment_summary,
            "coverage_gaps": scoped_assessment.get("coverage_gaps", []),
            "findings": findings,
            "poam_items": poam_items,
            "poam_workstreams": workstreams,
            "portfolio_poam_items": portfolio_items,
            "portfolio_delivery_waves": (
                scoped_assessment.get("portfolio_delivery_waves", []) if portfolio_admin else []
            ),
            "limitations": scoped_assessment.get("limitations", []),
            "disclaimer": disclaimer,
        },
        "evidence_only": not portfolio_admin,
        "candidate_only": bool(
            portfolio_admin and scoped_assessment.get("assessment_contract", {}).get("complete")
        ),
    }


@app.get("/api/v1/components/{component_id}/usage", tags=["components"])
def component_usage(
    component_id: int,
    source_collection: str | None = Query(None, min_length=1),
    service_group: str | None = Query(None, min_length=1),
    product_scope_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    explicit_crypto_only: bool = False,
    include_total: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    if (source_collection is None) != (service_group is None):
        raise HTTPException(status_code=422, detail="Source collection and service group must be supplied together")
    product_ctes = _product_scope_ctes(product_scope_id)
    cte_prefix = f"WITH {product_ctes.sql}" if product_ctes else ""
    source_files = product_ctes.source_files if product_ctes else "source_file"
    scope_params: tuple[Any, ...] = product_ctes.params if product_ctes else ()
    scope_clause = " AND sc.slug = %s AND sg.slug = %s" if source_collection is not None else ""
    scope_values = (source_collection, service_group) if source_collection is not None else ()
    component = _fetch_one(
        f"""
        {cte_prefix}
        SELECT c.id FROM component c
        WHERE c.id = %s AND EXISTS (
            SELECT 1 FROM document_component dc
            JOIN {source_files} sf ON sf.document_id = dc.document_id
            JOIN source_collection sc ON sc.id = sf.source_collection_id
            JOIN service_group sg ON sg.id = sf.service_group_id
            WHERE dc.component_id = c.id {'' if product_ctes else 'AND sf.is_present'} {scope_clause}
        )
        """,
        (*scope_params, component_id, *scope_values),
    )
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    crypto_predicate = """
        (
            (dc.crypto_properties IS NOT NULL AND dc.crypto_properties <> '{}'::jsonb)
            OR EXISTS (
                SELECT 1 FROM component_property cp
                WHERE cp.occurrence_id = dc.id
                  AND lower(cp.property_name) = 'fedramp:fips:crypto-relevant'
                  AND lower(trim(coalesce(cp.property_value, ''))) IN
                      ('1', 'true', 'yes', 'on', 'enabled', 'validated')
            )
        )
    """
    crypto_clause = f" AND {crypto_predicate}" if explicit_crypto_only else ""
    page_size = min(limit, _max_page_size())
    rows = _fetch_all(
        f"""
        {cte_prefix}
        SELECT dc.id AS occurrence_id, dc.bom_ref, dc.source_bom_ref,
               dc.scope, dc.is_subject, {crypto_predicate} AS explicit_crypto,
               d.id AS document_id, d.document_kind, d.spec_version,
               array_agg(
                   DISTINCT sc.slug || '/' || sg.display_name
                   ORDER BY sc.slug || '/' || sg.display_name
               ) AS service_groups,
               array_agg(DISTINCT sc.slug ORDER BY sc.slug) AS source_collections,
               array_agg(
                   DISTINCT sc.slug || '/' || sf.source_path
                   ORDER BY sc.slug || '/' || sf.source_path
               ) AS source_paths
        FROM document_component dc
        JOIN document d ON d.id = dc.document_id
        JOIN {source_files} sf ON sf.document_id = d.id
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        WHERE dc.component_id = %s {'' if product_ctes else 'AND sf.is_present'}
          {scope_clause} {crypto_clause}
        GROUP BY dc.id, d.id
        ORDER BY d.id
        LIMIT %s OFFSET %s
        """,
        (*scope_params, component_id, *scope_values, page_size, offset),
    )
    if not include_total:
        return rows
    count_row = _fetch_one(
        f"""
        {cte_prefix}
        SELECT count(DISTINCT dc.id) AS total
        FROM document_component dc
        JOIN {source_files} sf ON sf.document_id = dc.document_id
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        WHERE dc.component_id = %s {'' if product_ctes else 'AND sf.is_present'}
          {scope_clause} {crypto_clause}
        """,
        (*scope_params, component_id, *scope_values),
    )
    return {"items": rows, "total": int((count_row or {}).get("total") or 0), "limit": page_size, "offset": offset}


@app.get("/api/v1/artifacts", tags=["artifacts"])
def artifacts(
    query: str | None = None,
    digest: str | None = None,
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    product_ctes = _product_scope_ctes(product_scope_id)
    cte_prefix = f"WITH {product_ctes.sql}" if product_ctes else ""
    source_files = product_ctes.source_files if product_ctes else "source_file"
    clauses: list[str] = ["sf.is_present"]
    params: list[Any] = []
    if query:
        clauses.append("(a.name ILIKE %s OR a.canonical_key ILIKE %s OR a.purl ILIKE %s)")
        pattern = f"%{query}%"
        params.extend((pattern, pattern, pattern))
    if digest:
        clauses.append("a.digest = %s")
        params.append(digest)
    if source_collection:
        clauses.append("sc.slug = %s")
        params.append(source_collection)
    if service_group:
        clauses.append("sg.slug = %s")
        params.append(service_group)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend((min(limit, _max_page_size()), offset))
    return _fetch_all(
        f"""
        {cte_prefix}
        SELECT a.id, a.canonical_key, a.artifact_type, a.name, a.version,
               a.purl, a.cpe, a.registry, a.repository, a.tag, a.digest,
               count(DISTINCT da.document_id) AS document_count,
               array_agg(
                   DISTINCT sc.slug || '/' || sg.display_name
                   ORDER BY sc.slug || '/' || sg.display_name
               ) AS service_groups,
               array_agg(DISTINCT sc.slug ORDER BY sc.slug) AS source_collections
        FROM artifact a
        JOIN document_artifact da ON da.artifact_id = a.id
        JOIN {source_files} sf ON sf.document_id = da.document_id
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        {where}
        GROUP BY a.id
        ORDER BY document_count DESC, a.name
        LIMIT %s OFFSET %s
        """,
        (*(product_ctes.params if product_ctes else ()), *params),
    )


@app.get("/api/v1/dependency-documents", tags=["dependencies"])
def dependency_documents(
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    product_ctes = _product_scope_ctes(product_scope_id)
    source_files = product_ctes.source_files if product_ctes else "source_file"
    clauses: list[str] = ["sf.is_present"]
    params: list[Any] = []
    if source_collection:
        clauses.append("sc.slug = %s")
        params.append(source_collection)
    if service_group:
        clauses.append("sg.slug = %s")
        params.append(service_group)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend((min(limit, _max_page_size()), offset))
    return _fetch_all(
        f"""
        WITH {product_ctes.sql + ',' if product_ctes else ''} edge_stats AS (
            SELECT document_id, count(*) AS dependency_edges,
                   count(DISTINCT relationship_type) AS relationship_type_count,
                   array_agg(DISTINCT relationship_type ORDER BY relationship_type)
                       AS relationship_types
            FROM dependency_edge
            GROUP BY document_id
        )
        SELECT d.id AS document_id, d.document_kind, d.format_name, d.spec_version,
               es.dependency_edges, es.relationship_type_count, es.relationship_types,
               array_agg(DISTINCT sf.source_path ORDER BY sf.source_path) AS source_paths,
               array_agg(
                   DISTINCT sc.slug || '/' || sg.display_name
                   ORDER BY sc.slug || '/' || sg.display_name
               ) AS service_groups,
               coalesce(
                   array_remove(array_agg(DISTINCT dc.bom_ref) FILTER (WHERE dc.is_subject), NULL),
                   ARRAY[]::text[]
               ) AS subject_refs
        FROM edge_stats es
        JOIN document d ON d.id = es.document_id
        JOIN {source_files} sf ON sf.document_id = d.id
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        LEFT JOIN document_component dc ON dc.document_id = d.id
        {where}
        GROUP BY d.id, es.dependency_edges, es.relationship_type_count,
                 es.relationship_types
        ORDER BY ('DEPENDS_ON' = ANY(es.relationship_types)) DESC,
                 es.dependency_edges DESC, d.id
        LIMIT %s OFFSET %s
        """,
        (*(product_ctes.params if product_ctes else ()), *params),
    )


@app.get("/api/v1/documents/{document_id}/dependency-graph", tags=["dependencies"])
def dependency_graph(
    document_id: int,
    source_collection: str = Query(..., min_length=1),
    service_group: str = Query(..., min_length=1),
    product_scope_id: str | None = None,
    relationship_type: list[str] = Query(default=["DEPENDS_ON"]),
    node_limit: int = Query(80, ge=2, le=200),
    edge_limit: int = Query(240, ge=1, le=1000),
) -> dict[str, Any]:
    allowed_types = sorted(
        {item.strip().upper() for item in relationship_type if item.strip()}
    )
    if not allowed_types:
        raise HTTPException(status_code=400, detail="At least one relationship_type is required")
    product_ctes = _product_scope_ctes(product_scope_id)
    cte_prefix = f"WITH {product_ctes.sql}" if product_ctes else ""
    source_files = product_ctes.source_files if product_ctes else "source_file"
    document = _fetch_one(
        f"""
        {cte_prefix}
        SELECT d.id AS document_id, d.document_kind, d.format_name, d.spec_version,
               d.serial_number,
               array_agg(DISTINCT sf.source_path ORDER BY sf.source_path) AS source_paths
        FROM document d
        JOIN {source_files} sf ON sf.document_id = d.id {'' if product_ctes else 'AND sf.is_present'}
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        WHERE d.id = %s
          AND sc.slug = %s AND sg.slug = %s
        GROUP BY d.id
        """,
        (*(product_ctes.params if product_ctes else ()), document_id, source_collection, service_group),
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    totals = _fetch_one(
        """
        SELECT
            count(*) AS total_edges,
            (
                SELECT count(*)
                FROM (
                    SELECT from_ref AS ref
                    FROM dependency_edge
                    WHERE document_id = %s AND relationship_type = ANY(%s)
                    UNION
                    SELECT to_ref AS ref
                    FROM dependency_edge
                    WHERE document_id = %s AND relationship_type = ANY(%s)
                ) node_refs
            ) AS total_nodes
        FROM dependency_edge
        WHERE document_id = %s AND relationship_type = ANY(%s)
        """,
        (
            document_id,
            allowed_types,
            document_id,
            allowed_types,
            document_id,
            allowed_types,
        ),
    ) or {"total_edges": 0, "total_nodes": 0}

    rows = _fetch_all(
        """
        SELECT de.id AS edge_id, de.from_ref, de.to_ref, de.relationship_type,
               de.resolution_status,
               from_dc.is_subject AS from_is_subject,
               from_component.id AS from_component_id,
               from_component.name AS from_name,
               from_component.version AS from_version,
               from_component.component_type AS from_component_type,
               from_component.canonical_purl AS from_purl,
               to_dc.is_subject AS to_is_subject,
               to_component.id AS to_component_id,
               to_component.name AS to_name,
               to_component.version AS to_version,
               to_component.component_type AS to_component_type,
               to_component.canonical_purl AS to_purl
        FROM dependency_edge de
        LEFT JOIN document_component from_dc
          ON from_dc.document_id = de.document_id
         AND from_dc.id = de.from_occurrence_id
        LEFT JOIN component from_component ON from_component.id = from_dc.component_id
        LEFT JOIN document_component to_dc
          ON to_dc.document_id = de.document_id
         AND to_dc.id = de.to_occurrence_id
        LEFT JOIN component to_component ON to_component.id = to_dc.component_id
        WHERE de.document_id = %s AND de.relationship_type = ANY(%s)
        ORDER BY de.id
        LIMIT %s
        """,
        (document_id, allowed_types, edge_limit),
    )

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add_node(row: dict[str, Any], side: str) -> bool:
        ref = row[f"{side}_ref"]
        if ref in nodes:
            return True
        if len(nodes) >= node_limit:
            return False
        name = row.get(f"{side}_name")
        version = row.get(f"{side}_version")
        label = name or ref
        if name and version:
            label = f"{name}@{version}"
        nodes[ref] = {
            "ref": ref,
            "label": label,
            "component_id": row.get(f"{side}_component_id"),
            "name": name,
            "version": version,
            "component_type": row.get(f"{side}_component_type") or "external",
            "purl": row.get(f"{side}_purl"),
            "is_subject": bool(row.get(f"{side}_is_subject")),
            "resolved": row.get(f"{side}_component_id") is not None,
        }
        return True

    for row in rows:
        new_refs = {
            ref
            for ref in (row["from_ref"], row["to_ref"])
            if ref not in nodes
        }
        if len(nodes) + len(new_refs) > node_limit:
            continue
        from_added = add_node(row, "from")
        to_added = add_node(row, "to")
        if not (from_added and to_added):
            continue
        edges.append(
            {
                "id": row["edge_id"],
                "source": row["from_ref"],
                "target": row["to_ref"],
                "relationship_type": row["relationship_type"],
                "resolution_status": row["resolution_status"],
            }
        )

    shown_nodes = len(nodes)
    shown_edges = len(edges)
    return {
        "document": document,
        "relationship_types": allowed_types,
        "nodes": list(nodes.values()),
        "edges": edges,
        "summary": {
            "total_nodes": totals["total_nodes"],
            "total_edges": totals["total_edges"],
            "shown_nodes": shown_nodes,
            "shown_edges": shown_edges,
            "truncated": (
                int(totals["total_nodes"]) > shown_nodes
                or int(totals["total_edges"]) > shown_edges
            ),
        },
    }


@app.get("/api/v1/dependency-closure", tags=["dependencies"])
def dependency_closure(
    document_id: int,
    bom_ref: str,
    source_collection: str = Query(..., min_length=1),
    service_group: str = Query(..., min_length=1),
    product_scope_id: str | None = None,
    max_depth: int = Query(10, ge=1, le=50),
    limit: int = Query(500, ge=1, le=2_000),
    relationship_type: list[str] = Query(default=["DEPENDS_ON"]),
) -> list[dict[str, Any]]:
    allowed_types = [item.strip().upper() for item in relationship_type if item.strip()]
    if not allowed_types:
        raise HTTPException(status_code=400, detail="At least one relationship_type is required")
    if not _scoped_document_exists(document_id, source_collection, service_group, product_scope_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return _fetch_all(
        """
        WITH RECURSIVE closure AS (
            SELECT 1 AS depth, de.from_ref, de.to_ref, de.relationship_type,
                   ARRAY[de.from_ref, de.to_ref]::text[] AS path
            FROM dependency_edge de
            WHERE de.document_id = %s
              AND de.from_ref = %s
              AND de.relationship_type = ANY(%s)
              AND de.resolution_status <> 'ambiguous'
            UNION ALL
            SELECT closure.depth + 1, de.from_ref, de.to_ref, de.relationship_type,
                   closure.path || de.to_ref
            FROM closure
            JOIN dependency_edge de
              ON de.document_id = %s
             AND de.from_ref = closure.to_ref
             AND de.relationship_type = ANY(%s)
             AND de.resolution_status <> 'ambiguous'
            WHERE closure.depth < %s AND NOT de.to_ref = ANY(closure.path)
        )
        SELECT depth, from_ref, to_ref, relationship_type, path
        FROM closure
        ORDER BY depth, from_ref, to_ref
        LIMIT %s
        """,
        (document_id, bom_ref, allowed_types, document_id, allowed_types, max_depth, limit),
    )


@app.get("/api/v1/external-records", tags=["assessments and enrichment"])
def external_records(
    record_type: str | None = None,
    provider: str | None = None,
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    product_ctes = _product_scope_ctes(product_scope_id)
    cte_prefix = f"WITH {product_ctes.sql}" if product_ctes else ""
    source_files = product_ctes.source_files if product_ctes else "source_file"
    clauses: list[str] = ["sf.is_present"]
    params: list[Any] = []
    if record_type:
        clauses.append("er.record_type = %s")
        params.append(record_type)
    if provider:
        clauses.append("er.provider = %s")
        params.append(provider)
    if source_collection:
        clauses.append("sc.slug = %s")
        params.append(source_collection)
    if service_group:
        clauses.append("sg.slug = %s")
        params.append(service_group)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend((min(limit, _max_page_size()), offset))
    return _fetch_all(
        f"""
        {cte_prefix}
        SELECT er.id, er.document_id, er.record_type, er.external_id,
               er.observed_at_text, er.provider, er.payload_sha256, er.data,
               parent.id AS parent_record_id,
               parent.record_type AS parent_record_type,
               parent.external_id AS parent_external_id,
               a.canonical_key AS artifact_key, a.name AS artifact_name,
               array_agg(
                   DISTINCT sc.slug || '/' || sg.display_name
                   ORDER BY sc.slug || '/' || sg.display_name
               ) AS service_groups,
               array_agg(DISTINCT sc.slug ORDER BY sc.slug) AS source_collections
        FROM external_record er
        LEFT JOIN artifact a ON a.id = er.artifact_id
        LEFT JOIN external_record parent ON parent.id = er.parent_record_id
        JOIN {source_files} sf ON sf.document_id = er.document_id
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        {where}
        GROUP BY er.id, a.id, parent.id
        ORDER BY er.id
        LIMIT %s OFFSET %s
        """,
        (*(product_ctes.params if product_ctes else ()), *params),
    )


def _cached_fips_assessment(
    source_collection: str | None = None,
    service_group: str | None = None,
    contract: dict[str, Any] | None = None,
    product_scope_id: str | None = None,
) -> tuple[dict[str, Any], int, bool]:
    contract = contract if contract is not None else _fips_assessment_contract()
    contract_fingerprint = hashlib.sha256(
        json.dumps(contract or {}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    data, revision, cache_hit = _cached_catalog_value(
        "fips-assessment",
        (source_collection, service_group, product_scope_id, contract_fingerprint),
        lambda: _load_fips_assessment(source_collection, service_group, contract, product_scope_id),
    )
    return data, revision, cache_hit


def _shape_fips_assessment(
    assessment: dict[str, Any],
    *,
    include_findings: bool,
    query: str | None,
    poam_limit: int,
    poam_offset: int,
    candidate_overlays: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = {key: value for key, value in assessment.items() if key != "findings"}
    if not assessment.get("assessment_contract", {}).get("complete"):
        # Planning enrichment must not reintroduce candidate dimensions when the
        # assessment contract cannot support POA&M eligibility.
        result["poam_items"] = []
        result["poam_candidate_records"] = []
        result["poam_workstreams"] = []
        result["portfolio_poam_items"] = []
        summary = dict(result.get("summary") or {})
        summary["deduplicated_poam_candidates"] = 0
        summary["candidate_gap_findings"] = 0
        summary["proposed_remediation_workstreams"] = 0
        summary["portfolio_poam_candidates"] = 0
        result["summary"] = summary
        result["poam_page"] = {"total": 0, "limit": min(max(1, poam_limit), _max_page_size()), "offset": poam_offset}
        if include_findings:
            result["findings"] = assessment.get("findings", [])
        return result
    candidates = _apply_candidate_overlays(
        assessment.get("poam_items", []), candidate_overlays
    )
    if query:
        normalized = query.casefold()
        candidates = [
            item
            for item in candidates
            if normalized
            in " ".join(
                [
                    str(item.get("poam_candidate_id") or ""),
                    str(item.get("title") or ""),
                    str(item.get("responsible_owner") or ""),
                    *[str(value) for value in item.get("affected_services", [])],
                ]
            ).casefold()
        ]
    page_size = min(max(1, poam_limit), _max_page_size())
    result["poam_items"] = candidates[poam_offset : poam_offset + page_size]
    result["poam_page"] = {
        "total": len(candidates),
        "limit": page_size,
        "offset": poam_offset,
    }
    if include_findings:
        result["findings"] = assessment.get("findings", [])
    return result


def _product_fips_validation(
    source_collection: str | None, service_group: str | None, product_scope_id: str | None,
) -> dict[str, Any] | None:
    if product_scope_id is None:
        return None
    return validate_product_fips_contract(
        _fips_assessment_contract(),
        source_collection=source_collection or "",
        service_group=service_group or "",
        product_scope_id=product_scope_id,
    )


def _product_export_assessment(
    source_collection: str | None,
    service_group: str | None,
    product_scope_id: str | None,
) -> tuple[dict[str, Any], int]:
    """Load an export assessment, denying unverified product assertions.

    A routing decision and a boundary display label are deliberately
    insufficient to export a product-specific POA&M package.  The contract
    validator only enables exports after an independent primary-evidence
    verifier is wired in; at present this makes scoped exports fail closed.
    """
    validation = _product_fips_validation(source_collection, service_group, product_scope_id)
    assessment, revision, _ = _cached_fips_assessment(
        source_collection, service_group, product_scope_id=product_scope_id
    )
    if validation is not None and not validation.get("exports_allowed"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Product assessment evidence is pending independent verification; candidate export is unavailable.",
                "product_assessment_contract": validation,
            },
        )
    if not assessment.get("assessment_contract", {}).get("complete"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Assessment contract is incomplete; candidate export is not available.",
                "missing_required_facts": assessment.get("assessment_contract", {}).get("missing_required_facts", []),
            },
        )
    return assessment, revision


def _evidence_only_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove candidate semantics while retaining scoped evidence observations."""
    allowed = {
        "finding_id", "rule_id", "gap_code", "title", "weakness",
        "subject_identity", "subject_name", "document_id", "document_sha256",
        "affected_services", "scopes", "evidence", "control_refs",
        "duplicate_occurrence_count",
    }
    return [
        {
            key: value for key, value in finding.items()
            if key in allowed
        } | {"assertion_state": "evidence_observation", "poam_eligible": False}
        for finding in findings
    ]


@app.get("/api/v1/fips/assessment", tags=["FIPS 140-3 assessment"])
def fips_assessment(
    request: Request,
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
    include_findings: bool = False,
    query: str | None = None,
    poam_limit: int = Query(20, ge=1, le=250),
    poam_offset: int = Query(0, ge=0),
) -> Response:
    """Return a cached, compact assessment view; raw findings are opt-in."""
    validation = _product_fips_validation(source_collection, service_group, product_scope_id)
    assessment, revision, cache_hit = _cached_fips_assessment(
        source_collection, service_group, product_scope_id=product_scope_id
    )
    shaped = _shape_fips_assessment(
        assessment,
        include_findings=include_findings,
        query=query,
        poam_limit=poam_limit,
        poam_offset=poam_offset,
        candidate_overlays=_active_overlay_map("poam_candidate"),
    )
    if validation is not None:
        suppression = suppress_product_candidates(validation, shaped.get("poam_items", []))
        shaped["product_assessment_contract"] = validation
        shaped["poam_items"] = suppression["candidates"]
        shaped["poam_workstreams"] = [] if not suppression["exports_allowed"] else shaped.get("poam_workstreams", [])
        shaped["portfolio_poam_items"] = [] if not suppression["exports_allowed"] else shaped.get("portfolio_poam_items", [])
        shaped["poam_page"] = {"total": len(suppression["candidates"]), "limit": min(max(1, poam_limit), _max_page_size()), "offset": poam_offset}
        if not validation.get("candidate_eligible"):
            # The portfolio run and its candidate dimensions cannot be reused
            # as a product assessment while product evidence is unverified.
            shaped["assessment_run_id"] = None
            shaped["assessment_run"] = None
            shaped["assessment_run_eligibility"] = False
            shaped["poam_candidate_records"] = []
            shaped["portfolio_delivery_waves"] = []
            shaped["service_groups"] = [
                {**row, "poam_candidate_findings": 0, "finding_count": 0,
                 "needs_review_findings": 0}
                for row in shaped.get("service_groups", [])
            ]
            summary = dict(shaped.get("summary") or {})
            summary["deduplicated_poam_candidates"] = 0
            summary["candidate_gap_findings"] = 0
            summary["needs_review_findings"] = 0
            summary["proposed_remediation_workstreams"] = 0
            summary["portfolio_poam_candidates"] = 0
            shaped["summary"] = summary
            if include_findings:
                shaped["findings"] = _evidence_only_findings(
                    list(shaped.get("findings") or [])
                )
    parts = (
        source_collection,
        service_group,
        product_scope_id,
        include_findings,
        query,
        poam_limit,
        poam_offset,
        assessment.get("assessment_contract", {}).get("fingerprint"),
        validation.get("fingerprint") if validation else None,
    )
    return _conditional_json_response(
        request,
        shaped,
        namespace="fips-assessment-view",
        revision=revision,
        cache_hit=cache_hit,
        parts=parts,
    )


@app.get("/api/v1/portfolio/poam-summary", tags=["portfolio"])
def portfolio_poam_summary(request: Request) -> Response:
    """Aggregate-only candidate counts; never expose candidate or evidence detail."""
    assessment, revision, cache_hit = _cached_fips_assessment()
    contract = assessment.get("assessment_contract") if isinstance(assessment.get("assessment_contract"), dict) else {}
    payload = {
        "scope": "portfolio-summary",
        "assessment_contract": {
            "complete": bool(contract.get("complete")),
            "state": str(contract.get("state") or "not_assessable"),
        },
        "summary": _numeric_fields(assessment.get("summary")),
        "classification_counts": _numeric_fields(assessment.get("classification_counts")),
        "summary_metric_metadata": assessment.get("summary_metric_metadata") or {},
    }
    return _conditional_json_response(
        request, payload, namespace="portfolio-poam-summary", revision=revision,
        cache_hit=cache_hit, parts=(contract.get("fingerprint"),),
    )


@app.get("/api/v1/portfolio/product-scope-status", tags=["portfolio"])
def portfolio_product_scope_status(request: Request) -> dict[str, Any]:
    """Aggregate attribution coverage only; never exposes a source or service pair."""
    coverage = _fetch_one(
        """
        SELECT count(*) AS current_source_files,
               count(current_decision.id) AS attributed_source_files
        FROM source_file sf
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        LEFT JOIN LATERAL (
            SELECT eps.id, eps.product_scope_ids
            FROM app_auth.evidence_product_scope_decision eps
            WHERE eps.source_collection_id = sf.source_collection_id
              AND eps.service_group_id = sf.service_group_id
              AND eps.source_path = sf.source_path
              AND eps.source_sha256 = sf.content_sha256
            ORDER BY eps.attributed_at DESC, eps.id DESC
            LIMIT 1
        ) current_decision ON TRUE
        WHERE sf.is_present AND sf.content_sha256 IS NOT NULL
          AND sc.slug = 'sse-cboms'
        """
    ) or {}
    rows = _fetch_all(
        """
        SELECT decision_scope.product_scope_id, count(*) AS attributed_source_files
        FROM source_file sf
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN LATERAL (
            SELECT eps.product_scope_ids
            FROM app_auth.evidence_product_scope_decision eps
            WHERE eps.source_collection_id = sf.source_collection_id
              AND eps.service_group_id = sf.service_group_id
              AND eps.source_path = sf.source_path
              AND eps.source_sha256 = sf.content_sha256
            ORDER BY eps.attributed_at DESC, eps.id DESC
            LIMIT 1
        ) current_decision ON TRUE
        CROSS JOIN LATERAL unnest(current_decision.product_scope_ids) AS decision_scope(product_scope_id)
        WHERE sf.is_present AND sf.content_sha256 IS NOT NULL
          AND sc.slug = 'sse-cboms'
        GROUP BY decision_scope.product_scope_id
        ORDER BY decision_scope.product_scope_id
        """
    )
    counts = {row["product_scope_id"]: int(row["attributed_source_files"]) for row in rows}
    current_source_files = int(coverage.get("current_source_files") or 0)
    attributed_source_files = int(coverage.get("attributed_source_files") or 0)
    attribution_complete = current_source_files > 0 and attributed_source_files == current_source_files
    return {
        "state": (
            "active" if attribution_complete else "pending"
        ),
        "attribution_complete": attribution_complete,
        "current_source_files": current_source_files,
        "attributed_source_files": attributed_source_files,
        "product_scopes": [
            {
                "product_scope_id": scope_id,
                "boundary_name": boundary_name,
                "evidence_count": counts.get(scope_id, 0),
                "evidence_state": "evidence_attributed" if counts.get(scope_id, 0) else "no_source_evidence",
            }
            for scope_id, boundary_name in PRODUCT_SCOPES.items()
        ],
        "detail_evidence_enabled": _PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED,
    }


@app.get("/api/v1/fips/team-milestones", tags=["FIPS 140-3 assessment"])
def fips_team_milestones(
    source_collection: str | None = None, service_group: str | None = None,
) -> dict[str, Any]:
    """Reviewed tracker crosswalk; planning metadata only, never validation evidence."""
    payload = team_milestones(_active_target_module_contract())
    if source_collection is None or service_group is None:
        return payload
    selected = [
        row for row in payload.get("groups", [])
        if row.get("service_group") == service_group
    ]
    return {
        **payload,
        "groups": selected,
        "all_tracker_rows": [
            row for row in payload.get("all_tracker_rows", [])
            if service_group in row.get("mapped_service_groups", [])
        ],
        "scope": {"source_collection": source_collection, "service_group": service_group},
    }


@app.get("/api/v1/fips/target-modules", tags=["FIPS 140-3 assessment"])
def fips_target_modules(
    source_collection: str | None = None, service_group: str | None = None,
) -> dict[str, Any]:
    """Active checksum-addressed target-module planning import."""
    contract = _active_target_module_contract()
    if contract is None:
        return {
            "source": None,
            "teams": [],
            "groups": {},
            "disclaimer": "No target-module planning import is active.",
        }
    payload = {
        **contract,
        "disclaimer": (
            "Team status and certificate fields are user-asserted planning metadata. "
            "They do not prove a deployed module/version/environment match or FIPS validation."
        ),
    }
    if source_collection is None or service_group is None:
        return payload
    groups = payload.get("groups", {})
    selected_groups = (
        [row for row in groups if row.get("service_group") == service_group]
        if isinstance(groups, list)
        else ({service_group: groups[service_group]} if service_group in groups else {})
    )
    return {
        **payload,
        "groups": selected_groups,
        "teams": [row for row in payload.get("teams", []) if service_group in row.get("service_groups", [])],
        "scope": {"source_collection": source_collection, "service_group": service_group},
    }


@app.get("/api/v1/fips/target-modules/{record_sha256}/evidence", tags=["FIPS 140-3 assessment"])
def fips_target_module_evidence(record_sha256: str) -> dict[str, Any]:
    """Checksum-addressed claim evidence; never a deployment validation decision."""
    contract = _active_target_module_contract()
    if contract is None:
        raise HTTPException(status_code=404, detail="No active target-module import")
    for team in contract["teams"]:
        for module in team["modules"]:
            if module["record_sha256"] == record_sha256:
                return {
                    "record_sha256": record_sha256,
                    "team": team["team"],
                    "assertion": {key: module.get(key) for key in (
                        "current_module", "current_version", "target_module", "target_version",
                        "asserted_status", "current_cmvp_cert", "target_cmvp_cert",
                    )},
                    "verification": module["verification"],
                    "evidence_summary": module["evidence_summary"],
                    "evidence": module["evidence"],
                    "disclaimer": "Evidence correlations are candidate analysis and do not prove deployment applicability or FIPS validation.",
                }
    raise HTTPException(status_code=404, detail="Target-module assertion not found")


@app.get("/api/v1/fips/reporting/20x-preview", tags=["FIPS 140-3 assessment"])
def fips_20x_preview(
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
) -> dict[str, Any]:
    """Internal evaluation preview only; it is never a FedRAMP 20x submission."""
    if product_scope_id is None:
        assessment, revision, _ = _cached_fips_assessment(source_collection, service_group)
    else:
        assessment, revision = _product_export_assessment(
            source_collection, service_group, product_scope_id
        )
    return build_20x_readiness_preview(assessment, revision)


@app.get("/api/v1/fips/poam.csv", tags=["FIPS 140-3 assessment"])
def fips_poam_export(
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
) -> Response:
    """Export deduplicated draft POA&M candidates; no review decision is implied."""
    assessment, revision = _product_export_assessment(source_collection, service_group, product_scope_id)
    content = render_poam_csv(
        _apply_candidate_overlays(
            assessment["poam_items"], _active_overlay_map("poam_candidate")
        )
    )
    assessment_date = assessment["policy"]["assessment_date"]
    filename = f"fips-140-3-poam-candidates-{assessment_date}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Catalog-Revision": str(revision),
        },
    )


@app.get("/api/v1/fips/poam-workstreams.csv", tags=["FIPS 140-3 assessment"])
def fips_poam_workstream_export(
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
) -> Response:
    """Export proposed issue clusters for review, not accepted POA&M merges."""
    assessment, revision = _product_export_assessment(source_collection, service_group, product_scope_id)
    content = render_workstream_csv(assessment.get("poam_workstreams", []))
    assessment_date = assessment["policy"]["assessment_date"]
    filename = f"fips-140-3-poam-workstream-review-{assessment_date}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Catalog-Revision": str(revision),
        },
    )


@app.get("/api/v1/fips/portfolio-poam.csv", tags=["FIPS 140-3 assessment"])
def fips_portfolio_poam_export(
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
) -> Response:
    """Export the two requested portfolio candidates with scope-link evidence."""
    assessment, revision = _product_export_assessment(source_collection, service_group, product_scope_id)
    content = render_portfolio_poam_csv(assessment.get("portfolio_poam_items", []))
    assessment_date = assessment["policy"]["assessment_date"]
    filename = f"fips-140-3-portfolio-poam-candidates-{assessment_date}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Catalog-Revision": str(revision),
        },
    )


@app.get("/api/v1/fips/compliance-package.zip", tags=["FIPS 140-3 assessment"])
def fips_compliance_package_export(
    source_collection: str | None = None,
    service_group: str | None = None,
    product_scope_id: str | None = None,
) -> Response:
    """Export a checksum-manifested candidate package for compliance review."""
    assessment, revision = _product_export_assessment(source_collection, service_group, product_scope_id)
    assessment_date = assessment["policy"]["assessment_date"]
    effective_poam_items = _apply_candidate_overlays(
        assessment["poam_items"], _active_overlay_map("poam_candidate")
    )
    members: dict[str, bytes] = {
        "poam-portfolio-candidates.csv": render_portfolio_poam_csv(
            assessment.get("portfolio_poam_items", [])
        ).encode(),
        "poam-asset-candidates.csv": render_poam_csv(effective_poam_items).encode(),
        "poam-workstream-review.csv": render_workstream_csv(
            assessment.get("poam_workstreams", [])
        ).encode(),
        "assessment-summary.json": json.dumps(
            jsonable_encoder({
                "scope": assessment.get("scope"),
                "policy": assessment.get("policy"),
                "assessment_run": assessment.get("assessment_run"),
                "assessment_contract": assessment.get("assessment_contract"),
                "summary": assessment.get("summary"),
                "service_groups": assessment.get("service_groups"),
                "coverage_gaps": assessment.get("coverage_gaps"),
                "analyst_observations": assessment.get("analyst_observations"),
                "poam_candidate_records": assessment.get("poam_candidate_records"),
                "portfolio_poam_items": assessment.get("portfolio_poam_items"),
                "portfolio_delivery_waves": assessment.get("portfolio_delivery_waves"),
                "team_tracker_source": team_milestones(
                    _active_target_module_contract()
                ).get("source"),
                "disclaimer": "Machine-generated candidate analysis for authorized review; not an assessor conclusion, authorization decision, or proof of CMVP validation.",
            }),
            indent=2,
            sort_keys=True,
        ).encode(),
    }
    manifest = {
        "package_type": "FedRAMP FIPS 140-3 candidate POA&M review package",
        "assessment_date": assessment_date,
        "catalog_revision": revision,
        "scope": assessment.get("scope"),
        "candidate_only": True,
        "authorized_review_required": True,
        "assessment_run": assessment.get("assessment_run"),
        "assessment_contract": assessment.get("assessment_contract"),
        "files": {
            name: {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
            for name, payload in members.items()
        },
    }
    members["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True).encode()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in members.items():
            bundle.writestr(name, payload)
    filename = f"fips-140-3-compliance-review-{assessment_date}.zip"
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Catalog-Revision": str(revision),
        },
    )


app.mount("/ui", StaticFiles(directory=STATIC_DIRECTORY, html=True), name="ui")


@app.get("/api/v1/issues", tags=["operations"])
def issues(
    severity: str | None = None,
    code: str | None = None,
    source_collection: str | None = None,
    service_group: str | None = None,
    path_query: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if severity:
        clauses.append("ii.severity = %s")
        params.append(severity)
    if code:
        clauses.append("ii.issue_code = %s")
        params.append(code)
    if source_collection:
        clauses.append("sc.slug = %s")
        params.append(source_collection)
    if service_group:
        clauses.append("sg.slug = %s")
        params.append(service_group)
    if path_query:
        clauses.append("sf.source_path ILIKE %s")
        params.append(f"%{path_query}%")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend((min(limit, _max_page_size()), offset))
    return _fetch_all(
        f"""
        SELECT ii.id, ii.ingest_run_id, ii.document_id, ii.severity,
               ii.issue_code, ii.message, ii.context, ii.created_at,
               sf.source_path
        FROM ingest_issue ii
        LEFT JOIN source_file sf ON sf.id = ii.source_file_id
        LEFT JOIN source_collection sc ON sc.id = sf.source_collection_id
        LEFT JOIN service_group sg ON sg.id = sf.service_group_id
        {where}
        ORDER BY ii.id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )
