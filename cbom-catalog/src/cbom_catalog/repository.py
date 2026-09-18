from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import __version__
from .classify import EXCLUDED_DIRECTORY_NAMES, discover_files, media_type_for
from .parser import iter_licenses, parse_path, property_namespace, property_value
from .records import ArtifactRecord, EmptyDocumentError, ParsedDocument


FINGERPRINT_ALGORITHM = "sha256"

SERVICE_GROUP_ALIASES: dict[str, tuple[str, str]] = {
    "apix": ("apix-no-cbom", "APIX"),
    "zta-clap": ("zta-calp", "ZTA-CALP"),
    "zta-calp": ("zta-calp", "ZTA-CALP"),
    "resource-discovery": ("discovery", "Discovery"),
    "discovery": ("discovery", "Discovery"),
    "frup-microapps": ("avengers", "Avengers"),
    "frup-microapps-dapi": ("avengers", "Avengers"),
    "avengers": ("avengers", "Avengers"),
    "scc": ("scc-backend", "SCC-Backend"),
    "scc-backend": ("scc-backend", "SCC-Backend"),
    "pac": ("pac-cbom", "PAC-cbom"),
    "taac": ("taac-cbom", "TAAC-cbom"),
    "app-control": ("app-control", "App-Control"),
    "fis-sma-threatgrid": ("fis-sma-threatgrid", "FIS/SMA Threatgrid"),
}

# Coverage categories that must survive even when the current corpus has no
# directory for them.  This is intentionally collection-scoped: these names are
# part of the approved SSE inventory contract, not global defaults for every
# catalog someone may ingest with this tool.
RETAINED_EMPTY_SERVICE_GROUPS_BY_COLLECTION: dict[str, tuple[str, ...]] = {
    "sse-cboms": (
        "ANDROID-NO_CBOM",
        "IOS-NO_CBOM",
        "RSM-SECURE_CLIENT-NO_CBOM",
        "SWG-ROAMING-CLIENT-NO_CBOM",
    ),
}


@dataclass(slots=True)
class IngestStats:
    run_id: int
    files_seen: int = 0
    files_loaded: int = 0
    files_linked: int = 0
    files_unchanged: int = 0
    files_failed: int = 0
    files_empty: int = 0


def connect(database_url: str | None = None) -> psycopg.Connection[Any]:
    url = database_url or os.environ.get("DATABASE_URL")
    if url:
        return psycopg.connect(url, row_factory=dict_row)
    if os.environ.get("PGHOST"):
        return psycopg.connect(
            host=os.environ.get("PGHOST"),
            port=os.environ.get("PGPORT", "5432"),
            dbname=os.environ.get("PGDATABASE"),
            user=os.environ.get("PGUSER"),
            password=os.environ.get("PGPASSWORD"),
            row_factory=dict_row,
        )
    raise ValueError("DATABASE_URL or PostgreSQL PG* environment variables are required")


