from __future__ import annotations

import io
import json
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

try:
    from cbom_catalog import api
except ModuleNotFoundError as exc:
    if exc.name not in {"fastapi", "psycopg", "psycopg_pool"}:
        raise
    api = None


@unittest.skipIf(api is None, "install project dependencies to run API query tests")
class ApiQueryTests(unittest.TestCase):
    def test_invalid_numeric_environment_values_fall_back_safely(self) -> None:
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})
        with patch.dict(
            api.os.environ,
            {
                "CBOM_ENVIRONMENT": "local",
                "CBOM_API_PAGE_SIZE": "not-a-number",
                "CBOM_API_RATE_LIMIT_PER_MINUTE": "not-a-number",
            },
            clear=False,
        ):
            self.assertEqual(api._max_page_size(), 100)
            self.assertFalse(api._rate_limited(request))

    def test_fips_response_is_compact_filtered_and_paged(self) -> None:
        assessment = {
            "summary": {"deduplicated_poam_candidates": 3},
            "findings": [{"finding_id": "large-raw-finding"}],
            "poam_items": [
                {"poam_candidate_id": "FIPS3-A", "title": "OpenSSL gap", "responsible_owner": "A", "affected_services": ["CNHE"]},
                {"poam_candidate_id": "FIPS3-B", "title": "BoringSSL gap", "responsible_owner": "B", "affected_services": ["APIX"]},
                {"poam_candidate_id": "FIPS3-C", "title": "OpenSSL follow-up", "responsible_owner": "C", "affected_services": ["Discovery"]},
            ],
        }

        result = api._shape_fips_assessment(
            assessment,
            include_findings=False,
            query="openssl",
            poam_limit=1,
            poam_offset=1,
        )

        self.assertNotIn("findings", result)
        self.assertEqual(result["poam_page"], {"total": 2, "limit": 1, "offset": 1})
        self.assertEqual(result["poam_items"][0]["poam_candidate_id"], "FIPS3-C")

    def test_fips_assessment_keeps_both_queries_inside_the_selected_provenance_scope(self) -> None:
        """FIPS evidence must never be assembled from an unscoped document universe."""
        expected = {
            "scope": {"source_collection": "collection-a", "service_group": "team"},
            "summary": {},
        }
        with (
            patch.object(api, "_fetch_all", side_effect=[[], [], []]) as fetch_all,
            patch.object(api, "_active_target_module_contract", return_value=None),
            patch.object(api, "build_assessment", return_value=expected) as build,
        ):
            result = api._load_fips_assessment(
                source_collection="collection-a",
                service_group="team",
            )

        self.assertIs(result, expected)
        self.assertEqual(fetch_all.call_count, 3)
        inventory_sql, inventory_params = fetch_all.call_args_list[0].args
        self.assertIn("FROM service_group sg", inventory_sql)
        self.assertIn("LEFT JOIN source_file sf", inventory_sql)
        self.assertNotIn("fis-sma-threatgrid", inventory_sql)
        self.assertIn("sc.slug = %s", inventory_sql)
        self.assertIn("sg.slug = %s", inventory_sql)
        self.assertEqual(inventory_params, ("collection-a", "team"))
        for call in fetch_all.call_args_list[1:]:
            sql, params = call.args
            self.assertIn("WITH scoped_source_files AS", sql)
            self.assertIn("occurrence_relevance AS", sql)
            self.assertNotIn("fis-sma-threatgrid", sql)
            self.assertIn("sc.slug = %s", sql)
            self.assertIn("sg.slug = %s", sql)
            self.assertEqual(params, ("collection-a", "team"))
        evidence_sql = fetch_all.call_args_list[2].args[0]
        self.assertIn("lower(cp.property_name) <> 'fedramp:fips:crypto-relevant'", evidence_sql)
        self.assertIn("coalesce(relevance.explicitly_false, false)", evidence_sql)
        self.assertEqual(build.call_args.kwargs["scope"], expected["scope"])
        self.assertEqual(build.call_args.kwargs["service_group_inventory"], [])

    def test_fips_assessment_does_not_synthesize_virtual_service_groups(self) -> None:
        expected = {"summary": {}, "poam_items": []}
        with (
            patch.object(api, "_fetch_all", side_effect=[[], [], []]),
            patch.object(api, "_active_target_module_contract", return_value=None),
            patch.object(api, "build_assessment", return_value=expected) as build,
        ):
            result = api._load_fips_assessment(None, None)

        self.assertIs(result, expected)
        inventory = build.call_args.kwargs["service_group_inventory"]
        self.assertEqual(inventory, [])

    def test_fips_csv_is_a_draft_attachment_with_a_date_specific_filename(self) -> None:
        assessment = {
            "policy": {"assessment_date": "2026-09-18"},
            "poam_items": [{"poam_candidate_id": "FIPS3-EXAMPLE"}],
        }
        with (
            patch.object(api, "_cached_fips_assessment", return_value=(assessment, 7, False)) as load,
            patch.object(api, "render_poam_csv", return_value="POA&M ID\\r\\nFIPS3-EXAMPLE\\r\\n"),
        ):
            response = api.fips_poam_export("collection-a", "team")

        self.assertEqual(load.call_args.args, ("collection-a", "team"))
        self.assertEqual(response.media_type, "text/csv")
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="fips-140-3-poam-candidates-2026-09-18.csv"',
        )
        self.assertIn(b"FIPS3-EXAMPLE", response.body)

    def test_compliance_package_has_candidate_manifest_and_both_poam_views(self) -> None:
        assessment = {
            "policy": {"assessment_date": "2026-09-18"},
            "scope": {"source_collection": "collection-a"},
            "summary": {"deduplicated_poam_candidates": 1},
            "service_groups": [],
            "coverage_gaps": [],
            "poam_items": [{"poam_candidate_id": "FIPS3-EXAMPLE"}],
            "poam_workstreams": [{"workstream_id": "FIPS3-WS-EXAMPLE"}],
        }
        with (
            patch.object(api, "_cached_fips_assessment", return_value=(assessment, 9, False)),
            patch.object(api, "render_poam_csv", return_value="asset\r\n"),
            patch.object(api, "render_portfolio_poam_csv", return_value="portfolio\r\n"),
            patch.object(api, "render_workstream_csv", return_value="workstream\r\n"),
            patch.object(api, "team_milestones", return_value={"source": {"source_file_sha256": "abc"}}),
            patch.object(api, "_active_target_module_contract", return_value=None),
        ):
            response = api.fips_compliance_package_export("collection-a", None)

        self.assertEqual(response.media_type, "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.body)) as bundle:
            self.assertEqual(
                set(bundle.namelist()),
                {"poam-portfolio-candidates.csv", "poam-asset-candidates.csv", "poam-workstream-review.csv", "assessment-summary.json", "manifest.json"},
            )
            manifest = json.loads(bundle.read("manifest.json"))
            self.assertTrue(manifest["candidate_only"])
            self.assertTrue(manifest["authorized_review_required"])
            self.assertEqual(manifest["catalog_revision"], 9)

    def test_dashboard_aggregations_scope_provenance_before_grouping(self) -> None:
        with (
            patch.object(api, "_fetch_one", return_value={}) as fetch_one,
            patch.object(api, "_fetch_all", side_effect=[[], [], [], []]) as fetch_all,
        ):
            result = api._build_dashboard_overview(
                source_collection="collection-a",
                service_group="team",
            )

        calls = [fetch_one.call_args, *fetch_all.call_args_list]
        self.assertEqual(len(calls), 5)
        for call in calls:
            sql, params = call.args
            self.assertIn("WITH scoped_service_groups AS", sql)
            self.assertIn("scoped_source_files AS", sql)
            self.assertNotIn("fis-sma-threatgrid", sql)
            self.assertIn("sc.slug = %s", sql)
            self.assertIn("sg.slug = %s", sql)
            self.assertEqual(params, ("collection-a", "team"))
        group_sql = fetch_all.call_args_list[-1].args[0]
        self.assertIn("ssf.parse_status IN ('empty', 'invalid', 'unsupported', 'error')", group_sql)
        self.assertNotIn("JOIN ingest_issue", group_sql)
        self.assertEqual(
            result["scope"],
            {"source_collection": "collection-a", "service_group": "team"},
        )

    def test_dashboard_does_not_synthesize_virtual_service_groups(self) -> None:
        with (
            patch.object(
                api,
                "_fetch_one",
                return_value={"service_groups": 38, "empty_service_groups": 5},
            ),
            patch.object(api, "_fetch_all", side_effect=[[], [], [], []]),
        ):
            result = api._build_dashboard_overview()

        self.assertEqual(result["service_groups"], [])
        self.assertEqual(result["counts"]["service_groups"], 38)
        self.assertEqual(result["counts"]["empty_service_groups"], 5)

    def test_service_group_register_joins_planning_and_candidate_actions_by_scope(self) -> None:
        assessment = {
            "service_groups": [{
                "service": "collection-a/team",
                "service_group_name": "Team",
                "source_files": 3,
                "documents": 2,
                "documents_with_fips_evidence": 1,
                "documents_without_fips_evidence": 1,
                "evidence_coverage_percent": 50,
                "poam_candidate_findings": 2,
                "needs_review_findings": 1,
                "finding_count": 3,
                "ingest_issues": 0,
            }],
            "coverage_gaps": [],
            "poam_items": [{
                "poam_candidate_id": "FIPS3-ONE",
                "affected_services": ["collection-a/team"],
            }],
            "poam_workstreams": [{
                "workstream_id": "FIPSW-ONE",
                "affected_services": ["collection-a/team"],
            }],
        }
        overview = {"service_groups": [{
            "source_collection": "collection-a",
            "slug": "team",
            "display_name": "Team",
            "unique_crypto_components": 11,
            "unique_crypto_libraries": 7,
            "crypto_component_occurrences": 12,
            "issues": 7,
        }]}
        milestones = {"groups": [{
            "service_group": "team",
            "mapping_status": "mapped",
            "owners": ["Executive"],
            "leads": ["Lead"],
            "tracker_rows": [{
                "team": "Team",
                "il2": {"raw_value": "1 Oct 2026", "status": "date", "date": "2026-10-01"},
                "il5": {"raw_value": "", "status": "not_supplied", "date": None},
            }],
        }]}

        rows = api._service_group_register_rows(assessment, overview, milestones)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["service_key"], "collection-a/team")
        self.assertEqual(row["effective_owners"], ["Executive"])
        self.assertEqual(row["il2"]["farthest_date"], "2026-10-01")
        self.assertEqual(row["il5"]["state"], "not_supplied")
        self.assertEqual(row["candidate_crypto_assets"], 11)
        self.assertEqual(row["candidate_crypto_libraries"], 7)
        self.assertEqual(row["poam_candidate_ids"], ["FIPS3-ONE"])
        self.assertEqual(row["workstream_ids"], ["FIPSW-ONE"])
        self.assertEqual(row["ingest_issues"], 0)

    def test_service_group_register_filters_missing_planning_dates(self) -> None:
        rows = [
            {"service_key": "a/one", "display_name": "One", "effective_owners": [], "leads": [], "poam_candidate_ids": [], "workstream_ids": [], "il2": {"state": "not_supplied"}, "il5": {"state": "dated"}, "poam_candidate_count": 0, "finding_count": 0, "review_observations": 0},
            {"service_key": "a/two", "display_name": "Two", "effective_owners": ["Owner"], "leads": ["Lead"], "poam_candidate_ids": ["P"], "workstream_ids": [], "il2": {"state": "dated"}, "il5": {"state": "dated"}, "poam_candidate_count": 1, "finding_count": 2, "review_observations": 1},
        ]

        filtered = api._filter_service_group_register(
            rows, query=None, owner="__missing__", lead=None,
            il2_state="not_supplied", il5_state=None, action="no_action",
        )

        self.assertEqual([row["service_key"] for row in filtered], ["a/one"])

    def test_document_path_and_collection_use_the_same_provenance_row(self) -> None:
        with patch.object(api, "_fetch_all", return_value=[]) as fetch:
            api.documents(
                source_collection="collection-a",
                service_group="team",
                kind=None,
                spec_version=None,
                path_query="only-in-a.json",
                limit=10,
                offset=0,
            )

        sql, params = fetch.call_args.args
        self.assertIn("sf.document_id = inventory.document_id", sql)
        self.assertIn("sc.slug = %s", sql)
        self.assertIn("sg.slug = %s", sql)
        self.assertIn("sf.source_path ILIKE %s", sql)
        self.assertEqual(
            params[:3],
            ("collection-a", "team", "%only-in-a.json%"),
        )

    def test_document_components_supports_search_and_explicit_crypto_filter(self) -> None:
        with (
            patch.object(api, "_fetch_one", return_value={"id": 7}),
            patch.object(api, "_fetch_all", return_value=[]) as fetch,
        ):
            api.document_components(
                document_id=7,
                query="openssl",
                crypto_only=True,
                limit=25,
                offset=0,
            )

        sql, params = fetch.call_args.args
        self.assertIn("dc.document_id = %s", sql)
        self.assertIn("dc.crypto_properties", sql)
        self.assertIn("fedramp:fips:crypto-relevant", sql)
        self.assertEqual(params[:4], (7, "%openssl%", "%openssl%", "%openssl%"))

    def test_component_aggregates_are_scoped_before_grouping(self) -> None:
        with patch.object(api, "_fetch_all", return_value=[]) as fetch:
            api.components(
                query="openssl",
                purl=None,
                component_type=None,
                source_collection="collection-a",
                service_group="team",
                limit=10,
                offset=0,
            )

        sql, params = fetch.call_args.args
        self.assertNotIn("FROM v_component_usage", sql)
        self.assertIn("FROM component c", sql)
        self.assertIn("sc.slug = %s", sql)
        self.assertIn("sg.slug = %s", sql)
        self.assertIn("GROUP BY c.id", sql)
        self.assertEqual(params[3:5], ("collection-a", "team"))

    def test_fingerprint_query_is_collection_and_path_scoped(self) -> None:
        with patch.object(api, "_fetch_all", return_value=[]) as fetch:
            api.fingerprints(
                source_collection="collection-a",
                service_group="team",
                path_query="service.json",
                checksum="A" * 64,
                limit=10,
                offset=0,
            )

        sql, params = fetch.call_args.args
        self.assertIn("FROM v_source_fingerprint_status", sql)
        self.assertEqual(
            params[:4],
            ("collection-a", "team", "%service.json%", "a" * 64),
        )

    def test_issue_query_accepts_provenance_scope(self) -> None:
        with patch.object(api, "_fetch_all", return_value=[]) as fetch:
            api.issues(
                severity="warning",
                code=None,
                source_collection="collection-a",
                service_group="team",
                path_query="service.json",
                limit=10,
                offset=0,
            )

        sql, params = fetch.call_args.args
        self.assertIn("LEFT JOIN source_collection sc", sql)
        self.assertIn("LEFT JOIN service_group sg", sql)
        self.assertEqual(
            params[:4],
            ("warning", "collection-a", "team", "%service.json%"),
        )

    def test_dependency_graph_resolves_component_labels(self) -> None:
        document = {
            "document_id": 7,
            "document_kind": "cyclonedx",
            "format_name": "CycloneDX",
            "spec_version": "1.6",
            "serial_number": "urn:uuid:test",
            "source_paths": ["TEAM/service.cdx.json"],
        }
        totals = {"total_edges": 1, "total_nodes": 2}
        edge = {
            "edge_id": 11,
            "from_ref": "app",
            "to_ref": "pkg",
            "relationship_type": "DEPENDS_ON",
            "resolution_status": "resolved",
            "from_is_subject": True,
            "from_component_id": 21,
            "from_name": "service",
            "from_version": "1.0",
            "from_component_type": "application",
            "from_purl": None,
            "to_is_subject": False,
            "to_component_id": 22,
            "to_name": "openssl",
            "to_version": "3.0",
            "to_component_type": "library",
            "to_purl": "pkg:generic/openssl@3.0",
        }
        with (
            patch.object(api, "_fetch_one", side_effect=[document, totals]),
            patch.object(api, "_fetch_all", return_value=[edge]),
        ):
            result = api.dependency_graph(
                document_id=7,
                relationship_type=["DEPENDS_ON"],
                node_limit=80,
                edge_limit=240,
            )

        self.assertEqual(result["nodes"][0]["label"], "service@1.0")
        self.assertEqual(result["nodes"][1]["label"], "openssl@3.0")
        self.assertEqual(result["edges"][0]["resolution_status"], "resolved")
        self.assertFalse(result["summary"]["truncated"])

    def test_static_dashboard_is_mounted(self) -> None:
        paths = {getattr(route, "path", None) for route in api.app.routes}
        self.assertIn("/", paths)
        self.assertIn("/ui", paths)


if __name__ == "__main__":
    unittest.main()
