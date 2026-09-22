# ruff: noqa: SIM117
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import boto3
from botocore.config import Config
from psycopg.types.json import Jsonb

from .api_database import connection as api_connection
from .classify import EXCLUDED_DIRECTORY_NAMES, SUPPORTED_SUFFIXES, media_type_for
from .inventory import build_inventory
from .repository import connect, ingest_root, stats_as_dict

MANIFEST_SCHEMA_VERSION = 1
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COLLECTION_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$")
TERMINAL_STATES = frozenset({"succeeded", "failed", "expired"})
ACTIVE_STATES = frozenset({"submitting", "queued", "validating", "running"})
UPLOAD_PREFIX = "transfer/ingestion"

AWS_CLIENT_CONFIG = Config(
    retries={"total_max_attempts": 4, "mode": "adaptive"},
    connect_timeout=5,
    read_timeout=60,
    max_pool_connections=32,
    signature_version="s3v4",
)

LOGS_CLIENT_CONFIG = Config(
    retries={"total_max_attempts": 4, "mode": "adaptive"},
    connect_timeout=5,
    read_timeout=30,
)


class IngestionManifestError(ValueError):
    pass


class IngestionStateError(RuntimeError):
    pass


class IngestionConfigurationError(RuntimeError):
    pass


class IngestionValidationError(RuntimeError):
    pass


def _positive_int_setting(name: str, default: int, maximum: int) -> int:
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError as error:
        raise IngestionConfigurationError(f"{name} must be an integer") from error
    if value < 1 or value > maximum:
        raise IngestionConfigurationError(f"{name} must be between 1 and {maximum}")
    return value


def _required_setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise IngestionConfigurationError(f"{name} is required")
    return value


