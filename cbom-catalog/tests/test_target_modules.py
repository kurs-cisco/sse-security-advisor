from __future__ import annotations

import json
import unittest
from pathlib import Path

from cbom_catalog.target_modules import (
    _public_links,
    _projected_evidence_grade,
    apply_catalog_crypto_module_plans,
    evaluate_catalog_crypto_module_plan,
    parse_target_module_payload,
    public_module_suggestions,
)


class TargetModuleTests(unittest.TestCase):
    def test_vendor_statement_grade_is_downgraded_only_in_projection(self) -> None:
        self.assertEqual(_projected_evidence_grade("vendor_blog", "primary"), "curated_analysis")
        self.assertEqual(_projected_evidence_grade("vendor_release_note", "primary"), "curated_analysis")
        self.assertEqual(_projected_evidence_grade("cmvp_certificate", "primary"), "primary")

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

        target["current_version"] = "3.5.4+vendor-patch"
        self.assertEqual(_public_links(target, evidence)[0][2], "contradicts")
        target["current_version"] = "3.5.4"
        self.assertEqual(_public_links(target, evidence)[0][2], "corroborates")

    def test_certificate_link_requires_exact_current_module_version(self) -> None:
        row = {
            "current_module": "OpenSSL FIPS Provider",
            "current_version": "3.1.2+vendor-patch",
            "target_module": None,
            "normalized_status": "asserted_compliant",
            "current_cmvp_cert": "#4985",
            "target_cmvp_cert": None,
        }
        evidence = [{
            "evidence_key": "cmvp-4985",
            "certificate_number": "#4985",
            "module_name": "OpenSSL FIPS Provider",
            "module_version": "3.1.2",
            "public_status": "active",
        }]
        links = _public_links(row, evidence)
        self.assertEqual(next(link[2] for link in links if link[1] == "current_version"), "contradicts")
        row["current_version"] = "3.1.2"
        links = _public_links(row, evidence)
        self.assertEqual(next(link[2] for link in links if link[1] == "current_version"), "corroborates")

    def test_catalog_plan_requires_exact_active_cmvp_identity(self) -> None:
        evidence = {
            "key": "cmvp-4985",
            "source_kind": "cmvp_certificate",
            "url": "https://example.test/cmvp/4985",
            "certificate_number": "#4985",
            "module_name": "OpenSSL FIPS Provider",
            "module_version": "3.1.2",
            "public_status": "active",
            "payload_sha256": "a" * 64,
        }
        matched = evaluate_catalog_crypto_module_plan(
            {
                "target_module": "OpenSSL FIPS Provider",
                "target_version": "3.1.2",
                "cmvp_certificate": "4985",
                "target_preset_id": "cmvp-4985",
                "evidence_payload_sha256": "a" * 64,
            },
            [evidence],
        )
        self.assertEqual(matched["status"], "active_certificate")
        self.assertEqual(matched["evidence"]["key"], "cmvp-4985")

        no_module_match = evaluate_catalog_crypto_module_plan(
            {
                "target_module": "OpenSSL",
                "target_version": "3.1.2",
                "cmvp_certificate": "#4985",
                "target_preset_id": "cmvp-4985",
                "evidence_payload_sha256": "a" * 64,
            },
            [evidence],
        )
        self.assertEqual(no_module_match["status"], "planned_unverified")

    def test_vendor_go_pipeline_requires_exact_module_version_and_source(self) -> None:
        evidence = {
            "key": "go-fips140-doc",
            "source_kind": "vendor_release_note",
            "url": "https://go.dev/doc/security/fips140",
            "module_name": "Go Cryptographic Module",
            "module_version": "v1.26.0",
            "public_status": "cmvp_in_process",
            "payload_sha256": "b" * 64,
        }
        matched = evaluate_catalog_crypto_module_plan(
            {
                "target_module": "Go Cryptographic Module",
                "target_version": "v1.26.0",
                "evidence_url": "https://go.dev/doc/security/fips140",
                "target_preset_id": "go-fips140-doc",
                "evidence_payload_sha256": "b" * 64,
            },
            [evidence],
        )
        self.assertEqual(matched["status"], "cmvp_in_process")

        toolchain_patch = evaluate_catalog_crypto_module_plan(
            {
                "target_module": "Go Cryptographic Module",
                "target_version": "Go 1.26.8",
                "evidence_url": "https://go.dev/doc/security/fips140",
                "target_preset_id": "go-fips140-doc",
                "evidence_payload_sha256": "b" * 64,
            },
            [evidence],
        )
        self.assertEqual(toolchain_patch["status"], "planned_unverified")

    def test_go_public_link_does_not_upgrade_a_generic_toolchain_target(self) -> None:
        evidence = [{
            "evidence_key": "go-fips140-doc",
            "module_name": "Go Cryptographic Module",
            "module_version": "v1.26.0",
        }]
        links = _public_links(
            {
                "current_module": "Go boringcrypto",
                "current_version": "Go 1.23.2",
                "target_module": "GOFIPS140=v1.0.0, Go 1.26.8",
                "normalized_status": "asserted_not_compliant",
                "current_cmvp_cert": None,
                "target_cmvp_cert": None,
            },
            evidence,
        )
        self.assertEqual(links[0][1:4], ("target_public_status", "partially_corroborates", "name_only"))

    def test_catalog_overlay_requires_the_exact_imported_assertion(self) -> None:
        planning = {
            "source": {"source_collection": "sse-cboms"},
            "groups": [{
                "service_group": "dns-platform",
                "target_modules": [{
                    "record_sha256": "imported-assertion",
                    "target_disposition": "planned_unverified",
                    "evidence": [{
                        "source_locator": "cmvp-4985",
                        "source_kind": "cmvp_certificate",
                        "source_url": "https://example.test/cmvp/4985",
                        "source_payload_sha256": "a" * 64,
                        "observed_value": {
                            "certificate_number": "#4985",
                            "module_name": "OpenSSL FIPS Provider",
                            "module_version": "3.1.2",
                            "public_status": "active",
                        },
                    }],
                }],
            }],
        }
        rows = [{
            "service_group": "dns-platform",
            "source_collection": "sse-cboms",
            "crypto_module_plans": [{
                "source_record_sha256": "imported-assertion",
                "target_module": "OpenSSL FIPS Provider",
                "target_version": "3.1.2",
                "cmvp_certificate": "#4985",
                "target_preset_id": "cmvp-4985",
                "evidence_payload_sha256": "a" * 64,
            }],
        }]
        projected = apply_catalog_crypto_module_plans(planning, rows)
        module = projected["groups"][0]["target_modules"][0]
        self.assertEqual(module["target_disposition"], "planned_unverified")
        self.assertEqual(module["effective_target_disposition"], "active_certificate")
        self.assertEqual(module["effective_target_module"], "OpenSSL FIPS Provider")
        self.assertEqual(module["effective_target_version"], "3.1.2")
        self.assertEqual(planning["groups"][0]["target_modules"][0]["target_disposition"], "planned_unverified")

        rows[0]["crypto_module_plans"][0].pop("source_record_sha256")
        catalog_only = apply_catalog_crypto_module_plans(planning, rows)
        module = catalog_only["groups"][0]["target_modules"][0]
        self.assertNotIn("effective_target_disposition", module)
        self.assertEqual(catalog_only["groups"][0]["catalog_crypto_module_plans"][0]["projection_scope"], "catalog_only")
        extra = catalog_only["groups"][0]["target_modules"][1]
        self.assertEqual(extra["planning_origin"], "catalog_only")
        self.assertEqual(extra["effective_target_disposition"], "active_certificate")

    def test_catalog_only_plan_uses_active_external_evidence(self) -> None:
        planning = {"source": {"source_collection": "sse-cboms"}, "groups": [{"service_group": "new-service", "target_modules": []}]}
        rows = [{
            "service_group": "new-service",
            "source_collection": "sse-cboms",
            "crypto_module_plans": [{
                "target_module": "Go Cryptographic Module",
                "target_version": "v1.26.0",
                "evidence_url": "https://go.dev/doc/security/fips140",
                "target_preset_id": "go-fips140-doc",
                "evidence_payload_sha256": "b" * 64,
            }],
        }]
        projected = apply_catalog_crypto_module_plans(
            planning,
            rows,
            public_evidence=[{
                "evidence_key": "go-fips140-doc",
                "source_kind": "vendor_release_note",
                "source_url": "https://go.dev/doc/security/fips140",
                "module_name": "Go Cryptographic Module",
                "module_version": "v1.26.0",
                "public_status": "cmvp_in_process",
                "payload_sha256": "b" * 64,
            }],
        )
        extra = projected["groups"][0]["target_modules"][0]
        self.assertEqual(extra["planning_origin"], "catalog_only")
        self.assertEqual(extra["effective_target_disposition"], "cmvp_in_process")

    def test_catalog_plan_evidence_drift_stays_unverified(self) -> None:
        result = evaluate_catalog_crypto_module_plan(
            {
                "target_module": "OpenSSL FIPS Provider",
                "target_version": "3.1.2",
                "cmvp_certificate": "#4985",
                "target_preset_id": "cmvp-4985",
                "evidence_payload_sha256": "b" * 64,
            },
            [{
                "key": "cmvp-4985", "source_kind": "cmvp_certificate",
                "module_name": "OpenSSL FIPS Provider", "module_version": "3.1.2",
                "certificate_number": "#4985", "public_status": "active",
                "payload_sha256": "a" * 64,
            }],
        )
        self.assertEqual(result["status"], "planned_unverified")
        self.assertEqual(result["evidence_state"], "evidence_superseded")

    def test_custom_catalog_plan_remains_user_asserted_not_superseded(self) -> None:
        result = evaluate_catalog_crypto_module_plan(
            {
                "target_module": "Vendor custom module",
                "target_version": "9.1",
                "evidence_url": "https://vendor.example/fips",
            },
            [],
        )
        self.assertEqual(result["status"], "planned_unverified")
        self.assertEqual(result["evidence_state"], "user_asserted_unverified")

    def test_catalog_plan_isolated_by_collection_and_group(self) -> None:
        planning = {"source": {"source_collection": "sse-cboms"}, "groups": [{"service_group": "dns-platform", "target_modules": []}]}
        row = {
            "source_collection": "other-collection", "service_group": "dns-platform",
            "crypto_module_plans": [{
                "target_module": "OpenSSL FIPS Provider", "target_version": "3.1.2",
                "cmvp_certificate": "#4985", "target_preset_id": "cmvp-4985",
                "evidence_payload_sha256": "a" * 64,
            }],
        }
        projected = apply_catalog_crypto_module_plans(
            planning, [row], public_evidence=[{
                "evidence_key": "cmvp-4985", "source_kind": "cmvp_certificate",
                "module_name": "OpenSSL FIPS Provider", "module_version": "3.1.2",
                "certificate_number": "#4985", "public_status": "active",
                "payload_sha256": "a" * 64,
            }],
        )
        self.assertEqual(projected["groups"][0]["target_modules"], [])
        self.assertNotIn("catalog_crypto_module_plans", projected["groups"][0])

    def test_public_suggestion_requires_exact_formal_module_and_version(self) -> None:
        evidence = [{
            "evidence_key": "cmvp-4985",
            "source_kind": "cmvp_certificate",
            "source_title": "CMVP Certificate #4985 — OpenSSL FIPS Provider",
            "source_url": "https://example.test/cmvp/4985",
            "certificate_number": "#4985",
            "module_name": "OpenSSL FIPS Provider",
            "module_version": "3.1.2",
            "public_status": "active",
        }]
        exact = public_module_suggestions(
            {"current_module": "OpenSSL FIPS Provider", "current_version": "3.1.2"},
            evidence,
        )
        self.assertEqual(len(exact), 1)
        self.assertEqual(exact[0]["certificate_number"], "#4985")

        generic = public_module_suggestions(
            {"current_module": "OpenSSL", "current_version": "3.1.2"}, evidence
        )
        self.assertEqual(generic, [])

        toolchain = public_module_suggestions(
            {"current_module": "Go Cryptographic Module", "current_version": "Go 1.26.8"},
            [{
                "source_kind": "cmvp_certificate",
                "source_url": "https://example.test/cmvp/5247",
                "certificate_number": "#5247",
                "module_name": "Go Cryptographic Module",
                "module_version": "v1.0.0",
                "public_status": "active",
            }],
        )
        self.assertEqual(toolchain, [])

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
