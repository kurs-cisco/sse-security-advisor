from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .classify import detect_json_kind
from .records import (
    ArtifactRecord,
    ComponentRecord,
    DependencyRecord,
    EmptyDocumentError,
    ExternalRecord,
    ParsedDocument,
    SpdxFileRecord,
    VulnerabilityRecord,
)


VALID_CYCLONEDX_COMPONENT_TYPES = {
    "application",
    "container",
    "cryptographic-asset",
    "data",
    "device",
    "device-driver",
    "file",
    "firmware",
    "framework",
    "library",
    "machine-learning-model",
    "operating-system",
    "platform",
}
STANDARD_CDX_COMPONENT_KEYS = {
    "bom-ref",
    "type",
    "mime-type",
    "supplier",
    "manufacturer",
    "author",
    "publisher",
    "group",
    "name",
    "version",
    "description",
    "scope",
    "hashes",
    "licenses",
    "copyright",
    "cpe",
    "purl",
    "swid",
    "modified",
    "pedigree",
    "externalReferences",
    "properties",
    "components",
    "evidence",
    "releaseNotes",
    "modelCard",
    "data",
    "cryptoProperties",
    "tags",
    "signature",
}
SHA256_REF = re.compile(r"sha256:[0-9a-fA-F]{64}")


def parse_path(path: Path, content: bytes | None = None) -> ParsedDocument:
    content = path.read_bytes() if content is None else content
    if not content.strip():
        raise EmptyDocumentError(f"{path} is empty")
    if path.suffix.lower() == ".csv":
        return _parse_crypto_csv(content)

    value = json.loads(content.decode("utf-8-sig"))
    kind, format_name, spec_version = detect_json_kind(value)
    if kind == "cyclonedx":
        return _parse_cyclonedx(value)
    if kind == "spdx":
        return _parse_spdx(value)
    if kind == "oscal_assessment_results":
        return _parse_oscal(value)
    if kind == "cbom_generation_summary":
        return _parse_generation_summary(value)
    if kind == "scan_index":
        return _parse_scan_index(value)
    if kind == "fips_tool_report":
        return _parse_fips_report(value)
    return ParsedDocument(
        document_kind=kind,
        format_name=format_name,
        spec_version=spec_version,
        serial_number=None,
        document_version=None,
        generated_at_text=None,
        metadata={},
        raw=value,
        external_records=[
            ExternalRecord("unknown_json", "root", {"value": value} if not isinstance(value, dict) else value)
        ],
        warnings=[{"code": "unknown_json_shape", "message": "No supported schema signature matched"}],
    )


