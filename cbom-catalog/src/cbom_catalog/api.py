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
from pydantic import BaseModel, Field

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
from .service_impact import load_active_service_impacts
from .target_modules import load_active_target_modules
from .team_milestones import (
    build_portfolio_poam_items,
    enrich_poam_items,
    portfolio_delivery_waves,
    team_milestones,
)

LOGGER = logging.getLogger("cbom_catalog.access")


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


class ApiCredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=10)
    expires_in_days: int = Field(default=30, ge=1, le=90)


class OverlayCreate(BaseModel):
    resource_type: str
    resource_key: str = Field(min_length=1, max_length=240)
    payload: dict[str, Any]
    rationale: str = Field(min_length=8, max_length=2_000)


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
            if request.method in {"GET", "HEAD"} and principal.kind in {"token", "service"}:
                require_scope(principal, read_scope_for_path(request.url.path))
        except AccessDenied as error:
            return _authentication_error(request_id, error.detail, error.status_code)
        if _rate_limited(request):
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
               coalesce((SELECT max(id) FROM app_auth.admin_overlay), 0) AS overlay_revision
        """
    )
    # Keep one numeric revision for cache and ETag compatibility while ensuring
    # a planning-data import invalidates assessment and register responses.
    return (
        int((row or {}).get("ingest_revision") or 0) * 1_000_000_000_000_000_000_000_000
        + int((row or {}).get("target_revision") or 0) * 1_000_000_000_000_000_000
        + int((row or {}).get("evidence_revision") or 0) * 1_000_000_000_000
        + int((row or {}).get("service_impact_revision") or 0) * 1_000_000
        + int((row or {}).get("overlay_revision") or 0)
    )


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
    service_group: str | None,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if source_collection:
        clauses.append("sc.slug = %s")
        params.append(source_collection)
    if service_group:
        clauses.append("sg.slug = %s")
        params.append(service_group)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, tuple(params)


def _fips_scope_cte(source_collection: str | None, service_group: str | None) -> tuple[str, tuple[Any, ...]]:
    where, params = _scope_sql(source_collection, service_group)
    scoped_filters = where.replace(" WHERE ", " AND ", 1)
    return (
        f"""
        WITH scoped_source_files AS (
            SELECT sf.*, sc.slug AS collection_slug, sg.slug AS group_slug,
                   sg.display_name AS group_name
            FROM source_file sf
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
        params,
    )


