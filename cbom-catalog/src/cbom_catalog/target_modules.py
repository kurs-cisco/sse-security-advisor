"""Import and query user-asserted per-team target-module planning data.

The imported status is deliberately not validation evidence.  It is retained
with its source checksum and raw record so the assessment can distinguish a
planning assertion from a deployment-to-CMVP correlation.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from .repository import connect
from .team_milestones import (
    GROUP_TEAM_KEYS,
    TRACKER_SOURCE,
    _MERGED_SOURCE_KEYS,
    _MERGED_TEAM_KEYS,
    _TEAM_ROWS,
    _slug,
    _tracker_row,
)

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
            "A target is named, but its exact approved module identity/version and linked CMVP certificate or pipeline reference are not supplied.",
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
    return "corroborates" if _exact_version_match(claimed, observed) else "contradicts"


def _exact_version_match(claimed: str | None, observed: str | None) -> bool:
    """Return true only for an explicit whole-version match.

    This intentionally does not treat a Go toolchain patch release as its
    embedded cryptographic-module version, and does not turn a library-family
    name into a module identity.
    """
    if not claimed or not observed:
        return False
    return claimed.strip().casefold() == observed.strip().casefold()


def _projected_evidence_grade(source_kind: str | None, recorded_grade: str | None) -> str | None:
    """Keep legacy imported bytes intact while classifying vendor statements correctly."""
    if source_kind in {"vendor_blog", "vendor_release_note"}:
        return "curated_analysis"
    return recorded_grade


def _module_name_match(claimed: str | None, observed: str | None) -> bool:
    """Compare declared module identities without accepting library-only hints."""
    if not claimed or not observed:
        return False
    left = re.sub(r"[^a-z0-9]+", " ", claimed.casefold()).strip()
    right = re.sub(r"[^a-z0-9]+", " ", observed.casefold()).strip()
    return left == right


def _exact_module_version_identity(
    module_name: str | None,
    module_version: str | None,
    evidence: dict[str, Any],
) -> bool:
    """Recognize only an exact formal module and version identity.

    A package named OpenSSL, a product name, or a toolchain version is not a
    CMVP module identity. This tight predicate is used only to show a public
    reference suggestion; it never changes a planning disposition.
    """
    evidence_version = _clean(evidence.get("module_version"))
    return (
        _module_name_match(module_name, _clean(evidence.get("module_name")))
        and bool(module_version)
        and bool(evidence_version)
        and module_version.strip().casefold() == evidence_version.casefold()
    )


def public_module_suggestions(
    module: dict[str, Any], public_evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return exact active CMVP references that a reviewer may select in Catalog.

    Suggestions are deliberately separate from imported assertions and from
    effective planning disposition. They do not establish deployment,
    operational environment, approved mode, or FIPS validation for a service.
    """
    candidates = [
        (_clean(module.get("current_module")), _clean(module.get("current_version"))),
        (_clean(module.get("target_module")), _clean(module.get("target_version"))),
    ]
    suggestions: list[dict[str, Any]] = []
    for item in public_evidence:
        if item.get("source_kind") != "cmvp_certificate" or item.get("public_status") != "active":
            continue
        if not any(
            _exact_module_version_identity(name, version, item)
            for name, version in candidates
        ):
            continue
        suggestions.append(
            {
                "module_name": item.get("module_name"),
                "module_version": item.get("module_version"),
                "certificate_number": _certificate(item.get("certificate_number")),
                "public_status": item.get("public_status"),
                "source_url": item.get("source_url") or item.get("url"),
                "source_title": item.get("source_title") or item.get("title"),
                "source_kind": item.get("source_kind"),
                "suggestion_basis": (
                    "Exact formal module and version match to an active public CMVP certificate. "
                    "Select and approve it in Service Catalog before using it as planning metadata; "
                    "deployment and approved-mode evidence remain required."
                ),
            }
        )
    return sorted(
        suggestions,
        key=lambda row: (
            str(row.get("module_name") or ""),
            str(row.get("module_version") or ""),
            str(row.get("certificate_number") or ""),
        ),
    )


