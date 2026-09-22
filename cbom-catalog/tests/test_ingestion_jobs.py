from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self

import pytest

from cbom_catalog import ingestion_jobs
from cbom_catalog.ingestion_jobs import (
    IngestionManifestError,
    IngestionValidationError,
    _download_and_verify_object,
    _dry_run_comparison,
    create_ingestion_batch,
    get_ingestion_batch_logs,
    manifest_sha256,
    normalize_manifest,
    validate_manifest_checksum,
)


def _manifest_files() -> list[dict[str, object]]:
    return [
        {
            "path": "Zeta/b.json",
            "sha256": "b" * 64,
            "size_bytes": 7,
            "modified_at": "2026-09-18T12:00:00+00:00",
        },
        {
            "path": "Alpha/a.csv",
            "sha256": "a" * 64,
            "size_bytes": 3,
            "modified_at": None,
        },
    ]


def test_manifest_is_canonical_and_checksum_gated() -> None:
    manifest = normalize_manifest(
        source_collection="sse-cboms",
        dry_run=True,
        authoritative_snapshot=False,
        files=reversed(_manifest_files()),
    )
    assert [item["path"] for item in manifest["files"]] == ["Alpha/a.csv", "Zeta/b.json"]
    assert manifest["files"][1]["modified_at"] == "2026-09-18T12:00:00Z"
    digest = manifest_sha256(manifest)
    assert validate_manifest_checksum(manifest, digest) == digest
    with pytest.raises(IngestionManifestError, match="Manifest checksum mismatch"):
        validate_manifest_checksum(manifest, "0" * 64)


@pytest.mark.parametrize(
    "path",
    ["../secret.json", "/absolute.json", "group\\file.json", "group/./file.json", "group/file.txt"],
)
def test_manifest_rejects_unsafe_or_unsupported_paths(path: str) -> None:
    with pytest.raises(IngestionManifestError):
        normalize_manifest(
            source_collection="sse-cboms",
            dry_run=True,
            authoritative_snapshot=False,
            files=[{"path": path, "sha256": "a" * 64, "size_bytes": 1}],
        )


def test_dry_run_cannot_be_authoritative() -> None:
    with pytest.raises(IngestionManifestError, match="cannot be an authoritative"):
        normalize_manifest(
            source_collection="sse-cboms",
            dry_run=True,
            authoritative_snapshot=True,
            files=_manifest_files(),
        )


class _S3Body(io.BytesIO):
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class _S3Client:
    def __init__(self, content: bytes, *, returned_checksum: str | None = None):
        self.content = content
        self.returned_checksum = returned_checksum

    def get_object(self, **_kwargs: object) -> dict[str, object]:
        response: dict[str, object] = {
            "Body": _S3Body(self.content),
            "ContentLength": len(self.content),
        }
        if self.returned_checksum:
            response["ChecksumSHA256"] = self.returned_checksum
        return response


def test_download_verifies_s3_and_locally_computed_checksums() -> None:
    content = b'{"bomFormat":"CycloneDX"}'
    checksum = hashlib.sha256(content).hexdigest()
    returned = base64.b64encode(bytes.fromhex(checksum)).decode("ascii")
    item = {
        "relative_path": "team/cbom.json",
        "object_key": "transfer/ingestion/test/team/cbom.json",
        "sha256": checksum,
        "size_bytes": len(content),
        "source_modified_at": None,
    }
    with TemporaryDirectory() as temporary:
        destination = Path(temporary) / "team/cbom.json"
        _download_and_verify_object(
            _S3Client(content, returned_checksum=returned),
            bucket="bucket",
            item=item,
            destination=destination,
        )
        assert destination.read_bytes() == content


def test_download_rejects_checksum_mismatch() -> None:
    content = b"actual"
    item = {
        "relative_path": "team/cbom.json",
        "object_key": "transfer/ingestion/test/team/cbom.json",
        "sha256": hashlib.sha256(b"expected").hexdigest(),
        "size_bytes": len(content),
        "source_modified_at": None,
    }
    with TemporaryDirectory() as temporary, pytest.raises(
        IngestionValidationError, match="Downloaded SHA-256 mismatch"
    ):
        _download_and_verify_object(
            _S3Client(content),
            bucket="bucket",
            item=item,
            destination=Path(temporary) / "team/cbom.json",
        )