def _load_fips_assessment(
    source_collection: str | None,
    service_group: str | None,
) -> dict[str, Any]:
    target_module_contract = _active_target_module_contract()
    scoped_cte, scope_params = _fips_scope_cte(source_collection, service_group)
    scope_where, inventory_params = _scope_sql(source_collection, service_group)
    service_group_inventory = _fetch_all(
        f"""
        SELECT sc.slug AS source_collection, sg.slug AS service_group,
               sg.display_name AS service_group_name,
               count(DISTINCT sf.id) AS source_files,
               count(*) FILTER (
                   WHERE sf.parse_status IN ('empty', 'invalid', 'unsupported', 'error')
               ) AS ingest_issues
        FROM service_group sg
        JOIN source_collection sc ON sc.id = sg.source_collection_id
        LEFT JOIN source_file sf ON sf.service_group_id = sg.id
            AND sf.is_present
        {scope_where}
        GROUP BY sc.id, sg.id
        ORDER BY sc.slug, sg.slug
        """,
        inventory_params,
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
            "source_collection": source_collection,
            "service_group": service_group,
        },
        service_group_inventory=service_group_inventory,
    )
    if "poam_items" in assessment:
        assessment["poam_items"] = enrich_poam_items(
            assessment["poam_items"], target_module_contract
        )
        assessment["poam_workstreams"] = build_poam_workstreams(assessment["poam_items"])
        assessment["portfolio_poam_items"] = build_portfolio_poam_items(
            assessment["poam_items"], target_module_contract
        )
        assessment["portfolio_delivery_waves"] = portfolio_delivery_waves(
            [
                str(row.get("service") or "").rsplit("/", 1)[-1]
                for row in assessment.get("service_groups", [])
                if row.get("service")
            ],
            target_module_contract,
        )
        assessment.setdefault("summary", {})["proposed_remediation_workstreams"] = len(
            assessment["poam_workstreams"]
        )
        assessment["summary"]["portfolio_poam_candidates"] = len(
            assessment["portfolio_poam_items"]
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
        require_admin(principal)
        if principal.kind == "token" and scope:
            require_scope(principal, scope)
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
) -> None:
    user_id, credential_id = _actor_columns(principal)
    database.execute(
        """
        INSERT INTO app_auth.audit_event
            (request_id, actor_user_id, actor_credential_id, action,
             resource_type, resource_key, before_state, after_state)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
        ),
    )


@app.get("/api/v1/auth/me", tags=["access control"])
def current_user(request: Request) -> dict[str, Any]:
    principal = _request_principal(request)
    return {
        "kind": principal.kind,
        "email": principal.email,
        "display_name": principal.display_name,
        "role": principal.role,
        "status": "active",
        "scopes": sorted(principal.scopes),
        "can_edit": principal.is_admin,
    }


@app.get("/api/v1/admin/users", tags=["access control"])
def admin_users(request: Request) -> dict[str, Any]:
    _admin_principal(request, "users:admin")
    rows = _fetch_all(
        """
        SELECT id, email, display_name, role, status,
               oidc_subject IS NOT NULL AS identity_bound,
               created_at, updated_at, last_login_at
        FROM app_auth.app_user
        ORDER BY lower(email)
        """
    )
    return {"items": rows, "total": len(rows)}


@app.patch("/api/v1/admin/users/{user_id}", tags=["access control"])
def update_admin_user(user_id: int, body: UserAccessUpdate, request: Request) -> dict[str, Any]:
    principal = _admin_principal(request, "users:admin")
    if body.role is not None and body.role not in {"viewer", "admin"}:
        raise HTTPException(status_code=422, detail="Unsupported role")
    if body.status is not None and body.status not in {"invited", "active", "disabled"}:
        raise HTTPException(status_code=422, detail="Unsupported status")
    if principal.user_id == user_id and (
        (body.role is not None and body.role != "admin")
        or (body.status is not None and body.status != "active")
    ):
        raise HTTPException(status_code=409, detail="Administrators cannot remove their own access")
    with api_connection() as database:
        before = database.execute(
            "SELECT id, email, display_name, role, status FROM app_auth.app_user WHERE id = %s FOR UPDATE",
            (user_id,),
        ).fetchone()
        if before is None:
            raise HTTPException(status_code=404, detail="User not found")
        after = database.execute(
            """
            UPDATE app_auth.app_user
            SET role = coalesce(%s, role), status = coalesce(%s, status), updated_at = now()
            WHERE id = %s
            RETURNING id, email, display_name, role, status, updated_at
            """,
            (body.role, body.status, user_id),
        ).fetchone()
        _audit_event(
            database, request, principal, action="user.access.update",
            resource_type="app_user", resource_key=str(user_id),
            before_state=dict(before), after_state=dict(after or {}),
        )
        database.commit()
    return dict(after or {})


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
) -> dict[str, Any]:
    """Return a provenance-scoped dashboard summary without client-side overfetching."""
    where, scope_params = _scope_sql(source_collection, service_group)
    scoped_cte = f"""
        WITH scoped_service_groups AS (
            SELECT sg.*
            FROM service_group sg
            JOIN source_collection sc ON sc.id = sg.source_collection_id
            {where}
        ),
        scoped_source_files AS (
            SELECT sf.*
            FROM source_file sf
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
        scope_params,
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
        scope_params,
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
        scope_params,
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
        scope_params,
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
        scope_params,
    )
    return {
        "scope": {
            "source_collection": source_collection,
            "service_group": service_group,
        },
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
) -> Response:
    parts = (source_collection, service_group)
    data, revision, cache_hit = _cached_catalog_value(
        "dashboard-overview",
        parts,
        lambda: _build_dashboard_overview(source_collection, service_group),
    )
    return _conditional_json_response(
        request,
        data,
        namespace="dashboard-overview",
        revision=revision,
        cache_hit=cache_hit,
        parts=parts,
    )


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
                "coverage_gap_states": sorted(coverage_by_service.get(service_key, [])),
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
    assessment, revision, _ = _cached_fips_assessment(None, None)
    overview, _, _ = _cached_catalog_value(
        "dashboard-overview", (None, None), lambda: _build_dashboard_overview(None, None)
    )
    all_rows = _service_group_register_rows(
        assessment,
        overview,
        team_milestones(_active_target_module_contract()),
        _active_service_impact_map(),
    )
    group_overlays = _active_overlay_map("service_group")
    for row in all_rows:
        overlay = group_overlays.get(str(row.get("service_key"))) or group_overlays.get(
            str(row.get("service_key") or "").rsplit("/", 1)[-1]
        )
        if not overlay:
            continue
        patch = overlay.get("payload") or {}
        if "effective_owners" in patch:
            row["effective_owners"] = list(patch["effective_owners"] or [])
        if "leads" in patch:
            row["leads"] = list(patch["leads"] or [])
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
        "disclaimer": "Team Tracker owners and IL2/IL5 values and imported service-impact fields are user-asserted planning metadata. Findings and POA&M mappings are machine-generated candidates requiring authorized review.",
    }
    parts = (query, owner, lead, il2_state, il5_state, action, sort, direction, page_size, offset)
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
    path_query: str | None = None,
    checksum: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
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
    return _fetch_all(
        f"""
        SELECT *
        FROM v_source_fingerprint_status
        {where}
        ORDER BY source_collection, source_path
        LIMIT %s OFFSET %s
        """,
        tuple(params),
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
    kind: str | None = None,
    spec_version: str | None = None,
    path_query: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    rows, _ = _document_inventory_rows(
        source_collection=source_collection,
        service_group=service_group,
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
        clauses.append(
            "EXISTS (SELECT 1 FROM source_file sf "
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
    kind: str | None,
    spec_version: str | None,
    path_query: str | None,
    limit: int,
    offset: int,
    sort: str,
    direction: str,
    include_total: bool,
) -> tuple[list[dict[str, Any]], int | None]:
    where, filter_params = _document_inventory_filters(
        source_collection=source_collection,
        service_group=service_group,
        kind=kind,
        spec_version=spec_version,
        path_query=path_query,
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
        WITH page AS MATERIALIZED (
            SELECT inventory.*
            FROM v_document_inventory inventory
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
        (*filter_params, page_size, offset),
    )
    total: int | None = None
    if include_total:
        count_row = _fetch_one(
            f"SELECT count(*) AS total FROM v_document_inventory inventory {where}",
            tuple(filter_params),
        )
        total = int((count_row or {}).get("total") or 0)
    return rows, total


@app.get("/api/v1/inventory/documents", tags=["inventory"])
def paged_documents(
    source_collection: str | None = None,
    service_group: str | None = None,
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


@app.get("/api/v1/documents/{document_id}", tags=["documents"])
def document_detail(document_id: int, include_raw: bool = False) -> dict[str, Any]:
    if include_raw and not _env_bool("CBOM_API_ALLOW_RAW"):
        raise HTTPException(status_code=403, detail="Raw document responses are disabled")
    raw_column = ", d.raw_document" if include_raw else ""
    row = _fetch_one(
        f"""
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
        WHERE d.id = %s
        """,
        (document_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    row["source_files"] = _fetch_all(
        """
        SELECT sc.slug AS source_collection, sf.source_path, sf.source_uri,
               sf.parse_status, sf.byte_size, sg.slug AS service_group
        FROM source_file sf
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        WHERE sf.document_id = %s
        ORDER BY sf.source_path
        """,
        (document_id,),
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
    query: str | None = None,
    crypto_only: bool = False,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    if not _fetch_one("SELECT id FROM document WHERE id = %s", (document_id,)):
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
    params.extend((min(limit, _max_page_size()), offset))
    return _fetch_all(
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


@app.get("/api/v1/components", tags=["components"])
def components(
    query: str | None = None,
    purl: str | None = None,
    component_type: str | None = None,
    crypto_only: bool = False,
    source_collection: str | None = None,
    service_group: str | None = None,
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
    limit: int,
    offset: int,
    sort: str,
    direction: str,
    include_total: bool,
) -> tuple[list[dict[str, Any]], int | None]:
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
        JOIN source_file sf ON sf.document_id = dc.document_id
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        {where}
        GROUP BY c.id
        ORDER BY {order_column} {order_direction} NULLS LAST, c.name, c.version
        LIMIT %s OFFSET %s
        """,
        (*filter_params, page_size, offset),
    )
    total: int | None = None
    if include_total:
        count_row = _fetch_one(
            f"""
            SELECT count(DISTINCT c.id) AS total
            FROM component c
            JOIN document_component dc ON dc.component_id = c.id
            JOIN source_file sf ON sf.document_id = dc.document_id
            JOIN source_collection sc ON sc.id = sf.source_collection_id
            JOIN service_group sg ON sg.id = sf.service_group_id
            {where}
            """,
            tuple(filter_params),
        )
        total = int((count_row or {}).get("total") or 0)
    return rows, total


@app.get("/api/v1/inventory/libraries", tags=["inventory"])
def paged_crypto_libraries(
    source_collection: str | None = None,
    service_group: str | None = None,
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
    document_limit: int = Query(50, ge=1, le=250),
    document_offset: int = Query(0, ge=0),
    library_limit: int = Query(50, ge=1, le=250),
    library_offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Evidence and candidate-action detail for one provenance-scoped group."""
    assessment, _, _ = _cached_fips_assessment(source_collection, service_group)
    overview, _, _ = _cached_catalog_value(
        "dashboard-overview",
        (source_collection, service_group),
        lambda: _build_dashboard_overview(source_collection, service_group),
    )
    milestone_contract = team_milestones(_active_target_module_contract())
    register_rows = _service_group_register_rows(
        assessment,
        overview,
        milestone_contract,
        _active_service_impact_map(),
    )
    if not register_rows:
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
        limit=library_limit,
        offset=library_offset,
        sort="document_count",
        direction="desc",
        include_total=True,
    )
    poam_by_finding: dict[str, list[str]] = defaultdict(list)
    for item in assessment.get("poam_items", []):
        for finding_id in item.get("linked_finding_ids", []):
            candidate_id = item.get("poam_candidate_id")
            if candidate_id:
                poam_by_finding[finding_id].append(candidate_id)
    findings = [
        {**finding, "poam_candidate_ids": sorted(poam_by_finding.get(finding.get("finding_id"), []))}
        for finding in assessment.get("findings", [])
    ]
    return {
        "profile": register_rows[0],
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
            "assessment_run_id": assessment.get("assessment_run_id"),
            "policy": assessment.get("policy"),
            "summary": assessment.get("summary"),
            "coverage_gaps": assessment.get("coverage_gaps", []),
            "findings": findings,
            "poam_items": assessment.get("poam_items", []),
            "poam_workstreams": assessment.get("poam_workstreams", []),
            "portfolio_poam_items": assessment.get("portfolio_poam_items", []),
            "portfolio_delivery_waves": assessment.get("portfolio_delivery_waves", []),
            "limitations": assessment.get("limitations", []),
            "disclaimer": assessment.get("disclaimer"),
        },
        "candidate_only": True,
    }


@app.get("/api/v1/components/{component_id}/usage", tags=["components"])
def component_usage(
    component_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    component = _fetch_one("SELECT id FROM component WHERE id = %s", (component_id,))
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    return _fetch_all(
        """
        SELECT dc.id AS occurrence_id, dc.bom_ref, dc.source_bom_ref,
               dc.scope, dc.is_subject,
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
        JOIN source_file sf ON sf.document_id = d.id
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        WHERE dc.component_id = %s AND sf.is_present
        GROUP BY dc.id, d.id
        ORDER BY d.id
        LIMIT %s OFFSET %s
        """,
        (component_id, limit, offset),
    )


@app.get("/api/v1/artifacts", tags=["artifacts"])
def artifacts(
    query: str | None = None,
    digest: str | None = None,
    source_collection: str | None = None,
    service_group: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
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
        JOIN source_file sf ON sf.document_id = da.document_id
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        {where}
        GROUP BY a.id
        ORDER BY document_count DESC, a.name
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )


@app.get("/api/v1/dependency-documents", tags=["dependencies"])
def dependency_documents(
    source_collection: str | None = None,
    service_group: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
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
        WITH edge_stats AS (
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
        JOIN source_file sf ON sf.document_id = d.id
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
        tuple(params),
    )


@app.get("/api/v1/documents/{document_id}/dependency-graph", tags=["dependencies"])
def dependency_graph(
    document_id: int,
    relationship_type: list[str] = Query(default=["DEPENDS_ON"]),
    node_limit: int = Query(80, ge=2, le=200),
    edge_limit: int = Query(240, ge=1, le=1000),
) -> dict[str, Any]:
    allowed_types = sorted(
        {item.strip().upper() for item in relationship_type if item.strip()}
    )
    if not allowed_types:
        raise HTTPException(status_code=400, detail="At least one relationship_type is required")
    document = _fetch_one(
        """
        SELECT d.id AS document_id, d.document_kind, d.format_name, d.spec_version,
               d.serial_number,
               array_agg(DISTINCT sf.source_path ORDER BY sf.source_path) AS source_paths
        FROM document d
        LEFT JOIN source_file sf ON sf.document_id = d.id AND sf.is_present
        WHERE d.id = %s
        GROUP BY d.id
        """,
        (document_id,),
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
    max_depth: int = Query(10, ge=1, le=50),
    limit: int = Query(500, ge=1, le=2_000),
    relationship_type: list[str] = Query(default=["DEPENDS_ON"]),
) -> list[dict[str, Any]]:
    allowed_types = [item.strip().upper() for item in relationship_type if item.strip()]
    if not allowed_types:
        raise HTTPException(status_code=400, detail="At least one relationship_type is required")
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
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
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
        JOIN source_file sf ON sf.document_id = er.document_id
        JOIN source_collection sc ON sc.id = sf.source_collection_id
        JOIN service_group sg ON sg.id = sf.service_group_id
        {where}
        GROUP BY er.id, a.id, parent.id
        ORDER BY er.id
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )


def _cached_fips_assessment(
    source_collection: str | None = None,
    service_group: str | None = None,
) -> tuple[dict[str, Any], int, bool]:
    data, revision, cache_hit = _cached_catalog_value(
        "fips-assessment",
        (source_collection, service_group),
        lambda: _load_fips_assessment(source_collection, service_group),
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
    candidate_overlays = candidate_overlays or {}
    candidates = []
    for source in assessment.get("poam_items", []):
        item = dict(source)
        overlay = candidate_overlays.get(str(item.get("poam_candidate_id") or ""))
        if overlay:
            item.update(overlay.get("payload") or {})
            item["admin_overlay"] = overlay
        candidates.append(item)
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


@app.get("/api/v1/fips/assessment", tags=["FIPS 140-3 assessment"])
def fips_assessment(
    request: Request,
    source_collection: str | None = None,
    service_group: str | None = None,
    include_findings: bool = False,
    query: str | None = None,
    poam_limit: int = Query(20, ge=1, le=250),
    poam_offset: int = Query(0, ge=0),
) -> Response:
    """Return a cached, compact assessment view; raw findings are opt-in."""
    assessment, revision, cache_hit = _cached_fips_assessment(
        source_collection,
        service_group,
    )
    shaped = _shape_fips_assessment(
        assessment,
        include_findings=include_findings,
        query=query,
        poam_limit=poam_limit,
        poam_offset=poam_offset,
        candidate_overlays=_active_overlay_map("poam_candidate"),
    )
    parts = (
        source_collection,
        service_group,
        include_findings,
        query,
        poam_limit,
        poam_offset,
    )
    return _conditional_json_response(
        request,
        shaped,
        namespace="fips-assessment-view",
        revision=revision,
        cache_hit=cache_hit,
        parts=parts,
    )


@app.get("/api/v1/fips/team-milestones", tags=["FIPS 140-3 assessment"])
def fips_team_milestones() -> dict[str, Any]:
    """Reviewed tracker crosswalk; planning metadata only, never validation evidence."""
    return team_milestones(_active_target_module_contract())


@app.get("/api/v1/fips/target-modules", tags=["FIPS 140-3 assessment"])
def fips_target_modules() -> dict[str, Any]:
    """Active checksum-addressed target-module planning import."""
    contract = _active_target_module_contract()
    if contract is None:
        return {
            "source": None,
            "teams": [],
            "groups": {},
            "disclaimer": "No target-module planning import is active.",
        }
    return {
        **contract,
        "disclaimer": (
            "Team status and certificate fields are user-asserted planning metadata. "
            "They do not prove a deployed module/version/environment match or FIPS validation."
        ),
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


@app.get("/api/v1/fips/poam.csv", tags=["FIPS 140-3 assessment"])
def fips_poam_export(
    source_collection: str | None = None,
    service_group: str | None = None,
) -> Response:
    """Export deduplicated draft POA&M candidates; no review decision is implied."""
    assessment, revision, _ = _cached_fips_assessment(source_collection, service_group)
    content = render_poam_csv(assessment["poam_items"])
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
) -> Response:
    """Export proposed issue clusters for review, not accepted POA&M merges."""
    assessment, revision, _ = _cached_fips_assessment(source_collection, service_group)
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
) -> Response:
    """Export the two requested portfolio candidates with scope-link evidence."""
    assessment, revision, _ = _cached_fips_assessment(source_collection, service_group)
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
) -> Response:
    """Export a checksum-manifested candidate package for compliance review."""
    assessment, revision, _ = _cached_fips_assessment(source_collection, service_group)
    assessment_date = assessment["policy"]["assessment_date"]
    members: dict[str, bytes] = {
        "poam-portfolio-candidates.csv": render_portfolio_poam_csv(
            assessment.get("portfolio_poam_items", [])
        ).encode(),
        "poam-asset-candidates.csv": render_poam_csv(assessment["poam_items"]).encode(),
        "poam-workstream-review.csv": render_workstream_csv(
            assessment.get("poam_workstreams", [])
        ).encode(),
        "assessment-summary.json": json.dumps(
            jsonable_encoder({
                "scope": assessment.get("scope"),
                "policy": assessment.get("policy"),
                "summary": assessment.get("summary"),
                "service_groups": assessment.get("service_groups"),
                "coverage_gaps": assessment.get("coverage_gaps"),
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