def _parse_cyclonedx(value: dict[str, Any]) -> ParsedDocument:
    metadata = dict(_object(value.get("metadata")))
    top_level_extra = {
        key: item
        for key, item in value.items()
        if key
        not in {
            "bomFormat",
            "specVersion",
            "serialNumber",
            "version",
            "metadata",
            "components",
            "dependencies",
            "vulnerabilities",
            "services",
            "annotations",
            "properties",
        }
    }
    if top_level_extra:
        metadata["catalog:unmodeled-top-level"] = top_level_extra
    spec_version = _text(value.get("specVersion"))
    parsed = ParsedDocument(
        document_kind="cyclonedx",
        format_name="CycloneDX",
        spec_version=spec_version,
        serial_number=_text(value.get("serialNumber")),
        document_version=_text(value.get("version")),
        generated_at_text=_text(metadata.get("timestamp")),
        generator=metadata.get("tools") or {},
        metadata=metadata,
        raw=value,
    )
    if spec_version not in {"1.5", "1.6", "1.7"}:
        parsed.warnings.append(
            {"code": "unrecognized_cyclonedx_version", "value": spec_version}
        )

    for scope, properties in (
        ("metadata", metadata.get("properties")),
        ("document", value.get("properties")),
    ):
        for prop in _list_of_objects(properties):
            parsed.document_properties.append((scope, prop))

    root_component = metadata.get("component")
    if isinstance(root_component, dict):
        component = _component_from_cdx(root_component, fallback_ref="metadata.component", is_subject=True)
        parsed.components.append(component)
        parsed.artifacts.append(_artifact_from_component(root_component, "bom-subject"))

    seen_refs = {component.bom_ref for component in parsed.components}
    malformed_types: set[str] = set()
    raw_components = value.get("components")
    if raw_components is not None and not isinstance(raw_components, list):
        parsed.warnings.append(
            {"code": "invalid_components_shape", "message": "components must be an array"}
        )
        raw_components = []

    def visit_components(items: list[Any], path_prefix: str, parent_ref: str | None = None) -> None:
        for index, raw_component in enumerate(items):
            item_path = f"{path_prefix}:{index}"
            if not isinstance(raw_component, dict):
                parsed.warnings.append(
                    {
                        "code": "invalid_component_item",
                        "message": "Component array item is not an object",
                        "path": item_path,
                    }
                )
                continue
            component = _component_from_cdx(
                raw_component, fallback_ref=item_path, is_subject=False
            )
            source_ref = component.source_bom_ref
            if component.bom_ref in seen_refs:
                parsed.ambiguous_refs.add(source_ref)
                previous = next(
                    (item for item in parsed.components if item.source_bom_ref == source_ref), None
                )
                if previous is not None:
                    parsed.ambiguous_refs.add(previous.source_bom_ref)
                original_ref = component.bom_ref
                component.bom_ref = f"{component.bom_ref}#duplicate-{item_path.replace(':', '-')}"
                parsed.warnings.append(
                    {"code": "duplicate_bom_ref", "bom_ref": original_ref, "path": item_path}
                )
            seen_refs.add(component.bom_ref)
            if component.component_type and component.component_type not in VALID_CYCLONEDX_COMPONENT_TYPES:
                malformed_types.add(component.component_type)
            parsed.components.append(component)
            if parent_ref:
                parsed.dependencies.append(
                    DependencyRecord(
                        parent_ref,
                        source_ref,
                        "CONTAINS",
                        {"source": "nested-components", "path": item_path},
                    )
                )
            nested = raw_component.get("components")
            if nested is not None and not isinstance(nested, list):
                parsed.warnings.append(
                    {
                        "code": "invalid_nested_components_shape",
                        "message": "Nested components must be an array",
                        "path": item_path,
                    }
                )
            elif isinstance(nested, list):
                visit_components(nested, f"{item_path}.component", source_ref)

    visit_components(raw_components or [], "component")
    if malformed_types:
        parsed.warnings.append(
            {"code": "nonstandard_component_types", "values": sorted(malformed_types)}
        )

    for dependency in _list_of_objects(value.get("dependencies")):
        from_ref = _text(dependency.get("ref"))
        if not from_ref:
            continue
        depends_on = dependency.get("dependsOn") or []
        if not isinstance(depends_on, list):
            parsed.warnings.append(
                {"code": "invalid_depends_on_shape", "bom_ref": from_ref}
            )
            continue
        for to_ref in depends_on:
            if isinstance(to_ref, str):
                parsed.dependencies.append(
                    DependencyRecord(from_ref, to_ref, "DEPENDS_ON", dependency)
                )
            elif to_ref is not None:
                parsed.warnings.append(
                    {"code": "invalid_dependency_ref", "bom_ref": from_ref, "value": to_ref}
                )

    for raw_vulnerability in _list_of_objects(value.get("vulnerabilities")):
        vulnerability_id = _text(raw_vulnerability.get("id"))
        if not vulnerability_id:
            continue
        source = _object(raw_vulnerability.get("source"))
        parsed.vulnerabilities.append(
            VulnerabilityRecord(
                vulnerability_id=vulnerability_id,
                source_name=_text(source.get("name"), "") or "",
                source_url=_text(source.get("url")),
                ratings=_list_of_objects(raw_vulnerability.get("ratings")),
                analysis=_optional_object(raw_vulnerability.get("analysis")),
                description=_text(raw_vulnerability.get("description")),
                detail=_text(raw_vulnerability.get("detail")),
                advisories=_list_of_objects(raw_vulnerability.get("advisories")),
                properties=_list_of_objects(raw_vulnerability.get("properties")),
                affects=_list_of_objects(raw_vulnerability.get("affects")),
                raw=raw_vulnerability,
            )
        )

    for index, service in enumerate(_list_of_objects(value.get("services"))):
        external_id = _text(service.get("bom-ref"), f"service:{index}") or f"service:{index}"
        parsed.external_records.append(
            ExternalRecord("cyclonedx_service", external_id, service)
        )
    for index, annotation in enumerate(_list_of_objects(value.get("annotations"))):
        external_id = _text(annotation.get("bom-ref"), f"annotation:{index}") or f"annotation:{index}"
        parsed.external_records.append(
            ExternalRecord("cyclonedx_annotation", external_id, annotation)
        )
    return parsed


