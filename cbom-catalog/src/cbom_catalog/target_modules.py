"""Import and query user-asserted per-team target-module planning data.

The imported status is deliberately not validation evidence.  It is retained
with its source checksum and raw record so the assessment can distinguish a
planning assertion from a deployment-to-CMVP correlation.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from .repository import connect
from .team_milestones import _MERGED_TEAM_KEYS, _TEAM_ROWS, GROUP_TEAM_KEYS, _slug

_TEAM_KEY_ALIASES = {
    "dw-volt-dashweb": "DW-VOLT",
}
_GROUP_ALIASES = {"apix": "apix-no-cbom"}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _team_key(team_name: str) -> str:
    normalized = _slug(team_name)
    if normalized in _TEAM_KEY_ALIASES:
        return _TEAM_KEY_ALIASES[normalized]
    candidates = {
        _slug(row["team"]): key
        for key, row in _TEAM_ROWS.items()
    }
    try:
        return candidates[normalized]
    except KeyError as exc:
        raise ValueError(f"Unmapped target-module team: {team_name}") from exc


def _service_groups(team_key: str) -> list[str]:
    groups: list[str] = []
    for group, row_keys in GROUP_TEAM_KEYS.items():
        for row_key in row_keys:
            merged = _MERGED_TEAM_KEYS.get(row_key, (row_key,))
            if team_key == row_key or team_key in merged:
                groups.append(group)
                break
    return sorted(set(groups))


def _normalized_status(raw: str | None) -> str:
    value = (raw or "").strip().casefold()
    return {
        "compliant": "asserted_compliant",
        "not compliant": "asserted_not_compliant",
        "pending certification": "pending_certification",
        "not applicable": "not_applicable",
    }.get(value, "not_determined")


def _certificate(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    match = re.search(r"#?\s*(\d{4,})", text)
    return f"#{match.group(1)}" if match else text


def _target_certificate(target: str | None) -> str | None:
    if not target:
        return None
    match = re.search(r"(?:cert(?:ificate)?\s*)?#\s*(\d{4,})", target, re.IGNORECASE)
    return f"#{match.group(1)}" if match else None


def _target_disposition(
    *,
    status: str,
    target_module: str | None,
    current_certificate: str | None,
    target_certificate: str | None,
) -> tuple[str, str]:
    if status == "pending_certification":
        return (
            "cmvp_in_process",
            "Source status is Pending Certification; no active validation is inferred.",
        )
    if target_module and target_certificate:
        return (
            "active_certificate",
            "Target-module text names a certificate; exact module/version/deployment matching remains required.",
        )
    if status == "asserted_compliant" and current_certificate:
        return (
            "active_certificate",
            "Source asserts the current module is compliant and supplies a certificate; assertion requires independent correlation.",
        )
    if target_module:
        return (
            "planned_unverified",
            "A target module is named without a target certificate or CMVP pipeline state.",
        )
    if status == "not_applicable":
        return "not_applicable", "Source explicitly marks the module Not Applicable."
    if status == "not_determined":
        return "not_determined", "Source does not supply a usable module status."
    return "not_supplied", "No target module or target CMVP disposition is supplied."


def parse_target_module_payload(payload: dict[str, Any]) -> dict[str, Any]:
    teams = payload.get("teams")
    if not isinstance(teams, list):
        raise TypeError("Target-module payload must contain a teams array")
    retrieved_raw = _clean(payload.get("retrieved"))
    try:
        retrieved = date.fromisoformat(retrieved_raw).isoformat() if retrieved_raw else None
    except ValueError as exc:
        raise ValueError("retrieved must be an ISO date") from exc

    parsed_teams: list[dict[str, Any]] = []
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for team_position, team in enumerate(teams):
        if not isinstance(team, dict) or not _clean(team.get("team")):
            raise ValueError(f"Team row {team_position} has no team name")
        team_name = str(team["team"]).strip()
        key = _team_key(team_name)
        if key in seen:
            raise ValueError(f"Duplicate target-module team mapping: {team_name} -> {key}")
        seen.add(key)
        modules = team.get("modules")
        if modules is None:
            modules = [
                {
                    "module": team.get("current_modules"),
                    "version": None,
                    "used_by": None,
                    "target_module": team.get("target_modules"),
                    "fips_140_3_status": team.get("fips_140_3_status"),
                    "cmvp_cert": team.get("cmvp_cert"),
                }
            ]
        if not isinstance(modules, list) or not modules:
            raise ValueError(f"Team {team_name} must contain at least one module row")
        team_record = {
            "team_key": key,
            "team_name": team_name,
            "owner": _clean(team.get("owner")),
            "lead": _clean(team.get("lead")),
            "il2_raw": _clean(team.get("il2_date")),
            "il5_raw": _clean(team.get("il5_date")),
            "service_groups": _service_groups(key),
        }
        parsed_teams.append(team_record)
        for module_position, module in enumerate(modules):
            if not isinstance(module, dict):
                raise TypeError(f"Team {team_name} module {module_position} is not an object")
            target_module = _clean(module.get("target_module"))
            if target_module and target_module.casefold() in {"na", "n/a"}:
                target_module = None
            status = _normalized_status(_clean(module.get("fips_140_3_status")))
            current_certificate = _certificate(module.get("cmvp_cert"))
            target_certificate = _target_certificate(target_module)
            disposition, basis = _target_disposition(
                status=status,
                target_module=target_module,
                current_certificate=current_certificate,
                target_certificate=target_certificate,
            )
            raw_record = {"team": team, "module": module}
            record_sha256 = hashlib.sha256(
                json.dumps(raw_record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            ).hexdigest()
            records.append(
                {
                    **team_record,
                    "module_position": module_position,
                    "current_module": _clean(module.get("module")),
                    "current_version": _clean(module.get("version")),
                    "used_by": _clean(module.get("used_by")),
                    "target_module": target_module,
                    "asserted_status": _clean(module.get("fips_140_3_status")),
                    "normalized_status": status,
                    "current_cmvp_cert": current_certificate,
                    "target_cmvp_cert": target_certificate,
                    "target_disposition": disposition,
                    "disposition_basis": basis,
                    "reason": _clean(module.get("reason")),
                    "record_sha256": record_sha256,
                    "raw_record": raw_record,
                    "evidence_grade": "user_asserted",
                    "review_required": True,
                }
            )
    return {
        "retrieved": retrieved,
        "teams": parsed_teams,
        "records": records,
    }


def import_target_modules(path: Path, database_url: str | None = None) -> dict[str, Any]:
    source_bytes = path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    payload = json.loads(source_bytes)
    if not isinstance(payload, dict):
        raise TypeError("Target-module source must be a JSON object")
    parsed = parse_target_module_payload(payload)
    with connect(database_url) as connection:
        existing = connection.execute(
            "SELECT id, imported_at FROM target_module_import WHERE source_sha256 = %s",
            (source_sha256,),
        ).fetchone()
        if existing:
            return {
                "status": "unchanged",
                "import_id": existing["id"],
                "source_sha256": source_sha256,
                "team_count": len(parsed["teams"]),
                "module_record_count": len(parsed["records"]),
            }
        connection.execute("UPDATE target_module_import SET is_active = false WHERE is_active")
        imported = connection.execute(
            """
            INSERT INTO target_module_import (
                source_filename, source_sha256, retrieved_on, is_active,
                team_count, module_record_count, raw_payload
            ) VALUES (%s, %s, %s, true, %s, %s, %s)
            RETURNING id
            """,
            (
                path.name,
                source_sha256,
                parsed["retrieved"],
                len(parsed["teams"]),
                len(parsed["records"]),
                Jsonb(payload),
            ),
        ).fetchone()
        import_id = int(imported["id"])
        for record in parsed["records"]:
            connection.execute(
                """
                INSERT INTO team_target_module (
                    import_id, team_key, team_name, owner_name, lead_name,
                    il2_raw, il5_raw, service_groups, module_position,
                    current_module, current_version, used_by, target_module,
                    asserted_status, normalized_status, current_cmvp_cert,
                    target_cmvp_cert, target_disposition, disposition_basis,
                    reason, evidence_grade, review_required, record_sha256, raw_record
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    import_id,
                    record["team_key"], record["team_name"], record["owner"], record["lead"],
                    record["il2_raw"], record["il5_raw"], record["service_groups"],
                    record["module_position"], record["current_module"], record["current_version"],
                    record["used_by"], record["target_module"], record["asserted_status"],
                    record["normalized_status"], record["current_cmvp_cert"],
                    record["target_cmvp_cert"], record["target_disposition"],
                    record["disposition_basis"], record["reason"], record["evidence_grade"],
                    record["review_required"], record["record_sha256"], Jsonb(record["raw_record"]),
                ),
            )
    return {
        "status": "imported",
        "import_id": import_id,
        "source_sha256": source_sha256,
        "retrieved": parsed["retrieved"],
        "team_count": len(parsed["teams"]),
        "module_record_count": len(parsed["records"]),
    }


