from __future__ import annotations

import unittest

try:
    from cbom_catalog.service_impact import parse_service_impact_source
except ModuleNotFoundError as exc:
    if exc.name != "psycopg":
        raise
    parse_service_impact_source = None


@unittest.skipIf(parse_service_impact_source is None, "install project dependencies to run import tests")
class ServiceImpactImportTests(unittest.TestCase):
    def test_parser_keeps_only_requested_planning_fields(self) -> None:
        source = (
            "Owner\tTeam\tLead\tCBOM available?\tCBOM Valid?\tETA IL2\tETA IL5\t"
            "Impact on POA&M\u00a0\tRisk Category\tComments\r\n"
            "Changed owner\tRSM/Secure Client\tChanged lead\tYES\tNO\t31-Dec-99\t1-Jan-00\t"
            "Blocker: No Data Available\tCritical\tCustomer deliverable\r\n"
        ).encode("mac_roman")

        parsed = parse_service_impact_source(source)

        self.assertEqual(parsed["encoding"], "mac_roman")
        self.assertEqual(len(parsed["rows"]), 1)
        row = parsed["rows"][0]
        self.assertEqual(row["team_key"], "RSM-SECURE-CLIENT")
        self.assertEqual(row["service_groups"], ["rsm-secure-client-no-cbom"])
        self.assertEqual(row["poam_impact"], "Blocker: No Data Available")
        self.assertEqual(row["risk_category"], "Critical")
        self.assertEqual(row["comments"], "Customer deliverable")
        self.assertEqual(
            set(row["selected_record"]),
            {"team", "poam_impact", "risk_category", "comments"},
        )
        for excluded in ("owner", "lead", "il2", "il5", "cbom_available", "cbom_valid"):
            self.assertNotIn(excluded, row)
            self.assertNotIn(excluded, row["selected_record"])
        self.assertEqual(row["evidence_grade"], "user_asserted")
        self.assertTrue(row["review_required"])

    def test_team_mapping_can_expand_one_planning_row_to_multiple_groups(self) -> None:
        source = (
            b"Team\tImpact on POA&M\tRisk Category\tComments\n"
            b"PAC/CSC/OVD/TIG\tNo impact\tModerate\t\n"
        )

        row = parse_service_impact_source(source)["rows"][0]

        self.assertEqual(row["service_groups"], ["app-control", "pac-cbom", "taac-cbom"])
        self.assertIsNone(row["comments"])


if __name__ == "__main__":
    unittest.main()
