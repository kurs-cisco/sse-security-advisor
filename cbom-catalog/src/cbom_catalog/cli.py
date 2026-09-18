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


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
