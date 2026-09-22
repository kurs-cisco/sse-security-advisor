"""Import user-asserted service-impact planning metadata from a tabular source.

Only the three requested planning fields are retained. Owner, lead, CBOM status,
and milestone columns are deliberately ignored and cannot override catalog or
Team Tracker data.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from .repository import connect
from .target_modules import _service_groups, _team_key

_REQUIRED_HEADERS = ("Team", "Impact on POA&M", "Risk Category", "Comments")


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u00a0", " ").strip()
    return text or None


def _decode_source(source_bytes: bytes) -> tuple[str, str]:
    try:
        return source_bytes.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        # The supplied Excel export uses MacRoman 0xCA for a non-breaking space.
        return source_bytes.decode("mac_roman"), "mac_roman"


def parse_service_impact_source(source_bytes: bytes) -> dict[str, Any]:
    text, encoding = _decode_source(source_bytes)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter="\t")
    try:
        raw_headers = next(reader)
    except StopIteration as exc:
        raise ValueError("Service-impact source is empty") from exc

    headers = [str(_clean(value) or "") for value in raw_headers]
    positions = {header: index for index, header in enumerate(headers)}
    missing = [header for header in _REQUIRED_HEADERS if header not in positions]
    if missing:
        raise ValueError(f"Missing service-impact columns: {', '.join(missing)}")

    parsed_rows: list[dict[str, Any]] = []
    seen_teams: set[str] = set()
    claimed_groups: dict[str, str] = {}
    for values in reader:
        source_row = reader.line_num
        if not any(_clean(value) for value in values):
            continue
        padded = values + [""] * max(0, len(headers) - len(values))
        team_name = _clean(padded[positions["Team"]])
        if not team_name:
            raise ValueError(f"Service-impact row {source_row} has no team name")
        team_key = _team_key(team_name)
        if team_key in seen_teams:
            raise ValueError(f"Duplicate service-impact team mapping: {team_name} -> {team_key}")
        seen_teams.add(team_key)
        service_groups = _service_groups(team_key)
        if not service_groups:
            raise ValueError(f"Service-impact team has no mapped service group: {team_name}")
        for service_group in service_groups:
            prior = claimed_groups.get(service_group)
            if prior and prior != team_key:
                raise ValueError(
                    f"Service-impact group {service_group} is claimed by {prior} and {team_key}"
                )
            claimed_groups[service_group] = team_key

        selected_record = {
            "team": team_name,
            "poam_impact": _clean(padded[positions["Impact on POA&M"]]),
            "risk_category": _clean(padded[positions["Risk Category"]]),
            "comments": _clean(padded[positions["Comments"]]),
        }
        record_sha256 = hashlib.sha256(
            json.dumps(
                selected_record,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        parsed_rows.append(
            {
                "source_row": source_row,
                "team_key": team_key,
                "team_name": team_name,
                "service_groups": service_groups,
                **{key: selected_record[key] for key in ("poam_impact", "risk_category", "comments")},
                "evidence_grade": "user_asserted",
                "review_required": True,
                "record_sha256": record_sha256,
                "selected_record": selected_record,
            }
        )

    if not parsed_rows:
        raise ValueError("Service-impact source contains no populated rows")
    return {
        "encoding": encoding,
        "delimiter": "tab",
        "rows": parsed_rows,
    }


def import_service_impacts(
    path: Path,
    database_url: str | None = None,
    *,
    source_collection: str = "sse-cboms",
) -> dict[str, Any]:
    source_bytes = path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    parsed = parse_service_impact_source(source_bytes)
    selected_payload = {
        "source_collection": source_collection,
        "rows": [
            {
                "source_row": row["source_row"],
                "team_key": row["team_key"],
                "team_name": row["team_name"],
                "service_groups": row["service_groups"],
                "poam_impact": row["poam_impact"],
                "risk_category": row["risk_category"],
                "comments": row["comments"],
            }
            for row in parsed["rows"]
        ],
    }
    with connect(database_url) as connection:
        existing = connection.execute(
            """
            SELECT id, imported_at
            FROM service_impact_import
            WHERE source_collection = %s AND source_sha256 = %s
            """,
            (source_collection, source_sha256),
        ).fetchone()
        if existing:
            return {
                "status": "unchanged",
                "import_id": existing["id"],
                "source_sha256": source_sha256,
                "source_collection": source_collection,
                "row_count": len(parsed["rows"]),
            }
        connection.execute(
            "UPDATE service_impact_import SET is_active = false WHERE source_collection = %s AND is_active",
            (source_collection,),
        )
        imported = connection.execute(
            """
            INSERT INTO service_impact_import (
                source_collection, source_filename, source_sha256, source_encoding,
                source_delimiter, is_active, row_count, selected_payload
            ) VALUES (%s, %s, %s, %s, %s, true, %s, %s)
            RETURNING id
            """,
            (
                source_collection,
                path.name,
                source_sha256,
                parsed["encoding"],
                parsed["delimiter"],
                len(parsed["rows"]),
                Jsonb(selected_payload),
            ),
        ).fetchone()
        import_id = int(imported["id"])
        for row in parsed["rows"]:
            connection.execute(
                """
                INSERT INTO team_service_impact (
                    import_id, source_row, team_key, team_name, service_groups,
                    poam_impact, risk_category, comments, evidence_grade,
                    review_required, record_sha256, selected_record
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    import_id,
                    row["source_row"],
                    row["team_key"],
                    row["team_name"],
                    row["service_groups"],
                    row["poam_impact"],
                    row["risk_category"],
                    row["comments"],
                    row["evidence_grade"],
                    row["review_required"],
                    row["record_sha256"],
                    Jsonb(row["selected_record"]),
                ),
            )
    return {
        "status": "imported",
        "import_id": import_id,
        "source_sha256": source_sha256,
        "source_collection": source_collection,
        "row_count": len(parsed["rows"]),
        "mapped_service_group_count": len(
            {group for row in parsed["rows"] for group in row["service_groups"]}
        ),
    }


def load_active_service_impacts(connection: Any) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT source.source_collection, source.source_filename,
               source.source_sha256, source.imported_at,
               impact.source_row, impact.team_key, impact.team_name,
               impact.service_groups, impact.poam_impact,
               impact.risk_category, impact.comments,
               impact.evidence_grade, impact.review_required
        FROM service_impact_import source
        JOIN team_service_impact impact ON impact.import_id = source.id
        WHERE source.is_active
        ORDER BY source.source_collection, impact.source_row
        """
    ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        for service_group in row["service_groups"]:
            service_key = f"{row['source_collection']}/{service_group}"
            if service_key in result:
                raise ValueError(f"Duplicate active service-impact mapping: {service_key}")
            result[service_key] = {
                "poam_impact": row["poam_impact"],
                "risk_category": row["risk_category"],
                "comments": row["comments"],
                "team": row["team_name"],
                "evidence_grade": row["evidence_grade"],
                "review_required": row["review_required"],
                "source": {
                    "source_filename": row["source_filename"],
                    "source_sha256": row["source_sha256"],
                    "source_row": row["source_row"],
                    "imported_at": row["imported_at"],
                },
            }
    return result
