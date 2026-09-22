from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cbom_catalog.classify import discover_files
from cbom_catalog.ingestion_jobs import manifest_sha256, normalize_manifest


def _tls_context(ca_bundle: str | None) -> ssl.SSLContext:
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)

    defaults = ssl.get_default_verify_paths()
    if defaults.cafile and Path(defaults.cafile).is_file():
        return ssl.create_default_context()

    # The python.org macOS runtime does not automatically use the system
    # keychain. Homebrew/curl maintain a current bundle at this standard path.
    system_bundle = Path("/etc/ssl/cert.pem")
    if system_bundle.is_file():
        return ssl.create_default_context(cafile=system_bundle)
    return ssl.create_default_context()


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    stat = path.stat()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": digest.hexdigest(),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }


def _api_request(
    origin: str,
    path: str,
    token: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    tls_context: ssl.SSLContext,
) -> dict[str, Any]:
    payload = json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{origin.rstrip('/')}{path}",
        data=payload,
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60, context=tls_context) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:2_000]
        raise RuntimeError(f"API request failed with HTTP {error.code}: {detail}") from error


def _upload_file(
    upload: dict[str, Any], path: Path, tls_context: ssl.SSLContext
) -> str:
    request = urllib.request.Request(
        upload["url"],
        data=path.read_bytes(),
        method="PUT",
        headers=upload["headers"],
    )
    try:
        with urllib.request.urlopen(request, timeout=300, context=tls_context) as response:
            if response.status not in {200, 201, 204}:
                raise RuntimeError(f"Unexpected S3 response status {response.status}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:1_000]
        raise RuntimeError(f"S3 upload failed for {upload['path']}: {detail}") from error
    return str(upload["path"])


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload a checksum manifest directly to S3 and launch an asynchronous ingestion job"
    )
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--api-origin",
        default=os.environ.get("CBOM_PUBLIC_API_ORIGIN", "https://api.cbom.swg.dev-umbrellagov.com"),
    )
    parser.add_argument("--collection", default="sse-cboms")
    parser.add_argument("--token-env", default="CBOM_ADMIN_API_TOKEN")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--authoritative-snapshot", action="store_true")
    parser.add_argument("--upload-workers", type=int, default=8)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=int, default=3_600)
    parser.add_argument(
        "--ca-bundle",
        default=os.environ.get("SSL_CERT_FILE"),
        help="PEM CA bundle for API and S3 TLS verification (defaults to the system bundle)",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    token = os.environ.get(args.token_env, "")
    if not token:
        raise RuntimeError(f"Set {args.token_env} to a scoped administrator API token")
    root = args.root.resolve()
    if not root.is_dir():
        raise RuntimeError(f"Corpus root does not exist: {root}")
    tls_context = _tls_context(args.ca_bundle)

    paths = list(discover_files(root))
    records = [_file_record(root, path) for path in paths]
    manifest = normalize_manifest(
        source_collection=args.collection,
        dry_run=args.dry_run,
        authoritative_snapshot=args.authoritative_snapshot,
        files=records,
    )
    checksum = manifest_sha256(manifest)
    total_bytes = sum(int(item["size_bytes"]) for item in manifest["files"])
    print(
        f"Validated local manifest: {len(records)} files, {total_bytes} bytes, SHA-256 {checksum}"
    )

    batch = _api_request(
        args.api_origin,
        "/api/v1/admin/ingestion/batches",
        token,
        method="POST",
        body={**manifest, "manifest_sha256": checksum},
        tls_context=tls_context,
    )
    batch_id = str(batch["id"])
    path_lookup = {record["path"]: root / record["path"] for record in manifest["files"]}
    uploads = list(batch["uploads"])
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, min(args.upload_workers, 32))) as executor:
        futures = {
            executor.submit(
                _upload_file,
                upload,
                path_lookup[upload["path"]],
                tls_context,
            ): upload["path"]
            for upload in uploads
        }
        for future in as_completed(futures):
            future.result()
            completed += 1
            if completed % 25 == 0 or completed == len(uploads):
                print(f"Uploaded {completed}/{len(uploads)} files")

    _api_request(
        args.api_origin,
        f"/api/v1/admin/ingestion/batches/{batch_id}/submit",
        token,
        method="POST",
        body={"manifest_sha256": checksum},
        tls_context=tls_context,
    )
    print(f"Submitted ingestion batch {batch_id}")

    deadline = time.monotonic() + args.timeout_seconds
    last_progress: tuple[str, int] | None = None
    while time.monotonic() < deadline:
        status = _api_request(
            args.api_origin,
            f"/api/v1/admin/ingestion/batches/{batch_id}",
            token,
            tls_context=tls_context,
        )
        progress = (str(status["state"]), int(status.get("verified_file_count") or 0))
        if progress != last_progress:
            print(f"State {progress[0]}: verified {progress[1]}/{len(records)} files")
            last_progress = progress
        if status["state"] == "succeeded":
            print(json.dumps(status.get("result") or {}, indent=2, sort_keys=True))
            return 0
        if status["state"] in {"failed", "expired"}:
            raise RuntimeError(status.get("error_summary") or f"Batch ended in {status['state']}")
        time.sleep(max(1.0, args.poll_seconds))
    raise RuntimeError(f"Timed out waiting for ingestion batch {batch_id}")


def main() -> int:
    args = _arguments()
    try:
        return run(args)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
