from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from cbom_catalog import access_control, api

POLICY = {
    "version": "test-v1",
    "groups": {
        "fedsse-admins": {"access": "admin"},
        "fedsse-external": {"access": "summary"},
        "fedsse-scr2-leads": {"access": "summary"},
        "fedsse-team-a-leads": {
            "access": "lead",
            "service_key": "team-a",
            "grants": [{"source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2"}],
        },
        "fedsse-team-b-engineers": {
            "access": "engineer",
            "service_key": "team-b",
            "grants": [{"source_collection": "collection-a", "service_group": "team-b", "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2"}],
        },
    },
}


class OidcGroupPolicyTests(TestCase):
    def _scope(self, groups: set[str]) -> dict:
        principal = api.Principal(
            kind="human", subject="oidc:test-subject", role="viewer",
            scopes=frozenset(), oidc_groups=frozenset(groups),
        )
        with patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(POLICY)}, clear=False):
            return api._assigned_scope_for(principal)

    def test_exact_group_memberships_union_per_service(self) -> None:
        result = self._scope({"fedsse-team-a-leads", "fedsse-team-b-engineers"})
        self.assertEqual(result["role"], "lead")
        self.assertTrue(result["summary_access"])
        self.assertEqual(
            result["grants"],
            [
                {"source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2", "access": "lead"},
                {"source_collection": "collection-a", "service_group": "team-b", "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2", "access": "engineer"},
            ],
        )

    def test_mode_choices_come_only_from_exact_matched_categories(self) -> None:
        result = self._scope({"fedsse-admins", "fedsse-team-a-leads", "fedsse-team-b-engineers"})
        self.assertEqual(
            result["available_modes"], ["admin", "product_lead", "product_engineer"],
        )
        self.assertEqual(result["default_mode"], "admin")

        lead_only = self._scope({"fedsse-team-a-leads"})
        self.assertEqual(lead_only["available_modes"], ["product_lead"])
        with self.assertRaises(api.AssignedScopeError):
            api._apply_access_mode(lead_only, "product_engineer")

    def test_selected_product_engineer_is_a_read_only_union(self) -> None:
        base = self._scope({"fedsse-team-a-leads", "fedsse-team-b-engineers"})
        selected = api._apply_access_mode(base, "product_engineer")
        self.assertEqual(selected["mode"], "assigned")
        self.assertEqual(selected["role"], "engineer")
        self.assertEqual(selected["active_mode"], "product_engineer")
        self.assertEqual({row["access"] for row in selected["grants"]}, {"engineer"})

    def test_roster_snapshot_retains_admin_entitlement_after_lead_selection(self) -> None:
        principal = api.Principal(
            kind="human", subject="oidc:admin-lead", role="viewer", scopes=frozenset(),
            oidc_groups=frozenset({"fedsse-admins", "fedsse-team-a-leads"}), user_id=7,
        )
        assigned = api._apply_access_mode(
            self._scope({"fedsse-admins", "fedsse-team-a-leads"}), "product_lead",
        )
        database = MagicMock()
        with patch.object(api, "_access_roster_enabled", return_value=True), \
             patch.object(api, "api_connection") as connection, \
             patch.object(api, "record_snapshot") as record:
            connection.return_value.__enter__.return_value = database
            api._record_access_roster_snapshot(principal, assigned)
        self.assertEqual(record.call_args.kwargs["effective_role"], "lead")
        self.assertTrue(record.call_args.kwargs["verified_admin"])
        database.commit.assert_called_once()

    def test_product_lead_keeps_pair_level_write_boundaries(self) -> None:
        base = self._scope({"fedsse-team-a-leads", "fedsse-team-b-engineers"})
        selected = api._apply_access_mode(base, "product_lead")
        by_service = {row["service_group"]: row["access"] for row in selected["grants"]}
        self.assertEqual(by_service, {"team-a": "lead", "team-b": "engineer"})

    def test_union_register_requires_assigned_mode_and_has_no_query_widening(self) -> None:
        request = SimpleNamespace(url=SimpleNamespace(path="/api/v1/portfolio/assigned-service-groups"), method="GET", query_params={})
        self.assertTrue(api._request_within_assigned_scope(request, {"mode": "assigned", "grants": [{"service_group": "team-a"}]}))
        self.assertFalse(api._request_within_assigned_scope(request, {"mode": "summary", "grants": []}))
        self.assertFalse(api._request_within_assigned_scope(request, {"mode": "portfolio", "role": "admin", "grants": []}))

    def test_union_register_filters_rows_to_exact_grant_pairs(self) -> None:
        request = SimpleNamespace(state=SimpleNamespace(assigned_scope={
            "mode": "assigned", "active_mode": "product_lead", "grants": [{
                "source_collection": "collection-a", "service_group": "team-a",
                "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2", "access": "lead",
                "assessment_authorization_reference": "immutable-contract-a",
            }],
        }))
        response = api.assigned_service_group_register(request)
        self.assertEqual(response["scope"], "assigned-service-union")
        self.assertTrue(response["evidence_only"])
        self.assertEqual(response["detail_state"], "attribution_pending")
        self.assertEqual(response["items"], [{
            "source_collection": "collection-a", "service_group": "team-a",
            "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2",
            "access": "lead", "detail_state": "attribution_pending",
            "assessment_authorization_reference": "immutable-contract-a",
        }])

    def test_admin_user_query_qualifies_joined_identity_column(self) -> None:
        request = SimpleNamespace(state=SimpleNamespace(principal=api.Principal(
            kind="human", subject="oidc:admin", role="admin", scopes=frozenset(),
        )))
        with patch.object(api, "_fetch_all", return_value=[]) as fetch:
            self.assertEqual(api.admin_users(request), {"items": [], "total": 0})
        self.assertIn("app_user.oidc_subject IS NOT NULL", fetch.call_args.args[0])
        self.assertIn("snapshot.verified_admin", fetch.call_args.args[0])

    def test_roster_mutation_is_denied_when_the_feature_is_disabled(self) -> None:
        principal = api.Principal(
            kind="human", subject="oidc:admin", role="admin", scopes=frozenset(), user_id=7,
        )
        request = SimpleNamespace(state=SimpleNamespace(principal=principal, request_id="request-1"))
        with patch.object(api, "_access_roster_enabled", return_value=False):
            with self.assertRaises(api.HTTPException) as error:
                api.change_admin_user_access(
                    8, api.UserAccessActionCreate(action="revoke", reason="Approved operational revocation."), request,
                )
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(error.exception.detail, "Operational access roster is not enabled")

    def test_portfolio_overview_summary_returns_json_response(self) -> None:
        request = api.Request({
            "type": "http", "method": "GET", "path": "/api/v1/portfolio/overview-summary",
            "query_string": b"", "headers": [], "scheme": "http",
            "server": ("test", 80), "client": ("127.0.0.1", 1000),
        })
        overview = {"counts": {"documents": 3}, "format_coverage": [], "component_types": []}
        with patch.object(api, "_cached_catalog_value", return_value=(overview, 1, False)):
            response = api.portfolio_overview_summary(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"scope":"portfolio-summary"', response.body)

    def test_portfolio_overview_projection_excludes_identifier_bearing_data(self) -> None:
        """A Summary response may contain counts and generic categories only."""
        overview = {
            "counts": {
                "source_files": 12,
                "crypto_component_occurrences": 3,
                "internal_service_name": "dns-platform",
                "enabled": True,
                "nested": {"document": "private-sbom.json"},
            },
            "format_coverage": [
                {"format_name": "CycloneDX JSON", "source_files": 7, "source_path": "private-sbom.json"},
                {"document_kind": "SPDX", "source_files": 3, "document_name": "internal.spdx"},
                {"format_name": "Internal proprietary format", "source_files": 2, "source_path": "restricted.csv"},
            ],
            "component_types": [
                {"component_type": "library", "unique_components": 4, "component_name": "OpenSSL 3.1.2"},
                {"component_type": "service", "unique_components": 1, "service_name": "dns-platform"},
                {"component_type": "private-internal-type", "unique_components": 2, "component_name": "internal-crypto"},
            ],
            "service_groups": [{"slug": "dns-platform", "display_name": "DNS Platform"}],
            "top_crypto_libraries": [{"name": "OpenSSL", "version": "3.1.2"}],
        }

        payload = api._portfolio_overview_summary(overview)

        self.assertEqual(set(payload), {"scope", "counts", "format_coverage", "component_types"})
        self.assertEqual(payload["scope"], "portfolio-summary")
        self.assertEqual(payload["counts"], {"source_files": 12, "crypto_component_occurrences": 3})
        self.assertEqual(
            payload["format_coverage"],
            [
                {"format": "CycloneDX", "count": 7},
                {"format": "SPDX", "count": 3},
                {"format": "OSCAL", "count": 0},
                {"format": "Other", "count": 2},
            ],
        )
        self.assertEqual(
            payload["component_types"],
            [
                {"component_type": "library", "count": 4},
                {"component_type": "service", "count": 1},
                {"component_type": "unknown", "count": 2},
            ],
        )
        serialized = json.dumps(payload)
        for identifier in ("dns-platform", "DNS Platform", "private-sbom.json", "internal.spdx", "restricted.csv", "OpenSSL", "3.1.2", "internal-crypto"):
            self.assertNotIn(identifier, serialized)

    def test_shared_ato_does_not_grant_another_service(self) -> None:
        assigned = self._scope({"fedsse-team-a-leads"})
        own = SimpleNamespace(
            url=SimpleNamespace(path="/api/v1/documents"), method="GET",
            query_params={"source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government"},
        )
        other_product = SimpleNamespace(
            url=SimpleNamespace(path="/api/v1/documents"), method="GET",
            query_params={"source_collection": "collection-a", "service_group": "team-b"},
        )
        self.assertFalse(api._request_within_assigned_scope(own, assigned))
        self.assertFalse(api._request_within_assigned_scope(other_product, assigned))

    def test_assigned_product_scope_denies_every_detail_and_export_route_until_enabled(self) -> None:
        assigned = self._scope({"fedsse-team-a-leads"})
        paths = (
            "/api/v1/dashboard/overview",
            "/api/v1/fingerprints",
            "/api/v1/documents",
            "/api/v1/inventory/documents",
            "/api/v1/documents/42",
            "/api/v1/documents/42/components",
            "/api/v1/documents/42/dependency-graph",
            "/api/v1/components",
            "/api/v1/components/42/usage",
            "/api/v1/inventory/libraries",
            "/api/v1/artifacts",
            "/api/v1/dependency-documents",
            "/api/v1/dependency-closure",
            "/api/v1/external-records",
            "/api/v1/fips/assessment",
            "/api/v1/fips/reporting/20x-preview",
            "/api/v1/fips/poam.csv",
            "/api/v1/fips/poam-workstreams.csv",
            "/api/v1/fips/portfolio-poam.csv",
            "/api/v1/fips/compliance-package.zip",
            "/api/v1/review-proposals",
        )
        params = {
            "source_collection": "collection-a", "service_group": "team-a",
            "product_scope_id": "secure-access-government",
        }
        for path in paths:
            with self.subTest(path=path):
                request = SimpleNamespace(
                    url=SimpleNamespace(path=path), method="GET", query_params=params,
                )
                self.assertFalse(api._request_within_assigned_scope(request, assigned))

    def test_unknown_or_prefix_spoofed_group_is_denied(self) -> None:
        for group in ("fedsse-admins-extra", "FEDSSE-ADMINS", " fedsse-admins"):
            with self.subTest(group=group):
                result = self._scope({group})
                self.assertEqual(result["mode"], "denied")
                self.assertEqual(result["role"], "none")
                self.assertFalse(result["summary_access"])

    def test_external_has_summary_only(self) -> None:
        result = self._scope({"fedsse-external"})
        self.assertEqual(result["mode"], "summary")
        self.assertEqual(result["role"], "summary")
        self.assertEqual(result["grants"], [])

    def test_exact_admin_group_is_administrator(self) -> None:
        result = self._scope({"fedsse-admins"})
        self.assertEqual(result["mode"], "portfolio")
        self.assertEqual(result["role"], "admin")

    def test_lead_overrides_engineer_for_same_product_scope(self) -> None:
        policy = json.loads(json.dumps(POLICY))
        policy["groups"]["fedsse-team-a-engineers"] = {
            "access": "engineer",
            "service_key": "team-a",
            "grants": [{"source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2"}],
        }
        principal = api.Principal(kind="human", subject="oidc:test", role="viewer", scopes=frozenset(), oidc_groups=frozenset({"fedsse-team-a-leads", "fedsse-team-a-engineers"}))
        with patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(policy)}, clear=False):
            result = api._assigned_scope_for(principal)
        self.assertEqual(result["grants"][0]["access"], "lead")

    def test_service_key_must_match_group_stem(self) -> None:
        policy = json.loads(json.dumps(POLICY))
        policy["groups"]["fedsse-team-a-leads"]["service_key"] = "team-b"
        with (
            patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(policy)}, clear=False),
            self.assertRaises(api.AssignedScopeError),
        ):
            api._assigned_scope_for(api.Principal(kind="human", subject="oidc:test", role="viewer", scopes=frozenset(), oidc_groups=frozenset({"fedsse-team-a-leads"})))

    def test_summary_route_is_read_only(self) -> None:
        assigned = {"mode": "summary", "role": "viewer", "summary_access": True, "grants": []}
        request = SimpleNamespace(url=SimpleNamespace(path="/api/v1/portfolio/overview-summary"), method="GET", query_params={})
        self.assertTrue(api._request_within_assigned_scope(request, assigned))
        request.method = "POST"
        self.assertFalse(api._request_within_assigned_scope(request, assigned))

    def test_shared_planning_is_read_only_for_each_dashboard_role(self) -> None:
        for path in ("/api/v1/portfolio/poam-planning", "/api/v1/portfolio/risk-assessment-poam"):
            request = SimpleNamespace(url=SimpleNamespace(path=path), method="GET", query_params={})
            for mode, role in (("portfolio", "admin"), ("assigned", "lead"), ("assigned", "engineer"), ("summary", "summary")):
                with self.subTest(path=path, mode=mode, role=role):
                    assigned = {"mode": mode, "role": role, "summary_access": True, "grants": []}
                    self.assertTrue(api._request_within_assigned_scope(request, assigned))
                    request.method = "POST"
                    self.assertFalse(api._request_within_assigned_scope(request, assigned))
                    request.method = "PUT"
                    self.assertFalse(api._request_within_assigned_scope(request, assigned))
                    request.method = "GET"

    def test_summary_user_cannot_read_direct_catalog_or_export_routes(self) -> None:
        assigned = {"mode": "summary", "role": "viewer", "summary_access": True, "grants": []}
        for path in ("/api/v1/documents/42", "/api/v1/fips/poam.csv"):
            with self.subTest(path=path):
                request = SimpleNamespace(url=SimpleNamespace(path=path), method="GET", query_params={})
                self.assertFalse(api._request_within_assigned_scope(request, assigned))

    def test_local_admin_has_portfolio_access_without_a_grant(self) -> None:
        principal = api.Principal(kind="local", subject="local-development", role="admin", scopes=frozenset())
        assigned = api._assigned_scope_for(principal)
        request = SimpleNamespace(url=SimpleNamespace(path="/api/v1/documents"), method="GET", query_params={})
        self.assertEqual(assigned["role"], "admin")
        self.assertTrue(api._request_within_assigned_scope(request, assigned))

    def test_token_requires_endpoint_scope_even_with_portfolio_mapping(self) -> None:
        principal = api.Principal(kind="token", subject="token:test", role="viewer", scopes=frozenset({"users:admin"}))
        with patch.dict(os.environ, {"CBOM_PRINCIPAL_SCOPE_JSON": json.dumps({"token:test": {"portfolio": True, "grants": [{"source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2"}]}})}, clear=False):
            assigned = api._assigned_scope_for(principal)
        request = SimpleNamespace(url=SimpleNamespace(path="/api/v1/admin/users"), method="GET", query_params={})
        self.assertTrue(api._request_within_assigned_scope(request, assigned))
        self.assertIs(api._require_admin(principal, "users:admin"), principal)
        with self.assertRaises(api.HTTPException):
            api._require_admin(principal, "tokens:admin")

    def test_missing_or_invalid_policy_fails_closed(self) -> None:
        principal = api.Principal(kind="human", subject="oidc:test", role="viewer", scopes=frozenset(), oidc_groups=frozenset({"fedsse-admins"}))
        for policy in ("", "not-json", json.dumps({"groups": {}})):
            with (
                self.subTest(policy=policy),
                patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": policy}, clear=False),
                self.assertRaises(api.AssignedScopeError),
            ):
                api._assigned_scope_for(principal)

    def test_malformed_or_whitespace_claim_is_rejected_before_database_access(self) -> None:
        for raw_groups in ("not-json", json.dumps([" fedsse-admins"]), json.dumps([123])):
            with self.subTest(raw_groups=raw_groups):
                request = SimpleNamespace(headers={
                    "x-cbom-user-issuer": "https://idp.example", "x-cbom-user-sub": "sub",
                    "x-cbom-user-email": "person@example.test", "x-cbom-user-groups": raw_groups,
                })
                with self.assertRaises(access_control.AccessDenied):
                    access_control._resolve_human(request)

    def test_local_admin_is_rejected_in_production(self) -> None:
        request = SimpleNamespace(headers={})
        with (
            patch.dict(os.environ, {"CBOM_API_AUTH_MODE": "local-admin"}, clear=False),
            self.assertRaises(access_control.AccessDenied),
        ):
            access_control.authenticate_request(request, production=True)

    def test_middleware_enforces_summary_and_admin_groups(self) -> None:
        async def next_handler(_request):
            return api.JSONResponse({"ok": True})

        def request(path: str):
            return api.Request({
                "type": "http", "method": "GET", "path": path, "query_string": b"",
                "headers": [], "scheme": "http", "server": ("test", 80),
                "client": ("127.0.0.1", 1000),
            })

        external = api.Principal(kind="human", subject="oidc:external", role="viewer", scopes=frozenset(), oidc_groups=frozenset({"fedsse-external"}))
        scr2 = api.Principal(kind="human", subject="oidc:scr2", role="viewer", scopes=frozenset(), oidc_groups=frozenset({"fedsse-scr2-leads"}))
        admin = api.Principal(kind="human", subject="oidc:admin", role="viewer", scopes=frozenset(), oidc_groups=frozenset({"fedsse-admins"}))
        with patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(POLICY)}, clear=False):
            with patch.object(api, "_rate_limited", return_value=False):
                with patch.object(api, "authenticate_request", return_value=external):
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/portfolio/overview-summary"), next_handler)).status_code, 200)
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/portfolio/poam-planning"), next_handler)).status_code, 200)
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/portfolio/risk-assessment-poam"), next_handler)).status_code, 200)
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/fips/team-milestones"), next_handler)).status_code, 403)
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/service-catalog"), next_handler)).status_code, 403)
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/documents"), next_handler)).status_code, 403)
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/documents/42"), next_handler)).status_code, 404)
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/fips/poam.csv"), next_handler)).status_code, 403)
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/admin/users"), next_handler)).status_code, 403)
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/portfolio/product-scope-status"), next_handler)).status_code, 403)
                with patch.object(api, "authenticate_request", return_value=admin):
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/admin/users"), next_handler)).status_code, 200)
                with patch.object(api, "authenticate_request", return_value=scr2):
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/portfolio/poam-planning"), next_handler)).status_code, 200)
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/portfolio/risk-assessment-poam"), next_handler)).status_code, 200)
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/inventory/service-groups"), next_handler)).status_code, 403)
                    self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/admin/users"), next_handler)).status_code, 403)

    def test_shared_planning_projection_excludes_catalog_permissions_and_evidence(self) -> None:
        catalog_row = {
            "service_key": "sse-cboms/on-prem-clients", "source_collection": "sse-cboms",
            "service_group": "on-prem-clients", "display_name": "Chromebook Client",
            "owner": "Owner", "lead": "Lead", "il2": {"status": "planned", "date": date(2027, 1, 15)},
            "il5": {"status": "in_progress", "date": date(2027, 3, 31)},
            "service_impact_risk": "moderate", "comments": "Owner planning",
            "can_edit": True, "can_approve": True, "owner_profile": {"email": "private@example.test"},
            "attributes": {"internal": "do not publish"},
        }
        request = SimpleNamespace()
        with patch.object(api, "_catalog_rows", return_value=[catalog_row]) as rows, \
             patch.object(api, "_fetch_all", return_value=[{"service_key": "sse-cboms/on-prem-clients", "documents": 0}]), \
             patch.object(api, "_active_target_module_contract", return_value=None), \
             patch.object(api, "team_milestones", return_value={"groups": [], "all_tracker_rows": []}):
            response = api.portfolio_poam_planning(request)
        rows.assert_called_once_with(request, "sse-cboms", portfolio_planning=True)
        payload = json.loads(response.body)
        self.assertEqual(payload["scope"], "portfolio-planning")
        self.assertEqual(payload["catalog"][0]["display_name"], "Chromebook Client")
        self.assertEqual(payload["catalog"][0]["il2"]["date"], "2027-01-15")
        self.assertEqual(payload["catalog"][0]["il5"]["date"], "2027-03-31")
        self.assertNotIn("can_edit", payload["catalog"][0])
        self.assertNotIn("owner_profile", payload["catalog"][0])
        self.assertNotIn("attributes", payload["catalog"][0])
        self.assertEqual(payload["document_counts"], [{"service_key": "sse-cboms/on-prem-clients", "documents": 0}])

    def test_risk_assessment_poam_is_aggregate_planning_drafts(self) -> None:
        catalog = [
            {
                "source_collection": "sse-cboms", "service_group": "avengers",
                "display_name": "Avengers", "owner": "Owner", "lead": "Lead",
                "service_impact_risk": "Critical",
                "il2": {"status": "planned", "date": date(2026, 10, 31)},
                "il5": {"status": "not_supplied", "date": None},
                "can_edit": True, "owner_profile": {"email": "private@example.test"},
            },
            {
                "source_collection": "sse-cboms", "service_group": "data-platform",
                "display_name": "Data Platform", "owner": "Owner", "lead": "Lead",
                "service_impact_risk": "Moderate",
                "il2": {"status": "in_progress", "date": "2026-12-31"},
                "il5": {"status": "not_supplied", "date": None},
            },
            {
                "source_collection": "sse-cboms", "service_group": "ios-no-cbom",
                "display_name": "iOS", "owner": "Owner", "lead": "Lead",
                "service_impact_risk": "High",
                "il2": {"status": "complete", "date": "2027-03-31"},
                "il5": {"status": "not_supplied", "date": None},
            },
            {
                "source_collection": "sse-cboms", "service_group": "blocked-october-plan",
                "display_name": "Blocked October Plan", "owner": "Owner", "lead": "Lead",
                "service_impact_risk": "Medium",
                "il2": {"status": "blocked", "date": "2026-10-15"},
                "il5": {"status": "not_supplied", "date": None},
            },
            {
                "source_collection": "sse-cboms", "service_group": "dns-platform",
                "display_name": "DNS Platform", "owner": "Owner", "lead": "Lead",
                "service_impact_risk": None,
                "il2": {"status": "not_supplied", "date": None},
                "il5": {"status": "not_supplied", "date": None},
            },
            {
                # This group appears in the stale tracker October wave below,
                # but its current authoritative Catalog date is September.
                "source_collection": "sse-cboms", "service_group": "stale-tracker-group",
                "display_name": "Stale Tracker Group", "owner": "Owner", "lead": "Lead",
                "il2": {"status": "dated", "date": "2026-09-30"},
                "il5": {"status": "not_supplied", "date": None},
            },
            {
                # A stale target date must not override an explicit N/A status.
                "source_collection": "sse-cboms", "service_group": "not-applicable-stale-date",
                "display_name": "N/A stale date", "owner": "Owner", "lead": "Lead",
                "il2": {"status": "not_applicable", "date": "2026-10-31"},
                "il5": {"status": "not_supplied", "date": None},
            },
        ]
        request = SimpleNamespace()
        with (
            patch.object(api, "_catalog_rows", return_value=catalog) as rows,
            patch.object(api, "_fetch_all", return_value=[
                {"service_key": "sse-cboms/avengers", "documents": 4},
                {"service_key": "sse-cboms/blocked-october-plan", "documents": 2},
                {"service_key": "sse-cboms/data-platform", "documents": 3},
                {"service_key": "sse-cboms/ios-no-cbom", "documents": 1},
                {"service_key": "sse-cboms/dns-platform", "documents": 5},
                {"service_key": "sse-cboms/stale-tracker-group", "documents": 9},
                {"service_key": "sse-cboms/not-applicable-stale-date", "documents": 9},
            ]),
            patch.object(
                api, "portfolio_delivery_waves",
                side_effect=AssertionError("stale tracker waves must not select Catalog links"),
            ),
        ):
            response = api.portfolio_risk_assessment_poam(request)
            catalog[0]["il2"]["date"] = date(2026, 12, 15)
            catalog[0]["service_impact_risk"] = "Moderate"
            refreshed_response = api.portfolio_risk_assessment_poam(request)
        self.assertEqual(rows.call_count, 2)
        payload = json.loads(response.body)
        refreshed = json.loads(refreshed_response.body)
        self.assertEqual(payload["scope"], "portfolio-summary")
        self.assertEqual(payload["assessment_state"], "not_assessable")
        self.assertEqual(payload["items"][0]["milestones"][0]["target_date"], None)
        self.assertEqual(payload["items"][0]["milestones"][0]["label"], "October 2026 planning window")
        self.assertEqual([item["id"] for item in payload["items"]], [
            "OWNER-DRAFT-OCT-2026", "OWNER-DRAFT-DEC-2026",
            "OWNER-DRAFT-MAR-2027-VENDOR", "OWNER-DRAFT-DNSCRYPT",
        ])
        for item in payload["items"][:3]:
            self.assertEqual(item["kind"], "owner_directed_draft_deviation")
            self.assertEqual(item["control_id"], "SC-13")
            self.assertEqual(item["control_mapping_assertion"], "owner_proposed")
            self.assertEqual(item["risk"], {"value": "Moderate", "assertion": "user_asserted"})
            self.assertFalse(item["poam_eligibility"])
            self.assertEqual(item["status"], "owner_directed_draft_deviation")
            self.assertNotIn("candidates", item)
            self.assertNotIn("export", item)
        self.assertEqual(payload["items"][0]["impact_summary"], {
            "critical": {"service_group_count": 1, "catalog_record_count": 4},
            "moderate": {"service_group_count": 1, "catalog_record_count": 2},
            "other": {"service_group_count": 0, "catalog_record_count": 0},
            "total": {"service_group_count": 2, "catalog_record_count": 6},
        })
        self.assertEqual(payload["items"][1]["impact_summary"]["moderate"], {
            "service_group_count": 1, "catalog_record_count": 3,
        })
        self.assertEqual(refreshed["items"][0]["impact_summary"]["total"]["service_group_count"], 1)
        self.assertEqual(refreshed["items"][1]["impact_summary"]["moderate"], {
            "service_group_count": 2, "catalog_record_count": 7,
        })
        for item in payload["items"]:
            self.assertNotIn("linked_service_groups", item)
        serialized_items = json.dumps(payload["items"])
        self.assertNotIn("stale-tracker-group", serialized_items)
        self.assertNotIn("not-applicable-stale-date", serialized_items)
        self.assertNotIn("private@example.test", serialized_items)
        march = payload["items"][2]
        self.assertEqual(march["impact_summary"]["critical"], {
            "service_group_count": 1, "catalog_record_count": 1,
        })
        self.assertIn("no verified deployment", march["deviations"][0]["detail"])
        dnscrypt = payload["items"][3]
        self.assertEqual(dnscrypt["impact_summary"]["other"], {
            "service_group_count": 1, "catalog_record_count": 5,
        })
        self.assertIsNone(dnscrypt["milestones"][0]["target_date"])
        self.assertEqual(dnscrypt["control_id"], "Pending mapping")
        self.assertEqual(dnscrypt["control_mapping_assertion"], "pending_assessment")
        self.assertEqual(dnscrypt["risk"], {"value": "Not rated", "assertion": "pending_assessment"})
        self.assertFalse(dnscrypt["poam_eligibility"])
        self.assertEqual(len(dnscrypt["deviations"]), 2)
        self.assertIn("raw-ECDH to HKDF", dnscrypt["deviations"][0]["detail"])
        self.assertEqual(
            dnscrypt["deviations"][0]["reference_url"],
            "https://cisco-sbg.atlassian.net/wiki/spaces/trac3/pages/1516647476/DNSCrypt+ES3+to+ES4+Key+Derivation+and+the+FIPS+140-3+Gap",
        )
        self.assertEqual(dnscrypt["deviations"][0]["artifact"]["reference_status"], "user_provided_discussion_reference_only")
        self.assertIn("Ed25519/Ed448", dnscrypt["deviations"][1]["title"])
        self.assertFalse(dnscrypt["deviations"][1]["poam_eligibility"])

    def test_enabled_roster_blocks_revoked_human_before_handler_and_allows_restore(self) -> None:
        handled: list[str] = []

        async def next_handler(_request):
            handled.append("called")
            return api.JSONResponse({"ok": True})

        def request():
            return api.Request({
                "type": "http", "method": "GET", "path": "/api/v1/auth/me",
                "query_string": b"", "headers": [], "scheme": "http",
                "server": ("test", 80), "client": ("127.0.0.1", 1000),
            })

        principal = api.Principal(
            kind="human", subject="oidc:restored", role="viewer", scopes=frozenset(),
            oidc_groups=frozenset({"fedsse-admins"}), user_id=7,
        )
        with (
            patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(POLICY)}, clear=False),
            patch.object(api, "authenticate_request", return_value=principal),
            patch.object(api, "_access_roster_enabled", return_value=True),
            patch.object(api, "_access_is_revoked", side_effect=(True, False)),
            patch.object(api, "_record_access_roster_snapshot"),
            patch.object(api, "_rate_limited", return_value=False),
        ):
            self.assertEqual(asyncio.run(api.access_controls(request(), next_handler)).status_code, 403)
            self.assertEqual(handled, [])
            self.assertEqual(asyncio.run(api.access_controls(request(), next_handler)).status_code, 200)
            self.assertEqual(handled, ["called"])

    def test_multiple_modes_must_be_selected_before_catalog_data(self) -> None:
        async def next_handler(_request):
            return api.JSONResponse({"ok": True})

        principal = api.Principal(
            kind="human", subject="oidc:multi", role="viewer", scopes=frozenset(),
            oidc_groups=frozenset({"fedsse-team-a-leads", "fedsse-team-b-engineers"}),
        )

        def request(path: str, mode: str | None = None):
            headers = [] if mode is None else [(b"x-cbom-access-mode", mode.encode())]
            return api.Request({
                "type": "http", "method": "GET", "path": path, "query_string": b"",
                "headers": headers, "scheme": "http", "server": ("test", 80),
                "client": ("127.0.0.1", 1000),
            })

        with patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(POLICY)}, clear=False):
            with patch.object(api, "authenticate_request", return_value=principal), patch.object(api, "_rate_limited", return_value=False):
                profile = request("/api/v1/auth/me")
                self.assertEqual(asyncio.run(api.access_controls(profile, next_handler)).status_code, 200)
                self.assertIsNone(profile.state.assigned_scope["active_mode"])
                self.assertEqual(profile.state.assigned_scope["role"], "none")
                self.assertEqual(asyncio.run(api.access_controls(request("/api/v1/portfolio/assigned-service-groups"), next_handler)).status_code, 403)
                chosen = request("/api/v1/portfolio/assigned-service-groups", "product_engineer")
                self.assertEqual(asyncio.run(api.access_controls(chosen, next_handler)).status_code, 200)
                self.assertEqual(chosen.state.assigned_scope["role"], "engineer")
                self.assertEqual({item["access"] for item in chosen.state.assigned_scope["grants"]}, {"engineer"})

    def test_multimode_profile_keeps_product_grants_and_deduplicates_services(self) -> None:
        """A user with the Kurs group combination can select each exact mode.

        Two product contexts remain separate grants, while the profile's
        service register names each collection/service pair once.
        """
        policy = {
            "version": "kurs-multimode-v1",
            "groups": {
                "fedsse-admins": {"access": "admin"},
                "fedsse-scr2-leads": {"access": "summary"},
            },
        }
        product_scopes = [
            ("secure-access-government", "FedRAMP High/IL2"),
            ("secure-access-defense", "IL5"),
        ]
        for service in ("dlp", "saasapi"):
            grants = [
                {
                    "source_collection": "sse-cboms",
                    "service_group": service,
                    "product_scope_id": product_scope_id,
                    "boundary_name": boundary_name,
                }
                for product_scope_id, boundary_name in product_scopes
            ]
            policy["groups"][f"fedsse-{service}-leads"] = {
                "access": "lead", "service_key": service, "grants": grants,
            }
            policy["groups"][f"fedsse-{service}-engineers"] = {
                "access": "engineer", "service_key": service, "grants": grants,
            }

        principal = api.Principal(
            kind="human", subject="oidc:kurs", role="viewer", scopes=frozenset(),
            oidc_groups=frozenset({
                "fedsse-admins", "fedsse-scr2-leads",
                "fedsse-dlp-leads", "fedsse-dlp-engineers",
                "fedsse-saasapi-leads", "fedsse-saasapi-engineers",
            }),
        )

        async def next_handler(_request):
            return api.JSONResponse({"ok": True})

        def request(mode: str | None = None):
            headers = [] if mode is None else [(b"x-cbom-access-mode", mode.encode())]
            return api.Request({
                "type": "http", "method": "GET", "path": "/api/v1/auth/me",
                "query_string": b"", "headers": headers, "scheme": "http",
                "server": ("test", 80), "client": ("127.0.0.1", 1000),
            })

        with (
            patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(policy)}, clear=False),
            patch.object(api, "authenticate_request", return_value=principal),
            patch.object(api, "_rate_limited", return_value=False),
            patch.object(api, "_fetch_all", return_value=[
                {"source_collection": "sse-cboms", "service_group": "dlp"},
                {"source_collection": "sse-cboms", "service_group": "saasapi"},
            ]),
        ):
            unselected = request()
            self.assertEqual(asyncio.run(api.access_controls(unselected, next_handler)).status_code, 200)
            profile = api.current_user(unselected)
            self.assertEqual(profile["access"]["available_modes"], [
                "admin", "product_lead", "product_engineer", "summary",
            ])
            self.assertEqual(profile["access"]["default_mode"], "admin")
            self.assertIsNone(profile["access"]["active_mode"])
            self.assertEqual(profile["access"]["effective_role"], "none")
            self.assertEqual(len(profile["access"]["grants"]), 4)
            self.assertEqual(profile["assigned_scope"]["service_groups"], [
                "sse-cboms/dlp", "sse-cboms/saasapi",
            ])

            expectations = {
                "admin": ("admin", "portfolio", {"lead"}),
                "product_lead": ("lead", "assigned", {"lead"}),
                "product_engineer": ("engineer", "assigned", {"engineer"}),
                "summary": ("summary", "summary", set()),
            }
            for mode, (role, scope_mode, grant_access) in expectations.items():
                with self.subTest(mode=mode):
                    selected = request(mode)
                    self.assertEqual(asyncio.run(api.access_controls(selected, next_handler)).status_code, 200)
                    selected_profile = api.current_user(selected)
                    self.assertEqual(selected_profile["access"]["effective_role"], role)
                    self.assertEqual(selected_profile["access"]["active_mode"], mode)
                    self.assertEqual(selected_profile["assigned_scope"]["mode"], scope_mode)
                    self.assertEqual(
                        {grant["access"] for grant in selected_profile["access"]["grants"]},
                        grant_access,
                    )
                    if mode in {"product_lead", "product_engineer"}:
                        self.assertEqual(selected_profile["assigned_scope"]["service_groups"], [
                            "sse-cboms/dlp", "sse-cboms/saasapi",
                        ])

    def test_exact_product_lead_post_routes_resolve_scope_without_broadening_posts(self) -> None:
        async def next_handler(_request):
            return api.JSONResponse({"ok": True})

        principal = api.Principal(
            kind="human", subject="oidc:lead", role="viewer", scopes=frozenset(),
            oidc_groups=frozenset({"fedsse-team-a-leads"}),
        )

        def request(path: str, query: bytes):
            return api.Request({
                "type": "http", "method": "POST", "path": path, "query_string": query,
                "headers": [], "scheme": "http", "server": ("test", 80),
                "client": ("127.0.0.1", 1000),
            })

        exact = b"source_collection=collection-a&service_group=team-a&product_scope_id=secure-access-government"
        outside = b"source_collection=collection-a&service_group=team-b&product_scope_id=secure-access-government"
        with (
            patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(POLICY)}, clear=False),
            patch.object(api, "authenticate_request", return_value=principal),
            patch.object(api, "_rate_limited", return_value=False),
            patch.object(api, "_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED", True),
            patch.object(api, "_lead_review_proposals_enabled", return_value=True),
            patch.object(api, "_operational_evidence_notes_enabled", return_value=True),
        ):
            for path in ("/api/v1/review-proposals", "/api/v1/operational-evidence-notes"):
                with self.subTest(path=path):
                    allowed = request(path, exact)
                    self.assertEqual(asyncio.run(api.access_controls(allowed, next_handler)).status_code, 200)
                    self.assertEqual(allowed.state.assigned_scope["role"], "lead")
                    self.assertEqual(
                        asyncio.run(api.access_controls(request(path, outside), next_handler)).status_code,
                        403,
                    )
            unrelated = request("/api/v1/unknown-write", b"")
            self.assertEqual(asyncio.run(api.access_controls(unrelated, next_handler)).status_code, 200)
            self.assertFalse(hasattr(unrelated.state, "assigned_scope"))

        with (
            patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(POLICY)}, clear=False),
            patch.object(api, "authenticate_request", return_value=principal),
            patch.object(api, "_rate_limited", return_value=False),
            patch.object(api, "_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED", True),
            patch.object(api, "_lead_review_proposals_enabled", return_value=False),
            patch.object(api, "_operational_evidence_notes_enabled", return_value=False),
        ):
            self.assertEqual(
                asyncio.run(api.access_controls(request("/api/v1/review-proposals", exact), next_handler)).status_code,
                403,
            )
            self.assertEqual(
                asyncio.run(api.access_controls(request("/api/v1/operational-evidence-notes", exact), next_handler)).status_code,
                403,
            )

        with (
            patch.dict(os.environ, {"CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(POLICY)}, clear=False),
            patch.object(api, "authenticate_request", return_value=principal),
            patch.object(api, "_rate_limited", return_value=False),
            patch.object(api, "_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED", False),
        ):
            self.assertEqual(
                asyncio.run(api.access_controls(request("/api/v1/review-proposals", exact), next_handler)).status_code,
                403,
            )
            self.assertEqual(
                asyncio.run(api.access_controls(request("/api/v1/operational-evidence-notes", exact), next_handler)).status_code,
                403,
            )

    def test_auth_me_exposes_only_effective_access_contract(self) -> None:
        admin = api.Principal(kind="human", subject="oidc:admin", role="admin", scopes=frozenset())
        summary = api.Principal(kind="human", subject="oidc:external", role="summary", scopes=frozenset())
        no_group = api.Principal(kind="human", subject="oidc:none", role="none", scopes=frozenset())
        admin_request = SimpleNamespace(state=SimpleNamespace(principal=admin, assigned_scope={
            "policy_version": "test-v1", "fingerprint": "fingerprint", "role": "admin",
            "summary_access": True, "matched_groups": ["fedsse-admins"], "grants": [],
        }))
        admin_response = api.current_user(admin_request)
        self.assertTrue(admin_response["can_edit"])
        self.assertEqual(admin_response["access"]["effective_role"], "admin")
        self.assertEqual(admin_response["access"]["matched_groups"], ["fedsse-admins"])
        for principal, role in ((summary, "summary"), (no_group, "none")):
            request = SimpleNamespace(state=SimpleNamespace(principal=principal, assigned_scope={
                "policy_version": "test-v1", "fingerprint": "f", "role": role,
                "summary_access": role == "summary", "matched_groups": [], "grants": [],
            }))
            response = api.current_user(request)
            self.assertFalse(response["can_edit"])
            self.assertEqual(response["access"]["effective_role"], role)

    def test_profile_exposes_placeholder_workspace_only_for_selected_product_mode(self) -> None:
        principal = api.Principal(kind="human", subject="oidc:lead", role="lead", scopes=frozenset())
        grant = {
            "source_collection": "collection-a", "service_group": "team-a",
            "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2",
            "access": "lead",
        }
        selected = SimpleNamespace(state=SimpleNamespace(principal=principal, assigned_scope={
            "mode": "assigned", "role": "lead", "active_mode": "product_lead",
            "summary_access": True, "grants": [grant], "matched_groups": [],
        }))
        unselected = SimpleNamespace(state=SimpleNamespace(principal=principal, assigned_scope={
            "mode": "selection_required", "role": "none", "active_mode": None,
            "summary_access": False, "grants": [grant], "matched_groups": [],
        }))
        self.assertTrue(api.current_user(selected)["assigned_scope"]["assigned_workspace_placeholders"])
        self.assertFalse(api.current_user(unselected)["assigned_scope"]["assigned_workspace_placeholders"])

    def test_profile_exposes_review_proposals_only_for_enabled_selected_lead_scope(self) -> None:
        principal = api.Principal(kind="human", subject="oidc:lead", role="lead", scopes=frozenset())
        grant = {
            "source_collection": "collection-a", "service_group": "team-a",
            "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2",
            "access": "lead", "assessment_authorization_reference": "immutable-review-contract-v1",
        }
        selected = SimpleNamespace(state=SimpleNamespace(principal=principal, assigned_scope={
            "mode": "assigned", "role": "lead", "active_mode": "product_lead",
            "summary_access": True, "grants": [grant], "matched_groups": [],
        }))
        engineer = SimpleNamespace(state=SimpleNamespace(principal=principal, assigned_scope={
            "mode": "assigned", "role": "engineer", "active_mode": "product_engineer",
            "summary_access": True, "grants": [{**grant, "access": "engineer"}], "matched_groups": [],
        }))
        with (
            patch.object(api, "_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED", True),
            patch.object(api, "_lead_review_proposals_enabled", return_value=True),
        ):
            self.assertTrue(api.current_user(selected)["capabilities"]["review_proposals"])
            self.assertFalse(api.current_user(engineer)["capabilities"]["review_proposals"])
        with patch.object(api, "_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED", False):
            self.assertFalse(api.current_user(selected)["capabilities"]["review_proposals"])

    def test_product_scope_status_requires_complete_current_coverage(self) -> None:
        current = {"current_source_files": 534, "attributed_source_files": 534}
        complete = [
            {"product_scope_id": "secure-access-defense", "attributed_source_files": 534},
            {"product_scope_id": "secure-access-government", "attributed_source_files": 534},
        ]
        with (
            patch.object(api, "_fetch_one", return_value=current),
            patch.object(api, "_fetch_all", return_value=complete),
        ):
            self.assertEqual(api.portfolio_product_scope_status(SimpleNamespace())["state"], "active")
        with (
            patch.object(api, "_fetch_one", return_value=current),
            patch.object(api, "_fetch_all", return_value=[complete[0]]),
        ):
            self.assertEqual(api.portfolio_product_scope_status(SimpleNamespace())["state"], "active")
        with (
            patch.object(api, "_fetch_one", return_value={"current_source_files": 534, "attributed_source_files": 533}),
            patch.object(api, "_fetch_all", return_value=complete),
        ):
            self.assertEqual(api.portfolio_product_scope_status(SimpleNamespace())["state"], "pending")

    def test_manual_user_role_endpoint_is_retired(self) -> None:
        with self.assertRaises(api.HTTPException) as error:
            api.update_admin_user(1, api.UserAccessUpdate(role="admin"), SimpleNamespace())
        self.assertEqual(error.exception.status_code, 410)

    def test_middleware_token_needs_both_portfolio_and_endpoint_scope(self) -> None:
        async def next_handler(_request):
            return api.JSONResponse({"ok": True})

        request = api.Request({
            "type": "http", "method": "GET", "path": "/api/v1/admin/users",
            "query_string": b"", "headers": [], "scheme": "http",
            "server": ("test", 80), "client": ("127.0.0.1", 1000),
        })
        mapping = {"token:test": {"portfolio": True, "grants": [{"source_collection": "collection-a", "service_group": "team-a", "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2"}]}}
        allowed = api.Principal(kind="token", subject="token:test", role="viewer", scopes=frozenset({"users:admin"}))
        denied = api.Principal(kind="token", subject="token:test", role="viewer", scopes=frozenset({"catalog:read"}))
        with patch.dict(os.environ, {"CBOM_PRINCIPAL_SCOPE_JSON": json.dumps(mapping)}, clear=False):
            with patch.object(api, "_rate_limited", return_value=False):
                with patch.object(api, "authenticate_request", return_value=allowed):
                    self.assertEqual(asyncio.run(api.access_controls(request, next_handler)).status_code, 200)
                with patch.object(api, "authenticate_request", return_value=denied):
                    self.assertEqual(asyncio.run(api.access_controls(request, next_handler)).status_code, 403)
