from __future__ import annotations

import json
import unittest
from pathlib import Path

from cbom_catalog.target_modules import _public_links, parse_target_module_payload


class TargetModuleTests(unittest.TestCase):
    def test_workspace_source_maps_every_team_and_preserves_assertions(self) -> None:
        source = Path(__file__).parents[2] / "FIPS-140-3-21-sept.json"
        payload = json.loads(source.read_text())

        result = parse_target_module_payload(payload)

        self.assertEqual(result["retrieved"], "2026-09-24")
        self.assertEqual(len(result["teams"]), 39)
        self.assertEqual(len(result["records"]), 76)
        self.assertEqual(len({row["team_key"] for row in result["teams"]}), 39)
        self.assertTrue(all(row["evidence_grade"] == "user_asserted" for row in result["records"]))
        self.assertTrue(all(row["review_required"] for row in result["records"]))
        teams = {row["team_key"]: row for row in result["teams"]}
        self.assertEqual(teams["OPC"]["il2_raw"], "Done")
        self.assertEqual(teams["CONTRAAST"]["il2_raw"], "6-Oct-2026")
        self.assertEqual(teams["KNEX"]["il5_raw"], "4-Nov-2026")
        self.assertEqual(teams["VA"]["il2_raw"], "15-Dec-2026")
        self.assertEqual(teams["RSM-SECURE-CLIENT"]["il2_raw"], "31-Mar-2027")

    def test_pending_status_is_not_upgraded_by_certificate(self) -> None:
        payload = {
            "retrieved": "2026-09-21",
            "teams": [
                {
                    "team": "DP (Data Platform)",
                    "owner": "Owner",
                    "lead": "Lead",
                    "il2_date": "31-Dec-2026",
                    "il5_date": "31-Mar-2027",
                    "modules": [
                        {
                            "module": "OpenSSL",
                            "version": "deployment-build",
                            "target_module": "OpenSSL certificate #4794",
                            "fips_140_3_status": "Pending Certification",
                            "cmvp_cert": "#4794",
                        }
                    ],
                }
            ],
        }

        record = parse_target_module_payload(payload)["records"][0]

        self.assertEqual(record["normalized_status"], "pending_certification")
        self.assertEqual(record["target_disposition"], "cmvp_in_process")
        self.assertEqual(record["current_cmvp_cert"], "#4794")
        self.assertEqual(record["target_cmvp_cert"], "#4794")

    def test_asserted_compliant_is_retained_as_user_asserted(self) -> None:
        payload = {
            "retrieved": "2026-09-21",
            "teams": [
                {
                    "team": "OPC",
                    "modules": [
                        {
                            "module": "CiscoSSL",
                            "fips_140_3_status": "Compliant",
                            "cmvp_cert": "Certificate #4747",
                        }
                    ],
                }
            ],
        }

        record = parse_target_module_payload(payload)["records"][0]

        self.assertEqual(record["normalized_status"], "asserted_compliant")
        self.assertEqual(record["target_disposition"], "active_certificate")
        self.assertIn("requires independent correlation", record["disposition_basis"])

    def test_openssl_pipeline_evidence_is_version_specific(self) -> None:
        target = {
            "current_module": "OpenSSL",
            "current_version": "3.5.7",
            "target_module": None,
            "normalized_status": "pending_certification",
            "current_cmvp_cert": None,
            "target_cmvp_cert": None,
        }
        evidence = [{
            "evidence_key": "openssl-3.5.4-submission",
            "module_name": "OpenSSL FIPS Object Module",
            "module_version": "3.5.4",
        }]

        links = _public_links(target, evidence)

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0][1], "target_public_status")
        self.assertEqual(links[0][2], "contradicts")

    def test_catalog_correlation_matrix_is_complete_and_self_consistent(self) -> None:
        source = Path(__file__).parents[1] / "evidence" / "current-version-correlation-2026-09-21.json"
        payload = json.loads(source.read_text())

        self.assertEqual(len(payload["records"]), 76)
        self.assertTrue(all(row.get("match_basis") for row in payload["records"]))
        for row in payload["records"]:
            if row["catalog_verdict"] not in {"exact_name_version_match", "normalized_name_version_match"}:
                continue
            observed_version = row["observed_component"]["version"]
            self.assertIn(observed_version, row["current_version"])


if __name__ == "__main__":
    unittest.main()