def _component_from_cdx(
    value: dict[str, Any], fallback_ref: str, is_subject: bool
) -> ComponentRecord:
    name = _text(value.get("name"), "unnamed") or "unnamed"
    purl = _text(value.get("purl"))
    cpe = _text(value.get("cpe"))
    component_type = _text(value.get("type"))
    version = _text(value.get("version"))
    namespace = _text(value.get("group"))
    identity_hash = _component_identity_hash(
        purl=purl,
        cpe=cpe,
        component_type=component_type,
        namespace=namespace,
        name=name,
        version=version,
    )
    bom_ref = _text(value.get("bom-ref") or purl, fallback_ref) or fallback_ref
    supplier = value.get("supplier")
    supplier_text = _party_text(supplier)
    extra = {key: item for key, item in value.items() if key not in STANDARD_CDX_COMPONENT_KEYS}
    return ComponentRecord(
        identity_hash=identity_hash,
        bom_ref=bom_ref,
        source_bom_ref=bom_ref,
        name=name,
        component_type=component_type,
        namespace=namespace,
        version=version,
        purl=purl,
        cpe=cpe,
        publisher=_text(value.get("publisher") or value.get("author")),
        supplier=supplier_text,
        description=_text(value.get("description")),
        scope=_text(value.get("scope")),
        is_subject=is_subject,
        hashes=_list_of_objects(value.get("hashes")),
        licenses=list(value.get("licenses") or []),
        external_references=_list_of_objects(value.get("externalReferences")),
        properties=_list_of_objects(value.get("properties")),
        crypto_properties=_optional_object(value.get("cryptoProperties")),
        evidence=_optional_object(value.get("evidence")),
        raw_extra=extra,
    )


