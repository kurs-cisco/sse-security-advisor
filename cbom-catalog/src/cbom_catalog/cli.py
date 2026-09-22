from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .inventory import build_inventory


def main() -> None:
    parser = argparse.ArgumentParser(prog="cbom-catalog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory_parser = subparsers.add_parser(
        "inventory", help="Classify a corpus without writing to a database"
    )
    inventory_parser.add_argument("root", type=Path)
    inventory_parser.add_argument("--limit", type=int)
    inventory_parser.add_argument("--pretty", action="store_true")

    migrate_parser = subparsers.add_parser("migrate", help="Apply the PostgreSQL schema")
    migrate_parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    migrate_parser.add_argument("--schema", type=Path, help="Migration file or directory")

    ingest_parser = subparsers.add_parser("ingest", help="Ingest or relink corpus files")
    ingest_parser.add_argument("root", type=Path)
    ingest_parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ingest_parser.add_argument("--limit", type=int)
    ingest_parser.add_argument("--no-raw-json", action="store_true")
    ingest_parser.add_argument("--include-location-properties", action="store_true")
    ingest_parser.add_argument("--fail-on-error", action="store_true")
    ingest_parser.add_argument(
        "--force-reprocess",
        action="store_true",
        default=_env_bool("CBOM_FORCE_REPROCESS", False),
        help="Run parser validation on unchanged files; existing normalized documents stay immutable",
    )
    ingest_parser.add_argument(
        "--authoritative-snapshot",
        action="store_true",
        default=_env_bool("CBOM_AUTHORITATIVE_SNAPSHOT", False),
        help="Mark collection paths missing from a successful full refresh as historical",
    )
    ingest_parser.add_argument(
        "--collection",
        default=os.environ.get("CBOM_SOURCE_COLLECTION"),
        help="Stable logical source collection name (defaults to root folder name)",
    )
    ingest_parser.add_argument(
        "--source-uri",
        default=os.environ.get("CBOM_SOURCE_URI") or None,
        help="Stable base URI such as s3://bucket/prefix; required with --no-raw-json",
    )

    target_parser = subparsers.add_parser(
        "import-target-modules",
        help="Import checksum-gated per-team target-module planning data",
    )
    target_parser.add_argument("path", type=Path)
    target_parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))

    evidence_parser = subparsers.add_parser(
        "import-target-evidence",
        help="Import checksum-gated public and catalog evidence for target-module claims",
    )
    evidence_parser.add_argument("path", type=Path)
    evidence_parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))

    catalog_evidence_parser = subparsers.add_parser(
        "import-catalog-claim-evidence",
        help="Import checksum-gated CBOM current-version correlation evidence",
    )
    catalog_evidence_parser.add_argument("path", type=Path)
    catalog_evidence_parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))

    service_impact_parser = subparsers.add_parser(
        "import-service-impact",
        help="Import checksum-gated team POA&M impact, risk category, and comments",
    )
    service_impact_parser.add_argument("path", type=Path)
    service_impact_parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    service_impact_parser.add_argument(
        "--collection",
        default=os.environ.get("CBOM_SOURCE_COLLECTION", "sse-cboms"),
        help="Source collection whose service groups inherit the team planning rows",
    )

    args = parser.parse_args()
    if args.command == "inventory":
        result = build_inventory(args.root, limit=args.limit)
        print(json.dumps(result, indent=2 if args.pretty else None, ensure_ascii=False))
        return
    if args.command == "migrate":
        from .repository import apply_schema

        apply_schema(args.database_url, args.schema)
        print("Schema applied")
        return
    if args.command == "ingest":
        from .repository import ingest_root, stats_as_dict

        store_raw = not args.no_raw_json and _env_bool("CBOM_STORE_RAW_JSON", True)
        stats = ingest_root(
            args.root,
            database_url=args.database_url,
            store_raw_json=store_raw,
            include_location_properties=args.include_location_properties,
            fail_on_error=args.fail_on_error,
            limit=args.limit,
            collection=args.collection,
            source_uri=args.source_uri,
            force_reprocess=args.force_reprocess,
            authoritative_snapshot=args.authoritative_snapshot,
        )
        print(json.dumps(stats_as_dict(stats), indent=2))
        return
    if args.command == "import-target-modules":
        from .target_modules import import_target_modules

        print(json.dumps(import_target_modules(args.path, args.database_url), indent=2))
        return
    if args.command == "import-target-evidence":
        from .target_modules import import_target_module_evidence

        print(json.dumps(import_target_module_evidence(args.path, args.database_url), indent=2))
        return
    if args.command == "import-catalog-claim-evidence":
        from .target_modules import import_catalog_claim_evidence

        print(json.dumps(import_catalog_claim_evidence(args.path, args.database_url), indent=2))
        return
    if args.command == "import-service-impact":
        from .service_impact import import_service_impacts

        print(
            json.dumps(
                import_service_impacts(
                    args.path,
                    args.database_url,
                    source_collection=args.collection,
                ),
                indent=2,
            )
        )


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
