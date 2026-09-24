from __future__ import annotations

import csv
import io
import unittest
from datetime import date

from cbom_catalog.fips_assessment import (
    build_assessment,
    build_poam_workstreams,
    render_poam_csv,
    render_portfolio_poam_csv,
    render_workstream_csv,
)
from cbom_catalog.team_milestones import (
    build_portfolio_poam_items,
    enrich_poam_items,
    portfolio_delivery_waves,
    team_milestones,
)


def document(
    document_id: int,
    group: str,
    *,
    artifact_key: str | None = None,
) -> dict:
    artifacts = []
    if artifact_key:
        artifacts.append(
            {
                "artifact_id": document_id,
                "canonical_key": artifact_key,
                "name": artifact_key,
                "digest": None,
            }
        )
    return {
        "document_id": document_id,
        "document_sha256": f"{document_id:064x}",
        "scopes": [
            {
                "source_collection": "sse-cboms",
                "service_group": group,
                "source_path": f"{group}/service-{document_id}.json",
                "source_sha256": f"{document_id + 100:064x}",
            }
        ],
        "artifacts": artifacts,
    }


def observation(
    document_id: int,
    name: str,
    value: str,
    *,
    evidence_id: int,
    occurrence_id: int | None = None,
    kind: str = "document_property",
    details: dict | None = None,
    component_identity: str | None = None,
    component_name: str | None = None,
    evidence_sha256: str | None = None,
) -> dict:
    return {
        "document_id": document_id,
        "occurrence_id": occurrence_id,
        "evidence_kind": kind,
        "evidence_id": evidence_id,
        "property_name": name,
        "property_value": value,
        "component_identity": component_identity,
        "component_name": component_name,
        "component_version": None,
        "evidence_sha256": evidence_sha256 or f"{evidence_id:064x}",
        "observed_at": "2026-09-18T00:00:00Z",
        "details": details,
    }