def _parse_spdx(value: dict[str, Any]) -> ParsedDocument:
    creation = _object(value.get("creationInfo"))
    document_metadata = {
        key: item
        for key, item in value.items()
        if key not in {"packages", "files", "relationships"}
    }
    parsed = ParsedDocument(
        document_kind="spdx",
        format_name="SPDX",
        spec_version=(_text(value.get("spdxVersion"), "") or "").removeprefix("SPDX-"),
        serial_number=_text(value.get("documentNamespace")),
        document_version=None,
        generated_at_text=_text(creation.get("created")),
        generator={"creators": creation.get("creators") or []},
        metadata=document_metadata,
        raw=value,
    )
    described = {str(item) for item in value.get("documentDescribes") or []}
    for index, package in enumerate(_list_of_objects(value.get("packages"))):
        spdx_id = _text(package.get("SPDXID"), f"SPDXRef-Package-{index}") or f"SPDXRef-Package-{index}"
        purl, cpe = _spdx_external_identities(package.get("externalRefs"))
        name = _text(package.get("name"), "unnamed") or "unnamed"
        version = _text(package.get("versionInfo"))
        component_type = _spdx_component_type(package.get("primaryPackagePurpose"))
        component = ComponentRecord(
            identity_hash=_component_identity_hash(
                purl=purl,
                cpe=cpe,
                component_type=component_type,
                namespace=None,
                name=name,
                version=version,
            ),
            bom_ref=spdx_id,
            source_bom_ref=spdx_id,
            name=name,
            component_type=component_type,
            version=version,
            purl=purl,
            cpe=cpe,
            supplier=_text(package.get("supplier")),
            description=_text(package.get("description") or package.get("summary")),
            is_subject=spdx_id in described,
            hashes=_list_of_objects(package.get("checksums")),
            licenses=_spdx_licenses(package),
            external_references=_list_of_objects(package.get("externalRefs")),
            raw_extra={
                key: item
                for key, item in package.items()
                if key
                not in {
                    "SPDXID",
                    "name",
                    "versionInfo",
                    "supplier",
                    "description",
                    "summary",
                    "checksums",
                    "externalRefs",
                    "licenseConcluded",
                    "licenseDeclared",
                }
            },
        )
        parsed.components.append(component)
        if component.is_subject:
            parsed.artifacts.append(
                _artifact_from_values(
                    role="document-describes",
                    artifact_type=component_type,
                    name=name,
                    version=version,
                    purl=purl,
                    cpe=cpe,
                    evidence={"SPDXID": spdx_id},
                )
            )

    if not parsed.artifacts:
        parsed.artifacts.append(
            _artifact_from_values(
                role="document",
                artifact_type="spdx-document",
                name=_text(value.get("name"), "SPDX document"),
                version=None,
                purl=None,
                cpe=None,
                evidence={"documentNamespace": value.get("documentNamespace")},
            )
        )

    for relationship in _list_of_objects(value.get("relationships")):
        from_ref = _text(relationship.get("spdxElementId"))
        to_ref = _text(relationship.get("relatedSpdxElement"))
        if from_ref and to_ref:
            parsed.dependencies.append(
                DependencyRecord(
                    from_ref=from_ref,
                    to_ref=to_ref,
                    relationship_type=(
                        _text(relationship.get("relationshipType"), "RELATED_TO")
                        or "RELATED_TO"
                    ).upper(),
                    raw=relationship,
                )
            )
    for index, raw_file in enumerate(_list_of_objects(value.get("files"))):
        spdx_id = _text(raw_file.get("SPDXID"), f"SPDXRef-File-{index}") or f"SPDXRef-File-{index}"
        parsed.spdx_files.append(
            SpdxFileRecord(
                spdx_id=spdx_id,
                file_name=_text(raw_file.get("fileName")),
                checksums=_list_of_objects(raw_file.get("checksums")),
                license_concluded=_text(raw_file.get("licenseConcluded")),
                license_info_in_file=[str(item) for item in raw_file.get("licenseInfoInFiles") or []],
                copyright_text=_text(raw_file.get("copyrightText")),
                raw=raw_file,
            )
        )
    return parsed


def _parse_generation_summary(value: dict[str, Any]) -> ParsedDocument:
    parsed = ParsedDocument(
        document_kind="cbom_generation_summary",
        format_name="CBOM summary",
        spec_version=None,
        serial_number=None,
        document_version=None,
        generated_at_text=_text(value.get("generated_at")),
        metadata={key: item for key, item in value.items() if key != "images"},
        raw=value,
    )
    for index, image in enumerate(_list_of_objects(value.get("images"))):
        image_id = _text(image.get("id"), f"image:{index}") or f"image:{index}"
        artifact = _artifact_from_image_reference(image_id, "summary-subject")
        artifact.extra = {"summary": image}
        parsed.artifacts.append(artifact)
        parsed.external_records.append(
            ExternalRecord(
                "cbom_generation_summary_image",
                image_id,
                image,
                artifact_key=artifact.canonical_key,
                observed_at_text=parsed.generated_at_text,
                provider=_text(value.get("generator")),
            )
        )
    return parsed


def _parse_scan_index(value: dict[str, Any]) -> ParsedDocument:
    generated_at = _text(value.get("generated_at"))
    parsed = ParsedDocument(
        document_kind="scan_index",
        format_name="scan-index",
        spec_version=_text(value.get("schema")),
        serial_number=None,
        document_version=None,
        generated_at_text=generated_at,
        generator={"manifest": value.get("manifest"), "product_pid": value.get("product_pid")},
        metadata={key: item for key, item in value.items() if key != "results"},
        raw=value,
    )
    for index, result in enumerate(_list_of_objects(value.get("results"))):
        raw_artifact = _object(result.get("artifact"))
        reference = _text(raw_artifact.get("ref") or raw_artifact.get("name"), f"result:{index}") or f"result:{index}"
        digest = _text(raw_artifact.get("digest"))
        artifact = _artifact_from_values(
            role="scan-subject",
            artifact_type=_text(raw_artifact.get("type")),
            name=reference,
            version=_text(raw_artifact.get("version")),
            purl=_text(raw_artifact.get("purl")),
            cpe=_text(raw_artifact.get("cpe")),
            digest=digest,
            evidence={"artifact": raw_artifact},
        )
        parsed.artifacts.append(artifact)
        external_id = _text(result.get("id"), f"scan-result:{index}") or f"scan-result:{index}"
        parsed.external_records.append(
            ExternalRecord(
                "scan_index_result",
                external_id,
                result,
                artifact_key=artifact.canonical_key,
                observed_at_text=generated_at,
                provider=_text(value.get("product_pid")),
            )
        )
    return parsed