def _normalize_modified_at(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as error:
        raise IngestionManifestError(f"Invalid modified_at value: {value}") from error
    if parsed.tzinfo is None:
        raise IngestionManifestError("modified_at must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _normalize_relative_path(value: Any) -> str:
    path = str(value or "")
    if not path or path != path.strip() or "\\" in path or "\x00" in path:
        raise IngestionManifestError(f"Invalid relative path: {path!r}")
    pure = PurePosixPath(path)
    if pure.is_absolute() or pure.as_posix() != path or any(part in {"", ".", ".."} for part in pure.parts):
        raise IngestionManifestError(f"Path must be a normalized relative POSIX path: {path!r}")
    if any(part.startswith(".") or part in EXCLUDED_DIRECTORY_NAMES for part in pure.parts[:-1]):
        raise IngestionManifestError(f"Path contains an excluded directory: {path!r}")
    if pure.suffix.casefold() not in SUPPORTED_SUFFIXES:
        raise IngestionManifestError(f"Unsupported file type for {path!r}")
    if len(path.encode("utf-8")) > 1_024 or any(len(part.encode("utf-8")) > 255 for part in pure.parts):
        raise IngestionManifestError(f"Path is too long: {path!r}")
    return path


def normalize_manifest(
    *,
    source_collection: str,
    dry_run: bool,
    authoritative_snapshot: bool,
    files: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    collection = source_collection.strip().casefold()
    if not COLLECTION_PATTERN.fullmatch(collection):
        raise IngestionManifestError(
            "source_collection must be a lowercase slug containing only letters, digits, and hyphens"
        )
    if dry_run and authoritative_snapshot:
        raise IngestionManifestError("A dry run cannot be an authoritative snapshot")

    max_files = _positive_int_setting("CBOM_INGEST_MAX_FILES", 5_000, 100_000)
    max_file_bytes = _positive_int_setting(
        "CBOM_INGEST_MAX_FILE_BYTES", 5 * 1024 * 1024 * 1024, 5 * 1024 * 1024 * 1024
    )
    max_total_bytes = _positive_int_setting(
        "CBOM_INGEST_MAX_TOTAL_BYTES", 20 * 1024 * 1024 * 1024, 100 * 1024 * 1024 * 1024
    )
    normalized_files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    total_bytes = 0
    for raw in files:
        path = _normalize_relative_path(raw.get("path"))
        if path in seen_paths:
            raise IngestionManifestError(f"Duplicate manifest path: {path}")
        seen_paths.add(path)
        checksum = str(raw.get("sha256") or "").casefold()
        if not SHA256_PATTERN.fullmatch(checksum):
            raise IngestionManifestError(f"Invalid SHA-256 for {path}")
        try:
            size_bytes = int(raw.get("size_bytes"))
        except (TypeError, ValueError) as error:
            raise IngestionManifestError(f"Invalid size_bytes for {path}") from error
        if size_bytes < 0 or size_bytes > max_file_bytes:
            raise IngestionManifestError(f"size_bytes is outside the allowed range for {path}")
        total_bytes += size_bytes
        if total_bytes > max_total_bytes:
            raise IngestionManifestError("Manifest exceeds the configured total byte limit")
        normalized_files.append(
            {
                "path": path,
                "sha256": checksum,
                "size_bytes": size_bytes,
                "content_type": media_type_for(Path(path)),
                "modified_at": _normalize_modified_at(raw.get("modified_at")),
            }
        )

    if not normalized_files:
        raise IngestionManifestError("Manifest must contain at least one file")
    if len(normalized_files) > max_files:
        raise IngestionManifestError(f"Manifest exceeds the configured {max_files}-file limit")
    normalized_files.sort(key=lambda item: item["path"].casefold())
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source_collection": collection,
        "dry_run": bool(dry_run),
        "authoritative_snapshot": bool(authoritative_snapshot),
        "files": normalized_files,
    }


def manifest_sha256(manifest: dict[str, Any]) -> str:
    payload = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_manifest_checksum(manifest: dict[str, Any], supplied_sha256: str) -> str:
    supplied = supplied_sha256.casefold()
    if not SHA256_PATTERN.fullmatch(supplied):
        raise IngestionManifestError("manifest_sha256 must be a lowercase SHA-256 digest")
    calculated = manifest_sha256(manifest)
    if supplied != calculated:
        raise IngestionManifestError(
            f"Manifest checksum mismatch: expected {calculated}, received {supplied}"
        )
    return calculated


def _s3_client():  # type: ignore[no-untyped-def]
    return boto3.client(
        "s3",
        region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        config=AWS_CLIENT_CONFIG,
    )


def _ecs_client():  # type: ignore[no-untyped-def]
    return boto3.client(
        "ecs",
        region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        config=AWS_CLIENT_CONFIG,
    )


def _logs_client():  # type: ignore[no-untyped-def]
    return boto3.client(
        "logs",
        region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        config=LOGS_CLIENT_CONFIG,
    )


def create_ingestion_batch(
    *,
    manifest: dict[str, Any],
    supplied_manifest_sha256: str,
    request_id: str,
    actor_user_id: int | None,
    actor_credential_id: str | None,
    s3_client: Any = None,
) -> dict[str, Any]:
    calculated_manifest_sha256 = validate_manifest_checksum(manifest, supplied_manifest_sha256)
    if (actor_user_id is None) == (actor_credential_id is None):
        raise IngestionStateError("Exactly one provisioned ingestion actor is required")

    bucket = _required_setting("CBOM_INGEST_BUCKET")
    expiration_seconds = _positive_int_setting("CBOM_INGEST_URL_TTL_SECONDS", 3_600, 3_600)
    batch_id = str(uuid.uuid4())
    upload_prefix = f"{UPLOAD_PREFIX}/{batch_id}"
    expires_at = datetime.now(UTC) + timedelta(seconds=expiration_seconds)
    client = s3_client or _s3_client()
    uploads: list[dict[str, Any]] = []
    for item in manifest["files"]:
        checksum_base64 = base64.b64encode(bytes.fromhex(item["sha256"])).decode("ascii")
        object_key = f"{upload_prefix}/{item['path']}"
        params = {
            "Bucket": bucket,
            "Key": object_key,
            "ContentLength": item["size_bytes"],
            "ContentType": item["content_type"],
            "ChecksumSHA256": checksum_base64,
        }
        url = client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=expiration_seconds,
            HttpMethod="PUT",
        )
        uploads.append(
            {
                "path": item["path"],
                "method": "PUT",
                "url": url,
                "headers": {
                    "Content-Type": item["content_type"],
                    "Content-Length": str(item["size_bytes"]),
                    "x-amz-checksum-sha256": checksum_base64,
                },
            }
        )

    with api_connection() as database:
        with database.transaction():
            row = database.execute(
                """
                INSERT INTO app_auth.ingestion_batch (
                    id, source_collection, manifest_sha256, manifest_version,
                    dry_run, authoritative_snapshot, state, expected_file_count,
                    expected_total_bytes, upload_prefix, upload_expires_at,
                    created_by_user_id, created_by_credential_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'uploading', %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    batch_id,
                    manifest["source_collection"],
                    calculated_manifest_sha256,
                    manifest["schema_version"],
                    manifest["dry_run"],
                    manifest["authoritative_snapshot"],
                    len(manifest["files"]),
                    sum(item["size_bytes"] for item in manifest["files"]),
                    upload_prefix,
                    expires_at,
                    actor_user_id,
                    actor_credential_id,
                ),
            ).fetchone()
            with database.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO app_auth.ingestion_object (
                        batch_id, relative_path, object_key, sha256, size_bytes,
                        content_type, source_modified_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            batch_id,
                            item["path"],
                            f"{upload_prefix}/{item['path']}",
                            item["sha256"],
                            item["size_bytes"],
                            item["content_type"],
                            item["modified_at"],
                        )
                        for item in manifest["files"]
                    ],
                )
            database.execute(
                """
                INSERT INTO app_auth.audit_event (
                    request_id, actor_user_id, actor_credential_id, action,
                    resource_type, resource_key, after_state
                )
                VALUES (%s, %s, %s, 'ingestion.batch.create', 'ingestion_batch', %s, %s)
                """,
                (
                    request_id,
                    actor_user_id,
                    actor_credential_id,
                    batch_id,
                    Jsonb(
                        {
                            "source_collection": manifest["source_collection"],
                            "manifest_sha256": calculated_manifest_sha256,
                            "dry_run": manifest["dry_run"],
                            "authoritative_snapshot": manifest["authoritative_snapshot"],
                            "expected_file_count": len(manifest["files"]),
                            "expected_total_bytes": sum(
                                item["size_bytes"] for item in manifest["files"]
                            ),
                        }
                    ),
                ),
            )
    return {**dict(row or {}), "uploads": uploads}


def _batch_row(database: Any, batch_id: str, *, lock: bool = False) -> dict[str, Any] | None:
    suffix = " FOR UPDATE OF batch" if lock else ""
    return database.execute(
        f"""
        SELECT batch.*, app_user.email AS created_by_email,
               credential.token_prefix AS created_by_token_prefix
        FROM app_auth.ingestion_batch batch
        LEFT JOIN app_auth.app_user ON app_user.id = batch.created_by_user_id
        LEFT JOIN app_auth.api_credential credential
            ON credential.id = batch.created_by_credential_id
        WHERE batch.id = %s{suffix}
        """,
        (batch_id,),
    ).fetchone()


def get_ingestion_batch(batch_id: str, *, include_files: bool = True) -> dict[str, Any] | None:
    with api_connection() as database:
        row = _batch_row(database, batch_id)
        if row is None:
            return None
        result = dict(row)
        if include_files:
            result["files"] = list(
                database.execute(
                    """
                    SELECT relative_path AS path, sha256, size_bytes, content_type,
                           source_modified_at AS modified_at, verified_at
                    FROM app_auth.ingestion_object
                    WHERE batch_id = %s
                    ORDER BY lower(relative_path), relative_path
                    """,
                    (batch_id,),
                ).fetchall()
            )
        return result


def list_ingestion_batches(*, limit: int = 50) -> list[dict[str, Any]]:
    with api_connection() as database:
        return list(
            database.execute(
                """
                SELECT batch.*, app_user.email AS created_by_email,
                       credential.token_prefix AS created_by_token_prefix
                FROM app_auth.ingestion_batch batch
                LEFT JOIN app_auth.app_user ON app_user.id = batch.created_by_user_id
                LEFT JOIN app_auth.api_credential credential
                    ON credential.id = batch.created_by_credential_id
                ORDER BY batch.created_at DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        )


def get_ingestion_batch_logs(
    batch_id: str,
    *,
    limit: int = 200,
    logs_client: Any = None,
) -> dict[str, Any] | None:
    """Return the newest CloudWatch events for the ECS task attached to a batch."""
    batch = get_ingestion_batch(batch_id, include_files=False)
    if batch is None:
        return None

    task_arn = str(batch.get("ecs_task_arn") or "")
    log_group = os.environ.get("CBOM_INGEST_LOG_GROUP", "").strip()
    if not task_arn or not log_group:
        return {
            "available": False,
            "log_group": log_group or None,
            "log_stream": None,
            "items": [],
        }

    task_id = task_arn.rsplit("/", 1)[-1]
    stream_prefix = os.environ.get("CBOM_INGEST_LOG_STREAM_PREFIX", "job").strip() or "job"
    container_name = os.environ.get("CBOM_INGEST_CONTAINER_NAME", "job").strip() or "job"
    log_stream = f"{stream_prefix}/{container_name}/{task_id}"
    client = logs_client or _logs_client()
    try:
        response = client.get_log_events(
            logGroupName=log_group,
            logStreamName=log_stream,
            limit=limit,
            startFromHead=False,
        )
    except client.exceptions.ResourceNotFoundException:
        return {
            "available": False,
            "log_group": log_group,
            "log_stream": log_stream,
            "items": [],
        }

    return {
        "available": True,
        "log_group": log_group,
        "log_stream": log_stream,
        "items": [
            {
                "timestamp": event.get("timestamp"),
                "ingestion_time": event.get("ingestionTime"),
                "message": str(event.get("message") or ""),
            }
            for event in response.get("events", [])
        ],
    }


def submit_ingestion_batch(
    *,
    batch_id: str,
    supplied_manifest_sha256: str,
    request_id: str,
    actor_user_id: int | None,
    actor_credential_id: str | None,
    ecs_client: Any = None,
) -> dict[str, Any]:
    if not SHA256_PATTERN.fullmatch(supplied_manifest_sha256.casefold()):
        raise IngestionManifestError("manifest_sha256 must be a lowercase SHA-256 digest")

    if (actor_user_id is None) == (actor_credential_id is None):
        raise IngestionStateError("Exactly one provisioned ingestion actor is required")

    upload_expired = False
    with api_connection() as database:
        with database.transaction():
            row = _batch_row(database, batch_id, lock=True)
            if row is None:
                raise KeyError(batch_id)
            if row["manifest_sha256"] != supplied_manifest_sha256.casefold():
                raise IngestionManifestError("Submitted manifest checksum does not match the batch")
            if row["state"] != "uploading":
                if row["state"] in ACTIVE_STATES or row["state"] in TERMINAL_STATES:
                    return dict(row)
                raise IngestionStateError(f"Batch cannot be submitted from state {row['state']}")
            if row["upload_expires_at"] <= datetime.now(UTC):
                database.execute(
                    """
                    UPDATE app_auth.ingestion_batch
                    SET state = 'expired', completed_at = now(),
                        error_summary = 'Upload window expired before submission'
                    WHERE id = %s
                    """,
                    (batch_id,),
                )
                upload_expired = True
            else:
                max_active = _positive_int_setting("CBOM_INGEST_MAX_ACTIVE_JOBS", 3, 100)
                active_count = database.execute(
                    """
                    SELECT count(*) AS count
                    FROM app_auth.ingestion_batch
                    WHERE state IN ('submitting', 'queued', 'validating', 'running')
                    """
                ).fetchone()["count"]
                if int(active_count) >= max_active:
                    raise IngestionStateError("The ingestion concurrency limit has been reached")
                database.execute(
                    """
                    UPDATE app_auth.ingestion_batch
                    SET state = 'submitting', submitted_at = now(), error_summary = NULL
                    WHERE id = %s
                    """,
                    (batch_id,),
                )
                database.execute(
                    """
                    INSERT INTO app_auth.audit_event (
                        request_id, actor_user_id, actor_credential_id, action,
                        resource_type, resource_key, after_state
                    )
                    VALUES (%s, %s, %s, 'ingestion.batch.submit', 'ingestion_batch', %s, %s)
                    """,
                    (
                        request_id,
                        actor_user_id,
                        actor_credential_id,
                        batch_id,
                        Jsonb({"manifest_sha256": row["manifest_sha256"]}),
                    ),
                )

    if upload_expired:
        raise IngestionStateError("Batch upload window has expired")

    client = ecs_client or _ecs_client()
    try:
        response = client.run_task(
            cluster=_required_setting("CBOM_INGEST_ECS_CLUSTER"),
            taskDefinition=_required_setting("CBOM_INGEST_TASK_DEFINITION"),
            launchType="FARGATE",
            platformVersion="LATEST",
            count=1,
            startedBy=f"ingest-{batch_id[:8]}",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": [
                        item.strip()
                        for item in _required_setting("CBOM_INGEST_SUBNET_IDS").split(",")
                        if item.strip()
                    ],
                    "securityGroups": [
                        item.strip()
                        for item in _required_setting("CBOM_INGEST_SECURITY_GROUP_IDS").split(",")
                        if item.strip()
                    ],
                    "assignPublicIp": "DISABLED",
                }
            },
            overrides={
                "containerOverrides": [
                    {
                        "name": os.environ.get("CBOM_INGEST_CONTAINER_NAME", "job"),
                        "command": ["cbom-catalog", "run-ingestion-batch", batch_id],
                    }
                ]
            },
        )
        tasks = response.get("tasks") or []
        if not tasks:
            failures = response.get("failures") or []
            reason = "; ".join(str(item.get("reason") or "unknown failure") for item in failures)
            raise IngestionStateError(f"ECS did not start the ingestion task: {reason}")
        task_arn = str(tasks[0]["taskArn"])
    except Exception as error:
        _mark_batch_failed(batch_id, f"Unable to start ECS task: {error}")
        raise

    with api_connection() as database:
        with database.transaction():
            database.execute(
                """
                UPDATE app_auth.ingestion_batch
                SET ecs_task_arn = %s,
                    state = CASE WHEN state = 'submitting' THEN 'queued' ELSE state END
                WHERE id = %s
                """,
                (task_arn, batch_id),
            )
    return get_ingestion_batch(batch_id, include_files=False) or {}