class _Rows:
    def __init__(self, rows: list[dict[str, object]]):
        self.rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows

    def fetchone(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None


class _Context:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _CreateCursor(_Context):
    def __init__(self) -> None:
        self.rows: list[tuple[object, ...]] = []

    def executemany(self, _query: str, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows


class _CreateDatabase(_Context):
    def __init__(self) -> None:
        self.batch_cursor = _CreateCursor()

    def transaction(self) -> _Context:
        return _Context()

    def cursor(self) -> _CreateCursor:
        return self.batch_cursor

    def execute(self, query: str, _params: tuple[object, ...]) -> _Rows:
        if "RETURNING *" in query:
            return _Rows([{"id": "test-batch", "state": "uploading"}])
        return _Rows([])


class _PresigningS3Client:
    def __init__(self) -> None:
        self.params: list[dict[str, object]] = []

    def generate_presigned_url(self, _operation: str, **kwargs: object) -> str:
        self.params.append(kwargs)
        return f"https://uploads.invalid/{len(self.params)}"


def test_create_batch_uses_cursor_for_bulk_object_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _CreateDatabase()
    s3 = _PresigningS3Client()
    monkeypatch.setattr(ingestion_jobs, "api_connection", lambda: database)
    monkeypatch.setenv("CBOM_INGEST_BUCKET", "private-ingestion-bucket")
    manifest = normalize_manifest(
        source_collection="sse-cboms",
        dry_run=True,
        authoritative_snapshot=False,
        files=_manifest_files(),
    )

    batch = create_ingestion_batch(
        manifest=manifest,
        supplied_manifest_sha256=manifest_sha256(manifest),
        request_id="request-1",
        actor_user_id=None,
        actor_credential_id="00000000-0000-0000-0000-000000000001",
        s3_client=s3,
    )

    assert batch["state"] == "uploading"
    assert len(batch["uploads"]) == 2
    assert len(database.batch_cursor.rows) == 2
    assert len(s3.params) == 2


class _ComparisonDatabase:
    def execute(self, _query: str, _params: tuple[object, ...]) -> _Rows:
        return _Rows(
            [
                {"source_path": "team/a.json", "content_sha256": "a" * 64},
                {"source_path": "team/old.json", "content_sha256": "c" * 64},
            ]
        )


def test_dry_run_comparison_reports_without_writes() -> None:
    comparison = _dry_run_comparison(
        _ComparisonDatabase(),
        source_collection="sse-cboms",
        objects=[
            {"relative_path": "team/a.json", "sha256": "a" * 64},
            {"relative_path": "team/new.json", "sha256": "b" * 64},
        ],
    )
    assert comparison == {
        "current_file_count": 2,
        "manifest_file_count": 2,
        "unchanged": 1,
        "changed": 0,
        "new": 1,
        "unobserved_current": 1,
        "changed_samples": [],
        "new_samples": ["team/new.json"],
        "unobserved_current_samples": ["team/old.json"],
    }


class _MissingLogStream(Exception):
    pass


class _LogsClient:
    class exceptions:
        ResourceNotFoundException = _MissingLogStream

    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing
        self.request: dict[str, object] = {}

    def get_log_events(self, **kwargs: object) -> dict[str, object]:
        self.request = kwargs
        if self.missing:
            raise _MissingLogStream
        return {
            "events": [
                {"timestamp": 1_700_000_000_000, "ingestionTime": 1_700_000_000_100,
                 "message": "validated"}
            ]
        }


def test_batch_logs_are_scoped_to_the_batch_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingestion_jobs,
        "get_ingestion_batch",
        lambda *_args, **_kwargs: {
            "ecs_task_arn": "arn:aws:ecs:us-east-1:123:task/cluster/task-123"
        },
    )
    monkeypatch.setenv("CBOM_INGEST_LOG_GROUP", "/cbom-workbench/dev/jobs")
    client = _LogsClient()

    result = get_ingestion_batch_logs("batch-1", limit=25, logs_client=client)

    assert result is not None
    assert result["available"] is True
    assert result["items"][0]["message"] == "validated"
    assert client.request == {
        "logGroupName": "/cbom-workbench/dev/jobs",
        "logStreamName": "job/job/task-123",
        "limit": 25,
        "startFromHead": False,
    }


def test_batch_logs_are_pending_before_the_stream_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingestion_jobs,
        "get_ingestion_batch",
        lambda *_args, **_kwargs: {"ecs_task_arn": None},
    )
    monkeypatch.setenv("CBOM_INGEST_LOG_GROUP", "/cbom-workbench/dev/jobs")

    result = get_ingestion_batch_logs("batch-1", logs_client=_LogsClient(missing=True))

    assert result is not None
    assert result["available"] is False
    assert result["items"] == []
