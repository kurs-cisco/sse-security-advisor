from __future__ import annotations

import unittest
from pathlib import Path

from cbom_catalog.parser import parse_path


WORKSPACE = Path(__file__).resolve().parents[2]
CORPUS = WORKSPACE / "SSE_CBOMS"


@unittest.skipUnless(CORPUS.exists(), "workspace corpus is not present")
class WorkspaceSampleTests(unittest.TestCase):
    def test_cnhe_cyclonedx_and_summary(self) -> None:
        cbom = parse_path(CORPUS / "CNHE" / "cnhe-cortex-fips_0.1.121.698F-cbom.cdx.json")
        summary = parse_path(CORPUS / "CNHE" / "cbom-generation-summary.json")
        self.assertEqual(cbom.spec_version, "1.6")
        self.assertGreater(len(cbom.components), 10)
        self.assertEqual(summary.document_kind, "cbom_generation_summary")

    def test_auxiliary_formats(self) -> None:
        fips = parse_path(CORPUS / "LANDERS" / "lan-4746-fpa-fips-live-reloader.json")
        oscal = parse_path(CORPUS / "FROUTER" / "frouter-vm-cbom-oscal.json")
        scan = parse_path(CORPUS / "ZTA-BAP" / "scan-index.json")
        csv_inventory = parse_path(CORPUS / "ZTA-CALP" / "cbom_clap_crypto.csv")
        self.assertEqual(fips.document_kind, "fips_tool_report")
        self.assertEqual(oscal.document_kind, "oscal_assessment_results")
        self.assertEqual(scan.document_kind, "scan_index")
        self.assertEqual(csv_inventory.document_kind, "crypto_inventory_csv")
        self.assertTrue(oscal.artifacts)
        self.assertTrue(oscal.external_records[0].artifact_key)

    def test_generator_shapes_and_cyclonedx_17(self) -> None:
        syft = parse_path(CORPUS / "CNHE" / "cnhe-cortex-fips_0.1.121.698F-cbom.cdx.json")
        tool_array = parse_path(CORPUS / "SWG-PROXY" / "cbom-speedtest-2026-09-08.json")
        version_17 = parse_path(
            CORPUS / "Download Service" / "download_service-stage-cbom.json"
        )
        self.assertIsInstance(syft.generator, dict)
        self.assertIsInstance(tool_array.generator, list)
        self.assertEqual(version_17.spec_version, "1.7")
        self.assertTrue(version_17.dependencies)
        self.assertTrue(
            any(record.record_type == "cyclonedx_annotation" for record in version_17.external_records)
        )


if __name__ == "__main__":
    unittest.main()