def _mark_batch_failed(
    batch_id: str,
    message: str,
    *,
    database_url: str | None = None,
) -> None:
    summary = message[:2_000]
    with connect(database_url) as database:
        with database.transaction():
            database.execute(
                """
                UPDATE app_auth.ingestion_batch
                SET state = 'failed', error_summary = %s, completed_at = now()
                WHERE id = %s AND state NOT IN ('succeeded', 'failed', 'expired')
                """,
                (summary, batch_id),
            )


def _claim_batch(database: Any, batch_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with database.transaction():
        row = database.execute(
            "SELECT * FROM app_auth.ingestion_batch WHERE id = %s FOR UPDATE",
            (batch_id,),
        ).fetchone()
        if row is None:
            raise KeyError(batch_id)
        if row["state"] not in {"submitting", "queued"}:
            raise IngestionStateError(f"Batch cannot start from state {row['state']}")
        objects = list(
            database.execute(
                """
                SELECT relative_path, object_key, sha256, size_bytes,
                       content_type, source_modified_at
                FROM app_auth.ingestion_object
                WHERE batch_id = %s
                ORDER BY lower(relative_path), relative_path
                """,
                (batch_id,),
            ).fetchall()
        )
        if len(objects) != int(row["expected_file_count"]):
            raise IngestionValidationError("Stored object manifest is incomplete")
        database.execute(
            """
            UPDATE app_auth.ingestion_batch
            SET state = 'validating', started_at = coalesce(started_at, now()),
                verified_file_count = 0, error_summary = NULL
            WHERE id = %s
            """,
            (batch_id,),
        )
    return dict(row), objects


def _download_and_verify_object(
    client: Any,
    *,
    bucket: str,
    item: dict[str, Any],
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = client.get_object(Bucket=bucket, Key=item["object_key"], ChecksumMode="ENABLED")
    expected_checksum_base64 = base64.b64encode(bytes.fromhex(item["sha256"])).decode("ascii")
    returned_checksum = response.get("ChecksumSHA256")
    if returned_checksum and returned_checksum != expected_checksum_base64:
        response["Body"].close()
        raise IngestionValidationError(f"S3 checksum mismatch for {item['relative_path']}")
    if int(response.get("ContentLength", -1)) != int(item["size_bytes"]):
        response["Body"].close()
        raise IngestionValidationError(f"S3 size mismatch for {item['relative_path']}")

    digest = hashlib.sha256()
    bytes_written = 0
    with response["Body"] as body, destination.open("wb") as output:
        while chunk := body.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
            bytes_written += len(chunk)
    if bytes_written != int(item["size_bytes"]):
        raise IngestionValidationError(f"Downloaded size mismatch for {item['relative_path']}")
    if digest.hexdigest() != item["sha256"]:
        raise IngestionValidationError(f"Downloaded SHA-256 mismatch for {item['relative_path']}")
    if item.get("source_modified_at"):
        modified_at = item["source_modified_at"]
        if isinstance(modified_at, str):
            modified_at = datetime.fromisoformat(modified_at)
        timestamp = modified_at.timestamp()
        os.utime(destination, (timestamp, timestamp))


def _dry_run_comparison(
    database: Any,
    *,
    source_collection: str,
    objects: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = database.execute(
        """
        SELECT source.source_path, source.content_sha256
        FROM source_file source
        JOIN source_collection collection ON collection.id = source.source_collection_id
        WHERE collection.slug = %s AND source.is_present
        """,
        (source_collection,),
    ).fetchall()
    current = {str(row["source_path"]): row["content_sha256"] for row in rows}
    expected = {str(item["relative_path"]): item["sha256"] for item in objects}
    unchanged = sorted(path for path, checksum in expected.items() if current.get(path) == checksum)
    changed = sorted(path for path, checksum in expected.items() if path in current and current[path] != checksum)
    new = sorted(path for path in expected if path not in current)
    unobserved = sorted(path for path in current if path not in expected)
    return {
        "current_file_count": len(current),
        "manifest_file_count": len(expected),
        "unchanged": len(unchanged),
        "changed": len(changed),
        "new": len(new),
        "unobserved_current": len(unobserved),
        "changed_samples": changed[:20],
        "new_samples": new[:20],
        "unobserved_current_samples": unobserved[:20],
    }


def execute_ingestion_batch(
    batch_id: str,
    *,
    database_url: str | None = None,
    s3_client: Any = None,
) -> dict[str, Any]:
    claimed = False
    try:
        with connect(database_url) as database:
            batch, objects = _claim_batch(database, batch_id)
            claimed = True
            print(
                f"Ingestion batch {batch_id}: validating {len(objects)} uploaded files",
                flush=True,
            )
            bucket = _required_setting("CBOM_INGEST_BUCKET")
            client = s3_client or _s3_client()
            with tempfile.TemporaryDirectory(prefix=f"cbom-ingest-{batch_id[:8]}-") as temporary:
                root = Path(temporary)
                for index, item in enumerate(objects, start=1):
                    destination = root / item["relative_path"]
                    if not destination.resolve().is_relative_to(root.resolve()):
                        raise IngestionValidationError(
                            f"Manifest path escaped the working directory: {item['relative_path']}"
                        )
                    _download_and_verify_object(
                        client,
                        bucket=bucket,
                        item=item,
                        destination=destination,
                    )
                    with database.transaction():
                        database.execute(
                            """
                            UPDATE app_auth.ingestion_object
                            SET verified_at = now()
                            WHERE batch_id = %s AND relative_path = %s
                            """,
                            (batch_id, item["relative_path"]),
                        )
                        database.execute(
                            """
                            UPDATE app_auth.ingestion_batch
                            SET verified_file_count = %s
                            WHERE id = %s
                            """,
                            (index, batch_id),
                        )
                    if index % 50 == 0 or index == len(objects):
                        print(
                            f"Ingestion batch {batch_id}: checksum verified "
                            f"{index}/{len(objects)} files",
                            flush=True,
                        )

                inventory = build_inventory(root)
                if int(inventory["total_files"]) != int(batch["expected_file_count"]):
                    raise IngestionValidationError("Downloaded inventory file count does not match manifest")
                if int(inventory["total_bytes"]) != int(batch["expected_total_bytes"]):
                    raise IngestionValidationError("Downloaded inventory byte count does not match manifest")
                print(
                    f"Ingestion batch {batch_id}: inventory contains "
                    f"{inventory['total_files']} files and {inventory['total_bytes']} bytes",
                    flush=True,
                )

                if batch["dry_run"]:
                    comparison = _dry_run_comparison(
                        database,
                        source_collection=batch["source_collection"],
                        objects=objects,
                    )
                    result = {
                        "dry_run": True,
                        "catalog_changes_applied": False,
                        "checksum_verified_files": len(objects),
                        "inventory": {
                            "total_files": inventory["total_files"],
                            "total_bytes": inventory["total_bytes"],
                            "document_kinds": inventory["document_kinds"],
                            "issue_count": len(inventory["issues"]),
                        },
                        "comparison": comparison,
                    }
                    print(
                        f"Ingestion batch {batch_id}: dry-run comparison found "
                        f"{comparison['unchanged']} unchanged, {comparison['changed']} changed, "
                        f"{comparison['new']} new, and "
                        f"{comparison['unobserved_current']} unobserved files",
                        flush=True,
                    )
                    ingest_run_id = None
                else:
                    with database.transaction():
                        database.execute(
                            "UPDATE app_auth.ingestion_batch SET state = 'running' WHERE id = %s",
                            (batch_id,),
                        )
                    stats = ingest_root(
                        root,
                        database_url=database_url,
                        store_raw_json=False,
                        fail_on_error=True,
                        collection=batch["source_collection"],
                        source_uri=f"s3://{bucket}/{batch['upload_prefix']}",
                        authoritative_snapshot=bool(batch["authoritative_snapshot"]),
                    )
                    result = {
                        "dry_run": False,
                        "catalog_changes_applied": True,
                        "checksum_verified_files": len(objects),
                        "ingest": stats_as_dict(stats),
                    }
                    ingest_run_id = stats.run_id
                    print(
                        f"Ingestion batch {batch_id}: catalog ingest run {ingest_run_id} completed",
                        flush=True,
                    )

                with database.transaction():
                    database.execute(
                        """
                        UPDATE app_auth.ingestion_batch
                        SET state = 'succeeded', result = %s, ingest_run_id = %s,
                            completed_at = now(), error_summary = NULL
                        WHERE id = %s
                        """,
                        (Jsonb(result), ingest_run_id, batch_id),
                    )
                print(f"Ingestion batch {batch_id}: succeeded", flush=True)
                return result
    except Exception as error:
        if claimed:
            _mark_batch_failed(batch_id, str(error), database_url=database_url)
        print(
            f"Ingestion batch {batch_id}: failed with {type(error).__name__}: {str(error)[:500]}",
            flush=True,
        )
        raise


def stats_as_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, sort_keys=True)