class FipsAssessmentTests(unittest.TestCase):
    def test_workstreams_group_issue_owner_and_date_without_discarding_candidates(self) -> None:
        base = {
            "gap_codes": ["explicit_140_3_negative"],
            "rule_ids": ["FIPS1403-002"],
            "policy_version": "test-policy",
            "title": "FIPS 140-3 requirement is explicitly unmet",
            "control_id": "SC-13",
            "proposed_risk": "Moderate",
            "remediation_plan": "Replace or configure the module.",
            "responsible_owner": "Owner A",
            "ato_boundary": "Unassigned — review required",
            "milestone_mitigation_date": "2026-09-30",
        }
        items = [
            {**base, "poam_candidate_id": "FIPS3-A", "subject_identity": "artifact:a", "affected_services": ["sse-cboms/a"]},
            {**base, "poam_candidate_id": "FIPS3-B", "subject_identity": "artifact:b", "affected_services": ["sse-cboms/b"]},
            {**base, "poam_candidate_id": "FIPS3-C", "subject_identity": "artifact:c", "affected_services": ["sse-cboms/c"], "milestone_mitigation_date": None},
        ]

        workstreams = build_poam_workstreams(items)

        self.assertEqual(len(workstreams), 2)
        dated = next(row for row in workstreams if row["milestone_mitigation_date"])
        self.assertEqual(dated["candidate_count"], 2)
        self.assertEqual(dated["affected_service_count"], 2)
        self.assertEqual(dated["merge_decision"], "review_required")
        self.assertIn("impact:not-assessed", dated["tags"])
        self.assertEqual(len(dated["candidate_ids"]), 2)
        export = render_workstream_csv(workstreams)
        self.assertIn("Workstream ID", export)
        self.assertIn("Authorized Review Required", export)
        self.assertIn("FIPS3-A; FIPS3-B", export)

    def test_legacy_140_2_signal_is_a_candidate_not_a_compliance_verdict(self) -> None:
        result = build_assessment(
            [document(1, "DLP", artifact_key="registry/service:1")],
            [observation(1, "fedramp:fips-level", "FIPS 140-2", evidence_id=10)],
            as_of=date(2026, 9, 18),
        )

        self.assertEqual(result["findings"][0]["rule_id"], "FIPS1403-001")
        self.assertEqual(result["findings"][0]["assertion_state"], "likely_gap")
        self.assertTrue(result["findings"][0]["poam_eligible"])
        self.assertTrue(result["findings"][0]["requires_authorized_assessor_review"])
        self.assertEqual(result["summary"]["deduplicated_poam_candidates"], 1)

    def test_same_root_cause_and_artifact_deduplicate_across_service_groups(self) -> None:
        documents = [
            document(1, "GROUP-A", artifact_key="pkg:generic/shared@1"),
            document(2, "GROUP-B", artifact_key="pkg:generic/shared@1"),
        ]
        observations = [
            observation(1, "fedramp:meets-fips-140-3", "false", evidence_id=11),
            observation(2, "fedramp:meets-fips-140-3", "false", evidence_id=12),
        ]

        result = build_assessment(documents, observations, as_of=date(2026, 9, 18))

        self.assertEqual(len(result["findings"]), 2)
        self.assertEqual(len(result["poam_items"]), 1)
        self.assertEqual(
            result["poam_items"][0]["affected_services"],
            ["sse-cboms/GROUP-A", "sse-cboms/GROUP-B"],
        )
        self.assertEqual(result["poam_items"][0]["linked_finding_count"], 2)

    def test_non_crypto_not_applicable_component_is_excluded(self) -> None:
        observations = [
            observation(
                1,
                "fedramp:fips:crypto-relevant",
                "false",
                evidence_id=20,
                occurrence_id=100,
                kind="component_property",
            ),
            observation(
                1,
                "fedramp:fips:140-3-status",
                "not-validated",
                evidence_id=21,
                occurrence_id=100,
                kind="component_property",
            ),
        ]

        result = build_assessment(
            [document(1, "TEAM")], observations, as_of=date(2026, 9, 18)
        )

        self.assertEqual(result["findings"], [])
        self.assertEqual(result["summary"]["documents_with_fips_evidence"], 0)

    def test_inconclusive_probe_does_not_create_poam_candidate(self) -> None:
        result = build_assessment(
            [document(1, "LANDERS")],
            [
                observation(
                    1,
                    "fips_tool:overall_openssl_fips",
                    "false",
                    evidence_id=30,
                    kind="fips_tool_result",
                    details={"crypto_library": "OpenSSL not found"},
                )
            ],
            as_of=date(2026, 9, 18),
        )

        self.assertEqual(result["findings"][0]["rule_id"], "FIPS1403-005")
        self.assertEqual(result["findings"][0]["assertion_state"], "evidence_gap")
        self.assertEqual(result["poam_items"], [])

    def test_identified_library_without_version_is_still_inconclusive(self) -> None:
        result = build_assessment(
            [document(1, "LANDERS")],
            [
                observation(
                    1,
                    "fips_tool:overall_openssl_fips",
                    "false",
                    evidence_id=31,
                    kind="fips_tool_result",
                    details={
                        "crypto_library": "openssl",
                        "crypto_library_details": "OpenSSL not found",
                        "crypto_version": "",
                        "fips_module_version": "",
                    },
                )
            ],
            as_of=date(2026, 9, 18),
        )

        self.assertEqual(result["findings"][0]["rule_id"], "FIPS1403-005")
        self.assertEqual(result["poam_items"], [])

    def test_versioned_negative_runtime_observation_is_candidate_only(self) -> None:
        result = build_assessment(
            [document(1, "TEAM")],
            [
                observation(
                    1,
                    "fips_tool:overall_openssl_fips",
                    "false",
                    evidence_id=32,
                    kind="fips_tool_result",
                    details={
                        "crypto_library": "openssl",
                        "crypto_library_details": "Provider detected; approved mode disabled",
                        "crypto_version": "3.0.9",
                        "fips_module_version": "3.0.9",
                    },
                )
            ],
            as_of=date(2026, 9, 18),
        )

        self.assertEqual(result["findings"][0]["rule_id"], "FIPS1403-003")
        self.assertEqual(result["summary"]["deduplicated_poam_candidates"], 1)

    def test_conflicting_assertions_remain_review_only(self) -> None:
        result = build_assessment(
            [document(1, "TEAM")],
            [
                observation(1, "fedramp:meets-fips-140-3", "true", evidence_id=40),
                observation(1, "fedramp:meets-fips-140-3", "false", evidence_id=41),
            ],
            as_of=date(2026, 9, 18),
        )

        self.assertEqual([row["rule_id"] for row in result["findings"]], ["FIPS1403-004"])
        self.assertEqual(result["poam_items"], [])

    def test_different_components_are_not_collapsed_into_a_false_conflict(self) -> None:
        result = build_assessment(
            [document(1, "TEAM")],
            [
                observation(
                    1,
                    "fedramp:meets-fips-140-3",
                    "true",
                    evidence_id=42,
                    occurrence_id=101,
                    kind="component_property",
                    component_identity="pkg:generic/module-a@1",
                    component_name="module-a",
                ),
                observation(
                    1,
                    "fedramp:meets-fips-140-3",
                    "false",
                    evidence_id=43,
                    occurrence_id=102,
                    kind="component_property",
                    component_identity="pkg:generic/module-b@1",
                    component_name="module-b",
                ),
            ],
            as_of=date(2026, 9, 18),
        )

        self.assertNotIn("FIPS1403-004", [row["rule_id"] for row in result["findings"]])
        self.assertEqual(
            {row["rule_id"] for row in result["findings"]},
            {"FIPS1403-002", "FIPS1403-006"},
        )
        self.assertEqual(result["summary"]["deduplicated_poam_candidates"], 1)

    def test_bare_140_3_standard_is_not_positive_validation_evidence(self) -> None:
        result = build_assessment(
            [document(1, "TEAM", artifact_key="pkg:generic/service@1")],
            [
                observation(1, "fedramp:fips-level", "FIPS 140-2", evidence_id=44),
                observation(1, "fedramp:cmvp-standard", "FIPS 140-3", evidence_id=45),
            ],
            as_of=date(2026, 9, 18),
        )

        self.assertEqual([row["rule_id"] for row in result["findings"]], ["FIPS1403-001"])

    def test_positive_declaration_remains_an_evidence_gap(self) -> None:
        result = build_assessment(
            [document(1, "TEAM")],
            [observation(1, "fedramp:meets-fips-140-3", "true", evidence_id=46)],
            as_of=date(2026, 9, 18),
        )

        self.assertEqual(result["findings"][0]["rule_id"], "FIPS1403-006")
        self.assertEqual(result["findings"][0]["assertion_state"], "evidence_gap")
        self.assertEqual(result["poam_items"], [])

    def test_finding_id_does_not_depend_on_database_evidence_id(self) -> None:
        common_sha = "a" * 64
        first = build_assessment(
            [document(1, "TEAM")],
            [
                observation(
                    1,
                    "fedramp:meets-fips-140-3",
                    "false",
                    evidence_id=47,
                    evidence_sha256=common_sha,
                )
            ],
            as_of=date(2026, 9, 18),
        )
        second = build_assessment(
            [document(1, "TEAM")],
            [
                observation(
                    1,
                    "fedramp:meets-fips-140-3",
                    "false",
                    evidence_id=999,
                    evidence_sha256=common_sha,
                )
            ],
            as_of=date(2026, 9, 18),
        )

        self.assertEqual(first["findings"][0]["finding_id"], second["findings"][0]["finding_id"])

    def test_equivalent_occurrence_findings_are_counted_once(self) -> None:
        shared_sha = "b" * 64
        observations = [
            observation(
                1,
                "fedramp:meets-fips-140-3",
                "true",
                evidence_id=index,
                occurrence_id=index,
                kind="component_property",
                component_identity="pkg:generic/shared@1",
                component_name="shared",
                evidence_sha256=shared_sha,
            )
            for index in (100, 101)
        ]

        result = build_assessment(
            [document(1, "DLP")],
            observations,
            as_of=date(2026, 9, 18),
            service_group_inventory=[{
                "source_collection": "sse-cboms",
                "service_group": "DLP",
                "source_files": 1,
                "ingest_issues": 0,
            }],
        )

        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["duplicate_occurrence_count"], 2)
        self.assertEqual(result["summary"]["needs_review_findings"], 1)
        self.assertEqual(result["service_groups"][0]["finding_count"], 1)
        self.assertEqual(result["service_groups"][0]["needs_review_findings"], 1)

    def test_zero_document_service_groups_remain_visible_as_coverage_gaps(self) -> None:
        result = build_assessment(
            [document(1, "team")],
            [],
            as_of=date(2026, 9, 18),
            service_group_inventory=[
                {
                    "source_collection": "sse-cboms",
                    "service_group": "team",
                    "service_group_name": "TEAM",
                    "source_files": 1,
                    "ingest_issues": 0,
                },
                {
                    "source_collection": "sse-cboms",
                    "service_group": "apix-no-cbom",
                    "service_group_name": "APIX-NO_CBOM",
                    "source_files": 0,
                    "ingest_issues": 0,
                },
            ],
        )

        self.assertEqual(result["summary"]["service_groups_in_scope"], 2)
        self.assertEqual(result["summary"]["service_groups_without_documents"], 1)
        missing = next(
            row
            for row in result["service_groups"]
            if row["service"] == "sse-cboms/apix-no-cbom"
        )
        self.assertEqual(missing["documents"], 0)
        self.assertEqual(missing["evidence_coverage_percent"], 0.0)
        self.assertEqual(missing["poam_candidate_findings"], 0)
        self.assertEqual(result["summary"]["coverage_gap_observations"], 2)
        api_gap = next(
            row
            for row in result["coverage_gaps"]
            if row["scope"]["service_groups"] == ["apix-no-cbom"]
        )
        self.assertEqual(api_gap["assertion_state"], "not_assessable")
        self.assertFalse(api_gap["poam_eligibility"])
        self.assertTrue(api_gap["observation_id"].startswith("OBS-FIPS3-"))
        self.assertTrue(api_gap["missing_required_facts"])
        self.assertTrue(api_gap["review"]["requires_system_owner_attestation"])
        self.assertEqual(result["poam_items"], [])

    def test_partial_and_missing_fips_coverage_are_non_poam_observations(self) -> None:
        result = build_assessment(
            [document(1, "no-fips"), document(2, "partial"), document(3, "partial")],
            [observation(2, "fedramp:meets-fips-140-3", "true", evidence_id=301)],
            as_of=date(2026, 9, 18),
            service_group_inventory=[
                {
                    "source_collection": "sse-cboms",
                    "service_group": "no-fips",
                    "service_group_name": "NO-FIPS",
                    "source_files": 1,
                    "ingest_issues": 0,
                },
                {
                    "source_collection": "sse-cboms",
                    "service_group": "partial",
                    "service_group_name": "PARTIAL",
                    "source_files": 2,
                    "ingest_issues": 0,
                },
            ],
        )

        gaps = {
            row["scope"]["service_groups"][0]: row for row in result["coverage_gaps"]
        }
        self.assertEqual(gaps["no-fips"]["assertion_state"], "evidence_gap")
        self.assertIn("none contains", gaps["no-fips"]["technical_observation"])
        self.assertEqual(gaps["partial"]["assertion_state"], "evidence_gap")
        self.assertIn("1 of 2", gaps["partial"]["technical_observation"])
        self.assertTrue(all(not row["poam_eligibility"] for row in gaps.values()))
        self.assertEqual(result["summary"]["service_groups_without_fips_evidence"], 1)
        self.assertEqual(result["summary"]["service_groups_with_partial_fips_evidence"], 1)

    def test_csv_is_deterministic_and_explicitly_draft(self) -> None:
        result = build_assessment(
            [document(1, "DLP", artifact_key="pkg:generic/legacy@1")],
            [observation(1, "fedramp:fips-level", "FIPS 140-2", evidence_id=50)],
            as_of=date(2026, 9, 18),
        )

        first = render_poam_csv(result["poam_items"])
        second = render_poam_csv(result["poam_items"])
        self.assertEqual(first, second)
        rows = list(csv.DictReader(io.StringIO(first)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Controls"], "SC-13")
        self.assertIn("authorized review required", rows[0]["Status"])
        self.assertEqual(rows[0]["Assessor Review Required"], "Yes")

    def test_team_tracker_crosswalk_preserves_raw_milestones_and_merges_scc(self) -> None:
        tracker = team_milestones()
        groups = {row["service_group"]: row for row in tracker["groups"]}
        self.assertEqual(len(tracker["all_tracker_rows"]), 38)
        self.assertEqual(groups["zta-calp"]["tracker_rows"][0]["team"], "ZTA CLAP")
        self.assertEqual(
            groups["apix-no-cbom"]["tracker_rows"][0]["team"],
            "APIX (Authsvc,APIGW)",
        )
        self.assertEqual(groups["brain"]["tracker_rows"][0]["owner"], "Prashanth")
        self.assertEqual(len(groups["scc-backend"]["tracker_rows"]), 1)
        self.assertEqual(
            groups["scc-backend"]["tracker_rows"][0]["source_teams"],
            [
                "SCC",
                "SCC -Backend Services (Feature Service, Self-service, Platform Notification Service, SCG Service)",
            ],
        )
        self.assertEqual(
            [row["team"] for row in groups["discovery"]["tracker_rows"]],
            ["Discovery"],
        )
        discovery = next(
            row for row in tracker["all_tracker_rows"] if row["team"] == "Discovery"
        )
        self.assertEqual(discovery["mapped_service_groups"], ["discovery"])
        self.assertEqual(discovery["mapping_status"], "mapped")
        self.assertEqual(discovery["owner"], "Ashok")
        self.assertEqual(discovery["source_teams"], ["Discovery", "Resource Discovery"])
        self.assertFalse(groups["fis-sma-threatgrid"]["empty_service_category"])
        self.assertEqual(groups["pac-cbom"]["tracker_rows"][0]["il2"]["status"], "date")
        self.assertEqual(groups["pac-cbom"]["tracker_rows"][0]["il2"]["date"], "2026-09-17")
        self.assertEqual(groups["ovd-app-discovery"]["tracker_rows"][0]["il2"]["date"], "2026-09-30")
        self.assertEqual(groups["apix-no-cbom"]["tracker_rows"][0]["il2"]["date"], "2026-11-13")
        self.assertEqual(groups["apix-no-cbom"]["tracker_rows"][0]["il5"]["date"], "2026-11-20")
        self.assertEqual(groups["sfcn-ravpn"]["tracker_rows"][0]["il2"]["date"], "2026-11-18")
        self.assertEqual(groups["brain"]["tracker_rows"][0]["il2"]["date"], "2026-11-06")
        self.assertEqual(groups["adc"]["tracker_rows"][0]["il2"]["status"], "done")
        self.assertIsNone(groups["adc"]["tracker_rows"][0]["il2"]["date"])
        self.assertEqual(groups["opc"]["tracker_rows"][0]["il2"]["status"], "done")
        self.assertEqual(
            groups["opc"]["tracker_rows"][0]["cmvp_disposition"]["status"],
            "active_certificate",
        )
        self.assertEqual(
            groups["swg-proxy"]["tracker_rows"][0]["cmvp_disposition"]["status"],
            "cmvp_in_process",
        )

    def test_portfolio_delivery_waves_retain_group_specific_dates(self) -> None:
        waves = {row["wave"]: row for row in portfolio_delivery_waves()}
        october = {row["service_group"]: row for row in waves["october_2026"]["service_groups"]}
        december = {row["service_group"]: row for row in waves["december_2026"]["service_groups"]}
        march = {row["service_group"]: row for row in waves["march_2027"]["service_groups"]}

        self.assertEqual(october["discovery"]["farthest_explicit_il2_date"], "2026-10-11")
        self.assertEqual(december["sfcn-firewall"]["farthest_explicit_il2_date"], "2026-12-04")
        self.assertIn("va", december)
        self.assertEqual(december["va"]["raw_il2_values"], ["15-Dec-2026"])
        self.assertIn("rsm-secure-client-no-cbom", march)
        self.assertIn("ios-no-cbom", march)
        self.assertNotIn("adc", march)

    def test_two_portfolio_poams_keep_service_library_and_eta_links(self) -> None:
        items = [
            {
                "poam_candidate_id": "FIPS3-ACTIVE",
                "affected_services": ["sse-cboms/DLP"],
                "affected_service_groups": ["sse-cboms/DLP"],
                "service_scope_links": [{
                    "service_record_id": "document:7",
                    "service_record_name": "dlp.json",
                    "document_id": 7,
                    "document_sha256": "7" * 64,
                    "source_collection": "sse-cboms",
                    "service_group": "DLP",
                    "service_group_ref": "sse-cboms/DLP",
                    "source_path": "DLP/dlp.json",
                    "source_sha256": "8" * 64,
                    "subject_identity": "pkg:openssl@3.1.2",
                    "subject_name": "openssl@3.1.2",
                    "libraries": [{
                        "component_identity": "pkg:openssl@3.1.2",
                        "name": "openssl",
                        "version": "3.1.2",
                        "occurrence_id": 70,
                        "document_id": 7,
                    }],
                    "finding_ids": ["FIPSF-A"],
                }],
                "policy_version": "test",
                "gap_codes": ["legacy"],
                "subject_identity": "pkg:openssl@3.1.2",
                "remediation_plan": "migrate",
                "ato_boundary": "review",
            },
            {
                "poam_candidate_id": "FIPS3-PIPELINE",
                "affected_services": ["sse-cboms/SWG-PROXY"],
                "affected_service_groups": ["sse-cboms/SWG-PROXY"],
                "service_scope_links": [{
                    "service_record_id": "document:8",
                    "service_record_name": "proxy.json",
                    "document_id": 8,
                    "document_sha256": "9" * 64,
                    "source_collection": "sse-cboms",
                    "service_group": "SWG-PROXY",
                    "service_group_ref": "sse-cboms/SWG-PROXY",
                    "source_path": "SWG-PROXY/proxy.json",
                    "source_sha256": "a" * 64,
                    "subject_identity": "pkg:openssl@3.5",
                    "subject_name": "openssl@3.5",
                    "libraries": [],
                    "finding_ids": ["FIPSF-B"],
                }],
                "policy_version": "test",
                "gap_codes": ["pipeline"],
                "subject_identity": "pkg:openssl@3.5",
                "remediation_plan": "track validation",
                "ato_boundary": "review",
            },
        ]
        enrich_poam_items(items)
        portfolio = build_portfolio_poam_items(items)

        self.assertEqual(len(portfolio), 2)
        by_dimension = {row["dimension"]: row for row in portfolio}
        active = by_dimension["active_certificate_migration"]
        pipeline = by_dimension["cmvp_in_test_or_in_progress"]
        self.assertEqual(active["linked_candidate_ids"], ["FIPS3-ACTIVE"])
        self.assertEqual(active["affected_service_records"][0]["document_id"], 7)
        self.assertEqual(active["affected_libraries"][0]["name"], "openssl")
        self.assertEqual(pipeline["linked_candidate_ids"], ["FIPS3-PIPELINE"])
        csv_output = render_portfolio_poam_csv(portfolio)
        self.assertIn("FIPS3-PORTFOLIO-ACTIVE-CERT", csv_output)
        self.assertIn("dlp.json", csv_output)

    def test_poam_uses_farthest_explicit_il2_date_only(self) -> None:
        # Different document subjects may produce separate dedupe rows; enrich
        # a deliberately combined candidate to exercise the cross-group rule.
        item = {"affected_services": ["sse-cboms/CNHE", "sse-cboms/DW-VOLT"]}
        enrich_poam_items([item])
        self.assertEqual(item["milestone_mitigation_date"], "2026-11-08")
        self.assertEqual(item["scheduled_completion_date"], "2026-11-08")

    def test_explicit_date_is_used_while_relative_qualifier_is_ignored(self) -> None:
        item = {"affected_services": ["sse-cboms/ZTA-CALP"]}
        enrich_poam_items([item])
        self.assertEqual(item["scheduled_completion_date"], "2026-09-22")
        self.assertEqual(item["planned_milestone"], "IL2 group planning milestone: 2026-09-22")

    def test_relative_tracker_text_without_date_never_becomes_poam_due_date(self) -> None:
        item = {"affected_services": ["sse-cboms/SWG-PROXY"]}
        enrich_poam_items([item])
        self.assertIsNone(item["scheduled_completion_date"])
        self.assertIn("not supplied", item["planned_milestone"].casefold())


if __name__ == "__main__":
    unittest.main()
