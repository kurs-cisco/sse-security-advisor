from __future__ import annotations

import unittest

from cbom_catalog.fedramp_20x import build_20x_readiness_preview


class Fedramp20xReadinessTests(unittest.TestCase):
    def test_catalog_analysis_cannot_become_a_ver_record(self) -> None:
        preview = build_20x_readiness_preview(
            {
                "assessment_run_id": "INTERNAL-ONLY",
                "assessment_run": None,
                "assessment_contract": {"complete": False},
                "poam_candidate_records": [{"poam_candidate_id": "CANDIDATE"}],
            },
            42,
        )

        self.assertIsNone(preview["assessment_run_id"])
        self.assertEqual(preview["internal_analysis_id"], "INTERNAL-ONLY")
        self.assertEqual(preview["analysis_candidate_count"], 1)
        self.assertEqual(preview["evaluation_record_count"], 0)
        self.assertFalse(preview["record_generated"])
        self.assertFalse(preview["reportable"])
        self.assertFalse(preview["submission"])
        self.assertIn("Final vulnerability disposition", preview["missing_required_20x_fields"])
        self.assertIn("Necessary-party routing", preview["missing_reporting_governance_fields"])
        self.assertEqual(preview["accepted_vulnerability_readiness"]["state"], "not_assessed")

    def test_even_a_schema_run_does_not_supply_provider_evaluation(self) -> None:
        preview = build_20x_readiness_preview(
            {
                "assessment_run_id": "INTERNAL-ONLY",
                "assessment_run": {"assessment_run_id": "MANIFEST-ID"},
                "assessment_contract": {"complete": True, "reporting_profile": "dual-preview"},
                "poam_candidate_records": [],
            },
            43,
        )

        self.assertEqual(preview["assessment_run_id"], "MANIFEST-ID")
        self.assertFalse(preview["reportable"])
        self.assertEqual(preview["evaluation_record_count"], 0)
        self.assertTrue(all(
            row["state"] == "not_supplied"
            for row in preview["vulnerability_detail_readiness"]
        ))


if __name__ == "__main__":
    unittest.main()
