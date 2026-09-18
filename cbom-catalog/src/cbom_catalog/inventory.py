from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .classify import EXCLUDED_DIRECTORY_NAMES, detect_json_kind, discover_files


def build_inventory(root: Path, limit: int | None = None) -> dict[str, Any]:
    root = root.resolve()
    service_groups = {
        path.name: 0
        for path in root.iterdir()
        if path.is_dir()
        and not path.name.startswith(".")
        and path.name not in EXCLUDED_DIRECTORY_NAMES
    }
    kinds: Counter[str] = Counter()
    specs: Counter[str] = Counter()
    extensions: Counter[str] = Counter()
    component_types: Counter[str] = Counter()
    property_namespaces: Counter[str] = Counter()
    parse_issues: list[dict[str, Any]] = []
    hashes: defaultdict[str, list[str]] = defaultdict(list)
    total_bytes = 0
    total_components = 0
    files = list(discover_files(root))
    if limit is not None:
        files = files[:limit]

    for path in files:
        relative = path.relative_to(root)
        service_group = relative.parts[0] if len(relative.parts) > 1 else "(root)"
        service_groups[service_group] = service_groups.get(service_group, 0) + 1
        content = path.read_bytes()
        total_bytes += len(content)
        extensions[path.suffix.lower() or "(none)"] += 1
        digest = hashlib.sha256(content).hexdigest()
        hashes[digest].append(relative.as_posix())
        if not content.strip():
            kinds["empty"] += 1
            parse_issues.append(
                {"path": relative.as_posix(), "code": "empty_file", "message": "File is empty"}
            )
            continue
        if path.suffix.lower() == ".csv":
            kinds["crypto_inventory_csv"] += 1
            continue
        try:
            value = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            kinds["invalid_json"] += 1
            parse_issues.append(
                {"path": relative.as_posix(), "code": "invalid_json", "message": str(exc)}
            )
            continue

        kind, _, spec = detect_json_kind(value)
        kinds[kind] += 1
        if spec:
            specs[f"{kind}:{spec}"] += 1
        if kind == "cyclonedx" and isinstance(value, dict):
            components = value.get("components") if isinstance(value.get("components"), list) else []
            total_components += len(components)
            for component in components:
                if not isinstance(component, dict):
                    continue
                component_types[str(component.get("type") or "(missing)")] += 1
                for prop in component.get("properties") or []:
                    if not isinstance(prop, dict) or not prop.get("name"):
                        continue
                    name = str(prop["name"])
                    namespace = name.split(":", 1)[0] if ":" in name else "(none)"
                    property_namespaces[namespace] += 1

    duplicates = [
        {"sha256": digest, "paths": paths}
        for digest, paths in sorted(hashes.items())
        if len(paths) > 1
    ]
    return {
        "root": str(root),
        "total_files": len(files),
        "total_bytes": total_bytes,
        "extensions": dict(sorted(extensions.items())),
        "service_groups": dict(
            sorted(service_groups.items(), key=lambda item: (-item[1], item[0].casefold()))
        ),
        "document_kinds": dict(sorted(kinds.items())),
        "spec_versions": dict(sorted(specs.items())),
        "cyclonedx_component_count": total_components,
        "component_types": dict(component_types.most_common()),
        "property_namespaces": dict(property_namespaces.most_common()),
        "duplicate_content_groups": duplicates,
        "issues": parse_issues,
    }