def apply_schema(database_url: str | None = None, schema_path: Path | None = None) -> None:
    path = schema_path or Path(__file__).resolve().parents[2] / "db"
    migrations = [path] if path.is_file() else sorted(path.glob("[0-9][0-9][0-9]_*.sql"))
    if not migrations:
        raise FileNotFoundError(f"No SQL migrations found at {path}")
    connection = connect(database_url)
    connection.autocommit = True
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migration (
                version text PRIMARY KEY,
                description text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        has_catalog_meta = connection.execute(
            "SELECT to_regclass('public.catalog_meta') AS relation"
        ).fetchone()["relation"]
        if has_catalog_meta:
            legacy = connection.execute(
                "SELECT value FROM catalog_meta WHERE key = 'schema_version'"
            ).fetchone()
            if legacy and legacy["value"] == "1":
                connection.execute(
                    """
                    INSERT INTO schema_migration(version, description)
                    VALUES ('001', 'initial catalog schema (legacy installation)')
                    ON CONFLICT (version) DO NOTHING
                    """
                )
        for migration in migrations:
            version = migration.name.split("_", 1)[0]
            applied = connection.execute(
                "SELECT 1 FROM schema_migration WHERE version = %s", (version,)
            ).fetchone()
            if not applied:
                connection.execute(migration.read_text(encoding="utf-8"))
    finally:
        connection.close()


def ingest_root(
    root: Path,
    *,
    database_url: str | None = None,
    store_raw_json: bool = True,
    include_location_properties: bool = False,
    fail_on_error: bool = False,
    limit: int | None = None,
    collection: str | None = None,
    source_uri: str | None = None,
    force_reprocess: bool = False,
    authoritative_snapshot: bool = False,
) -> IngestStats:
    root = root.resolve()
    if not store_raw_json and not source_uri:
        raise ValueError("--source-uri is required when raw JSON storage is disabled")
    collection_slug = _slug(collection or root.name)
    collection_name = collection or root.name
    source_base_uri = source_uri or root.as_uri()
    paths = list(discover_files(root))
    if authoritative_snapshot and limit is not None:
        raise ValueError("--authoritative-snapshot cannot be combined with --limit")
    if limit is not None:
        paths = paths[:limit]
    with connect(database_url) as connection:
        with connection.transaction():
            collection_id = _upsert_source_collection(
                connection,
                slug=collection_slug,
                display_name=collection_name,
                root_uri=source_base_uri,
            )
            run_id = connection.execute(
                """
                INSERT INTO ingest_run (
                    source_collection_id, root_path, parser_version,
                    fingerprint_algorithm, force_reprocess
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    collection_id,
                    str(root),
                    __version__,
                    FINGERPRINT_ALGORITHM,
                    force_reprocess,
                ),
            ).fetchone()["id"]
            for directory in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
                if (
                    directory.is_dir()
                    and directory.name not in EXCLUDED_DIRECTORY_NAMES
                    and not directory.name.startswith(".")
                ):
                    _upsert_service_group(connection, collection_id, directory.name)
            for retained_name in RETAINED_EMPTY_SERVICE_GROUPS_BY_COLLECTION.get(
                collection_slug, ()
            ):
                _upsert_service_group(connection, collection_id, retained_name)
        stats = IngestStats(run_id=run_id)

        for path in paths:
            stats.files_seen += 1
            try:
                outcome = _ingest_one(
                    connection,
                    run_id,
                    collection_id,
                    source_base_uri,
                    root,
                    path,
                    store_raw_json=store_raw_json,
                    include_location_properties=include_location_properties,
                    force_reprocess=force_reprocess,
                )
                if outcome == "loaded":
                    stats.files_loaded += 1
                elif outcome == "linked":
                    stats.files_linked += 1
                elif outcome == "unchanged":
                    stats.files_unchanged += 1
                elif outcome == "empty":
                    stats.files_empty += 1
                    stats.files_failed += 1
            except Exception as exc:  # keep the corpus run moving; the issue is persisted
                stats.files_failed += 1
                _record_failed_file(
                    connection,
                    run_id,
                    collection_id,
                    source_base_uri,
                    root,
                    path,
                    exc,
                )
                if fail_on_error:
                    _finish_run(connection, stats, status="failed")
                    raise

        if authoritative_snapshot and not stats.files_failed:
            with connection.transaction():
                connection.execute(
                    """
                    UPDATE source_file
                    SET is_present = false, absent_since_run_id = %s, updated_at = now()
                    WHERE source_collection_id = %s
                      AND is_present
                      AND last_seen_run_id <> %s
                    """,
                    (run_id, collection_id, run_id),
                )
        status = "completed_with_errors" if stats.files_failed else "completed"
        _finish_run(connection, stats, status=status)
        return stats


def _read_stable_file(path: Path) -> tuple[bytes, os.stat_result, str]:
    """Read and hash one stable snapshot, retrying once if the file changes mid-read."""
    for _attempt in range(2):
        before = path.stat()
        content = path.read_bytes()
        after = path.stat()
        before_signature = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        after_signature = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if before_signature == after_signature and len(content) == after.st_size:
            return content, after, hashlib.sha256(content).hexdigest()
    raise RuntimeError(f"File changed while it was being fingerprinted: {path}")


def _ingest_one(
    connection: psycopg.Connection[Any],
    run_id: int,
    collection_id: int,
    source_base_uri: str,
    root: Path,
    path: Path,
    *,
    store_raw_json: bool,
    include_location_properties: bool,
    force_reprocess: bool,
) -> str:
    content, stat, digest = _read_stable_file(path)
    relative = path.relative_to(root)
    service_name = relative.parts[0] if len(relative.parts) > 1 else "(root)"
    resolved_source_uri = _join_source_uri(source_base_uri, relative)
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

    if not force_reprocess:
        with connection.transaction():
            existing_source = connection.execute(
                """
                SELECT sf.id, sf.document_id, sf.content_sha256,
                       sf.fingerprint_algorithm, d.sha256 AS document_sha256
                FROM source_file sf
                LEFT JOIN document d ON d.id = sf.document_id
                WHERE sf.source_collection_id = %s AND sf.source_path = %s
                FOR UPDATE OF sf
                """,
                (collection_id, relative.as_posix()),
            ).fetchone()
            if (
                existing_source
                and existing_source["fingerprint_algorithm"] == FINGERPRINT_ALGORITHM
                and existing_source["content_sha256"] == digest
            ):
                document_id = existing_source["document_id"]
                document_checksum = existing_source["document_sha256"]
                if document_id is None or document_checksum == digest:
                    _mark_source_unchanged(
                        connection,
                        source_file_id=existing_source["id"],
                        run_id=run_id,
                        source_uri=resolved_source_uri,
                        filename=path.name,
                        media_type=media_type_for(path),
                        byte_size=len(content),
                        checksum=digest,
                        modified_at=modified_at,
                    )
                    return "unchanged"
                _insert_issue(
                    connection,
                    run_id,
                    existing_source["id"],
                    document_id,
                    "warning",
                    "fingerprint_document_mismatch",
                    "Source checksum matched but its linked document checksum did not; reprocessing",
                    {
                        "source_checksum": digest,
                        "document_checksum": document_checksum,
                    },
                )

    if not content.strip():
        with connection.transaction():
            group_id = _upsert_service_group(connection, collection_id, service_name)
            source_id = _upsert_source_file(
                connection,
                source_collection_id=collection_id,
                service_group_id=group_id,
                document_id=None,
                run_id=run_id,
                source_path=relative.as_posix(),
                source_uri=resolved_source_uri,
                filename=path.name,
                media_type=media_type_for(path),
                byte_size=len(content),
                content_sha256=digest,
                modified_at=modified_at,
                status="empty",
                message="File is empty",
            )
            _insert_issue(
                connection,
                run_id,
                source_id,
                None,
                "warning",
                "empty_file",
                "File is empty and was not parsed",
                {},
            )
        return "empty"

    with connection.transaction():
        existing = connection.execute(
            "SELECT id FROM document WHERE sha256 = %s", (digest,)
        ).fetchone()
        group_id = _upsert_service_group(connection, collection_id, service_name)
        if existing and not force_reprocess:
            _upsert_source_file(
                connection,
                source_collection_id=collection_id,
                service_group_id=group_id,
                document_id=existing["id"],
                run_id=run_id,
                source_path=relative.as_posix(),
                source_uri=resolved_source_uri,
                filename=path.name,
                media_type=media_type_for(path),
                byte_size=len(content),
                content_sha256=digest,
                modified_at=modified_at,
                status="linked",
                message="Exact content already cataloged",
            )
            return "linked"

    parsed = parse_path(path, content)
    with connection.transaction():
        group_id = _upsert_service_group(connection, collection_id, service_name)
        document_id, inserted = _insert_document(
            connection,
            parsed,
            digest=digest,
            byte_size=len(content),
            store_raw_json=store_raw_json,
        )
        source_id = _upsert_source_file(
            connection,
            source_collection_id=collection_id,
            service_group_id=group_id,
            document_id=document_id,
            run_id=run_id,
            source_path=relative.as_posix(),
            source_uri=resolved_source_uri,
            filename=path.name,
            media_type=media_type_for(path),
            byte_size=len(content),
            content_sha256=digest,
            modified_at=modified_at,
            status="loaded" if inserted else "linked",
            message=(
                None
                if inserted
                else (
                    "Parser validation passed; exact content already cataloged"
                    if force_reprocess
                    else "Exact content cataloged by a concurrent worker"
                )
            ),
        )
        if not inserted:
            return "linked"
        artifact_ids = _insert_artifacts(connection, document_id, parsed.artifacts)
        occurrence_ids = _insert_components(
            connection,
            document_id,
            parsed,
            include_location_properties=include_location_properties,
        )
        _insert_document_properties(connection, document_id, parsed)
        _insert_dependencies(connection, document_id, parsed, occurrence_ids)
        _insert_vulnerabilities(connection, document_id, parsed)
        _insert_spdx_files(connection, document_id, parsed)
        _insert_external_records(connection, document_id, parsed, artifact_ids)
        for warning in parsed.warnings:
            _insert_issue(
                connection,
                run_id,
                source_id,
                document_id,
                "warning",
                str(warning.get("code") or "parser_warning"),
                str(warning.get("message") or warning.get("code") or "Parser warning"),
                warning,
            )
    return "loaded"


def _insert_document(
    connection: psycopg.Connection[Any],
    parsed: ParsedDocument,
    *,
    digest: str,
    byte_size: int,
    store_raw_json: bool,
) -> tuple[int, bool]:
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (digest,))
    row = connection.execute(
        """
        WITH inserted AS (
            INSERT INTO document (
                sha256, byte_size, document_kind, format_name, spec_version,
                serial_number, document_version, generated_at_text, generator,
                metadata, raw_document, parser_version, warnings
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (sha256) DO NOTHING
            RETURNING id
        )
        SELECT id, true AS inserted FROM inserted
        UNION ALL
        SELECT id, false AS inserted FROM document WHERE sha256 = %s
        LIMIT 1
        """,
        (
            digest,
            byte_size,
            parsed.document_kind,
            parsed.format_name,
            parsed.spec_version,
            parsed.serial_number,
            parsed.document_version,
            parsed.generated_at_text,
            Jsonb(parsed.generator),
            Jsonb(parsed.metadata),
            Jsonb(parsed.raw) if store_raw_json else None,
            __version__,
            Jsonb(parsed.warnings),
            digest,
        ),
    ).fetchone()
    if not row:
        raise RuntimeError(f"Unable to insert or resolve document {digest}")
    return row["id"], row["inserted"]


def _insert_artifacts(
    connection: psycopg.Connection[Any],
    document_id: int,
    artifacts: list[ArtifactRecord],
) -> dict[str, int]:
    artifact_ids: dict[str, int] = {}
    for artifact in artifacts:
        row = connection.execute(
            """
            INSERT INTO artifact (
                canonical_key, artifact_type, name, version, purl, cpe,
                registry, repository, tag, digest, extra
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (canonical_key) DO UPDATE SET
                artifact_type = coalesce(artifact.artifact_type, EXCLUDED.artifact_type),
                name = coalesce(artifact.name, EXCLUDED.name),
                version = coalesce(artifact.version, EXCLUDED.version),
                purl = coalesce(artifact.purl, EXCLUDED.purl),
                cpe = coalesce(artifact.cpe, EXCLUDED.cpe),
                registry = coalesce(artifact.registry, EXCLUDED.registry),
                repository = coalesce(artifact.repository, EXCLUDED.repository),
                tag = coalesce(artifact.tag, EXCLUDED.tag),
                digest = coalesce(artifact.digest, EXCLUDED.digest),
                extra = artifact.extra || EXCLUDED.extra,
                updated_at = now()
            RETURNING id
            """,
            (
                artifact.canonical_key,
                artifact.artifact_type,
                artifact.name,
                artifact.version,
                artifact.purl,
                artifact.cpe,
                artifact.registry,
                artifact.repository,
                artifact.tag,
                artifact.digest,
                Jsonb(artifact.extra),
            ),
        ).fetchone()
        artifact_id = row["id"]
        artifact_ids[artifact.canonical_key] = artifact_id
        connection.execute(
            """
            INSERT INTO document_artifact (document_id, artifact_id, role, confidence, evidence)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (document_id, artifact_id, role) DO UPDATE SET
                confidence = EXCLUDED.confidence,
                evidence = EXCLUDED.evidence
            """,
            (
                document_id,
                artifact_id,
                artifact.role,
                artifact.confidence,
                Jsonb(artifact.evidence),
            ),
        )
    return artifact_ids


def _insert_components(
    connection: psycopg.Connection[Any],
    document_id: int,
    parsed: ParsedDocument,
    *,
    include_location_properties: bool,
) -> dict[str, int]:
    if not parsed.components:
        return {}

    components_by_hash = {component.identity_hash: component for component in parsed.components}
    component_rows = [
        (
            component.identity_hash,
            component.purl,
            component.cpe,
            component.component_type,
            component.namespace,
            component.name,
            component.version,
            component.publisher,
            component.supplier,
            component.description,
        )
        for component in components_by_hash.values()
    ]
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO component (
                identity_hash, canonical_purl, cpe, component_type, namespace,
                name, version, publisher, supplier, description
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (identity_hash) DO UPDATE SET
                canonical_purl = coalesce(component.canonical_purl, EXCLUDED.canonical_purl),
                cpe = coalesce(component.cpe, EXCLUDED.cpe),
                component_type = coalesce(component.component_type, EXCLUDED.component_type),
                namespace = coalesce(component.namespace, EXCLUDED.namespace),
                name = coalesce(component.name, EXCLUDED.name),
                version = coalesce(component.version, EXCLUDED.version),
                publisher = coalesce(component.publisher, EXCLUDED.publisher),
                supplier = coalesce(component.supplier, EXCLUDED.supplier),
                description = coalesce(component.description, EXCLUDED.description),
                updated_at = now()
            """,
            component_rows,
        )
    component_ids = {
        row["identity_hash"].strip(): row["id"]
        for row in connection.execute(
            "SELECT id, identity_hash FROM component WHERE identity_hash::text = ANY(%s)",
            (list(components_by_hash),),
        ).fetchall()
    }
    occurrence_rows = [
        (
            document_id,
            component_ids[component.identity_hash],
            component.bom_ref,
            component.source_bom_ref,
            component.scope,
            component.is_subject,
            Jsonb(component.hashes),
            Jsonb(component.licenses),
            Jsonb(component.external_references),
            Jsonb(component.properties),
            Jsonb(component.crypto_properties) if component.crypto_properties is not None else None,
            Jsonb(component.evidence) if component.evidence is not None else None,
            Jsonb(component.raw_extra),
        )
        for component in parsed.components
    ]
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO document_component (
                document_id, component_id, bom_ref, source_bom_ref, scope, is_subject,
                hashes, licenses, external_references, properties,
                crypto_properties, evidence, raw_extra
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (document_id, bom_ref) DO UPDATE SET
                component_id = EXCLUDED.component_id,
                source_bom_ref = EXCLUDED.source_bom_ref,
                scope = EXCLUDED.scope,
                is_subject = EXCLUDED.is_subject,
                hashes = EXCLUDED.hashes,
                licenses = EXCLUDED.licenses,
                external_references = EXCLUDED.external_references,
                properties = EXCLUDED.properties,
                crypto_properties = EXCLUDED.crypto_properties,
                evidence = EXCLUDED.evidence,
                raw_extra = EXCLUDED.raw_extra
            """,
            occurrence_rows,
        )
    occurrence_rows_from_db = connection.execute(
        "SELECT id, bom_ref, source_bom_ref FROM document_component WHERE document_id = %s",
        (document_id,),
    ).fetchall()
    occurrence_ids_by_key = {
        row["bom_ref"]: row["id"]
        for row in occurrence_rows_from_db
    }
    source_ref_counts = Counter(component.source_bom_ref for component in parsed.components)
    occurrence_ids = {
        row["source_bom_ref"]: row["id"]
        for row in occurrence_rows_from_db
        if source_ref_counts[row["source_bom_ref"]] == 1
    }

    property_rows: list[tuple[Any, ...]] = []
    license_rows: list[tuple[Any, ...]] = []
    for component in parsed.components:
        occurrence_id = occurrence_ids_by_key[component.bom_ref]
        for ordinal, prop in enumerate(component.properties):
            name = str(prop.get("name") or "")
            if not name:
                continue
            if not include_location_properties and name.startswith("syft:location:"):
                continue
            property_rows.append(
                (
                    occurrence_id,
                    ordinal,
                    name,
                    property_value(prop.get("value")),
                    property_namespace(name),
                )
            )
        for ordinal, license_values in enumerate(iter_licenses(component.licenses)):
            license_id, license_name, expression, acknowledgement, raw = license_values
            license_rows.append(
                (
                    occurrence_id,
                    ordinal,
                    license_id,
                    license_name,
                    expression,
                    acknowledgement,
                    Jsonb(raw),
                )
            )
    with connection.cursor() as cursor:
        if property_rows:
            cursor.executemany(
                """
                INSERT INTO component_property (
                    occurrence_id, ordinal, property_name, property_value, property_namespace
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (occurrence_id, ordinal) DO UPDATE SET
                    property_name = EXCLUDED.property_name,
                    property_value = EXCLUDED.property_value,
                    property_namespace = EXCLUDED.property_namespace
                """,
                property_rows,
            )
        if license_rows:
            cursor.executemany(
                """
                INSERT INTO component_license (
                    occurrence_id, ordinal, license_id, license_name,
                    expression, acknowledgement, raw_license
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (occurrence_id, ordinal) DO UPDATE SET
                    license_id = EXCLUDED.license_id,
                    license_name = EXCLUDED.license_name,
                    expression = EXCLUDED.expression,
                    acknowledgement = EXCLUDED.acknowledgement,
                    raw_license = EXCLUDED.raw_license
                """,
                license_rows,
            )
    return occurrence_ids


def _insert_document_properties(
    connection: psycopg.Connection[Any], document_id: int, parsed: ParsedDocument
) -> None:
    scope_ordinals: dict[str, int] = {}
    for scope, prop in parsed.document_properties:
        ordinal = scope_ordinals.get(scope, 0)
        scope_ordinals[scope] = ordinal + 1
        name = str(prop.get("name") or "")
        if not name:
            continue
        connection.execute(
            """
            INSERT INTO document_property (
                document_id, ordinal, property_scope, property_name,
                property_value, property_namespace
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (document_id, property_scope, ordinal) DO UPDATE SET
                property_name = EXCLUDED.property_name,
                property_value = EXCLUDED.property_value,
                property_namespace = EXCLUDED.property_namespace
            """,
            (
                document_id,
                ordinal,
                scope,
                name,
                property_value(prop.get("value")),
                property_namespace(name),
            ),
        )


def _insert_dependencies(
    connection: psycopg.Connection[Any],
    document_id: int,
    parsed: ParsedDocument,
    occurrence_ids: dict[str, int],
) -> None:
    rows: list[tuple[Any, ...]] = []
    for dependency in parsed.dependencies:
        from_id = occurrence_ids.get(dependency.from_ref)
        to_id = occurrence_ids.get(dependency.to_ref)
        if (
            dependency.from_ref in parsed.ambiguous_refs
            or dependency.to_ref in parsed.ambiguous_refs
        ):
            resolution_status = "ambiguous"
            from_id = None if dependency.from_ref in parsed.ambiguous_refs else from_id
            to_id = None if dependency.to_ref in parsed.ambiguous_refs else to_id
        elif from_id is not None and to_id is not None:
            resolution_status = "resolved"
        elif from_id is None and to_id is None:
            resolution_status = "external"
        else:
            resolution_status = "partial"
        raw_edge = dict(dependency.raw)
        raw_edge["catalog:resolution-status"] = resolution_status
        rows.append(
            (
                document_id,
                from_id,
                to_id,
                dependency.from_ref,
                dependency.to_ref,
                dependency.relationship_type,
                resolution_status,
                Jsonb(raw_edge),
            )
        )
    if rows:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO dependency_edge (
                    document_id, from_occurrence_id, to_occurrence_id,
                    from_ref, to_ref, relationship_type, resolution_status, raw_edge
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id, from_ref, to_ref, relationship_type) DO UPDATE SET
                    from_occurrence_id = EXCLUDED.from_occurrence_id,
                    to_occurrence_id = EXCLUDED.to_occurrence_id,
                    resolution_status = EXCLUDED.resolution_status,
                    raw_edge = EXCLUDED.raw_edge
                """,
                rows,
            )


def _insert_vulnerabilities(
    connection: psycopg.Connection[Any], document_id: int, parsed: ParsedDocument
) -> None:
    for item in parsed.vulnerabilities:
        vulnerability_id = connection.execute(
            """
            INSERT INTO vulnerability (source_name, vulnerability_id, source_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (source_name, vulnerability_id) DO UPDATE SET
                source_url = coalesce(vulnerability.source_url, EXCLUDED.source_url)
            RETURNING id
            """,
            (item.source_name, item.vulnerability_id, item.source_url),
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO document_vulnerability (
                document_id, vulnerability_id, ratings, analysis, description,
                detail, advisories, properties, raw_vulnerability
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (document_id, vulnerability_id) DO UPDATE SET
                ratings = EXCLUDED.ratings,
                analysis = EXCLUDED.analysis,
                description = EXCLUDED.description,
                detail = EXCLUDED.detail,
                advisories = EXCLUDED.advisories,
                properties = EXCLUDED.properties,
                raw_vulnerability = EXCLUDED.raw_vulnerability
            """,
            (
                document_id,
                vulnerability_id,
                Jsonb(item.ratings),
                Jsonb(item.analysis) if item.analysis is not None else None,
                item.description,
                item.detail,
                Jsonb(item.advisories),
                Jsonb(item.properties),
                Jsonb(item.raw),
            ),
        )
        for affected in item.affects:
            affected_ref = str(affected.get("ref") or "")
            if not affected_ref:
                continue
            connection.execute(
                """
                INSERT INTO vulnerability_affect (
                    document_id, vulnerability_id, affected_ref, versions
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (document_id, vulnerability_id, affected_ref) DO UPDATE SET
                    versions = EXCLUDED.versions
                """,
                (
                    document_id,
                    vulnerability_id,
                    affected_ref,
                    Jsonb(affected.get("versions") or []),
                ),
            )


def _insert_spdx_files(
    connection: psycopg.Connection[Any], document_id: int, parsed: ParsedDocument
) -> None:
    rows = [
        (
            document_id,
            item.spdx_id,
            item.file_name,
            Jsonb(item.checksums),
            item.license_concluded,
            Jsonb(item.license_info_in_file),
            item.copyright_text,
            Jsonb(item.raw),
        )
        for item in parsed.spdx_files
    ]
    if rows:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO spdx_file (
                    document_id, spdx_id, file_name, checksums, license_concluded,
                    license_info_in_file, copyright_text, raw_file
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id, spdx_id) DO UPDATE SET
                    file_name = EXCLUDED.file_name,
                    checksums = EXCLUDED.checksums,
                    license_concluded = EXCLUDED.license_concluded,
                    license_info_in_file = EXCLUDED.license_info_in_file,
                    copyright_text = EXCLUDED.copyright_text,
                    raw_file = EXCLUDED.raw_file
                """,
                rows,
            )


def _insert_external_records(
    connection: psycopg.Connection[Any],
    document_id: int,
    parsed: ParsedDocument,
    artifact_ids: dict[str, int],
) -> None:
    record_ids: dict[tuple[str, str], int] = {}
    for item in parsed.external_records:
        payload = json.dumps(
            item.data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        parent_record_id = None
        if item.parent_record_type and item.parent_external_id:
            parent_record_id = record_ids.get(
                (item.parent_record_type, item.parent_external_id)
            )
        row = connection.execute(
            """
            INSERT INTO external_record (
                document_id, artifact_id, parent_record_id, record_type, external_id,
                observed_at_text, provider, payload_sha256, data
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (document_id, record_type, external_id, payload_sha256)
            DO UPDATE SET
                artifact_id = coalesce(EXCLUDED.artifact_id, external_record.artifact_id),
                parent_record_id = coalesce(
                    EXCLUDED.parent_record_id, external_record.parent_record_id
                )
            RETURNING id
            """,
            (
                document_id,
                artifact_ids.get(item.artifact_key) if item.artifact_key else None,
                parent_record_id,
                item.record_type,
                item.external_id,
                item.observed_at_text,
                item.provider,
                payload_sha256,
                Jsonb(item.data),
            ),
        ).fetchone()
        record_ids[(item.record_type, item.external_id)] = row["id"]


def _record_failed_file(
    connection: psycopg.Connection[Any],
    run_id: int,
    collection_id: int,
    source_base_uri: str,
    root: Path,
    path: Path,
    exc: Exception,
) -> None:
    try:
        content, stat, digest = _read_stable_file(path)
        size = len(content)
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    except (OSError, RuntimeError):
        digest = None
        size = 0
        modified_at = None
    relative = path.relative_to(root)
    service_name = relative.parts[0] if len(relative.parts) > 1 else "(root)"
    status = "empty" if isinstance(exc, EmptyDocumentError) else "invalid"
    with connection.transaction():
        existing = connection.execute(
            """
            SELECT id, document_id, content_sha256
            FROM source_file
            WHERE source_collection_id = %s AND source_path = %s
            FOR UPDATE
            """,
            (collection_id, relative.as_posix()),
        ).fetchone()
        if digest is None and existing:
            connection.execute(
                """
                UPDATE source_file
                SET last_seen_run_id = %s,
                    source_uri = %s,
                    parse_status = %s,
                    parse_message = %s,
                    is_present = true,
                    absent_since_run_id = NULL,
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    run_id,
                    _join_source_uri(source_base_uri, relative),
                    status,
                    str(exc),
                    existing["id"],
                ),
            )
            _insert_issue(
                connection,
                run_id,
                existing["id"],
                existing["document_id"],
                "error" if status == "invalid" else "warning",
                "parse_error" if status == "invalid" else "empty_file",
                str(exc),
                {"exception_type": type(exc).__name__},
            )
            return
        group_id = _upsert_service_group(connection, collection_id, service_name)
        preserved_document_id = (
            existing["document_id"]
            if existing and existing["content_sha256"] == digest
            else None
        )
        source_id = _upsert_source_file(
            connection,
            source_collection_id=collection_id,
            service_group_id=group_id,
            document_id=preserved_document_id,
            run_id=run_id,
            source_path=relative.as_posix(),
            source_uri=_join_source_uri(source_base_uri, relative),
            filename=path.name,
            media_type=media_type_for(path),
            byte_size=size,
            content_sha256=digest,
            modified_at=modified_at,
            status=status,
            message=str(exc),
        )
        _insert_issue(
            connection,
            run_id,
            source_id,
            preserved_document_id,
            "error" if status == "invalid" else "warning",
            "parse_error" if status == "invalid" else "empty_file",
            str(exc),
            {"exception_type": type(exc).__name__},
        )


def _upsert_service_group(
    connection: psycopg.Connection[Any], collection_id: int, name: str
) -> int:
    source_name = name
    slug = _slug(name)
    slug, name = SERVICE_GROUP_ALIASES.get(slug, (slug, name))
    return connection.execute(
        """
        INSERT INTO service_group (source_collection_id, slug, display_name, source_path)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (source_collection_id, slug) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            source_path = EXCLUDED.source_path
        RETURNING id
        """,
        (collection_id, slug, name, source_name),
    ).fetchone()["id"]


def _upsert_source_collection(
    connection: psycopg.Connection[Any], *, slug: str, display_name: str, root_uri: str
) -> int:
    return connection.execute(
        """
        INSERT INTO source_collection (slug, display_name, root_uri)
        VALUES (%s, %s, %s)
        ON CONFLICT (slug) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            root_uri = EXCLUDED.root_uri,
            updated_at = now()
        RETURNING id
        """,
        (slug, display_name, root_uri),
    ).fetchone()["id"]


def _upsert_source_file(
    connection: psycopg.Connection[Any],
    *,
    source_collection_id: int,
    service_group_id: int,
    document_id: int | None,
    run_id: int,
    source_path: str,
    source_uri: str,
    filename: str,
    media_type: str,
    byte_size: int,
    content_sha256: str | None,
    modified_at: datetime | None,
    status: str,
    message: str | None,
) -> int:
    source_file_id = connection.execute(
        """
        INSERT INTO source_file (
            source_collection_id, service_group_id, document_id, last_seen_run_id,
            source_path, source_uri, filename, media_type, byte_size, content_sha256, modified_at,
            fingerprint_algorithm, fingerprinted_at, parse_status, parse_message,
            is_present, absent_since_run_id
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, CASE WHEN %s::text IS NULL THEN NULL ELSE now() END, %s, %s,
            true, NULL
        )
        ON CONFLICT (source_collection_id, source_path) DO UPDATE SET
            service_group_id = EXCLUDED.service_group_id,
            document_id = EXCLUDED.document_id,
            last_seen_run_id = EXCLUDED.last_seen_run_id,
            source_uri = EXCLUDED.source_uri,
            filename = EXCLUDED.filename,
            media_type = EXCLUDED.media_type,
            byte_size = EXCLUDED.byte_size,
            content_sha256 = EXCLUDED.content_sha256,
            modified_at = EXCLUDED.modified_at,
            fingerprint_algorithm = EXCLUDED.fingerprint_algorithm,
            fingerprinted_at = EXCLUDED.fingerprinted_at,
            parse_status = EXCLUDED.parse_status,
            parse_message = EXCLUDED.parse_message,
            is_present = true,
            absent_since_run_id = NULL,
            updated_at = now()
        RETURNING id
        """,
        (
            source_collection_id,
            service_group_id,
            document_id,
            run_id,
            source_path,
            source_uri,
            filename,
            media_type,
            byte_size,
            content_sha256,
            modified_at,
            FINGERPRINT_ALGORITHM,
            content_sha256,
            status,
            message,
        ),
    ).fetchone()["id"]
    if content_sha256 is not None:
        _record_source_fingerprint(
            connection,
            source_file_id=source_file_id,
            run_id=run_id,
            checksum=content_sha256,
            byte_size=byte_size,
        )
    return source_file_id


def _mark_source_unchanged(
    connection: psycopg.Connection[Any],
    *,
    source_file_id: int,
    run_id: int,
    source_uri: str,
    filename: str,
    media_type: str,
    byte_size: int,
    checksum: str,
    modified_at: datetime,
) -> None:
    connection.execute(
        """
        UPDATE source_file
        SET last_seen_run_id = %s,
            source_uri = %s,
            filename = %s,
            media_type = %s,
            byte_size = %s,
            content_sha256 = %s,
            modified_at = %s,
            fingerprint_algorithm = %s,
            fingerprinted_at = now(),
            is_present = true,
            absent_since_run_id = NULL,
            updated_at = now()
        WHERE id = %s
        """,
        (
            run_id,
            source_uri,
            filename,
            media_type,
            byte_size,
            checksum,
            modified_at,
            FINGERPRINT_ALGORITHM,
            source_file_id,
        ),
    )
    _record_source_fingerprint(
        connection,
        source_file_id=source_file_id,
        run_id=run_id,
        checksum=checksum,
        byte_size=byte_size,
    )


def _record_source_fingerprint(
    connection: psycopg.Connection[Any],
    *,
    source_file_id: int,
    run_id: int,
    checksum: str,
    byte_size: int,
) -> None:
    connection.execute(
        """
        INSERT INTO source_file_fingerprint (
            source_file_id, algorithm, checksum, byte_size,
            first_seen_run_id, last_seen_run_id
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_file_id, algorithm, checksum) DO UPDATE SET
            byte_size = EXCLUDED.byte_size,
            last_seen_run_id = EXCLUDED.last_seen_run_id,
            last_seen_at = now(),
            observation_count = source_file_fingerprint.observation_count + 1
        """,
        (
            source_file_id,
            FINGERPRINT_ALGORITHM,
            checksum,
            byte_size,
            run_id,
            run_id,
        ),
    )


def _insert_issue(
    connection: psycopg.Connection[Any],
    run_id: int,
    source_file_id: int | None,
    document_id: int | None,
    severity: str,
    code: str,
    message: str,
    context: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO ingest_issue (
            ingest_run_id, source_file_id, document_id,
            severity, issue_code, message, context
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (run_id, source_file_id, document_id, severity, code, message, Jsonb(context)),
    )


def _finish_run(
    connection: psycopg.Connection[Any], stats: IngestStats, *, status: str
) -> None:
    with connection.transaction():
        connection.execute(
            """
            UPDATE ingest_run
            SET status = %s,
                files_seen = %s,
                files_loaded = %s,
                files_linked = %s,
                files_unchanged = %s,
                files_failed = %s,
                completed_at = now()
            WHERE id = %s
            """,
            (
                status,
                stats.files_seen,
                stats.files_loaded,
                stats.files_linked,
                stats.files_unchanged,
                stats.files_failed,
                stats.run_id,
            ),
        )


def stats_as_dict(stats: IngestStats) -> dict[str, int]:
    return asdict(stats)


def _slug(value: str) -> str:
    lowered = value.strip().casefold()
    slug = "".join(character if character.isalnum() else "-" for character in lowered)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "root"


def _join_source_uri(base_uri: str, relative: Path) -> str:
    encoded_path = quote(relative.as_posix(), safe="/@:+")
    return f"{base_uri.rstrip('/')}/{encoded_path}"
