from __future__ import annotations

import asyncio
import io
import json
import os
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    from cbom_catalog import api
except ModuleNotFoundError as exc:
    if exc.name not in {"fastapi", "psycopg", "psycopg_pool"}:
        raise
    api = None


@unittest.skipIf(api is None, "install project dependencies to run API query tests")
class ApiQueryTests(unittest.TestCase):
    def test_assigned_scope_requires_exact_granted_collection_group_pair(self) -> None:
        assigned = {"mode": "assigned", "grants": [{"source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2"}]}
        allowed = SimpleNamespace(url=SimpleNamespace(path="/api/v1/fips/assessment"), query_params={"source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government"})
        denied = SimpleNamespace(url=SimpleNamespace(path="/api/v1/fips/assessment"), query_params={"source_collection": "collection-a", "service_group": "team-b"})
        with patch.object(api, "_fips_assessment_contract", return_value=None):
            self.assertFalse(api._request_within_assigned_scope(allowed, assigned))
        self.assertFalse(api._request_within_assigned_scope(denied, assigned))
        detail = SimpleNamespace(url=SimpleNamespace(path="/api/v1/inventory/service-groups/collection-a/team-a"), query_params={})
        self.assertFalse(api._request_within_assigned_scope(detail, assigned))

    def test_assigned_scope_requires_pair_query_for_document_component_detail(self) -> None:
        assigned = {"mode": "assigned", "grants": [{
            "source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2",
        }]}
        path = "/api/v1/documents/12/components"
        missing_pair = SimpleNamespace(url=SimpleNamespace(path=path), query_params={})
        granted_pair = SimpleNamespace(
            url=SimpleNamespace(path=path),
            query_params={"source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government"},
        )
        other_pair = SimpleNamespace(
            url=SimpleNamespace(path=path),
            query_params={"source_collection": "collection-a", "service_group": "team-b"},
        )
        self.assertFalse(api._request_within_assigned_scope(missing_pair, assigned))
        self.assertFalse(api._request_within_assigned_scope(granted_pair, assigned))
        self.assertFalse(api._request_within_assigned_scope(other_pair, assigned))

    def test_complete_fips_contract_must_match_assigned_ato(self) -> None:
        assigned = {"mode": "assigned", "grants": [{"source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2", "assessment_authorization_reference": "immutable-package-a"}]}
        request = SimpleNamespace(
            url=SimpleNamespace(path="/api/v1/fips/assessment"),
            query_params={"source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government"},
        )
        with (
            patch.object(api, "_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED", True),
            patch.object(api, "_product_fips_validation", return_value={"complete": True, "authorization_reference": "other-package"}),
        ):
            self.assertFalse(api._request_within_assigned_scope(request, assigned))

    def test_fips_assessment_allows_only_exact_referenced_product_evidence_view(self) -> None:
        assigned = {"mode": "assigned", "grants": [{
            "source_collection": "collection-a", "service_group": "team-a",
            "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2",
            "assessment_authorization_reference": "immutable-package-a",
        }]}
        request = SimpleNamespace(
            url=SimpleNamespace(path="/api/v1/fips/assessment"),
            method="GET",
            query_params={"source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government"},
        )
        incomplete_contract = {
            **request.query_params,
            "authorization_reference": "immutable-package-a",
        }
        with patch.object(api, "_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED", True):
            with patch.object(api, "_fips_assessment_contract", return_value=incomplete_contract):
                self.assertTrue(api._request_within_assigned_scope(request, assigned))
                for path in (
                    "/api/v1/fips/reporting/20x-preview",
                    "/api/v1/fips/poam.csv",
                    "/api/v1/fips/poam-workstreams.csv",
                    "/api/v1/fips/portfolio-poam.csv",
                    "/api/v1/fips/compliance-package.zip",
                ):
                    with self.subTest(path=path):
                        request.url.path = path
                        self.assertFalse(api._request_within_assigned_scope(request, assigned))
                request.url.path = "/api/v1/fips/assessment"
                request.method = "POST"
                self.assertFalse(api._request_within_assigned_scope(request, assigned))
                request.method = "GET"
                request.query_params = {**request.query_params, "service_group": "team-b"}
                self.assertFalse(api._request_within_assigned_scope(request, assigned))
                request.query_params = {**request.query_params, "service_group": "team-a"}
            with patch.object(api, "_fips_assessment_contract", return_value={**incomplete_contract, "authorization_reference": "other-package"}):
                self.assertFalse(api._request_within_assigned_scope(request, assigned))
            with patch.object(api, "_fips_assessment_contract", return_value={**incomplete_contract, "authorization_reference": ""}):
                self.assertFalse(api._request_within_assigned_scope(request, assigned))
            with patch.object(api, "_fips_assessment_contract", return_value={"authorization_reference": "immutable-package-a"}):
                self.assertFalse(api._request_within_assigned_scope(request, assigned))
            with patch.object(api, "_product_fips_validation", return_value={"complete": True, "authorization_reference": "immutable-package-a"}):
                self.assertTrue(api._request_within_assigned_scope(request, assigned))
        with (
            patch.object(api, "_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED", False),
            patch.object(api, "_fips_assessment_contract", return_value=incomplete_contract),
        ):
            self.assertFalse(api._request_within_assigned_scope(request, assigned))

    def test_admin_operational_reads_require_explicit_portfolio_grant(self) -> None:
        request = SimpleNamespace(url=SimpleNamespace(path="/api/v1/admin/overlays"), query_params={})
        self.assertFalse(api._request_within_assigned_scope(request, {"mode": "assigned", "grants": []}))
        self.assertFalse(api._request_within_assigned_scope(request, {"mode": "portfolio", "grants": []}))
        self.assertTrue(api._request_within_assigned_scope(request, {"mode": "portfolio", "role": "admin", "grants": []}))

    def test_assigned_admin_cannot_reach_global_write_handlers(self) -> None:
        principal = api.Principal(
            kind="human", subject="oidc:assigned-admin", role="viewer",
            scopes=frozenset(), user_id=7, oidc_groups=frozenset({"fedsse-team-a-engineers"}),
        )
        group_policy = json.dumps({"version": "test", "groups": {
            "fedsse-admins": {"access": "admin"},
            "fedsse-team-a-engineers": {"access": "engineer", "service_key": "team-a", "grants": [{
                "source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2",
            }]},
        }})
        reached_handler = False

        async def next_handler(_request):
            nonlocal reached_handler
            reached_handler = True
            return api.JSONResponse({"ok": True})

        for method, path in (
            ("POST", "/api/v1/admin/tokens"),
            ("PATCH", "/api/v1/admin/users/7"),
            ("DELETE", "/api/v1/admin/overlays/3"),
        ):
            with self.subTest(method=method, path=path):
                request = api.Request({
                    "type": "http", "method": method, "path": path,
                    "query_string": b"", "headers": [],
                    "scheme": "http", "server": ("test", 80),
                    "client": ("127.0.0.1", 1000),
                })
                with (
                    patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": group_policy}),
                    patch.object(api, "authenticate_request", return_value=principal),
                ):
                    response = asyncio.run(api.access_controls(request, next_handler))
                self.assertEqual(response.status_code, 403)
                self.assertFalse(reached_handler)
        request = api.Request({
            "type": "http", "method": "POST", "path": "/api/v1/admin/tokens",
            "query_string": b"", "headers": [], "scheme": "http",
            "server": ("test", 80), "client": ("127.0.0.1", 1000),
        })
        with (
            patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": group_policy}),
            patch.object(api, "authenticate_request", return_value=principal),
        ):
            response = asyncio.run(api.access_controls(request, next_handler))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(reached_handler)
        admin_principal = api.Principal(
            kind="human", subject="oidc:group-admin", role="viewer", scopes=frozenset(),
            user_id=7, oidc_groups=frozenset({"fedsse-admins"}),
        )
        admin_policy = json.dumps({"version": "test", "groups": {"fedsse-admins": {"access": "admin"}}})
        with (
            patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": admin_policy}),
            patch.object(api, "authenticate_request", return_value=admin_principal),
            patch.object(api, "_rate_limited", return_value=False),
        ):
            response = asyncio.run(api.access_controls(request, next_handler))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(reached_handler)

    def test_current_user_retains_configured_scope(self) -> None:
        principal = api.Principal(
            kind="human", subject="oidc:bootstrap-admin", role="viewer",
            scopes=frozenset(), user_id=7, oidc_groups=frozenset({"fedsse-team-a-engineers"}),
        )
        mapping = json.dumps({"version": "test", "groups": {
            "fedsse-admins": {"access": "admin"},
            "fedsse-team-a-engineers": {"access": "engineer", "service_key": "team-a", "grants": [{
                "source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2",
            }]},
        }})

        async def next_handler(_request):
            return api.JSONResponse({"role": "admin"})

        request = api.Request({
            "type": "http", "method": "GET", "path": "/api/v1/auth/me",
            "query_string": b"", "headers": [], "scheme": "http",
            "server": ("test", 80), "client": ("127.0.0.1", 1000),
        })
        with (
            patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": mapping}),
            patch.object(api, "authenticate_request", return_value=principal),
            patch.object(api, "_rate_limited", return_value=False),
        ):
            response = asyncio.run(api.access_controls(request, next_handler))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.state.assigned_scope["grants"][0]["service_group"], "team-a")

    def test_current_user_bootstraps_without_a_scope_grant(self) -> None:
        principal = api.Principal(
            kind="human", subject="oidc:bootstrap-admin", role="admin",
            scopes=frozenset(), user_id=7,
        )
        reached_handler = False

        async def next_handler(_request):
            nonlocal reached_handler
            reached_handler = True
            return api.JSONResponse({"role": "admin"})

        request = api.Request({
            "type": "http", "method": "GET", "path": "/api/v1/auth/me",
            "query_string": b"", "headers": [], "scheme": "http",
            "server": ("test", 80), "client": ("127.0.0.1", 1000),
        })
        with (
            patch.dict(os.environ, {"CBOM_PRINCIPAL_SCOPE_JSON": ""}),
            patch.object(api, "authenticate_request", return_value=principal),
            patch.object(api, "_rate_limited", return_value=False),
        ):
            response = asyncio.run(api.access_controls(request, next_handler))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(reached_handler)
        self.assertIsNone(getattr(request.state, "assigned_scope", "missing"))

    def test_unscoped_catalog_read_remains_denied_during_bootstrap(self) -> None:
        principal = api.Principal(
            kind="human", subject="oidc:bootstrap-admin", role="admin",
            scopes=frozenset(), user_id=7,
        )
        reached_handler = False

        async def next_handler(_request):
            nonlocal reached_handler
            reached_handler = True
            return api.JSONResponse({"catalog": "must not be returned"})

        request = api.Request({
            "type": "http", "method": "GET", "path": "/api/v1/documents",
            "query_string": b"", "headers": [], "scheme": "http",
            "server": ("test", 80), "client": ("127.0.0.1", 1000),
        })
        with (
            patch.dict(os.environ, {"CBOM_PRINCIPAL_SCOPE_JSON": ""}),
            patch.object(api, "authenticate_request", return_value=principal),
        ):
            response = asyncio.run(api.access_controls(request, next_handler))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(reached_handler)

    def test_pair_query_does_not_unlock_an_unscoped_catalog_route(self) -> None:
        assigned = {"mode": "assigned", "grants": [{"source_collection": "collection-a", "service_group": "team-a", "ato_boundary": "ATO-A"}]}
        request = SimpleNamespace(
            url=SimpleNamespace(path="/api/v1/stats"),
            query_params={"source_collection": "collection-a", "service_group": "team-a"},
        )
        self.assertFalse(api._request_within_assigned_scope(request, assigned))

    def test_service_register_etag_parts_include_the_selected_pair(self) -> None:
        with (
            patch.object(api, "_cached_fips_assessment", return_value=({}, 7, False)),
            patch.object(api, "_cached_catalog_value", return_value=({"service_groups": []}, 7, False)),
            patch.object(api, "_service_group_register_rows", return_value=[]),
            patch.object(api, "_active_service_impact_map", return_value={}),
            patch.object(api, "_active_overlay_map", return_value={}),
            patch.object(api, "_conditional_json_response", return_value=api.Response()) as respond,
        ):
            api.service_group_register(
                SimpleNamespace(), source_collection="collection-a",
                service_group="team-a", limit=50, offset=0,
            )
        self.assertEqual(respond.call_args.kwargs["parts"][:2], ("collection-a", "team-a"))

    def test_assigned_scope_rejects_duplicate_pair_with_different_ato(self) -> None:
        principal = api.Principal(
            kind="human", subject="oidc:scope-test", role="viewer", scopes=frozenset()
        )
        mapping = {
            principal.subject: {
                "grants": [
                    {"source_collection": "collection-a", "service_group": "team-a", "ato_boundary": "ATO-A"},
                    {"source_collection": "collection-a", "service_group": "team-a", "ato_boundary": "ATO-B"},
                ]
            }
        }
        with patch.dict(api.os.environ, {"CBOM_PRINCIPAL_SCOPE_JSON": json.dumps(mapping)}, clear=False):
            with self.assertRaises(api.AssignedScopeError):
                api._assigned_scope_for(principal)

    def test_fips_scope_cte_uses_list_predicate_for_multi_group_contract(self) -> None:
        sql, params = api._fips_scope_cte("collection-a", ["team-a", "team-b"])
        self.assertIn("sg.slug = ANY(%s)", sql)
        self.assertEqual(params, ("collection-a", ["team-a", "team-b"]))

    def test_20x_preview_keeps_internal_id_distinct_from_missing_run(self) -> None:
        assessment = {"assessment_run_id": "ASSESS-INTERNAL", "assessment_run": None, "assessment_contract": {"complete": False}, "poam_candidate_records": []}
        with patch.object(api, "_cached_fips_assessment", return_value=(assessment, 4, False)):
            result = api.fips_20x_preview()
        self.assertIsNone(result["assessment_run_id"])
        self.assertEqual(result["internal_analysis_id"], "ASSESS-INTERNAL")
        self.assertFalse(result["reportable"])

    def test_portfolio_poam_summary_exposes_semantic_metric_metadata(self) -> None:
        assessment = {
            "assessment_contract": {"complete": True, "fingerprint": "assessment"},
            "summary": {"deduplicated_poam_candidates": 2},
            "summary_metric_metadata": {
                "deduplicated_poam_candidates": {
                    "label": "Deduplicated draft POA&M candidates",
                    "unit": "candidates",
                    "interpretation": "Draft only.",
                },
            },
        }
        with (
            patch.object(api, "_cached_fips_assessment", return_value=(assessment, 1, False)),
            patch.object(api, "_conditional_json_response", return_value=api.Response()) as response,
        ):
            api.portfolio_poam_summary(SimpleNamespace())
        payload = response.call_args.args[1]
        self.assertEqual(payload["summary"]["deduplicated_poam_candidates"], 2)
        self.assertEqual(
            payload["summary_metric_metadata"]["deduplicated_poam_candidates"]["label"],
            "Deduplicated draft POA&M candidates",
        )

    def test_load_fips_assessment_binds_complete_multi_group_contract_at_sql_layer(self) -> None:
        contract = {
            "ato_boundary": "Test ATO", "source_collection": "collection-a",
            "service_groups": ["team-a", "team-b"], "accountable_owner": "Owner",
            "assessment_as_of": "2026-09-22T00:00:00+00:00", "reporting_profile": "rev5-candidate",
            "authority_register": {"path": "authority", "sha256": "a" * 64, "retrieved_at": "2026-09-22"},
        }
        expected = {"assessment_contract": {"complete": False}, "summary": {}, "service_groups": []}
        with (
            patch.object(api, "_fetch_all", side_effect=[[], [], []]) as fetch_all,
            patch.object(api, "_active_target_module_contract", return_value={"teams": []}) as planning,
            patch.object(api, "build_assessment", return_value=expected) as build,
            patch.object(api, "portfolio_delivery_waves", return_value=[]) as waves,
        ):
            result = api._load_fips_assessment(None, None, contract)
        self.assertIs(result, expected)
        self.assertEqual(fetch_all.call_count, 3)
        for call in fetch_all.call_args_list:
            sql, params = call.args
            self.assertIn("sg.slug = ANY(%s)", sql)
            self.assertEqual(params, ("collection-a", ["team-a", "team-b"]))
        self.assertEqual(build.call_args.kwargs["scope"], {"source_collection": "collection-a", "service_group": ["team-a", "team-b"]})
        planning.assert_not_called()
        waves.assert_not_called()
        self.assertEqual(result["portfolio_delivery_waves"], [])
        self.assertIn("Portfolio delivery waves are unavailable", result["limitations"][-1])

    def test_incomplete_contract_hides_all_candidate_dimensions(self) -> None:
        assessment = {
            "assessment_contract": {"complete": False, "missing_required_facts": ["ato_boundary"]},
            "summary": {"candidate_gap_findings": 3, "deduplicated_poam_candidates": 3, "proposed_remediation_workstreams": 2, "portfolio_poam_candidates": 2},
            "poam_items": [{"poam_candidate_id": "FIPS3-ONE"}],
            "poam_candidate_records": [{"poam_candidate_id": "FIPS3-ONE"}],
            "poam_workstreams": [{"workstream_id": "FIPSW-ONE"}],
            "portfolio_poam_items": [{"portfolio_poam_id": "FIPS3-PORTFOLIO-ACTIVE-CERT"}],
            "portfolio_delivery_waves": [{"wave": "October"}],
        }
        shaped = api._shape_fips_assessment(
            assessment, include_findings=False, query=None, poam_limit=20, poam_offset=0
        )
        self.assertEqual(shaped["poam_items"], [])
        self.assertEqual(shaped["poam_candidate_records"], [])
        self.assertEqual(shaped["poam_workstreams"], [])
        self.assertEqual(shaped["portfolio_poam_items"], [])
        self.assertEqual(shaped["portfolio_delivery_waves"], [{"wave": "October"}])
        self.assertEqual(shaped["poam_page"]["total"], 0)
        self.assertEqual(shaped["summary"]["portfolio_poam_candidates"], 0)
        self.assertEqual(shaped["summary"]["candidate_gap_findings"], 0)

    def test_admin_helper_enforces_token_scope(self) -> None:
        principal = api.Principal(
            kind="token",
            subject="token:test",
            role="admin",
            scopes=frozenset({"annotations:write"}),
            user_id=7,
            credential_id="00000000-0000-0000-0000-000000000001",
        )

        self.assertIs(api._require_admin(principal, "annotations:write"), principal)
        with self.assertRaises(api.HTTPException) as error:
            api._require_admin(principal, "poam:write")
        self.assertEqual(error.exception.status_code, 403)

    def test_audit_event_serializes_database_datetimes_for_jsonb(self) -> None:
        recorded: list[tuple[object, ...]] = []

        class Database:
            def execute(self, _query: str, params: tuple[object, ...]) -> None:
                recorded.append(params)

        principal = api.Principal(
            kind="human",
            subject="oidc:test",
            role="admin",
            scopes=frozenset(),
            user_id=7,
            email="admin@example.invalid",
        )
        request = SimpleNamespace(state=SimpleNamespace(request_id="request-1"))
        observed = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)

        with patch.object(api, "Jsonb", side_effect=lambda value: value):
            api._audit_event(
                Database(),
                request,
                principal,
                action="test.update",
                resource_type="test",
                resource_key="one",
                after_state={"observed_at": observed},
            )

        self.assertEqual(recorded[0][-2], {"observed_at": "2026-09-22T12:00:00+00:00"})
        self.assertEqual(recorded[0][-1], "success")

    def test_distinct_cold_cache_builders_do_not_block_each_other(self) -> None:
        barrier = threading.Barrier(2)

        def build(value: str) -> str:
            barrier.wait(timeout=2)
            return value

        with api._cache_lock:
            api._data_cache.clear()
            api._cache_revision = None

        with (
            patch.object(api, "_catalog_revision", return_value=17),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(
                api._cached_catalog_value, "dashboard", (), lambda: build("dashboard")
            )
            second = executor.submit(
                api._cached_catalog_value, "assessment", (), lambda: build("assessment")
            )

        self.assertEqual(first.result(), ("dashboard", 17, False))
        self.assertEqual(second.result(), ("assessment", 17, False))

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
            "assessment_contract": {"complete": True},
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

    def test_fips_response_applies_versioned_overlay_without_mutating_evidence(self) -> None:
        source = {
            "assessment_contract": {"complete": True},
            "poam_items": [
                {
                    "poam_candidate_id": "FIPS3-A",
                    "responsible_owner": "Evidence owner",
                    "scheduled_completion_date": "2026-10-01",
                }
            ]
        }
        result = api._shape_fips_assessment(
            source,
            include_findings=False,
            query=None,
            poam_limit=20,
            poam_offset=0,
            candidate_overlays={
                "FIPS3-A": {
                    "version": 2,
                    "payload": {
                        "responsible_owner": "Reviewed owner",
                        "scheduled_completion_date": "2026-12-01",
                    },
                }
            },
        )

        self.assertEqual(source["poam_items"][0]["responsible_owner"], "Evidence owner")
        self.assertEqual(result["poam_items"][0]["responsible_owner"], "Reviewed owner")
        self.assertEqual(result["poam_items"][0]["admin_overlay"]["version"], 2)

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
            "assessment_contract": {"complete": True},
            "policy": {"assessment_date": "2026-09-18"},
            "poam_items": [{
                "poam_candidate_id": "FIPS3-EXAMPLE",
                "responsible_owner": "Evidence owner",
            }],
        }
        with (
            patch.object(api, "_cached_fips_assessment", return_value=(assessment, 7, False)) as load,
            patch.object(api, "_active_overlay_map", return_value={
                "FIPS3-EXAMPLE": {
                    "version": 2,
                    "payload": {"responsible_owner": "Reviewed owner"},
                }
            }),
            patch.object(api, "render_poam_csv", return_value="POA&M ID\\r\\nFIPS3-EXAMPLE\\r\\n") as render,
        ):
            response = api.fips_poam_export("collection-a", "team")

        self.assertEqual(load.call_args.args, ("collection-a", "team"))
        self.assertEqual(response.media_type, "text/csv")
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="fips-140-3-poam-candidates-2026-09-18.csv"',
        )
        self.assertIn(b"FIPS3-EXAMPLE", response.body)
        self.assertEqual(render.call_args.args[0][0]["responsible_owner"], "Reviewed owner")
        self.assertEqual(
            assessment["poam_items"][0]["responsible_owner"], "Evidence owner"
        )

    def test_compliance_package_has_candidate_manifest_and_both_poam_views(self) -> None:
        assessment = {
            "assessment_contract": {"complete": True},
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
            patch.object(api, "_active_overlay_map", return_value={}),
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
            "target_modules": [{
                "normalized_status": "asserted_not_compliant",
                "verification": {"overall": {"state": "contradicted"}},
            }],
        }]}

        service_impacts = {"collection-a/team": {
            "poam_impact": "Blocker: No Data Available",
            "risk_category": "Critical",
            "comments": "Customer-facing service",
            "team": "Team",
            "evidence_grade": "user_asserted",
            "review_required": True,
            "source": {"source_filename": "service_impact.csv", "source_row": 7},
        }}

        rows = api._service_group_register_rows(
            assessment, overview, milestones, service_impacts
        )

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
        self.assertEqual(row["poam_impact"], "Blocker: No Data Available")
        self.assertEqual(row["risk_category"], "Critical")
        self.assertEqual(row["comments"], "Customer-facing service")
        self.assertEqual(row["coverage_gap_count"], 0)
        self.assertEqual(row["target_module_review_count"], 1)
        self.assertEqual(row["target_module_asserted_not_compliant_count"], 1)
        self.assertEqual(row["target_module_verification_conflict_count"], 1)
        self.assertEqual(row["service_impact_evidence_grade"], "user_asserted")
        self.assertTrue(row["service_impact_review_required"])

    def test_service_group_overlays_apply_to_register_and_detail_copies(self) -> None:
        rows = [{
            "service_key": "collection-a/team",
            "effective_owners": ["Evidence owner"],
            "leads": ["Evidence lead"],
            "il2": {"state": "done", "farthest_date": None},
            "il5": {"state": "not_supplied", "farthest_date": None},
        }]
        overlay = {
            "version": 3,
            "payload": {
                "effective_owners": ["Reviewed owner"],
                "il2_date": "2026-12-01",
            },
        }

        result = api._apply_service_group_overlays(
            rows, {"collection-a/team": overlay}
        )

        self.assertEqual(result[0]["effective_owners"], ["Reviewed owner"])
        self.assertEqual(result[0]["owner_state"], "supplied")
        self.assertEqual(result[0]["il2"]["farthest_date"], "2026-12-01")
        self.assertTrue(result[0]["il2"]["admin_override"])
        self.assertEqual(result[0]["admin_overlay"]["version"], 3)

    def test_service_group_detail_withholds_candidates_and_planning_without_collection_provenance(self) -> None:
        service_key = "collection-a/team"
        canonical = {
            "assessment_run_id": "RUN-CANONICAL",
            "assessment_run": None,
            "service_groups": [{
                "service": service_key,
                "service_group_name": "Team",
                "documents": 1,
                "finding_count": 1,
            }],
            "coverage_gaps": [],
            "poam_items": [{
                "poam_candidate_id": "FIPS3-CANONICAL",
                "affected_services": [service_key, "collection-a/other"],
                "linked_finding_ids": ["FINDING-1"],
            }],
            "poam_workstreams": [{
                "workstream_id": "FIPSW-CANONICAL",
                "affected_services": [service_key, "collection-a/other"],
            }],
            "portfolio_poam_items": [{
                "portfolio_poam_id": "FIPSP-CANONICAL",
                "affected_service_groups": [service_key],
            }],
        }
        canonical_with_run = {
            **canonical,
            "assessment_run": {"assessment_run_id": "RUN-CANONICAL"},
        }
        scoped = {
            **canonical,
            "assessment_run_id": "RUN-SCOPED",
            "policy": {},
            "summary": {},
            "coverage_gaps": [],
            "findings": [{
                "finding_id": "FINDING-1", "rule_id": "FIPS-RULE", "title": "Evidence observation",
                "poam_eligible": True, "poam_candidate_id": "FIPS3-CANONICAL",
                "poam_candidate_ids": ["FIPS3-CANONICAL"], "candidate_status": "draft",
                "remediation": "Candidate remediation text", "risk_rationale": "Candidate risk text",
                "workstream_ids": ["FIPSW-CANONICAL"],
            }],
        }
        scoped_with_run = {**scoped, "assessment_run": {"assessment_run_id": "RUN-CANONICAL"}}
        overview = {"service_groups": [{
            "source_collection": "collection-a",
            "slug": "team",
            "display_name": "Team",
        }]}
        milestones = {"groups": [{
            "service_group": "team",
            "mapping_status": "mapped",
            "owners": ["Owner"],
            "leads": ["Lead"],
            "tracker_rows": [],
            "target_modules": [],
        }]}

        with (
            patch.object(api, "_cached_fips_assessment", side_effect=[
                (scoped, 1, False), (scoped_with_run, 1, False), (scoped_with_run, 1, False),
            ]),
            patch.object(api, "_cached_catalog_value", return_value=(overview, 1, False)),
            patch.object(api, "_active_target_module_contract", return_value=None),
            patch.object(api, "team_milestones", return_value=milestones),
            patch.object(api, "_active_service_impact_map", return_value={}),
            patch.object(api, "_active_overlay_map", return_value={}),
            patch.object(api, "_document_inventory_rows", return_value=([], 0)),
            patch.object(api, "_component_inventory_rows", return_value=([], 0)),
        ):
            result = api.service_group_register_detail(
                "collection-a", "team", product_scope_id="secure-access-government",
                document_limit=50, document_offset=0, library_limit=50, library_offset=0,
            )
            positive = api.service_group_register_detail(
                "collection-a", "team", product_scope_id="secure-access-government",
                document_limit=50, document_offset=0, library_limit=50, library_offset=0,
            )
            admin = api.service_group_register_detail(
                "collection-a", "team", product_scope_id=None,
                document_limit=50, document_offset=0, library_limit=50, library_offset=0,
                request=SimpleNamespace(state=SimpleNamespace(assigned_scope={
                    "mode": "portfolio", "role": "admin",
                })),
            )

        self.assertTrue(result["evidence_only"])
        self.assertFalse(result["candidate_only"])
        self.assertEqual(result["profile"]["effective_owners"], [])
        self.assertEqual(result["profile"]["poam_candidate_ids"], [])
        self.assertEqual(result["assessment"]["poam_items"], [])
        self.assertEqual(result["assessment"]["poam_workstreams"], [])
        self.assertEqual(result["assessment"]["portfolio_poam_items"], [])
        self.assertEqual(result["assessment"]["summary"]["candidate_dimensions"], 0)
        self.assertEqual(
            result["assessment"]["canonical_assessment_run_id"],
            None,
        )
        self.assertEqual(positive["assessment"]["canonical_assessment_run_id"], "RUN-CANONICAL")
        observation = result["assessment"]["findings"][0]
        self.assertFalse(observation["poam_eligible"])
        self.assertEqual(observation["assertion_state"], "evidence_observation")
        for hidden in ("poam_candidate_id", "poam_candidate_ids", "candidate_status", "remediation", "risk_rationale", "workstream_ids"):
            self.assertNotIn(hidden, observation)
        self.assertFalse(admin["evidence_only"])
        self.assertEqual(admin["profile"]["effective_owners"], ["Owner"])
        self.assertEqual(
            [item["poam_candidate_id"] for item in admin["assessment"]["poam_items"]],
            ["FIPS3-CANONICAL"],
        )

    def test_team_milestones_projects_only_selected_group_and_tracker_rows(self) -> None:
        payload = {
            "groups": [
                {"service_group": "team-a", "owners": ["A"]},
                {"service_group": "team-b", "owners": ["B"]},
            ],
            "all_tracker_rows": [
                {"team": "A", "mapped_service_groups": ["team-a"]},
                {"team": "Shared", "mapped_service_groups": ["team-a", "team-b"]},
                {"team": "B", "mapped_service_groups": ["team-b"]},
            ],
        }
        with (
            patch.object(api, "_active_target_module_contract", return_value=None),
            patch.object(api, "team_milestones", return_value=payload),
        ):
            result = api.fips_team_milestones("collection-a", "team-a")

        self.assertEqual([row["service_group"] for row in result["groups"]], ["team-a"])
        self.assertEqual([row["team"] for row in result["all_tracker_rows"]], ["A", "Shared"])

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

    def test_planning_summary_exposes_done_and_vendor_dependency_states(self) -> None:
        profile = {
            "tracker_rows": [
                {
                    "team": "One",
                    "il2": {"raw_value": "Done", "status": "done", "date": None},
                    "il5": {
                        "raw_value": "Vendor Dependency",
                        "status": "vendor_dependency",
                        "date": None,
                    },
                }
            ]
        }

        self.assertEqual(api._planning_summary(profile, "il2")["state"], "done")
        self.assertEqual(
            api._planning_summary(profile, "il5")["state"], "vendor_dependency"
        )

        mixed_profile = {
            "tracker_rows": [
                {"team": "One", "il2": {"raw_value": "Done", "status": "done", "date": None}},
                {"team": "Two", "il2": {"raw_value": "", "status": "not_supplied", "date": None}},
            ]
        }
        self.assertEqual(api._planning_summary(mixed_profile, "il2")["state"], "done")

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
        self.assertIn("WITH inventory AS MATERIALIZED", sql)
        self.assertIn("array_agg(sf.source_path", sql)
        self.assertEqual(
            params[:5],
            ("collection-a", "team", "collection-a", "team", "%only-in-a.json%"),
        )

    def test_document_components_supports_search_and_explicit_crypto_filter(self) -> None:
        with (
            patch.object(api, "_fetch_one", return_value={"id": 7}),
            patch.object(api, "_fetch_all", return_value=[]) as fetch,
        ):
            api.document_components(
                document_id=7,
                source_collection="collection-a",
                service_group="team",
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

    def test_document_components_can_return_total_without_changing_legacy_list_response(self) -> None:
        with (
            patch.object(api, "_fetch_one", side_effect=[{"id": 7}, {"total": 4}]),
            patch.object(api, "_fetch_all", return_value=[{"occurrence_id": 1}]),
        ):
            result = api.document_components(
                document_id=7, source_collection="collection-a", service_group="team",
                include_total=True, limit=25, offset=0,
            )

        self.assertEqual(result["items"], [{"occurrence_id": 1}])
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["limit"], 25)

    def test_admin_document_components_can_read_portfolio_detail(self) -> None:
        with (
            patch.object(api, "_fetch_one", side_effect=[{"id": 7}, {"total": 2}]) as fetch_one,
            patch.object(api, "_fetch_all", return_value=[{"occurrence_id": 1}]),
        ):
            result = api.document_components(
                document_id=7, source_collection=None, service_group=None,
                include_total=True, limit=25, offset=0,
            )

        self.assertIn("sf.is_present", fetch_one.call_args_list[0].args[0])
        self.assertEqual(result["total"], 2)

    def test_component_usage_can_read_portfolio_detail(self) -> None:
        with (
            patch.object(api, "_fetch_one", side_effect=[{"id": 9}, {"total": 3}]),
            patch.object(api, "_fetch_all", return_value=[{"occurrence_id": 1}]) as fetch,
        ):
            result = api.component_usage(
                component_id=9, source_collection=None, service_group=None,
                explicit_crypto_only=True, include_total=True, limit=25, offset=0,
            )

        sql, params = fetch.call_args.args
        self.assertNotIn("sc.slug = %s", sql)
        self.assertEqual(params, (9, 25, 0))
        self.assertEqual(result["total"], 3)

    def test_component_usage_explicit_filter_matches_library_aggregate_semantics(self) -> None:
        with (
            patch.object(api, "_fetch_one", side_effect=[{"id": 9}, {"total": 3}]),
            patch.object(api, "_fetch_all", return_value=[{"occurrence_id": 1, "explicit_crypto": True}]) as fetch,
        ):
            result = api.component_usage(
                component_id=9, source_collection="collection-a", service_group="team",
                explicit_crypto_only=True, include_total=True, limit=25, offset=0,
            )

        sql, params = fetch.call_args.args
        self.assertIn("fedramp:fips:crypto-relevant", sql)
        self.assertIn("dc.component_id = %s AND sf.is_present", sql)
        self.assertEqual(params, (9, "collection-a", "team", 25, 0))
        self.assertEqual(result["total"], 3)

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
                source_collection="collection-a",
                service_group="team",
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
