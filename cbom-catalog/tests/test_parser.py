from __future__ import annotations

import json
import unittest
from pathlib import Path

from cbom_catalog.parser import parse_path


class ParserTests(unittest.TestCase):
    def parse_json(self, value: object, filename: str = "test.json"):
        return parse_path(Path(filename), json.dumps(value).encode())

    def test_cyclonedx_15_and_crypto_extensions_are_preserved(self) -> None:
        parsed = self.parse_json(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "serialNumber": "urn:uuid:test",
                "version": 1,
                "metadata": {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "tools": {"components": [{"name": "syft", "version": "1"}]},
                    "component": {
                        "bom-ref": "root",
                        "type": "container",
                        "name": "registry.example/app",
                        "version": "1.2.3",
                    },
                },
                "components": [
                    {
                        "bom-ref": "crypto-1",
                        "type": "cryptographic-asset",
                        "name": "certificate",
                        "properties": [{"name": "fedramp:fips:status", "value": "validated"}],
                        "cryptoProperties": {
                            "assetType": "certificate",
                            "certificateProperties": {"subjectName": "CN=test"},
                        },
                        "components": [
                            {
                                "bom-ref": "nested-lib",
                                "type": "library",
                                "name": "nested-lib",
                                "version": "2.0",
                            }
                        ],
                    }
                ],
                "dependencies": [{"ref": "root", "dependsOn": ["crypto-1"]}],
                "vulnerabilities": [
                    {"id": "CVE-2026-0001", "source": {"name": "NVD"}, "affects": [{"ref": "crypto-1"}]}
                ],
            }
        )
        self.assertEqual(parsed.document_kind, "cyclonedx")
        self.assertEqual(parsed.spec_version, "1.5")
        self.assertEqual(len(parsed.components), 3)
        self.assertEqual(parsed.components[1].crypto_properties["assetType"], "certificate")
        self.assertTrue(
            any(
                edge.relationship_type == "DEPENDS_ON" and edge.to_ref == "crypto-1"
                for edge in parsed.dependencies
            )
        )
        self.assertTrue(
            any(
                edge.relationship_type == "CONTAINS" and edge.to_ref == "nested-lib"
                for edge in parsed.dependencies
            )
        )
        self.assertEqual(parsed.vulnerabilities[0].vulnerability_id, "CVE-2026-0001")
        self.assertEqual(parsed.artifacts[0].role, "bom-subject")

    def test_spdx_packages_files_and_relationships_map_to_common_records(self) -> None:
        parsed = self.parse_json(
            {
                "spdxVersion": "SPDX-2.3",
                "SPDXID": "SPDXRef-DOCUMENT",
                "name": "demo",
                "documentNamespace": "https://example.test/spdx/demo",
                "creationInfo": {
                    "created": "2026-01-01T00:00:00Z",
                    "creators": ["Tool: scanner-1"],
                },
                "documentDescribes": ["SPDXRef-Package-app"],
                "packages": [
                    {
                        "SPDXID": "SPDXRef-Package-app",
                        "name": "app",
                        "versionInfo": "1.0",
                        "primaryPackagePurpose": "APPLICATION",
                        "externalRefs": [
                            {
                                "referenceType": "purl",
                                "referenceLocator": "pkg:generic/app@1.0",
                            }
                        ],
                        "licenseDeclared": "Apache-2.0",
                    }
                ],
                "files": [{"SPDXID": "SPDXRef-File-a", "fileName": "a.txt"}],
                "relationships": [
                    {
                        "spdxElementId": "SPDXRef-DOCUMENT",
                        "relationshipType": "describes",
                        "relatedSpdxElement": "SPDXRef-Package-app",
                    }
                ],
            }
        )
        self.assertEqual(parsed.document_kind, "spdx")
        self.assertEqual(parsed.spec_version, "2.3")
        self.assertTrue(parsed.components[0].is_subject)
        self.assertEqual(parsed.components[0].component_type, "application")
        self.assertEqual(parsed.components[0].purl, "pkg:generic/app@1.0")
        self.assertEqual(parsed.spdx_files[0].spdx_id, "SPDXRef-File-a")
        self.assertEqual(parsed.dependencies[0].relationship_type, "DESCRIBES")

    def test_summary_scan_index_fips_oscal_and_csv_are_distinct(self) -> None:
        summary = self.parse_json(
            {"images": [{"id": "example/app_1", "components": 3, "enriched": True}]}
        )
        self.assertEqual(summary.document_kind, "cbom_generation_summary")
        self.assertEqual(summary.external_records[0].record_type, "cbom_generation_summary_image")

        scan = self.parse_json(
            {
                "generated_at": "2026-01-01T00:00:00Z",
                "product_pid": "BAP",
                "results": [
                    {
                        "artifact": {
                            "ref": "service/a",
                            "digest": "sha256:" + "a" * 64,
                            "type": "container",
                        }
                    }
                ],
            }
        )
        self.assertEqual(scan.document_kind, "scan_index")
        self.assertTrue(scan.artifacts[0].canonical_key.startswith("oci:sha256:"))

        fips = self.parse_json(
            {"image": "example/app:1", "tool": "FipsChecker", "status": "complete", "result": {"ok": True}}
        )
        self.assertEqual(fips.document_kind, "fips_tool_report")
        self.assertEqual(fips.external_records[0].provider, "FipsChecker")

        oscal = self.parse_json(
            {
                "assessment-results": {
                    "uuid": "assessment",
                    "metadata": {
                        "version": "1",
                        "last-modified": "2026-01-01T00:00:00Z",
                        "props": [
                            {"name": "tool-name", "value": "FedRAMP Toolkit"},
                            {"name": "tool-version", "value": "1.2.3"},
                        ],
                    },
                    "results": [
                        {
                            "uuid": "result",
                            "props": [
                                {
                                    "name": "image-name",
                                    "value": "registry.example/app@sha256:" + "b" * 64,
                                },
                                {"name": "resource-type", "value": "container"},
                            ],
                            "observations": [{"uuid": "observation"}],
                            "findings": [],
                        }
                    ],
                }
            }
        )
        self.assertEqual(oscal.document_kind, "oscal_assessment_results")
        self.assertEqual({record.record_type for record in oscal.external_records}, {"oscal_result", "oscal_observation"})
        self.assertEqual(oscal.generator["tool_name"], "FedRAMP Toolkit")
        self.assertEqual(len(oscal.artifacts), 1)
        self.assertEqual(oscal.external_records[0].artifact_key, oscal.artifacts[0].canonical_key)
        observation = next(
            record
            for record in oscal.external_records
            if record.record_type == "oscal_observation"
        )
        self.assertEqual(observation.parent_record_type, "oscal_result")
        self.assertEqual(observation.parent_external_id, "result")

        csv_data = b"component,component_type,crypto_library\nservice/a,Go service,crypto/tls\n"
        csv_parsed = parse_path(Path("crypto.csv"), csv_data)
        self.assertEqual(csv_parsed.document_kind, "crypto_inventory_csv")
        self.assertEqual(csv_parsed.external_records[0].data["crypto_library"], "crypto/tls")

    def test_duplicate_bom_refs_are_preserved_but_marked_ambiguous(self) -> None:
        parsed = self.parse_json(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "components": [
                    {"bom-ref": "same", "type": "library", "name": "one"},
                    {"bom-ref": "same", "type": "library", "name": "two"},
                ],
                "dependencies": [{"ref": "same", "dependsOn": ["elsewhere"]}],
            }
        )
        self.assertEqual({component.source_bom_ref for component in parsed.components}, {"same"})
        self.assertEqual(len({component.bom_ref for component in parsed.components}), 2)
        self.assertEqual(parsed.ambiguous_refs, {"same"})
        self.assertTrue(any(warning["code"] == "duplicate_bom_ref" for warning in parsed.warnings))


if __name__ == "__main__":
    unittest.main()