def _claim_value(row: dict[str, Any], field: str) -> Any:
    return {
        "current_certificate": row.get("current_cmvp_cert"),
        "target_certificate": row.get("target_cmvp_cert"),
        "current_version": row.get("current_version"),
        "target_version": row.get("target_version"),
        "target_public_status": row.get("target_disposition"),
        "target_module_identity": row.get("target_module"),
    }.get(field)


def _version_verdict(claimed: str | None, observed: str | None) -> str | None:
    if not claimed or not observed:
        return None
    left = claimed.casefold().replace(" ", "")
    right = observed.casefold().replace(" ", "")
    return "corroborates" if right in left else "contradicts"


def _public_links(row: dict[str, Any], evidence: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str, str, str, str]]:
    """Return evidence, claim field, verdict, strength, and a conservative note."""
    links: list[tuple[dict[str, Any], str, str, str, str]] = []
    current_cert = row.get("current_cmvp_cert")
    target_cert = row.get("target_cmvp_cert")
    current_version = row.get("current_version")
    module_text = " ".join(filter(None, [row.get("current_module"), row.get("target_module")])).casefold()
    for item in evidence:
        certificate = item.get("certificate_number")
        if certificate and certificate in {current_cert, target_cert}:
            field = "current_certificate" if certificate == current_cert else "target_certificate"
            links.append((item, field, "corroborates", "uncorrelated", "Certificate record corroborates the public certificate identity/status only."))
            public_verdict = "contradicts" if item.get("public_status") == "historical" else "corroborates"
            links.append((item, "target_public_status", public_verdict, "uncorrelated", "Public lifecycle status is independent of service deployment applicability."))
            version_verdict = _version_verdict(current_version, item.get("module_version"))
            if version_verdict:
                links.append((item, "current_version", version_verdict, "name_version_match" if version_verdict == "corroborates" else "name_only", "Exact certified-module version comparison; no runtime or boundary inference."))
        key = item.get("evidence_key")
        if key == "openssl-3.5.4-submission" and row.get("normalized_status") == "pending_certification" and "openssl" in module_text:
            verdict = "corroborates" if current_version and "3.5.4" in current_version else "contradicts"
            links.append((item, "target_public_status", verdict, "name_version_match" if verdict == "corroborates" else "name_only", "The public submission is version-specific to OpenSSL 3.5.4."))
        if key == "go-fips140-doc" and ("go 1.26" in module_text or "gofips140" in module_text):
            links.append((item, "target_public_status", "partially_corroborates", "name_only", "Official Go guidance supports module v1.26.0 in process, not a generic Go patch release or deployed mode."))
        if key == "bouncycastle-java-fips" and ("bouncy" in module_text or "bc-fja" in module_text or "bc-fips" in module_text):
            links.append((item, "target_public_status", "partially_corroborates", "name_only", "Vendor lifecycle evidence requires exact provider/artifact boundary correlation."))
    return links