def _parse_fips_report(value: dict[str, Any]) -> ParsedDocument:
    image = _text(value.get("image"), "unknown-image") or "unknown-image"
    artifact = _artifact_from_image_reference(image, "fips-assessment-subject")
    return ParsedDocument(
        document_kind="fips_tool_report",
        format_name=_text(value.get("tool"), "tool-report"),
        spec_version=None,
        serial_number=None,
        document_version=_text(value.get("tool_version")),
        generated_at_text=_text(value.get("generated_at") or value.get("timestamp")),
        generator={"tool": value.get("tool"), "container_runtime": value.get("container_runtime")},
        metadata={"status": value.get("status")},
        raw=value,
        artifacts=[artifact],
        external_records=[
            ExternalRecord(
                "fips_tool_result",
                "result",
                _object(value.get("result")),
                artifact_key=artifact.canonical_key,
                observed_at_text=_text(value.get("generated_at") or value.get("timestamp")),
                provider=_text(value.get("tool")),
            )
        ],
    )


def _parse_oscal(value: dict[str, Any]) -> ParsedDocument:
    assessment = _object(value.get("assessment-results"))
    metadata = _object(assessment.get("metadata"))
    metadata_props = _props_by_name(metadata.get("props"))
    tool_name = metadata_props.get("tool-name")
    tool_version = metadata_props.get("tool-version")
    parsed = ParsedDocument(
        document_kind="oscal_assessment_results",
        format_name="OSCAL",
        spec_version=_text(value.get("oscal-version") or assessment.get("oscal-version")),
        serial_number=_text(assessment.get("uuid")),
        document_version=_text(metadata.get("version")),
        generated_at_text=_text(metadata.get("last-modified")),
        generator={
            "tools": metadata.get("tools") or [],
            "tool_name": tool_name,
            "tool_version": tool_version,
            "source_command": metadata_props.get("source-command"),
        },
        metadata=metadata,
        raw=value,
    )
    artifacts_by_key: dict[str, ArtifactRecord] = {}
    for result_index, result in enumerate(_list_of_objects(assessment.get("results"))):
        result_id = _text(result.get("uuid"), f"result:{result_index}") or f"result:{result_index}"
        result_props = _props_by_name(result.get("props"))
        image_name = result_props.get("image-name")
        resource_type = result_props.get("resource-type")
        if not image_name:
            local_definitions = _object(
                result.get("local-definitions") or result.get("localDefinitions")
            )
            inventory_items = _list_of_objects(local_definitions.get("inventory-items"))
            if inventory_items:
                inventory_props = _props_by_name(inventory_items[0].get("props"))
                image_name = inventory_props.get("image-name")
                resource_type = resource_type or inventory_props.get("asset-type")
        artifact_key: str | None = None
        if image_name:
            if (resource_type or "").casefold() == "container":
                artifact = _artifact_from_image_reference(image_name, "oscal-assessment-subject")
            else:
                artifact = _artifact_from_values(
                    role="oscal-assessment-subject",
                    artifact_type=resource_type or "assessment-subject",
                    name=image_name,
                    version=None,
                    purl=None,
                    cpe=None,
                    evidence={"result_uuid": result_id},
                )
            artifacts_by_key.setdefault(artifact.canonical_key, artifact)
            artifact_key = artifact.canonical_key
        parsed.external_records.append(
            ExternalRecord(
                "oscal_result",
                result_id,
                result,
                artifact_key=artifact_key,
                observed_at_text=_text(result.get("start") or result.get("end")),
                provider=tool_name or "OSCAL",
            )
        )
        for section in ("observations", "findings", "risks", "attestations"):
            for item_index, item in enumerate(_list_of_objects(result.get(section))):
                item_id = _text(item.get("uuid"), f"{result_id}:{section}:{item_index}")
                parsed.external_records.append(
                    ExternalRecord(
                        f"oscal_{section[:-1] if section.endswith('s') else section}",
                        item_id or f"{result_id}:{section}:{item_index}",
                        {"parent_result": result_id, **item},
                        artifact_key=artifact_key,
                        observed_at_text=_text(item.get("collected") or result.get("start")),
                        provider=tool_name or "OSCAL",
                        parent_record_type="oscal_result",
                        parent_external_id=result_id,
                    )
                )
    parsed.artifacts = list(artifacts_by_key.values())
    return parsed


