from __future__ import annotations

import csv
import hashlib
import io
import os
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


POLICY_VERSION = "FIPS1403-MIGRATION-2026-09-18"
ASSESSOR_VERSION = "1.0.0"
LAST_NEW_SYSTEM_DATE = date(2026, 9, 21)
HISTORICAL_EFFECTIVE_DATE = date(2026, 9, 22)

AUTHORITATIVE_SOURCES = [
    {
        "authority": "NIST CMVP",
        "title": "Cryptographic Module Validation Program",
        "url": "https://csrc.nist.gov/projects/cryptographic-module-validation-program",
        "retrieved_on": "2026-09-18",
        "claim": (
            "FIPS 140-2 modules may be used for new systems through 2026-09-21; "
            "afterward they move to the Historical List and may continue only for existing systems."
        ),
    },
    {
        "authority": "NIST CMVP",
        "title": "CMVP FAQs",
        "url": "https://csrc.nist.gov/Projects/cryptographic-module-validation-program/faqs",
        "retrieved_on": "2026-09-18",
        "claim": (
            "Only FIPS 140-3 validations remain active on 2026-09-22; validation requires "
            "matching the certificate, module version, and operational environment."
        ),
    },
    {
        "authority": "FedRAMP",
        "title": "FIPS 140-2 sunset guidance",
        "url": (
            "https://help.fedramp.gov/hc/en-us/articles/53386638354843-"
            "Q-Will-FedRAMP-provide-guidance-on-the-sunsetting-of-FIPS-140-2-"
            "What-do-I-do-if-our-planned-140-3-Module-is-not-yet-approved"
        ),
        "retrieved_on": "2026-09-18",
        "claim": (
            "Use of a historical FIPS 140-2 module, or early use of a FIPS 140-3 module "
            "before validation completes, carries risk and should be tracked as an open vulnerability."
        ),
    },
    {
        "authority": "FedRAMP",
        "title": "RFC-0003 Review Initiation Checks",
        "url": "https://www.fedramp.gov/rfcs/0003/",
        "retrieved_on": "2026-09-18",
        "claim": (
            "SC-13 evidence must cover each in-scope data flow and data store and identify the "
            "associated validated module and certificate; non-validated modules belong in the POA&M."
        ),
    },
]

LIMITATIONS = [
    "CBOM/SBOM presence does not prove that a cryptographic module is deployed or invoked.",
    "A FIPS label, provider name, library version, or enabled-mode signal is not a CMVP validation.",
    "The exact module boundary, version, operational environment, approved mode, and certificate must be verified.",
    "Risk rating, scope, vendor dependency, milestones, and POA&M status require CSP, assessor, and AO review.",
]

FALSE_VALUES = {"0", "false", "no", "off", "disabled", "not-validated", "not validated"}
TRUE_VALUES = {"1", "true", "yes", "on", "enabled", "validated"}
UNKNOWN_MARKERS = (
    "unknown",
    "undetermined",
    "not assessed",
    "not-assessed",
    "pending",
    "unverified",
    "not collected",
    "inaccessible",
    "not determined",
)
NOT_APPLICABLE_VALUES = {"not-applicable", "not applicable", "n/a", "na"}

EXPLICIT_1403_KEYS = {
    "fedramp:meets-fips-140-3",
    "fedramp:fips-140-3-compliant",
    "fedramp:fips:140-3-status",
    "fedramp:fips:overall-compliant",
}
GENERAL_FIPS_RESULT_KEYS = {
    "fedramp:fips-result",
    "fedramp:fips-compliant",
    "fedramp:fips-validated",
}

RULES: dict[str, dict[str, Any]] = {
    "FIPS1403-001": {
        "gap_code": "legacy_140_2_transition",
        "assertion_state": "likely_gap",
        "title": "FIPS 140-2 module requires FIPS 140-3 migration validation",
        "weakness": (
            "Catalog evidence identifies FIPS 140-2 without sufficient evidence of an active, "
            "deployment-matched FIPS 140-3 validation."
        ),
        "risk_rationale": (
            "FIPS 140-2 validations move to the CMVP Historical List after 2026-09-21. "
            "Historical use may continue only for existing systems and FedRAMP directs CSPs to "
            "track the residual risk while migrating."
        ),
        "remediation": (
            "Confirm the deployed cryptographic boundary and existing/new-system status; identify "
            "an active FIPS 140-3 certificate and security policy; migrate through the applicable "
            "significant-change process; retain runtime proof of approved-mode operation."
        ),
        "proposed_risk": "Moderate",
        "poam_eligible": True,
    },
    "FIPS1403-002": {
        "gap_code": "explicit_140_3_negative",
        "assertion_state": "likely_gap",
        "title": "FIPS 140-3 requirement is explicitly unmet",
        "weakness": (
            "Normalized source evidence explicitly declares that the subject does not meet the "
            "FIPS 140-3 requirement or is not validated."
        ),
        "risk_rationale": (
            "If the declaration describes an in-scope deployed cryptographic module, SC-13 evidence "
            "is incomplete and the exposure should remain open until remediated or dispositioned."
        ),
        "remediation": (
            "Validate production scope, replace or correctly configure the module with an active "
            "FIPS 140-3 validated implementation, and capture certificate, boundary, environment, "
            "flow/store, and approved-mode evidence."
        ),
        "proposed_risk": "Moderate",
        "poam_eligible": True,
    },
    "FIPS1403-003": {
        "gap_code": "runtime_fips_negative",
        "assertion_state": "likely_gap",
        "title": "Runtime observation indicates FIPS mode is not active",
        "weakness": (
            "A point-in-time FIPS tool observation reports a negative runtime result for an "
            "identified cryptographic library."
        ),
        "risk_rationale": (
            "A deployed module that is not operating in its approved configuration may not provide "
            "the validated cryptographic protection required by SC-13."
        ),
        "remediation": (
            "Re-run the probe in the production-equivalent environment, identify the exact module "
            "and CMVP certificate, enable the validated approved mode, and attach reproducible runtime evidence."
        ),
        "proposed_risk": "Moderate",
        "poam_eligible": True,
    },
    "FIPS1403-004": {
        "gap_code": "conflicting_evidence",
        "assertion_state": "evidence_gap",
        "title": "FIPS 140-3 evidence conflicts within the same catalog subject",
        "weakness": (
            "The catalog contains both positive and negative FIPS 140-3 assertions that cannot be "
            "resolved from inventory evidence alone."
        ),
        "risk_rationale": (
            "Conflicting evidence prevents an assessor from establishing the module, deployment, "
            "and approved-mode state required for SC-13."
        ),
        "remediation": (
            "Correlate evidence to the deployed artifact digest and environment, establish evidence "
            "recency and authority, and obtain an assessor-reviewed module/certificate mapping."
        ),
        "proposed_risk": "To be determined",
        "poam_eligible": False,
    },
    "FIPS1403-005": {
        "gap_code": "runtime_inconclusive",
        "assertion_state": "evidence_gap",
        "title": "Runtime FIPS probe is inconclusive",
        "weakness": (
            "The FIPS probe did not identify the expected library or could not inspect a required "
            "runtime condition; absence of a result is not favorable evidence."
        ),
        "risk_rationale": (
            "The catalog cannot establish whether the deployed cryptographic boundary is validated "
            "and operating in an approved mode."
        ),
        "remediation": (
            "Run an environment-appropriate probe, identify the actual cryptographic provider, and "
            "capture certificate, module version, boundary, configuration, and observation time."
        ),
        "proposed_risk": "To be determined",
        "poam_eligible": False,
    },
    "FIPS1403-006": {
        "gap_code": "insufficient_validation_evidence",
        "assertion_state": "evidence_gap",
        "title": "FIPS 140-3 validation evidence is incomplete",
        "weakness": (
            "FIPS-related evidence is unknown, pending, unverified, or lacks the facts needed to "
            "match a deployed cryptographic boundary to a CMVP certificate."
        ),
        "risk_rationale": (
            "Inventory signals alone cannot substantiate the SC-13 implementation or determine "
            "whether an open vulnerability exists."
        ),
        "remediation": (
            "Collect deployment attestation, module and version, CMVP certificate and security "
            "policy, operational environment, approved-mode configuration, and affected flow/store evidence."
        ),
        "proposed_risk": "To be determined",
        "poam_eligible": False,
    },
}