def import_target_module_evidence(path: Path, database_url: str | None = None) -> dict[str, Any]:
    """Import primary public evidence and link it to unchanged planning assertions.

    Links never establish deployment applicability. They only compare an asserted
    certificate/version/lifecycle state with a checksum-addressed public source.
    """
    source_bytes = path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    payload = json.loads(source_bytes)
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise TypeError("Evidence payload must contain a records array")
    retrieved = date.fromisoformat(str(payload.get("retrieved")))
    records = payload["records"]
    with connect(database_url) as connection:
        existing = connection.execute(
            "SELECT id FROM target_module_evidence_import WHERE source_sha256 = %s",
            (source_sha256,),
        ).fetchone()
        if existing:
            return {"status": "unchanged", "import_id": existing["id"], "source_sha256": source_sha256, "evidence_record_count": len(records)}
        connection.execute("UPDATE target_module_evidence_import SET is_active = false WHERE is_active AND evidence_set_kind = 'public_authority'")
        imported = connection.execute(
            """INSERT INTO target_module_evidence_import
               (source_filename, source_sha256, evidence_set_kind, retrieved_on, is_active, evidence_record_count, raw_payload)
               VALUES (%s, %s, 'public_authority', %s, true, %s, %s) RETURNING id""",
            (path.name, source_sha256, retrieved, len(records), Jsonb(payload)),
        ).fetchone()
        import_id = int(imported["id"])
        inserted: list[dict[str, Any]] = []
        for raw in records:
            if not isinstance(raw, dict) or not raw.get("key") or not raw.get("url"):
                raise ValueError("Every evidence record needs key and url")
            record_hash = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            saved = connection.execute(
                """INSERT INTO target_module_external_evidence
                   (import_id, evidence_key, authority, source_kind, source_title, source_url,
                    published_on, retrieved_on, certificate_number, module_name, module_version,
                    public_status, evidence_grade, supports_fields, limitations, payload_sha256, raw_record)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (import_id, raw["key"], raw["authority"], raw["source_kind"], raw["title"], raw["url"],
                 raw.get("published_on"), retrieved, raw.get("certificate_number"), raw.get("module_name"),
                 raw.get("module_version"), raw.get("public_status"), raw["evidence_grade"],
                 raw.get("supports_fields", []), raw.get("limitations", []), record_hash, Jsonb(raw)),
            ).fetchone()
            inserted.append({**raw, "id": saved["id"], "payload_sha256": record_hash, "evidence_key": raw["key"]})
        target_import = connection.execute("SELECT id FROM target_module_import WHERE is_active").fetchone()
        if not target_import:
            raise RuntimeError("Import target-module planning data before claim evidence")
        targets = connection.execute("SELECT * FROM team_target_module WHERE import_id = %s ORDER BY id", (target_import["id"],)).fetchall()
        linked = 0
        now = datetime.now(timezone.utc)
        for raw_target in targets:
            row = dict(raw_target)
            assertion_hash = hashlib.sha256(json.dumps({
                "team_key": row["team_key"], "module_position": row["module_position"],
                "current_module": row["current_module"], "current_version": row["current_version"],
                "target_module": row["target_module"], "target_version": row.get("target_version"),
                "asserted_status": row["asserted_status"],
            }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            connection.execute("UPDATE team_target_module SET assertion_subject_sha256 = %s WHERE id = %s AND assertion_subject_sha256 IS NULL", (assertion_hash, row["id"]))
            for item, field, verdict, strength, note in _public_links(row, inserted):
                connection.execute(
                    """INSERT INTO target_module_claim_evidence
                       (target_module_id, evidence_import_id, external_evidence_id, claim_field, claim_value, observed_value,
                        verdict, evidence_grade, source_kind, correlation_strength, provider, source_url,
                        source_title, source_locator, source_payload_sha256, retrieved_at, published_at,
                        evidence_payload, notes)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                    (row["id"], import_id, item["id"], field, Jsonb(_claim_value(row, field)), Jsonb({
                        "module_name": item.get("module_name"), "module_version": item.get("module_version"),
                        "certificate_number": item.get("certificate_number"), "public_status": item.get("public_status")}),
                     verdict, item["evidence_grade"], item["source_kind"], strength, item["authority"],
                     item["url"], item["title"], item["evidence_key"], item["payload_sha256"], now,
                     item.get("published_on"), Jsonb(item), note),
                )
                linked += 1
    return {"status": "imported", "import_id": import_id, "source_sha256": source_sha256, "evidence_record_count": len(records), "claim_links_considered": linked}