def _parse_crypto_csv(content: bytes) -> ParsedDocument:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(row) for row in reader]
    parsed = ParsedDocument(
        document_kind="crypto_inventory_csv",
        format_name="CSV",
        spec_version=None,
        serial_number=None,
        document_version=None,
        generated_at_text=None,
        generator={},
        metadata={"columns": reader.fieldnames or [], "row_count": len(rows)},
        raw=rows,
    )
    artifacts_by_key: dict[str, ArtifactRecord] = {}
    for index, row in enumerate(rows, start=2):
        component_name = _text(row.get("component"), "unknown-component") or "unknown-component"
        artifact = _artifact_from_values(
            role="crypto-inventory-subject",
            artifact_type=_text(row.get("component_type")),
            name=component_name,
            version=None,
            purl=None,
            cpe=None,
            evidence={"csv_row": index},
        )
        artifacts_by_key.setdefault(artifact.canonical_key, artifact)
        parsed.external_records.append(
            ExternalRecord(
                "crypto_inventory_row",
                f"row:{index}",
                row,
                artifact_key=artifact.canonical_key,
                provider="curated-csv",
            )
        )
    parsed.artifacts = list(artifacts_by_key.values())
    return parsed


def _artifact_from_component(value: dict[str, Any], role: str) -> ArtifactRecord:
    return _artifact_from_values(
        role=role,
        artifact_type=_text(value.get("type")),
        name=_text(value.get("name")),
        version=_text(value.get("version")),
        purl=_text(value.get("purl")),
        cpe=_text(value.get("cpe")),
        evidence={"bom-ref": value.get("bom-ref")},
    )


def _artifact_from_image_reference(reference: str, role: str) -> ArtifactRecord:
    name, registry, repository, tag, digest = _split_image_reference(reference)
    return _artifact_from_values(
        role=role,
        artifact_type="container",
        name=name,
        version=tag,
        purl=None,
        cpe=None,
        registry=registry,
        repository=repository,
        tag=tag,
        digest=digest,
        evidence={"image_reference": reference},
    )