def _digest(*parts: Any) -> str:
    material = "|".join("" if part is None else str(part).strip() for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _current_assessment_date() -> tuple[date, str]:
    requested = os.environ.get("CBOM_ASSESSMENT_TIMEZONE", "UTC").strip() or "UTC"
    try:
        timezone = ZoneInfo(requested)
        resolved = requested
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
        resolved = "UTC"
    return datetime.now(timezone).date(), resolved


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _is_false(value: Any) -> bool:
    normalized = _normalized(value)
    return normalized in FALSE_VALUES or normalized.startswith("false ")


def _is_true(value: Any) -> bool:
    normalized = _normalized(value)
    return normalized in TRUE_VALUES or normalized.startswith("true ")


def _is_unknown(value: Any) -> bool:
    normalized = _normalized(value)
    return any(marker in normalized for marker in UNKNOWN_MARKERS)


def _mentions(value: Any, standard: str) -> bool:
    normalized = _normalized(value).replace("_", "-")
    alternatives = {
        "140-2": ("140-2", "140 2", "1402"),
        "140-3": ("140-3", "140 3", "1403"),
    }[standard]
    return any(token in normalized for token in alternatives)


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _public_evidence(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        key: observation.get(key)
        for key in (
            "evidence_kind",
            "evidence_id",
            "document_id",
            "occurrence_id",
            "property_name",
            "property_value",
            "component_identity",
            "component_name",
            "component_version",
            "evidence_sha256",
            "observed_at",
            "details",
        )
        if observation.get(key) is not None
    }


def _dedupe_evidence(observations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for observation in observations:
        public = _public_evidence(observation)
        key = (
            public.get("evidence_kind"),
            public.get("property_name"),
            public.get("property_value"),
            public.get("component_identity"),
            public.get("evidence_sha256"),
            public.get("observed_at"),
        )
        unique[key] = public
    return [unique[key] for key in sorted(unique, key=lambda item: tuple(str(v or "") for v in item))]


def _subject_for(
    document: dict[str, Any], evidence: list[dict[str, Any]]
) -> tuple[str, str]:
    component_identities = sorted(
        {
            str(item.get("component_identity"))
            for item in evidence
            if item.get("component_identity")
        }
    )
    if len(component_identities) == 1:
        identity = component_identities[0]
        matching = next(
            (item for item in evidence if item.get("component_identity") == identity),
            {},
        )
        name = matching.get("component_name") or identity
        version = matching.get("component_version")
        return identity, f"{name}@{version}" if version else str(name)

    occurrence_evidence = [item for item in evidence if item.get("occurrence_id") is not None]
    if occurrence_evidence:
        bom_refs = sorted(
            {
                str((item.get("details") or {}).get("bom_ref"))
                for item in occurrence_evidence
                if (item.get("details") or {}).get("bom_ref")
            }
        )
        names = sorted(
            {
                (
                    str(item.get("component_name")),
                    str(item.get("component_version") or ""),
                )
                for item in occurrence_evidence
                if item.get("component_name")
            }
        )
        document_digest = document.get("document_sha256") or document.get("sha256")
        if len(bom_refs) == 1:
            identity = f"component:{document_digest}:{bom_refs[0]}"
            label = names[0] if len(names) == 1 else (bom_refs[0], "")
            return identity, f"{label[0]}@{label[1]}" if label[1] else label[0]
        if len(names) == 1:
            name, version = names[0]
            return f"component:{name}:{version}", f"{name}@{version}" if version else name
        stable_facts = sorted(
            f"{item.get('property_name')}={item.get('property_value')}"
            for item in occurrence_evidence
        )
        identity = _digest("component-evidence", document_digest, *stable_facts)
        return f"component-evidence:{identity}", "Unresolved component boundary"

    artifacts = _safe_list(document.get("artifacts"))
    if artifacts:
        artifact = sorted(
            artifacts,
            key=lambda item: (
                str(item.get("digest") or ""),
                str(item.get("canonical_key") or ""),
            ),
        )[0]
        identity = artifact.get("digest") or artifact.get("canonical_key")
        if identity:
            return f"artifact:{identity}", str(artifact.get("name") or identity)

    digest = document.get("document_sha256") or document.get("sha256") or document["document_id"]
    return f"document:{digest}", f"Document {document['document_id']}"


def _make_finding(
    document: dict[str, Any],
    rule_id: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    rule = RULES[rule_id]
    public_evidence = _dedupe_evidence(evidence)
    subject_identity, subject_name = _subject_for(document, public_evidence)
    finding_key = _digest(
        POLICY_VERSION,
        rule_id,
        subject_identity,
        document.get("document_sha256") or document.get("sha256"),
        *(
            f"{item.get('evidence_kind')}:{item.get('property_name')}:{item.get('property_value')}:{item.get('component_identity')}:{item.get('evidence_sha256')}:{item.get('observed_at')}"
            for item in public_evidence
        ),
    )
    scopes = _safe_list(document.get("scopes"))
    affected_services = sorted(
        {
            f"{scope.get('source_collection')}/{scope.get('service_group')}"
            for scope in scopes
            if scope.get("source_collection") and scope.get("service_group")
        }
    )
    return {
        "finding_id": f"FIPSF-{finding_key[:12].upper()}",
        "finding_key": finding_key,
        "rule_id": rule_id,
        "gap_code": rule["gap_code"],
        "assertion_state": rule["assertion_state"],
        "title": rule["title"],
        "weakness": rule["weakness"],
        "risk_rationale": rule["risk_rationale"],
        "remediation": rule["remediation"],
        "proposed_risk": rule["proposed_risk"],
        "poam_eligible": rule["poam_eligible"],
        "subject_identity": subject_identity,
        "subject_name": subject_name,
        "document_id": document["document_id"],
        "document_sha256": document.get("document_sha256") or document.get("sha256"),
        "affected_services": affected_services,
        "scopes": scopes,
        "artifacts": _safe_list(document.get("artifacts")),
        "evidence": public_evidence,
        "control_refs": [
            {"control_id": "SC-13", "basis": "primary"},
            {"control_id": "SC-8(1)", "basis": "conditional-data-in-transit"},
            {"control_id": "SC-28(1)", "basis": "conditional-data-at-rest"},
        ],
        "limitations": list(LIMITATIONS),
        "requires_authorized_assessor_review": True,
    }


def _eligible_component_observations(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_occurrence: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    document_level: list[dict[str, Any]] = []
    for observation in observations:
        occurrence_id = observation.get("occurrence_id")
        if occurrence_id is None:
            document_level.append(observation)
        else:
            by_occurrence[occurrence_id].append(observation)

    eligible = list(document_level)
    for occurrence_rows in by_occurrence.values():
        relevance = [
            row
            for row in occurrence_rows
            if _normalized(row.get("property_name")) == "fedramp:fips:crypto-relevant"
        ]
        explicitly_false = any(_is_false(row.get("property_value")) for row in relevance)
        explicitly_true = any(_is_true(row.get("property_value")) for row in relevance)
        if explicitly_false and not explicitly_true:
            continue
        eligible.extend(occurrence_rows)
    return eligible


def _classify_subject(
    document: dict[str, Any], observations: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    applicable = [
        row
        for row in observations
        if _normalized(row.get("property_name")) != "fedramp:fips:crypto-relevant"
        if _normalized(row.get("property_value")) not in NOT_APPLICABLE_VALUES
    ]

    negative_1403: list[dict[str, Any]] = []
    positive_1403: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    legacy: list[dict[str, Any]] = []
    tool_negative: list[dict[str, Any]] = []
    tool_inconclusive: list[dict[str, Any]] = []
    signals_1403: list[dict[str, Any]] = []

    for row in applicable:
        name = _normalized(row.get("property_name"))
        value = row.get("property_value")
        normalized_value = _normalized(value)
        combined = f"{name} {normalized_value}"
        if _mentions(combined, "140-3"):
            signals_1403.append(row)
        if name in EXPLICIT_1403_KEYS:
            if _is_false(value) or "not-validated" in _normalized(value):
                negative_1403.append(row)
            elif _is_true(value):
                positive_1403.append(row)
        elif name in GENERAL_FIPS_RESULT_KEYS:
            if _is_false(value):
                negative_1403.append(row)
            elif _is_true(value):
                positive_1403.append(row)
        elif _mentions(combined, "140-3"):
            if _is_false(value) or "not-validated" in _normalized(value):
                negative_1403.append(row)
            elif _is_true(value):
                positive_1403.append(row)

        name_mentions_1402 = _mentions(name, "140-2")
        value_mentions_1402 = _mentions(normalized_value, "140-2")
        affirmative_legacy_status = _is_true(value) or normalized_value in {
            "active",
            "historical",
        }
        if value_mentions_1402 or (name_mentions_1402 and affirmative_legacy_status):
            legacy.append(row)
        if _is_unknown(value):
            unknown.append(row)

        if row.get("evidence_kind") == "fips_tool_result" and _is_false(value):
            details = row.get("details") or {}
            library = _normalized(details.get("crypto_library"))
            library_details = _normalized(details.get("crypto_library_details"))
            crypto_version = _normalized(details.get("crypto_version"))
            module_version = _normalized(details.get("fips_module_version"))
            if (
                not library
                or "not found" in library
                or "not found" in library_details
                or library in {"none", "unknown"}
                or not (crypto_version or module_version)
            ):
                tool_inconclusive.append(row)
            else:
                tool_negative.append(row)

    findings: list[dict[str, Any]] = []
    conflicting = bool(positive_1403 and (negative_1403 or legacy or tool_negative))
    if conflicting:
        findings.append(
            _make_finding(
                document,
                "FIPS1403-004",
                negative_1403 + positive_1403 + legacy + tool_negative,
            )
        )
    elif tool_negative:
        findings.append(_make_finding(document, "FIPS1403-003", tool_negative))
    elif negative_1403:
        findings.append(_make_finding(document, "FIPS1403-002", negative_1403))
    elif legacy:
        findings.append(_make_finding(document, "FIPS1403-001", legacy + signals_1403))
    elif tool_inconclusive:
        findings.append(_make_finding(document, "FIPS1403-005", tool_inconclusive))
    elif unknown or positive_1403 or signals_1403:
        findings.append(
            _make_finding(
                document,
                "FIPS1403-006",
                unknown + positive_1403 + signals_1403,
            )
        )

    signals = {
        "has_fips_evidence": bool(applicable),
        "has_positive_1403": bool(positive_1403),
        "has_negative_1403": bool(negative_1403),
        "has_legacy_1402": bool(legacy),
        "has_unknown": bool(unknown),
        "has_1403_signal": bool(signals_1403),
    }
    return findings, signals


def _classify_document(
    document: dict[str, Any], observations: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    active = _eligible_component_observations(observations)
    partitions: dict[tuple[str, Any], list[dict[str, Any]]] = defaultdict(list)
    for row in active:
        occurrence_id = row.get("occurrence_id")
        key = ("document", None) if occurrence_id is None else ("occurrence", occurrence_id)
        partitions[key].append(row)

    aggregate = {
        "has_fips_evidence": False,
        "has_positive_1403": False,
        "has_negative_1403": False,
        "has_legacy_1402": False,
        "has_unknown": False,
        "has_1403_signal": False,
    }
    findings: list[dict[str, Any]] = []
    for key in sorted(partitions, key=lambda item: (item[0], str(item[1] or ""))):
        subject_findings, signals = _classify_subject(document, partitions[key])
        findings.extend(subject_findings)
        for signal_name, present in signals.items():
            aggregate[signal_name] = aggregate[signal_name] or present
    return findings, aggregate


def _build_poam_items(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        if not finding["poam_eligible"]:
            continue
        source_collections = sorted(
            {
                str(scope.get("source_collection"))
                for scope in finding["scopes"]
                if scope.get("source_collection")
            }
        )
        boundary_basis = "source-collections:" + ",".join(source_collections)
        poam_key = _digest(
            "poam-v1",
            finding["gap_code"],
            finding["subject_identity"],
            finding["remediation"],
            boundary_basis,
        )
        groups[poam_key].append(finding)

    items: list[dict[str, Any]] = []
    for poam_key in sorted(groups):
        linked = groups[poam_key]
        first = linked[0]
        scopes = [scope for finding in linked for scope in finding["scopes"]]
        source_paths = sorted(
            {str(scope.get("source_path")) for scope in scopes if scope.get("source_path")}
        )
        source_hashes = sorted(
            {str(scope.get("source_sha256")) for scope in scopes if scope.get("source_sha256")}
        )
        services = sorted(
            {service for finding in linked for service in finding["affected_services"]}
        )
        artifacts_by_identity: dict[str, dict[str, Any]] = {}
        for finding in linked:
            for artifact in finding["artifacts"]:
                identity = str(
                    artifact.get("digest")
                    or artifact.get("canonical_key")
                    or artifact.get("name")
                    or ""
                )
                if identity:
                    artifacts_by_identity[identity] = artifact
        evidence_hashes = sorted(
            {
                str(item.get("evidence_sha256"))
                for finding in linked
                for item in finding["evidence"]
                if item.get("evidence_sha256")
            }
        )
        library_links_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        scope_links_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        for finding in linked:
            finding_libraries: list[dict[str, Any]] = []
            for evidence in finding["evidence"]:
                if not evidence.get("component_identity") and not evidence.get("component_name"):
                    continue
                library = {
                    "component_identity": evidence.get("component_identity"),
                    "name": evidence.get("component_name") or evidence.get("component_identity"),
                    "version": evidence.get("component_version"),
                    "occurrence_id": evidence.get("occurrence_id"),
                    "document_id": finding["document_id"],
                    "evidence_kind": evidence.get("evidence_kind"),
                }
                library_key = (
                    library["component_identity"],
                    library["name"],
                    library["version"],
                    library["occurrence_id"],
                    library["document_id"],
                )
                library_links_by_key[library_key] = library
                finding_libraries.append(library)
            for scope in finding["scopes"]:
                collection = scope.get("source_collection")
                group = scope.get("service_group")
                path = scope.get("source_path")
                if not collection or not group:
                    continue
                link = {
                    "service_record_id": f"document:{finding['document_id']}",
                    "service_record_name": str(path or f"Document {finding['document_id']}").rsplit("/", 1)[-1],
                    "document_id": finding["document_id"],
                    "document_sha256": finding.get("document_sha256"),
                    "source_collection": collection,
                    "service_group": group,
                    "service_group_ref": f"{collection}/{group}",
                    "source_path": path,
                    "source_sha256": scope.get("source_sha256"),
                    "subject_identity": finding["subject_identity"],
                    "subject_name": finding["subject_name"],
                    "libraries": sorted(
                        finding_libraries,
                        key=lambda row: (
                            str(row.get("name") or ""),
                            str(row.get("version") or ""),
                            int(row.get("occurrence_id") or 0),
                        ),
                    ),
                    "finding_ids": [finding["finding_id"]],
                }
                link_key = (
                    link["document_id"],
                    link["service_group_ref"],
                    link["source_path"],
                    link["subject_identity"],
                )
                existing = scope_links_by_key.get(link_key)
                if existing:
                    existing["finding_ids"] = sorted(
                        {*existing["finding_ids"], finding["finding_id"]}
                    )
                    existing_libraries = {
                        (
                            row.get("component_identity"),
                            row.get("occurrence_id"),
                            row.get("document_id"),
                        ): row
                        for row in existing["libraries"]
                    }
                    for library in finding_libraries:
                        existing_libraries[
                            (
                                library.get("component_identity"),
                                library.get("occurrence_id"),
                                library.get("document_id"),
                            )
                        ] = library
                    existing["libraries"] = sorted(
                        existing_libraries.values(),
                        key=lambda row: (
                            str(row.get("name") or ""),
                            str(row.get("version") or ""),
                            int(row.get("occurrence_id") or 0),
                        ),
                    )
                else:
                    scope_links_by_key[link_key] = link
        service_scope_links = [
            scope_links_by_key[key]
            for key in sorted(
                scope_links_by_key,
                key=lambda row: tuple(str(value or "") for value in row),
            )
        ]
        service_records = sorted(
            {
                (link["document_id"], link["service_record_name"], link["source_path"])
                for link in service_scope_links
            },
            key=lambda row: tuple(str(value or "") for value in row),
        )
        items.append(
            {
                "poam_candidate_id": f"FIPS3-{poam_key[:12].upper()}",
                "dedupe_key": poam_key,
                "status": "Draft candidate — authorized review required",
                "ato_boundary": "Unassigned — review required",
                "control_id": "SC-13",
                "title": first["title"],
                "weakness": first["weakness"],
                "risk_rationale": first["risk_rationale"],
                "proposed_risk": first["proposed_risk"],
                "detection_source": "FIPS 140-3 Migration Assessment / CBOM evidence",
                "subject_identity": first["subject_identity"],
                "subject_name": first["subject_name"],
                "remediation_plan": first["remediation"],
                "planned_milestone": (
                    "By 2026-09-21: confirm deployed boundary, certificate/status, owner, "
                    "vendor plan, and significant-change path."
                ),
                "responsible_owner": "Unassigned",
                "original_detection_date": None,
                "scheduled_completion_date": None,
                "vendor_dependency": "Unknown — review required",
                "vendor_check_in_date": None,
                "affected_services": services,
                "affected_service_count": len(services),
                "affected_service_groups": services,
                "affected_service_records": [
                    {
                        "document_id": document_id,
                        "name": name,
                        "source_path": source_path,
                    }
                    for document_id, name, source_path in service_records
                ],
                "affected_service_record_count": len(service_records),
                "affected_libraries": [
                    library_links_by_key[key]
                    for key in sorted(
                        library_links_by_key,
                        key=lambda row: tuple(str(value or "") for value in row),
                    )
                ],
                "affected_library_count": len(library_links_by_key),
                "service_scope_links": service_scope_links,
                "affected_artifacts": [artifacts_by_identity[key] for key in sorted(artifacts_by_identity)],
                "source_paths": source_paths,
                "source_sha256": source_hashes,
                "evidence_sha256": evidence_hashes,
                "linked_finding_ids": sorted(finding["finding_id"] for finding in linked),
                "linked_finding_count": len(linked),
                "rule_ids": sorted({finding["rule_id"] for finding in linked}),
                "gap_codes": sorted({finding["gap_code"] for finding in linked}),
                "policy_version": POLICY_VERSION,
                "dedupe_scope_basis": (
                    "Provisional source-collection boundary; confirm the authoritative ATO "
                    "boundary before accepting consolidation."
                ),
                "comments": (
                    "Candidate generated from normalized inventory evidence. Confirm ATO scope, "
                    "asset identifiers, risk rating, detection date, owner, milestones, and CMVP "
                    "deployment match before inserting into the authoritative FedRAMP POA&M."
                ),
                "limitations": list(LIMITATIONS),
                "requires_authorized_assessor_review": True,
            }
        )
    return items


def build_poam_workstreams(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group asset candidates for triage without asserting an authoritative POA&M merge."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        issue_codes = sorted(item.get("gap_codes") or item.get("rule_ids") or ["unclassified"])
        owner = str(item.get("responsible_owner") or "Unassigned")
        mitigation_date = item.get("milestone_mitigation_date") or item.get(
            "scheduled_completion_date"
        )
        workstream_key = _digest(
            "poam-workstream-v1",
            item.get("policy_version") or POLICY_VERSION,
            ",".join(issue_codes),
            item.get("proposed_risk") or "Unassessed",
            item.get("remediation_plan") or "",
            owner,
            item.get("ato_boundary") or "Unassigned",
            mitigation_date or "date-not-supplied",
        )
        groups[workstream_key].append(item)

    workstreams: list[dict[str, Any]] = []
    for workstream_key in sorted(groups):
        linked = groups[workstream_key]
        first = linked[0]
        services = sorted(
            {service for item in linked for service in item.get("affected_services", [])}
        )
        candidate_ids = sorted(
            str(item["poam_candidate_id"])
            for item in linked
            if item.get("poam_candidate_id")
        )
        subjects = sorted(
            {
                str(item.get("subject_identity"))
                for item in linked
                if item.get("subject_identity")
            }
        )
        issue_codes = sorted(
            {
                str(code)
                for item in linked
                for code in (item.get("gap_codes") or item.get("rule_ids") or [])
            }
        )
        rule_ids = sorted(
            {str(rule) for item in linked for rule in item.get("rule_ids", [])}
        )
        owner = str(first.get("responsible_owner") or "Unassigned")
        mitigation_date = first.get("milestone_mitigation_date") or first.get(
            "scheduled_completion_date"
        )
        risk = str(first.get("proposed_risk") or "Unassessed")
        workstreams.append(
            {
                "workstream_id": f"FIPSW-{workstream_key[:12].upper()}",
                "workstream_key": workstream_key,
                "status": "Proposed consolidation — authorized review required",
                "title": first.get("title"),
                "issue_codes": issue_codes,
                "rule_ids": rule_ids,
                "control_id": first.get("control_id") or "SC-13",
                "proposed_risk": risk,
                "impact_assessment_status": "not_assessed",
                "potential_adverse_impact": None,
                "responsible_owner": owner,
                "ato_boundary": first.get("ato_boundary") or "Unassigned",
                "milestone_mitigation_date": mitigation_date,
                "remediation_plan": first.get("remediation_plan"),
                "candidate_count": len(candidate_ids),
                "subject_count": len(subjects),
                "affected_service_count": len(services),
                "affected_services": services,
                "candidate_ids": candidate_ids,
                "subject_identities": subjects,
                "tags": [
                    *[f"issue:{code}" for code in issue_codes],
                    f"risk:{risk.casefold().replace(' ', '-')}",
                    "impact:not-assessed",
                    f"owner:{owner.casefold().replace(' ', '-')}",
                    f"control:{first.get('control_id') or 'SC-13'}",
                ],
                "merge_decision": "review_required",
                "merge_blockers": [
                    "Confirm one shared technical root cause across every linked subject.",
                    "Confirm the same cryptographic module/boundary and operational environment.",
                    "Confirm the authoritative ATO boundary and accountable owner.",
                    "Confirm one remediation and validation plan can close every linked subject.",
                    "Assess reachability, exploitability, prevalence, mitigation, and potential adverse impact.",
                ],
                "comments": (
                    "Operational issue cluster only. It preserves each asset-level candidate and must "
                    "not replace authoritative POA&M rows until the merge blockers are resolved."
                ),
                "requires_authorized_assessor_review": True,
            }
        )
    return workstreams


def _build_coverage_gap_observations(
    rollups: list[dict[str, Any]],
    *,
    assessment_date: date,
    assessment_run_id: str,
) -> list[dict[str, Any]]:
    """Create non-POA&M analyst observations for missing assessment coverage.

    A missing CBOM/SBOM or missing FIPS evidence is not proof of a technical
    deficiency.  It is still an actionable evidence-collection gap and must be
    visible to the assessor instead of disappearing behind a zero finding count.
    """
    observations: list[tuple[int, dict[str, Any]]] = []
    created_at = f"{assessment_date.isoformat()}T00:00:00+00:00"
    for rollup in rollups:
        documents = int(rollup.get("documents") or 0)
        with_fips = int(rollup.get("documents_with_fips_evidence") or 0)
        without_fips = int(rollup.get("documents_without_fips_evidence") or 0)
        source_files = int(rollup.get("source_files") or 0)
        ingest_issues = int(rollup.get("ingest_issues") or 0)
        if documents == 0:
            priority = 0
            assertion_state = "not_assessable"
            title = "No service inventory evidence is available"
            technical_observation = (
                f"The registered service group has {source_files} source files and zero parsed "
                "CBOM, SBOM, assessment, or tool-summary documents. Its FIPS 140-3 posture "
                "cannot be assessed from the catalog."
            )
            missing = [
                "System-owner attestation confirming the service and ATO-boundary scope",
                "Current CBOM, SBOM, scanner evidence, or tool summary for deployed artifacts",
                "Deployed artifact digest and cryptographic module/boundary inventory",
                "CMVP certificate, operational environment, and approved-mode evidence",
            ]
        elif with_fips == 0:
            priority = 1
            assertion_state = "evidence_gap"
            title = "No FIPS 140-3 assessment evidence is available"
            technical_observation = (
                f"The service group has {documents} parsed documents, but none contains a "
                "usable FIPS/CMVP assertion or runtime observation. Absence of evidence is not "
                "a favorable result."
            )
            missing = [
                "Identification of every in-scope cryptographic data flow and data store",
                "Deployed module name, version, build, artifact digest, and module boundary",
                "CMVP certificate/security policy and operational-environment match",
                "Reproducible approved-mode runtime evidence",
            ]
        elif without_fips > 0:
            priority = 2
            assertion_state = "evidence_gap"
            title = "FIPS 140-3 evidence coverage is incomplete"
            uncovered_label = "document remains" if without_fips == 1 else "documents remain"
            technical_observation = (
                f"FIPS-related evidence is present for {with_fips} of {documents} parsed "
                f"documents; {without_fips} {uncovered_label} without usable FIPS/CMVP evidence."
            )
            missing = [
                "Document-to-deployed-artifact correlation for records without FIPS evidence",
                "Cryptographic boundary and CMVP certificate mapping for uncovered artifacts",
                "Approved-mode runtime evidence for every uncovered in-scope deployment",
            ]
        else:
            continue

        service = str(rollup["service"])
        source_collection, service_group = service.split("/", 1)
        observation_key = _digest(
            POLICY_VERSION,
            "coverage-gap",
            assertion_state,
            service,
            documents,
            with_fips,
            without_fips,
            source_files,
            ingest_issues,
        )
        observations.append(
            (
                priority,
                {
                    "schema_version": "1.0",
                    "observation_id": f"OBS-FIPS3-{observation_key[:12].upper()}",
                    "output_type": "analyst_observation",
                    "assertion_state": assertion_state,
                    "poam_eligibility": False,
                    "title": title,
                    "technical_observation": technical_observation,
                    "scope": {
                        "source_collection": source_collection,
                        "service_groups": [service_group],
                        "ato_boundary": None,
                    },
                    "evidence": [
                        {
                            "evidence_kind": "manual_attestation",
                            "source_collection": source_collection,
                            "service_group": service_group,
                            "locator": f"catalog:service-group/{service}",
                            "claim_supported": (
                                "Catalog coverage counts establish only the presence or absence "
                                "of ingested evidence for this registered service category."
                            ),
                            "evidence_grade": "inventory",
                            "limitations": [
                                "A catalog coverage count does not establish deployment, ATO "
                                "scope, module identity, validation, or compliance."
                            ],
                        }
                    ],
                    "missing_required_facts": missing,
                    "conflict_summary": None,
                    "limitations": list(LIMITATIONS),
                    "assessment_run_id": assessment_run_id,
                    "created_at": created_at,
                    "review": {
                        "requires_authorized_assessor_review": True,
                        "requires_ao_review": True,
                        "requires_system_owner_attestation": True,
                    },
                },
            )
        )
    return [
        row
        for _priority, row in sorted(
            observations,
            key=lambda item: (
                item[0],
                item[1]["scope"]["source_collection"],
                item[1]["scope"]["service_groups"][0],
            ),
        )
    ]


def build_assessment(
    documents: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    *,
    as_of: date | None = None,
    scope: dict[str, str | None] | None = None,
    service_group_inventory: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current_date, assessment_timezone = _current_assessment_date()
    assessment_date = as_of or current_date
    observations_by_document: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        observations_by_document[int(observation["document_id"])].append(observation)

    findings: list[dict[str, Any]] = []
    signal_by_document: dict[int, dict[str, bool]] = {}
    documents_by_id = {int(document["document_id"]): document for document in documents}
    for document_id in sorted(documents_by_id):
        document_findings, signals = _classify_document(
            documents_by_id[document_id], observations_by_document.get(document_id, [])
        )
        findings.extend(document_findings)
        signal_by_document[document_id] = signals

    findings.sort(key=lambda item: (item["rule_id"], item["subject_name"], item["finding_id"]))
    poam_items = _build_poam_items(findings)

    service_rollups: dict[str, dict[str, Any]] = {}
    for inventory_row in service_group_inventory or []:
        collection_slug = inventory_row.get("source_collection")
        group_slug = inventory_row.get("service_group") or inventory_row.get("slug")
        if not collection_slug or not group_slug:
            continue
        service = f"{collection_slug}/{group_slug}"
        service_rollups[service] = {
            "service": service,
            "service_group_name": inventory_row.get("service_group_name")
            or inventory_row.get("display_name")
            or group_slug,
            "source_files": int(inventory_row.get("source_files") or 0),
            "ingest_issues": int(inventory_row.get("ingest_issues") or 0),
            "documents": 0,
            "documents_with_fips_evidence": 0,
            "poam_candidate_findings": 0,
            "needs_review_findings": 0,
            "finding_ids": set(),
        }
    for document_id, document in documents_by_id.items():
        doc_findings = [item for item in findings if item["document_id"] == document_id]
        services = {
            f"{row.get('source_collection')}/{row.get('service_group')}"
            for row in _safe_list(document.get("scopes"))
            if row.get("source_collection") and row.get("service_group")
        }
        for service in services:
            rollup = service_rollups.setdefault(
                service,
                {
                    "service": service,
                    "service_group_name": service.rsplit("/", 1)[-1],
                    "source_files": 0,
                    "ingest_issues": 0,
                    "documents": 0,
                    "documents_with_fips_evidence": 0,
                    "poam_candidate_findings": 0,
                    "needs_review_findings": 0,
                    "finding_ids": set(),
                },
            )
            rollup["documents"] += 1
            if signal_by_document[document_id]["has_fips_evidence"]:
                rollup["documents_with_fips_evidence"] += 1
            for finding in doc_findings:
                rollup["finding_ids"].add(finding["finding_id"])
                if finding["poam_eligible"]:
                    rollup["poam_candidate_findings"] += 1
                else:
                    rollup["needs_review_findings"] += 1

    rollups = []
    for key in sorted(service_rollups):
        rollup = service_rollups[key]
        rollup["finding_count"] = len(rollup.pop("finding_ids"))
        rollup["documents_without_fips_evidence"] = (
            rollup["documents"] - rollup["documents_with_fips_evidence"]
        )
        rollup["evidence_coverage_percent"] = round(
            100 * rollup["documents_with_fips_evidence"] / rollup["documents"], 1
        ) if rollup["documents"] else 0.0
        rollups.append(rollup)
    rollups.sort(
        key=lambda item: (
            -item["poam_candidate_findings"],
            -item["needs_review_findings"],
            item["service"],
        )
    )

    assessment_run_id = "ASSESS-FIPS3-" + _digest(
        POLICY_VERSION,
        assessment_date.isoformat(),
        (scope or {}).get("source_collection"),
        (scope or {}).get("service_group"),
        *(rollup["service"] for rollup in rollups),
    )[:12].upper()
    coverage_gaps = _build_coverage_gap_observations(
        rollups,
        assessment_date=assessment_date,
        assessment_run_id=assessment_run_id,
    )

    eligible = [finding for finding in findings if finding["poam_eligible"]]
    review = [finding for finding in findings if not finding["poam_eligible"]]
    evidence_documents = sum(
        1 for signals in signal_by_document.values() if signals["has_fips_evidence"]
    )
    return {
        "assessment_run_id": assessment_run_id,
        "policy": {
            "policy_version": POLICY_VERSION,
            "assessor_version": ASSESSOR_VERSION,
            "assessment_date": assessment_date.isoformat(),
            "assessment_timezone": assessment_timezone,
            "last_new_system_date": LAST_NEW_SYSTEM_DATE.isoformat(),
            "historical_effective_date": HISTORICAL_EFFECTIVE_DATE.isoformat(),
            "days_until_last_new_system_date": (LAST_NEW_SYSTEM_DATE - assessment_date).days,
            "days_until_historical": (HISTORICAL_EFFECTIVE_DATE - assessment_date).days,
            "authoritative_sources": AUTHORITATIVE_SOURCES,
        },
        "scope": scope or {"source_collection": None, "service_group": None},
        "summary": {
            "service_groups_in_scope": len(rollups),
            "service_groups_without_documents": sum(
                1 for rollup in rollups if not rollup["documents"]
            ),
            "documents_in_scope": len(documents),
            "documents_with_fips_evidence": evidence_documents,
            "documents_without_fips_evidence": len(documents) - evidence_documents,
            "candidate_gap_findings": len(eligible),
            "needs_review_findings": len(review),
            "coverage_gap_observations": len(coverage_gaps),
            "needs_review_observations": len(review) + len(coverage_gaps),
            "not_assessable_service_groups": sum(
                1 for row in coverage_gaps if row["assertion_state"] == "not_assessable"
            ),
            "service_groups_without_fips_evidence": sum(
                1
                for rollup in rollups
                if rollup["documents"] and not rollup["documents_with_fips_evidence"]
            ),
            "service_groups_with_partial_fips_evidence": sum(
                1
                for rollup in rollups
                if rollup["documents_with_fips_evidence"]
                and rollup["documents_without_fips_evidence"]
            ),
            "deduplicated_poam_candidates": len(poam_items),
            "affected_services": len(
                {service for finding in findings for service in finding["affected_services"]}
            ),
        },
        "service_groups": rollups,
        "coverage_gaps": coverage_gaps,
        "findings": findings,
        "poam_items": poam_items,
        "limitations": list(LIMITATIONS),
        "disclaimer": (
            "Decision-support output only. These are candidate findings and draft POA&M rows, "
            "not a FIPS validation, FedRAMP compliance determination, 3PAO conclusion, or AO decision."
        ),
    }


POAM_CSV_FIELDS = [
    "POA&M ID",
    "Controls",
    "Weakness Name",
    "Weakness Description",
    "Detection Source",
    "Status",
    "Risk Rating (Proposed)",
    "Original Detection Date",
    "Scheduled Completion Date",
    "Planned Milestones",
    "Vendor Dependency",
    "Vendor Check-In Date",
    "Responsible Owner",
    "ATO Boundary",
    "Affected Service Groups",
    "Affected Service Records",
    "Affected Libraries",
    "Service-Group Milestones",
    "Affected Assets",
    "Remediation Plan",
    "Evidence SHA-256",
    "Source File SHA-256",
    "Evidence Sources",
    "Dedupe Scope Basis",
    "Rule Version",
    "Comments",
    "Assessor Review Required",
]


def render_poam_csv(items: list[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=POAM_CSV_FIELDS, lineterminator="\r\n")
    writer.writeheader()
    for item in sorted(items, key=lambda row: row["poam_candidate_id"]):
        artifact_names = [
            str(artifact.get("name") or artifact.get("canonical_key") or artifact.get("digest"))
            for artifact in item["affected_artifacts"]
        ]
        writer.writerow(
            {
                "POA&M ID": item["poam_candidate_id"],
                "Controls": item["control_id"],
                "Weakness Name": item["title"],
                "Weakness Description": item["weakness"],
                "Detection Source": item["detection_source"],
                "Status": item["status"],
                "Risk Rating (Proposed)": item["proposed_risk"],
                "Original Detection Date": item["original_detection_date"] or "",
                "Scheduled Completion Date": item["scheduled_completion_date"] or "",
                "Planned Milestones": item["planned_milestone"],
                "Vendor Dependency": item["vendor_dependency"],
                "Vendor Check-In Date": item["vendor_check_in_date"] or "",
                "Responsible Owner": item["responsible_owner"],
                "ATO Boundary": item["ato_boundary"],
                "Affected Service Groups": "; ".join(
                    item.get("affected_service_groups") or item["affected_services"]
                ),
                "Affected Service Records": "; ".join(
                    f"document:{row.get('document_id')}:{row.get('name')}"
                    for row in item.get("affected_service_records", [])
                ),
                "Affected Libraries": "; ".join(
                    f"{row.get('name')}@{row.get('version') or 'unknown'}"
                    for row in item.get("affected_libraries", [])
                ),
                "Service-Group Milestones": "; ".join(
                    f"{row.get('service_group')}:{row.get('delivery_wave', {}).get('label')}:"
                    f"{row.get('delivery_wave', {}).get('farthest_explicit_il2_date') or 'date-not-supplied'}"
                    for row in item.get("milestone_deliverables", [])
                ),
                "Affected Assets": "; ".join(artifact_names),
                "Remediation Plan": item["remediation_plan"],
                "Evidence SHA-256": "; ".join(item["evidence_sha256"]),
                "Source File SHA-256": "; ".join(item["source_sha256"]),
                "Evidence Sources": "; ".join(item["source_paths"]),
                "Dedupe Scope Basis": item["dedupe_scope_basis"],
                "Rule Version": item["policy_version"],
                "Comments": item["comments"],
                "Assessor Review Required": "Yes",
            }
        )
    return output.getvalue()


WORKSTREAM_CSV_FIELDS = [
    "Workstream ID",
    "Status",
    "Issue Tags",
    "Control",
    "Risk (Proposed)",
    "Impact Assessment",
    "Responsible Owner",
    "IL2 Mitigation Date",
    "Asset Candidate Count",
    "Subject Count",
    "Affected Service Groups",
    "Remediation Plan",
    "Merge Confirmation Gates",
    "Linked Candidate IDs",
    "Authorized Review Required",
]


def render_workstream_csv(items: list[dict[str, Any]]) -> str:
    """Render proposed issue clusters for review; never imply an accepted merge."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=WORKSTREAM_CSV_FIELDS, lineterminator="\r\n")
    writer.writeheader()
    for item in sorted(items, key=lambda row: row["workstream_id"]):
        writer.writerow(
            {
                "Workstream ID": item["workstream_id"],
                "Status": item["status"],
                "Issue Tags": "; ".join(item["tags"]),
                "Control": item["control_id"],
                "Risk (Proposed)": item["proposed_risk"],
                "Impact Assessment": item["impact_assessment_status"],
                "Responsible Owner": item["responsible_owner"],
                "IL2 Mitigation Date": item["milestone_mitigation_date"] or "",
                "Asset Candidate Count": item["candidate_count"],
                "Subject Count": item["subject_count"],
                "Affected Service Groups": "; ".join(item["affected_services"]),
                "Remediation Plan": item["remediation_plan"],
                "Merge Confirmation Gates": "; ".join(item["merge_blockers"]),
                "Linked Candidate IDs": "; ".join(item["candidate_ids"]),
                "Authorized Review Required": "Yes",
            }
        )
    return output.getvalue()


PORTFOLIO_POAM_CSV_FIELDS = [
    "Portfolio POA&M ID",
    "Dimension",
    "Status",
    "Control",
    "Condition",
    "Responsible Owners",
    "Scheduled Completion Date",
    "Affected Service Groups",
    "Affected Service Records",
    "Affected Libraries",
    "October Milestone Groups",
    "December Milestone Groups",
    "March Milestone Groups",
    "Linked Candidate IDs",
    "Unclassified Candidate Count",
    "Merge Confirmation Gates",
    "Authorized Review Required",
]


def render_portfolio_poam_csv(items: list[dict[str, Any]]) -> str:
    """Render the two portfolio candidates with scope and milestone traceability."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=PORTFOLIO_POAM_CSV_FIELDS,
        lineterminator="\r\n",
    )
    writer.writeheader()
    for item in sorted(items, key=lambda row: row["portfolio_poam_id"]):
        waves = {row["wave"]: row for row in item.get("milestone_deliverables", [])}

        def wave_groups(wave: str) -> str:
            return "; ".join(
                f"{row.get('service_group')} ({row.get('farthest_explicit_il2_date') or 'date-not-supplied'})"
                for row in waves.get(wave, {}).get("service_groups", [])
            )

        writer.writerow(
            {
                "Portfolio POA&M ID": item["portfolio_poam_id"],
                "Dimension": item["dimension"],
                "Status": item["status"],
                "Control": item["control_id"],
                "Condition": item["condition"],
                "Responsible Owners": "; ".join(item["responsible_owners"]),
                "Scheduled Completion Date": item["scheduled_completion_date"] or "",
                "Affected Service Groups": "; ".join(item["affected_service_groups"]),
                "Affected Service Records": "; ".join(
                    f"document:{row.get('document_id')}:{row.get('name')}"
                    for row in item["affected_service_records"]
                ),
                "Affected Libraries": "; ".join(
                    f"{row.get('name')}@{row.get('version') or 'unknown'}"
                    for row in item["affected_libraries"]
                ),
                "October Milestone Groups": wave_groups("october_2026"),
                "December Milestone Groups": wave_groups("december_2026"),
                "March Milestone Groups": wave_groups("march_2027"),
                "Linked Candidate IDs": "; ".join(item["linked_candidate_ids"]),
                "Unclassified Candidate Count": item["unclassified_candidate_count"],
                "Merge Confirmation Gates": "; ".join(item["merge_blockers"]),
                "Authorized Review Required": "Yes",
            }
        )
    return output.getvalue()