def import_catalog_claim_evidence(path: Path, database_url: str | None = None) -> dict[str, Any]:
    """Import a deterministic current-version-to-CBOM correlation matrix."""
    source_bytes = path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    payload = json.loads(source_bytes)
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise TypeError("Catalog evidence payload must contain a records array")
    assessed_on = date.fromisoformat(str(payload.get("assessment_as_of")))
    verdict_map = {
        "exact_name_version_match": ("corroborates", "name_version_match", "current_version"),
        "normalized_name_version_match": ("partially_corroborates", "name_version_match", "current_version"),
        "name_match_version_not_observed": ("contradicts", "name_only", "current_version"),
        "name_only_unpinned": ("partially_corroborates", "name_only", "current_module_identity"),
        "not_found": ("not_observed", "service_group_scope", "current_module_identity"),
        "not_assessable": ("not_assessable", "uncorrelated", "current_module_identity"),
    }
    with connect(database_url) as connection:
        existing = connection.execute("SELECT id FROM target_module_evidence_import WHERE source_sha256 = %s", (source_sha256,)).fetchone()
        if existing:
            return {"status": "unchanged", "import_id": existing["id"], "source_sha256": source_sha256, "evidence_record_count": len(records)}
        connection.execute("UPDATE target_module_evidence_import SET is_active = false WHERE is_active AND evidence_set_kind = 'catalog_correlation'")
        imported = connection.execute(
            """INSERT INTO target_module_evidence_import
               (source_filename, source_sha256, evidence_set_kind, retrieved_on, is_active, evidence_record_count, raw_payload)
               VALUES (%s,%s,'catalog_correlation',%s,true,%s,%s) RETURNING id""",
            (path.name, source_sha256, assessed_on, len(records), Jsonb(payload)),
        ).fetchone()
        import_id = int(imported["id"])
        target_import = connection.execute("SELECT id FROM target_module_import WHERE is_active").fetchone()
        if not target_import:
            raise RuntimeError("Import target-module planning data before catalog claim evidence")
        linked = 0
        for record in records:
            target = connection.execute(
                """SELECT * FROM team_target_module
                   WHERE import_id = %s AND team_key = %s AND module_position = %s""",
                (target_import["id"], record.get("team_key"), record.get("module_position")),
            ).fetchone()
            if not target:
                raise ValueError(f"Unmapped catalog evidence record: {record.get('team_key')}/{record.get('module_position')}")
            if target["current_module"] != record.get("current_module") or target["current_version"] != record.get("current_version"):
                raise ValueError(f"Stale catalog evidence for changed assertion: {record.get('team_key')}/{record.get('module_position')}")
            verdict, strength, field = verdict_map[record["catalog_verdict"]]
            observed = record.get("observed_component")
            document_id = source_file_id = component_occurrence_id = None
            if isinstance(observed, dict) and observed.get("document_sha256"):
                located = connection.execute(
                    """SELECT d.id AS document_id, sf.id AS source_file_id
                       FROM document d JOIN source_file sf ON sf.document_id = d.id
                       WHERE d.sha256 = %s AND sf.source_path = %s AND sf.is_present LIMIT 1""",
                    (observed["document_sha256"], observed.get("source_path")),
                ).fetchone()
                if located:
                    document_id, source_file_id = located["document_id"], located["source_file_id"]
                    component = connection.execute(
                        """SELECT dc.id FROM document_component dc JOIN component c ON c.id = dc.component_id
                           WHERE dc.document_id = %s AND lower(c.name) = lower(%s)
                           AND (c.version IS NOT DISTINCT FROM %s OR %s::text IS NULL) LIMIT 1""",
                        (document_id, observed.get("component"), observed.get("version"), observed.get("version")),
                    ).fetchone()
                    component_occurrence_id = component["id"] if component else None
            record_hash = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            connection.execute(
                """INSERT INTO target_module_claim_evidence
                   (target_module_id, evidence_import_id, claim_field, claim_value, observed_value, verdict, evidence_grade,
                    source_kind, correlation_strength, document_id, source_file_id, document_component_id,
                    provider, source_title, source_locator, source_payload_sha256, retrieved_at,
                    evidence_payload, notes)
                   VALUES (%s,%s,%s,%s,%s,%s,'inventory','catalog_tool_result',%s,%s,%s,%s,
                           'CBOM Catalog','Scoped CBOM current-version correlation',%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (target["id"], import_id, field, Jsonb(_claim_value(dict(target), field)), Jsonb(observed), verdict,
                 strength, document_id, source_file_id, component_occurrence_id,
                 observed.get("source_path") if isinstance(observed, dict) else None,
                 record_hash, datetime.combine(assessed_on, datetime.min.time(), tzinfo=timezone.utc),
                 Jsonb(record), "Inventory presence is not proof of runtime use, approved mode, or module validation."),
            )
            linked += 1
    return {"status": "imported", "import_id": import_id, "source_sha256": source_sha256, "evidence_record_count": len(records), "claim_links": linked}


def load_active_target_modules(connection: Any) -> dict[str, Any] | None:
    source = connection.execute(
        """
        SELECT id, source_filename, source_sha256, retrieved_on, imported_at,
               team_count, module_record_count
        FROM target_module_import
        WHERE is_active
        """
    ).fetchone()
    if not source:
        return None
    rows = connection.execute(
        """
        SELECT id, team_key, team_name, owner_name, lead_name, il2_raw, il5_raw,
               service_groups, module_position, current_module, current_version,
               used_by, target_module, target_version, asserted_status, normalized_status,
               current_cmvp_cert, target_cmvp_cert, target_disposition,
               disposition_basis, reason, evidence_grade, review_required,
               record_sha256, assertion_subject_sha256
        FROM team_target_module
        WHERE import_id = %s
        ORDER BY team_name, module_position
        """,
        (source["id"],),
    ).fetchall()
    evidence_rows = connection.execute(
        """SELECT e.target_module_id, e.id AS evidence_id, e.claim_field, e.verdict,
                  e.evidence_grade, e.source_kind, e.correlation_strength, e.provider,
                  e.source_url, e.source_title, e.source_locator, e.source_payload_sha256,
                  e.retrieved_at, e.published_at, e.observed_value, e.notes
           FROM target_module_claim_evidence e
           JOIN team_target_module tm ON tm.id = e.target_module_id
           LEFT JOIN target_module_evidence_import evidence_import ON evidence_import.id = e.evidence_import_id
           WHERE tm.import_id = %s AND (evidence_import.id IS NULL OR evidence_import.is_active)
           ORDER BY e.target_module_id, e.claim_field, e.id""",
        (source["id"],),
    ).fetchall()
    evidence_by_target: dict[int, list[dict[str, Any]]] = {}
    for raw_evidence in evidence_rows:
        evidence = dict(raw_evidence)
        target_id = int(evidence.pop("target_module_id"))
        for timestamp in ("retrieved_at", "published_at"):
            if evidence.get(timestamp):
                evidence[timestamp] = evidence[timestamp].isoformat()
        evidence_by_target.setdefault(target_id, []).append(evidence)

    def state_for(items: list[dict[str, Any]]) -> str:
        verdicts = {item["verdict"] for item in items}
        if "conflict" in verdicts or ({"corroborates", "contradicts"} <= verdicts):
            return "conflicting_evidence"
        if "contradicts" in verdicts:
            return "contradicted"
        if "corroborates" in verdicts:
            return "corroborated"
        if "partially_corroborates" in verdicts:
            return "partially_corroborated"
        if "not_observed" in verdicts:
            return "not_observed"
        if "not_assessable" in verdicts:
            return "not_assessable"
        return "not_assessable"

    def conservative_state(items: list[dict[str, Any]]) -> str:
        verdicts = {item["verdict"] for item in items}
        if "conflict" in verdicts:
            return "conflicting_evidence"
        if "contradicts" in verdicts:
            return "contradicted"
        if "corroborates" in verdicts:
            return "corroborated"
        if "partially_corroborates" in verdicts:
            return "partially_corroborated"
        if "not_observed" in verdicts:
            return "not_observed"
        return "not_assessable"
    teams: dict[str, dict[str, Any]] = {}
    groups: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        target_module_id = int(row.pop("id"))
        service_groups = sorted(
            {
                _GROUP_ALIASES.get(group, group)
                for group in (row.pop("service_groups") or [])
            }
        )
        key = row["team_key"]
        team = teams.setdefault(
            key,
            {
                "team_key": key,
                "team": row["team_name"],
                "owner": row["owner_name"],
                "lead": row["lead_name"],
                "il2_raw": row["il2_raw"],
                "il5_raw": row["il5_raw"],
                "service_groups": service_groups,
                "modules": [],
            },
        )
        module = {
            name: value
            for name, value in row.items()
            if name not in {"team_key", "team_name", "owner_name", "lead_name", "il2_raw", "il5_raw"}
        }
        module_evidence = evidence_by_target.get(target_module_id, [])
        inventory_evidence = [item for item in module_evidence if item["source_kind"].startswith("catalog_")]
        public_evidence = [item for item in module_evidence if item["claim_field"] == "target_public_status"]
        authority_evidence = [item for item in module_evidence if not item["source_kind"].startswith("catalog_")]
        inventory_state = state_for(inventory_evidence)
        public_state = state_for(public_evidence)
        authority_state = conservative_state(authority_evidence)
        overall = "contradicted" if "contradicted" in {inventory_state, authority_state} else "conflicting_evidence" if "conflicting_evidence" in {inventory_state, authority_state} else "not_assessable"
        module["verification"] = {
            "current_inventory_match": {"state": inventory_state, "evidence_count": len(inventory_evidence)},
            "target_public_status": {"state": public_state, "evidence_count": len(public_evidence)},
            "public_authority_alignment": {"state": authority_state, "evidence_count": len(authority_evidence)},
            "deployment_applicability": {"state": "not_assessable", "evidence_count": 0},
            "overall": {"state": overall, "review_required": True},
        }
        module["evidence_summary"] = {
            "evidence_count": len(module_evidence),
            "corroborates": sum(item["verdict"] == "corroborates" for item in module_evidence),
            "contradicts": sum(item["verdict"] == "contradicts" for item in module_evidence),
            "partial": sum(item["verdict"] == "partially_corroborates" for item in module_evidence),
            "not_observed": sum(item["verdict"] == "not_observed" for item in module_evidence),
            "unresolved_requirements": [
                "Exact deployed artifact digest and module boundary",
                "Approved operational environment and FIPS mode/configuration",
                "ATO-boundary deployment attestation",
            ],
        }
        module["evidence"] = module_evidence
        team["modules"].append(module)
        for group_slug in service_groups:
            group = groups.setdefault(
                group_slug,
                {"service_group": group_slug, "teams": [], "modules": []},
            )
            group["modules"].append({**module, "team_key": key, "team": row["team_name"]})
    for team in teams.values():
        for group_slug in team["service_groups"]:
            group = groups[group_slug]
            if not any(existing["team_key"] == team["team_key"] for existing in group["teams"]):
                group["teams"].append({name: value for name, value in team.items() if name != "modules"})
    evidence_imports = connection.execute(
        """SELECT evidence_set_kind, source_filename, source_sha256, retrieved_on,
                  imported_at, evidence_record_count
           FROM target_module_evidence_import WHERE is_active
           ORDER BY evidence_set_kind"""
    ).fetchall()
    return {
        "source": {
            "import_id": source["id"],
            "source_file": source["source_filename"],
            "source_file_sha256": source["source_sha256"],
            "retrieved_on": source["retrieved_on"].isoformat() if source["retrieved_on"] else None,
            "imported_at": source["imported_at"].isoformat(),
            "team_count": source["team_count"],
            "module_record_count": source["module_record_count"],
            "evidence_grade": "user_asserted",
            "review_required": True,
            "evidence_imports": [
                {
                    **dict(item),
                    "retrieved_on": item["retrieved_on"].isoformat(),
                    "imported_at": item["imported_at"].isoformat(),
                }
                for item in evidence_imports
            ],
        },
        "teams": sorted(teams.values(), key=lambda row: row["team"].casefold()),
        "groups": groups,
    }