def _artifact_from_values(
    *,
    role: str,
    artifact_type: str | None,
    name: str | None,
    version: str | None,
    purl: str | None,
    cpe: str | None,
    registry: str | None = None,
    repository: str | None = None,
    tag: str | None = None,
    digest: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> ArtifactRecord:
    if name and artifact_type == "container" and not any((registry, repository, tag, digest)):
        name, registry, repository, inferred_tag, inferred_digest = _split_image_reference(name)
        tag = tag or inferred_tag
        digest = digest or inferred_digest
        version = version or tag
    digest = digest or _find_digest(name) or _find_digest(version)
    if digest:
        canonical_key = f"oci:{digest.lower()}"
        identity_basis = "digest"
        confidence = 1.0
    elif purl:
        canonical_key = f"purl:{purl}"
        identity_basis = "purl"
        confidence = 1.0
    elif cpe:
        canonical_key = f"cpe:{cpe}"
        identity_basis = "cpe"
        confidence = 0.9
    else:
        canonical_key = f"name:{(name or 'unknown').strip().casefold()}@{(version or '').strip()}"
        identity_basis = "name-version"
        confidence = 0.6
    artifact_evidence = dict(evidence or {})
    artifact_evidence.setdefault("identity_basis", identity_basis)
    return ArtifactRecord(
        canonical_key=canonical_key,
        role=role,
        artifact_type=artifact_type,
        name=name,
        version=version,
        purl=purl,
        cpe=cpe,
        registry=registry,
        repository=repository,
        tag=tag,
        digest=digest,
        confidence=confidence,
        evidence=artifact_evidence,
    )


def _component_identity_hash(
    *,
    purl: str | None,
    cpe: str | None,
    component_type: str | None,
    namespace: str | None,
    name: str,
    version: str | None,
) -> str:
    if purl:
        material = f"purl\0{purl.strip()}"
    elif cpe:
        material = f"cpe\0{cpe.strip()}"
    else:
        material = "\0".join(
            (
                "fallback",
                (component_type or "").strip().casefold(),
                (namespace or "").strip().casefold(),
                name.strip().casefold(),
                (version or "").strip(),
            )
        )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _split_image_reference(reference: str) -> tuple[str, str | None, str | None, str | None, str | None]:
    clean = reference.removeprefix("docker://").strip()
    digest_match = SHA256_REF.search(clean)
    digest = digest_match.group(0) if digest_match else None
    without_digest = clean.split("@", 1)[0]
    slash = without_digest.rfind("/")
    colon = without_digest.rfind(":")
    tag = without_digest[colon + 1 :] if colon > slash else None
    name = without_digest[:colon] if tag else without_digest
    parts = name.split("/")
    registry = parts[0] if len(parts) > 1 and ("." in parts[0] or ":" in parts[0]) else None
    repository = "/".join(parts[1:]) if registry else name
    return name, registry, repository or None, tag, digest


def _find_digest(value: str | None) -> str | None:
    if not value:
        return None
    match = SHA256_REF.search(value)
    return match.group(0) if match else None


def _spdx_external_identities(raw_references: Any) -> tuple[str | None, str | None]:
    purl = None
    cpe = None
    for reference in _list_of_objects(raw_references):
        reference_type = (_text(reference.get("referenceType"), "") or "").casefold()
        locator = _text(reference.get("referenceLocator"))
        if not locator:
            continue
        if reference_type == "purl" or locator.startswith("pkg:"):
            purl = purl or locator
        if "cpe" in reference_type or locator.startswith("cpe:"):
            cpe = cpe or locator
    return purl, cpe


def _spdx_component_type(primary_purpose: Any) -> str:
    purpose = (_text(primary_purpose, "LIBRARY") or "LIBRARY").strip().upper()
    mapping = {
        "APPLICATION": "application",
        "CONTAINER": "container",
        "DEVICE": "device",
        "FILE": "file",
        "FIRMWARE": "firmware",
        "FRAMEWORK": "framework",
        "LIBRARY": "library",
        "OPERATING-SYSTEM": "operating-system",
        "OPERATING_SYSTEM": "operating-system",
        "SOURCE": "file",
    }
    return mapping.get(purpose, purpose.casefold().replace("_", "-"))


def _spdx_licenses(package: dict[str, Any]) -> list[dict[str, Any]]:
    licenses: list[dict[str, Any]] = []
    concluded = _text(package.get("licenseConcluded"))
    declared = _text(package.get("licenseDeclared"))
    if concluded:
        licenses.append({"expression": concluded, "acknowledgement": "concluded"})
    if declared and declared != concluded:
        licenses.append({"expression": declared, "acknowledgement": "declared"})
    return licenses


def _props_by_name(raw_properties: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for prop in _list_of_objects(raw_properties):
        name = _text(prop.get("name"))
        value = _text(prop.get("value"))
        if name and value is not None and name not in result:
            result[name] = value
    return result


def _party_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("url"))
    return str(value)


def property_namespace(name: str) -> str | None:
    return name.split(":", 1)[0] if ":" in name else None


def property_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value).lower() if isinstance(value, bool) else str(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def iter_licenses(raw_licenses: Iterable[Any]) -> Iterable[tuple[str | None, str | None, str | None, str | None, dict[str, Any]]]:
    for raw in raw_licenses:
        normalized = raw if isinstance(raw, dict) else {"expression": str(raw)}
        license_object = normalized.get("license")
        if not isinstance(license_object, dict):
            license_object = {}
        yield (
            _text(license_object.get("id")),
            _text(license_object.get("name")),
            _text(normalized.get("expression")),
            _text(normalized.get("acknowledgement")),
            normalized,
        )


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_object(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _list_of_objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _text(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    return str(value)