def evaluate_catalog_crypto_module_plan(
    plan: dict[str, Any], public_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate a Service Catalog crypto-module plan against imported evidence.

    Contract for the catalog overlay: ``target_module`` and ``target_version``
    are required.  An active-certificate plan also supplies
    ``cmvp_certificate``.  A pipeline plan supplies the exact ``evidence_url``
    for a known vendor/CMVP source.  The returned disposition is suitable for
    *planning display only*: it never establishes a deployed module match,
    approved mode, or authorization status.

    The caller owns authorization and persistence.  This function is pure so
    rendering an overlay cannot modify imported target-module assertions.
    """
    target_module = _clean(plan.get("target_module"))
    target_version = _clean(plan.get("target_version"))
    certificate = _certificate(plan.get("cmvp_certificate"))
    evidence_url = _clean(plan.get("evidence_url"))
    preset_id = _clean(plan.get("target_preset_id"))
    evidence_payload_sha256 = _clean(plan.get("evidence_payload_sha256"))
    if not target_module or not target_version:
        return {
            "status": "planned_unverified",
            "evidence_state": "evidence_superseded",
            "basis": "The catalog plan needs an exact target module name and version.",
            "evidence": None,
        }
    if not preset_id:
        return {
            "status": "planned_unverified",
            "evidence_state": "user_asserted_unverified",
            "basis": "This is a custom catalog target with a supporting URL; its module identity and lifecycle evidence require reviewer confirmation.",
            "evidence": None,
        }
    if not evidence_payload_sha256:
        return {
            "status": "planned_unverified",
            "evidence_state": "evidence_superseded",
            "basis": "An approved target preset and its current evidence payload reference are required before this catalog plan can affect Planning.",
            "evidence": None,
        }

    matching = [
        item
        for item in public_evidence
        if _module_name_match(target_module, _clean(item.get("module_name")))
        and _exact_version_match(target_version, _clean(item.get("module_version")))
        and str(item.get("key") or item.get("evidence_key") or "") == preset_id
        and str(item.get("payload_sha256") or item.get("evidence_payload_sha256") or "") == evidence_payload_sha256
    ]
    if certificate:
        matching = [
            item for item in matching
            if _certificate(item.get("certificate_number")) == certificate
            and item.get("source_kind") == "cmvp_certificate"
            and item.get("public_status") == "active"
        ]
        if matching:
            item = matching[0]
            return {
                "status": "active_certificate",
                "evidence_state": "current",
                "basis": (
                    f"Catalog plan exactly matches linked CMVP certificate {certificate}; "
                    "deployment, operational-environment, and approved-mode evidence remain required."
                ),
                "evidence": item,
            }
        return {
            "status": "planned_unverified",
            "evidence_state": "evidence_superseded",
            "basis": "The supplied certificate does not exactly match an active imported CMVP module record.",
            "evidence": None,
        }

    matching = [
        item for item in matching
        if evidence_url
        and item.get("url") == evidence_url
        and item.get("public_status") in {
            "cmvp_in_process", "cmvp_review", "submission_planned_or_in_progress",
        }
    ]
    if matching:
        item = matching[0]
        return {
            "status": "cmvp_in_process",
            "evidence_state": "current",
            "basis": (
                "Catalog plan exactly matches linked public CMVP pipeline evidence; "
                "it is not an active validation certificate or deployment conclusion."
            ),
            "evidence": item,
        }
    return {
        "status": "planned_unverified",
        "evidence_state": "evidence_superseded",
        "basis": "The approved target's evidence reference no longer matches active exact CMVP certificate or pipeline evidence; re-review the catalog plan.",
        "evidence": None,
    }


def apply_catalog_crypto_module_plans(
    planning: dict[str, Any],
    catalog_rows: list[dict[str, Any]],
    *,
    public_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a non-persistent planning projection with catalog plan overlays.

    ``catalog_rows`` are Service Catalog API rows.  Each row may carry
    ``crypto_module_plans`` directly or inside ``attributes``.  A plan changes
    an imported record's *effective planning display* only when it has an
    exact ``source_record_sha256`` for that imported assertion.  Plans without
    that identifier remain visible as catalog-only plans and never affect
    imported target-module dispositions.

    Required plan fields are defined by :func:`evaluate_catalog_crypto_module_plan`.
    ``public_evidence`` should be the active external-evidence query, when
    available; it allows a newly selected preset to be evaluated even before
    any imported tracker assertion links to the same record.  The function also
    uses evidence already linked to imported records as a fallback.
    This function returns a deep copy and does not write the tracker import,
    external evidence import, or Service Catalog row.
    """
    projected = deepcopy(planning)
    planning_source_collection = _clean(
        (projected.get("source") or {}).get("source_collection")
    ) or str(TRACKER_SOURCE["source_collection"])
    catalog_by_scope: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in catalog_rows:
        group = _clean(row.get("service_group"))
        collection = _clean(row.get("source_collection"))
        if not group or not collection:
            continue
        attributes = row.get("attributes")
        plans = row.get("crypto_module_plans")
        if plans is None and isinstance(attributes, dict):
            plans = attributes.get("crypto_module_plans")
        if isinstance(plans, list):
            catalog_by_scope.setdefault((collection, _slug(group)), []).extend(
                plan for plan in plans if isinstance(plan, dict)
            )

    public_evidence_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for item in public_evidence or []:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("key") or item.get("evidence_key") or ""), str(item.get("url") or item.get("source_url") or ""))
        if key == ("", ""):
            continue
        public_evidence_by_key[key] = {
            "key": item.get("key") or item.get("evidence_key"),
            "source_kind": item.get("source_kind"),
            "url": item.get("url") or item.get("source_url"),
            "certificate_number": item.get("certificate_number"),
            "module_name": item.get("module_name"),
            "module_version": item.get("module_version"),
            "public_status": item.get("public_status"),
            "payload_sha256": item.get("payload_sha256") or item.get("evidence_payload_sha256"),
        }
    for group in projected.get("groups", []):
        for module in group.get("target_modules", []):
            for linked in module.get("evidence", []):
                observed = linked.get("observed_value")
                if not isinstance(observed, dict):
                    observed = {}
                item = {
                    "key": linked.get("source_locator"),
                    "source_kind": linked.get("source_kind"),
                    "url": linked.get("source_url"),
                    "certificate_number": observed.get("certificate_number"),
                    "module_name": observed.get("module_name"),
                    "module_version": observed.get("module_version"),
                    "public_status": observed.get("public_status"),
                    "payload_sha256": linked.get("source_payload_sha256"),
                }
                key = (str(item.get("key") or ""), str(item.get("url") or ""))
                if key != ("", ""):
                    public_evidence_by_key[key] = item
    public_evidence = list(public_evidence_by_key.values())

    for group in projected.get("groups", []):
        plans = catalog_by_scope.get(
            (planning_source_collection, _slug(str(group.get("service_group") or ""))),
            [],
        )
        if not plans:
            continue
        catalog_projection: list[dict[str, Any]] = []
        modules_by_sha = {
            str(module.get("record_sha256")): module
            for module in group.get("target_modules", [])
            if module.get("record_sha256")
        }
        for plan in plans:
            evaluation = evaluate_catalog_crypto_module_plan(plan, public_evidence)
            safe_evidence = evaluation.pop("evidence")
            if safe_evidence:
                safe_evidence = {
                    "key": safe_evidence.get("key"),
                    "source_kind": safe_evidence.get("source_kind"),
                    "url": safe_evidence.get("url"),
                    "certificate_number": safe_evidence.get("certificate_number"),
                    "module_name": safe_evidence.get("module_name"),
                    "module_version": safe_evidence.get("module_version"),
                    "public_status": safe_evidence.get("public_status"),
                }
            source_record_sha256 = _clean(plan.get("source_record_sha256"))
            module = modules_by_sha.get(str(source_record_sha256)) if source_record_sha256 else None
            projected_plan = {
                "source_record_sha256": source_record_sha256,
                "target_preset_id": _clean(plan.get("target_preset_id")),
                "target_module": _clean(plan.get("target_module")),
                "target_version": _clean(plan.get("target_version")),
                "cmvp_certificate": _certificate(plan.get("cmvp_certificate")),
                "evidence_url": _clean(plan.get("evidence_url")),
                "evidence_payload_sha256": _clean(plan.get("evidence_payload_sha256")),
                "effective_target_disposition": evaluation["status"],
                "evidence_state": evaluation["evidence_state"],
                "effective_disposition_basis": evaluation["basis"],
                "linked_public_evidence": safe_evidence,
                "projection_scope": "imported_record" if module else "catalog_only",
            }
            catalog_projection.append(projected_plan)
            if module is not None:
                module["catalog_crypto_module_plan"] = projected_plan
                module["effective_target_disposition"] = evaluation["status"]
                module["effective_disposition_basis"] = evaluation["basis"]
                # Preserve the imported assertion verbatim and expose the
                # reviewed Catalog selection as an overlay for Planning views.
                # A selected target may deliberately supersede an older
                # free-text target in the imported tracker.
                module["effective_target_module"] = projected_plan["target_module"]
                module["effective_target_version"] = projected_plan["target_version"]
                module["effective_target_cmvp_cert"] = projected_plan["cmvp_certificate"]
            else:
                # A Catalog plan is still useful when no imported record is
                # available. Represent it as a separate planning row instead
                # of altering a tracker import by inference.
                plan_key = hashlib.sha256(
                    json.dumps(projected_plan, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                group.setdefault("target_modules", []).append(
                    {
                        "planning_record_key": f"catalog-plan:{plan_key}",
                        "record_sha256": None,
                        "current_module": None,
                        "current_version": None,
                        "used_by": None,
                        "target_module": projected_plan["target_module"],
                        "target_version": projected_plan["target_version"],
                        "target_cmvp_cert": projected_plan["cmvp_certificate"],
                        "target_disposition": "planned_unverified",
                        "disposition_basis": "Catalog-only planning assertion; no imported target-module record is linked.",
                        "effective_target_disposition": evaluation["status"],
                        "effective_disposition_basis": evaluation["basis"],
                        "effective_target_module": projected_plan["target_module"],
                        "effective_target_version": projected_plan["target_version"],
                        "effective_target_cmvp_cert": projected_plan["cmvp_certificate"],
                        "catalog_crypto_module_plan": projected_plan,
                        "evidence_grade": "user_asserted",
                        "review_required": True,
                        "planning_origin": "catalog_only",
                    }
                )
        group["catalog_crypto_module_plans"] = catalog_projection
    return projected


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
            verdict = "corroborates" if _exact_version_match(current_version, "3.5.4") else "contradicts"
            links.append((item, "target_public_status", verdict, "name_version_match" if verdict == "corroborates" else "name_only", "The public submission is version-specific to OpenSSL 3.5.4."))
        if key == "go-fips140-doc" and "gofips140" in module_text:
            if _exact_version_match(row.get("target_module"), item.get("module_version")):
                links.append((item, "target_module_identity", "corroborates", "name_version_match", "Official Go guidance corroborates the exact in-process Go Cryptographic Module version only; deployment and FIPS mode remain unverified."))
            else:
                links.append((item, "target_public_status", "partially_corroborates", "name_only", "Official Go guidance supports module v1.26.0 in process, not a generic Go patch release, GOFIPS140=latest, or deployed mode."))
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
            "SELECT id, is_active FROM target_module_evidence_import WHERE source_sha256 = %s",
            (source_sha256,),
        ).fetchone()
        if existing:
            import_id = int(existing["id"])
            if not existing["is_active"]:
                connection.execute("UPDATE target_module_evidence_import SET is_active = false WHERE is_active AND evidence_set_kind = 'public_authority'")
                connection.execute("UPDATE target_module_evidence_import SET is_active = true WHERE id = %s", (import_id,))
            saved_rows = connection.execute(
                """SELECT id, evidence_key, payload_sha256, raw_record
                   FROM target_module_external_evidence WHERE import_id = %s
                   ORDER BY evidence_key""",
                (import_id,),
            ).fetchall()
            inserted = [
                {
                    **dict(saved["raw_record"]),
                    "id": saved["id"],
                    "payload_sha256": saved["payload_sha256"],
                    "evidence_key": saved["evidence_key"],
                }
                for saved in saved_rows
            ]
        else:
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
                saved_link = connection.execute(
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
                linked += saved_link.rowcount
    status = "imported" if not existing else "relinked" if linked else "unchanged"
    return {"status": status, "import_id": import_id, "source_sha256": source_sha256, "evidence_record_count": len(records), "claim_links_considered": linked}


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
        existing = connection.execute("SELECT id, is_active FROM target_module_evidence_import WHERE source_sha256 = %s", (source_sha256,)).fetchone()
        if existing:
            import_id = int(existing["id"])
            if not existing["is_active"]:
                connection.execute("UPDATE target_module_evidence_import SET is_active = false WHERE is_active AND evidence_set_kind = 'catalog_correlation'")
                connection.execute("UPDATE target_module_evidence_import SET is_active = true WHERE id = %s", (import_id,))
        else:
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
            saved_link = connection.execute(
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
            linked += saved_link.rowcount
    status = "imported" if not existing else "relinked" if linked else "unchanged"
    return {"status": status, "import_id": import_id, "source_sha256": source_sha256, "evidence_record_count": len(records), "claim_links": linked}


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
    active_public_evidence_rows = connection.execute(
        """SELECT external.evidence_key, external.source_kind, external.source_title,
                  external.source_url, external.certificate_number, external.module_name,
                  external.module_version, external.public_status
           FROM target_module_external_evidence external
           JOIN target_module_evidence_import imported ON imported.id = external.import_id
           WHERE imported.is_active AND imported.evidence_set_kind = 'public_authority'
           ORDER BY external.evidence_key"""
    ).fetchall()
    active_public_evidence = [dict(item) for item in active_public_evidence_rows]
    evidence_by_target: dict[int, list[dict[str, Any]]] = {}
    for raw_evidence in evidence_rows:
        evidence = dict(raw_evidence)
        target_id = int(evidence.pop("target_module_id"))
        grade = _projected_evidence_grade(evidence.get("source_kind"), evidence.get("evidence_grade"))
        if grade != evidence.get("evidence_grade"):
            evidence["recorded_evidence_grade"] = evidence["evidence_grade"]
            evidence["evidence_grade"] = grade
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
        imported_planning = {
            "team": row["team_name"],
            "owner": row["owner_name"],
            "lead": row["lead_name"],
            "il2_raw": row["il2_raw"],
            "il5_raw": row["il5_raw"],
        }
        if key in _TEAM_ROWS:
            approved_planning = _tracker_row(key)
        else:
            approved_planning = None
        effective_team = approved_planning["team"] if approved_planning else row["team_name"]
        effective_owner = approved_planning["owner"] if approved_planning else row["owner_name"]
        effective_lead = approved_planning["lead"] if approved_planning else row["lead_name"]
        effective_il2 = approved_planning["il2"] if approved_planning else row["il2_raw"]
        effective_il5 = approved_planning["il5"] if approved_planning else row["il5_raw"]
        team = teams.setdefault(
            key,
            {
                "team_key": key,
                "team": effective_team,
                "owner": effective_owner or None,
                "lead": effective_lead or None,
                "il2_raw": effective_il2 or None,
                "il5_raw": effective_il5 or None,
                "service_groups": service_groups,
                "planning_source": TRACKER_SOURCE,
                "imported_planning": imported_planning,
                "planning_merged_into": next(
                    (
                        canonical
                        for canonical, source_keys in _MERGED_TEAM_KEYS.items()
                        if key in source_keys and key != canonical
                    ),
                    None,
                )
                if key in _MERGED_SOURCE_KEYS
                else None,
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
        module["public_module_suggestions"] = public_module_suggestions(
            module, active_public_evidence
        )
        team["modules"].append(module)
        for group_slug in service_groups:
            group = groups.setdefault(
                group_slug,
                {"service_group": group_slug, "teams": [], "modules": []},
            )
            group["modules"].append({**module, "team_key": key, "team": team["team"]})
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
