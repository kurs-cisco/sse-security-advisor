from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


JsonObject = dict[str, Any]


@dataclass(slots=True)
class ArtifactRecord:
    canonical_key: str
    role: str
    artifact_type: str | None = None
    name: str | None = None
    version: str | None = None
    purl: str | None = None
    cpe: str | None = None
    registry: str | None = None
    repository: str | None = None
    tag: str | None = None
    digest: str | None = None
    confidence: float = 1.0
    evidence: JsonObject = field(default_factory=dict)
    extra: JsonObject = field(default_factory=dict)


@dataclass(slots=True)
class ComponentRecord:
    identity_hash: str
    bom_ref: str
    source_bom_ref: str
    name: str
    component_type: str | None = None
    namespace: str | None = None
    version: str | None = None
    purl: str | None = None
    cpe: str | None = None
    publisher: str | None = None
    supplier: str | None = None
    description: str | None = None
    scope: str | None = None
    is_subject: bool = False
    hashes: list[JsonObject] = field(default_factory=list)
    licenses: list[Any] = field(default_factory=list)
    external_references: list[JsonObject] = field(default_factory=list)
    properties: list[JsonObject] = field(default_factory=list)
    crypto_properties: JsonObject | None = None
    evidence: JsonObject | None = None
    raw_extra: JsonObject = field(default_factory=dict)


@dataclass(slots=True)
class DependencyRecord:
    from_ref: str
    to_ref: str
    relationship_type: str = "DEPENDS_ON"
    raw: JsonObject = field(default_factory=dict)


@dataclass(slots=True)
class VulnerabilityRecord:
    vulnerability_id: str
    source_name: str = ""
    source_url: str | None = None
    ratings: list[JsonObject] = field(default_factory=list)
    analysis: JsonObject | None = None
    description: str | None = None
    detail: str | None = None
    advisories: list[JsonObject] = field(default_factory=list)
    properties: list[JsonObject] = field(default_factory=list)
    affects: list[JsonObject] = field(default_factory=list)
    raw: JsonObject = field(default_factory=dict)


@dataclass(slots=True)
class SpdxFileRecord:
    spdx_id: str
    file_name: str | None
    checksums: list[JsonObject] = field(default_factory=list)
    license_concluded: str | None = None
    license_info_in_file: list[str] = field(default_factory=list)
    copyright_text: str | None = None
    raw: JsonObject = field(default_factory=dict)


@dataclass(slots=True)
class ExternalRecord:
    record_type: str
    external_id: str
    data: JsonObject
    artifact_key: str | None = None
    observed_at_text: str | None = None
    provider: str | None = None
    parent_record_type: str | None = None
    parent_external_id: str | None = None


@dataclass(slots=True)
class ParsedDocument:
    document_kind: str
    format_name: str | None
    spec_version: str | None
    serial_number: str | None
    document_version: str | None
    generated_at_text: str | None
    generator: Any = field(default_factory=dict)
    metadata: JsonObject = field(default_factory=dict)
    raw: Any = None
    document_properties: list[tuple[str, JsonObject]] = field(default_factory=list)
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    components: list[ComponentRecord] = field(default_factory=list)
    dependencies: list[DependencyRecord] = field(default_factory=list)
    vulnerabilities: list[VulnerabilityRecord] = field(default_factory=list)
    spdx_files: list[SpdxFileRecord] = field(default_factory=list)
    external_records: list[ExternalRecord] = field(default_factory=list)
    ambiguous_refs: set[str] = field(default_factory=set)
    warnings: list[JsonObject] = field(default_factory=list)


class EmptyDocumentError(ValueError):
    """Raised for a zero-byte or whitespace-only input."""
