from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "cbom-catalog",
    "graphify-out",
}
SUPPORTED_SUFFIXES = {".json", ".csv"}


def discover_files(root: Path) -> Iterable[Path]:
    """Yield supported corpus files in stable order, excluding generated outputs."""
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts[:-1]
        if any(part in EXCLUDED_DIRECTORY_NAMES or part.startswith(".") for part in relative_parts):
            continue
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path


def media_type_for(path: Path) -> str:
    if path.suffix.lower() == ".json":
        return "application/json"
    if path.suffix.lower() == ".csv":
        return "text/csv"
    return "application/octet-stream"


def detect_json_kind(value: Any) -> tuple[str, str | None, str | None]:
    """Return (document_kind, format_name, spec_version)."""
    if not isinstance(value, dict):
        return "unknown_json", "JSON", None

    if value.get("bomFormat") == "CycloneDX":
        return "cyclonedx", "CycloneDX", _text(value.get("specVersion"))
    if _text(value.get("spdxVersion"), "").startswith("SPDX-"):
        version = _text(value.get("spdxVersion"))
        return "spdx", "SPDX", version.removeprefix("SPDX-") if version else None
    if isinstance(value.get("assessment-results"), dict):
        return "oscal_assessment_results", "OSCAL", None
    if isinstance(value.get("images"), list):
        return "cbom_generation_summary", "CBOM summary", None
    if (
        isinstance(value.get("results"), list)
        and ("product_pid" in value or "manifest" in value or "generated_at" in value)
    ):
        return "scan_index", "scan-index", _text(value.get("schema"))
    if "result" in value and "image" in value and "tool" in value:
        return "fips_tool_report", _text(value.get("tool"), "tool-report"), None
    return "unknown_json", "JSON", None


def _text(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    return str(value)

