from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    from cbom_catalog import api
    from cbom_catalog.service_catalog import ServiceCatalogError, normalized_change
except ModuleNotFoundError as exc:
    if exc.name not in {"fastapi", "psycopg", "psycopg_pool"}:
        raise
    api = None


@unittest.skipIf(api is None, "install project dependencies to run API tests")
class ServiceCatalogTests(unittest.TestCase):
    def _request(self, principal: object, grants: list[dict[str, str]] | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            state=SimpleNamespace(
                principal=principal, request_id="request-1",
                assigned_scope={"mode": "assigned", "role": "lead", "grants": grants or []},
            ),
        )

    def _lead(self) -> object:
        return api.Principal(kind="human", subject="oidc:lead", role="lead", scopes=frozenset(), user_id=42)

    @staticmethod
    def _catalog_row(source_collection: str, service_group: str) -> dict[str, object]:
        return {
            "source_collection": source_collection, "service_group": service_group,
            "catalog_display_name": "Brain", "revision": None, "display_name": None,
            "owner": None, "lead": None, "il2_status": None, "il2_target_date": None,
            "il5_status": None, "il5_target_date": None, "service_impact_risk": None,
            "comments": None, "attributes": {}, "overridden_fields": [], "updated_at": None,
            "owner_user_id": None, "owner_user_email": None, "owner_user_display_name": None,
            "lead_user_id": None, "lead_user_email": None, "lead_user_display_name": None,
            "has_evidence": True,
        }

    @staticmethod
    def _tracker_profiles() -> dict[str, object]:
        return {"groups": [{
            "service_group": "brain", "owners": ["Imported owner"], "leads": ["Imported lead"],
            "tracker_rows": [{
                "team": "Brain",
                "il2": {"status": "planned", "date": "2027-01-15"},
                "il5": {"status": "in_progress", "date": "2027-03-01"},
            }],
        }]}

    def test_change_rejects_access_attributes_and_invalid_dates(self) -> None:
        with self.assertRaises(ServiceCatalogError):
            normalized_change({"attributes": {"role": "admin"}})
        with self.assertRaises(ServiceCatalogError):
            normalized_change({"il2_target_date": "2026-02-31"})
        with self.assertRaises(ServiceCatalogError):
            normalized_change({"display_name": None})
        self.assertEqual(
            normalized_change({"il2_status": "not_applicable"}),
            {"il2_status": "not_applicable", "il2_target_date": None},
        )
        self.assertEqual(
            normalized_change({"owner_profile_email": "Owner@Example.test", "il2_status": "planned"}),
            {"owner_profile_email": "owner@example.test", "il2_status": "planned"},
        )

    def test_crypto_plan_requires_one_target_and_bounded_supporting_evidence(self) -> None:
        preset = {
            "current_module": "OpenSSL", "current_version": "3.0.0",
            "target_preset_id": "cmvp-4985", "source_record_sha256": "a" * 64,
        }
        normalized = normalized_change({"crypto_module_plans": [preset]})["crypto_module_plans"]
        self.assertEqual(normalized[0]["target_preset_id"], "cmvp-4985")
        self.assertEqual(normalized[0]["source_record_sha256"], "a" * 64)
        custom = {
            "current_module": "Python cryptography", "custom_target_module": "Vendor OpenSSL provider",
            "custom_target_version": "1.2.3", "supporting_url": "https://vendor.example/module",
            "evidence_basis": "vendor_recommendation",
        }
        self.assertEqual(
            normalized_change({"crypto_module_plans": [custom]})["crypto_module_plans"][0]["evidence_basis"],
            "vendor_recommendation",
        )
        for invalid in (
            {**preset, "cmvp_certificate": "#4985"},
            {**preset, "custom_target_module": "Other module"},
            {**custom, "supporting_url": "http://vendor.example/module"},
            {**custom, "supporting_url": "https://user:secret@vendor.example/module"},
            {**custom, "custom_target_version": ""},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ServiceCatalogError):
                normalized_change({"crypto_module_plans": [invalid]})

    def test_curated_catalog_plan_snapshots_public_reference_not_deployment_proof(self) -> None:
        payload = normalized_change({"crypto_module_plans": [{
            "current_module": "OpenSSL", "target_preset_id": "cmvp-4985",
        }]})
        evidence = {
            "evidence_key": "cmvp-4985", "module_name": "OpenSSL FIPS Provider",
            "module_version": "3.1.2", "certificate_number": "#4985",
            "public_status": "active", "source_kind": "cmvp_certificate",
            "source_url": "https://csrc.nist.gov/projects/cryptographic-module-validation-program/certificate/4985",
            "payload_sha256": "b" * 64, "authority": "NIST CMVP",
        }
        with patch.object(api, "_active_public_module_evidence", return_value=[evidence]):
            enriched = api._resolve_catalog_crypto_plans(
                MagicMock(), payload, source_collection="sse-cboms", service_group="dlp",
            )["crypto_module_plans"][0]
        self.assertEqual(enriched["target_module"], "OpenSSL FIPS Provider")
        self.assertEqual(enriched["cmvp_certificate"], "#4985")
        self.assertEqual(enriched["evidence_payload_sha256"], "b" * 64)
        self.assertEqual(enriched["evidence_grade"], "user_asserted")
        self.assertTrue(enriched["review_required"])

    def test_catalog_plan_projection_uses_current_evidence_without_mutating_plan(self) -> None:
        """Catalog reads re-evaluate approved plans against the active import."""
        principal = api.Principal(kind="human", subject="oidc:admin", role="admin", scopes=frozenset(), user_id=1)
        request = SimpleNamespace(
            state=SimpleNamespace(
                principal=principal, request_id="request-1",
                assigned_scope={"mode": "portfolio", "role": "admin", "grants": []},
            ),
        )
        row = self._catalog_row("sse-cboms", "brain")
        current_plan = {
            "target_preset_id": "cmvp-4985",
            "target_module": "OpenSSL FIPS Provider",
            "target_version": "3.1.2",
            "cmvp_certificate": "#4985",
            "evidence_url": "https://example.test/cmvp/4985",
            "evidence_payload_sha256": "a" * 64,
        }
        superseded_plan = {**current_plan, "evidence_payload_sha256": "b" * 64}
        row["crypto_module_plans"] = [current_plan, superseded_plan]
        evidence = [{
            # SQL row keys deliberately differ from the evaluator contract.
            "evidence_key": "cmvp-4985",
            "source_url": "https://example.test/cmvp/4985",
            "payload_sha256": "a" * 64,
            "source_kind": "cmvp_certificate",
            "module_name": "OpenSSL FIPS Provider",
            "module_version": "3.1.2",
            "certificate_number": "#4985",
            "public_status": "active",
        }]
        with (
            patch.object(api, "_service_catalog_enabled", return_value=True),
            patch.object(api, "_fetch_all", return_value=[row]),
            patch.object(api, "_active_target_module_contract", return_value=None),
            patch.object(api, "team_milestones", return_value=self._tracker_profiles()),
            patch.object(api, "_active_service_impact_map", return_value={}),
            patch.object(api, "_active_public_module_evidence", return_value=evidence),
        ):
            plans = api._catalog_rows(request)[0]["crypto_module_plans"]

        self.assertEqual(plans[0]["planning_disposition"], "active_certificate")
        self.assertEqual(plans[0]["evidence_state"], "current")
        self.assertIn("#4985", plans[0]["disposition_basis"])
        self.assertEqual(plans[1]["planning_disposition"], "planned_unverified")
        self.assertEqual(plans[1]["evidence_state"], "evidence_superseded")
        self.assertNotIn("planning_disposition", current_plan)
        self.assertNotIn("evidence_state", superseded_plan)

    def test_imported_module_identity_is_server_verified_at_submission_and_approval(self) -> None:
        source_hash = "a" * 64
        database = MagicMock()
        database.execute.return_value.fetchone.return_value = {
            "record_sha256": source_hash,
            "current_module": "OpenSSL",
            "current_version": "3.0.0",
        }
        evidence = {
            "evidence_key": "cmvp-4985", "module_name": "OpenSSL FIPS Provider",
            "module_version": "3.1.2", "certificate_number": "#4985",
            "public_status": "active", "source_kind": "cmvp_certificate",
            "source_url": "https://csrc.nist.gov/projects/cryptographic-module-validation-program/certificate/4985",
            "payload_sha256": "b" * 64, "authority": "NIST CMVP",
        }
        with patch.object(api, "_active_public_module_evidence", return_value=[evidence]):
            for field, incorrect in (("current_module", "Go"), ("current_version", "9.9")):
                plan = {
                    "source_record_sha256": source_hash,
                    "current_module": "OpenSSL", "current_version": "3.0.0",
                    "target_preset_id": "cmvp-4985",
                }
                plan[field] = incorrect
                with self.subTest(field=field), self.assertRaises(api.HTTPException) as error:
                    api._resolve_catalog_crypto_plans(
                        database, normalized_change({"crypto_module_plans": [plan]}),
                        source_collection="sse-cboms", service_group="dlp",
                    )
                self.assertEqual(error.exception.status_code, 422)
            correct = normalized_change({"crypto_module_plans": [{
                "source_record_sha256": source_hash,
                "current_module": "OpenSSL", "current_version": "3.0.0",
                "target_preset_id": "cmvp-4985",
            }]})
            enriched = api._resolve_catalog_crypto_plans(
                database, correct, source_collection="sse-cboms", service_group="dlp",
            )
            self.assertEqual(enriched["crypto_module_plans"][0]["current_module"], "OpenSSL")
            self.assertEqual(enriched["crypto_module_plans"][0]["current_version"], "3.0.0")
            api._verify_catalog_crypto_plan_references(
                database, enriched, source_collection="sse-cboms", service_group="dlp",
            )
            database.execute.return_value.fetchone.return_value["current_version"] = "3.0.1"
            with self.assertRaises(api.HTTPException) as stale:
                api._verify_catalog_crypto_plan_references(
                    database, enriched, source_collection="sse-cboms", service_group="dlp",
                )
            self.assertEqual(stale.exception.status_code, 409)

    def test_custom_catalog_plan_cannot_claim_a_verified_certificate(self) -> None:
        payload = normalized_change({"crypto_module_plans": [{
            "current_module": "Python cryptography", "custom_target_module": "Custom provider",
            "custom_target_version": "2.0", "supporting_url": "https://vendor.example/fips",
            "evidence_basis": "cmvp_certificate",
        }]})
        with patch.object(api, "_active_public_module_evidence", return_value=[]):
            enriched = api._resolve_catalog_crypto_plans(
                MagicMock(), payload, source_collection="sse-cboms", service_group="dlp",
            )["crypto_module_plans"][0]
        self.assertIsNone(enriched["cmvp_certificate"])
        self.assertEqual(enriched["public_status"], "user_asserted_unverified")
        self.assertEqual(enriched["evidence_grade"], "user_asserted")

    def test_proposed_preset_must_remain_the_same_active_public_record(self) -> None:
        proposal = {"crypto_module_plans": [{
            "target_preset_id": "cmvp-4985", "evidence_payload_sha256": "a" * 64,
        }]}
        with patch.object(api, "_active_public_module_evidence", return_value=[{
            "evidence_key": "cmvp-4985", "payload_sha256": "b" * 64,
        }]), self.assertRaises(api.HTTPException) as error:
            api._verify_catalog_crypto_plan_references(
                MagicMock(), proposal, source_collection="sse-cboms", service_group="dlp",
            )
        self.assertEqual(error.exception.status_code, 409)

    def test_module_options_distinguish_public_certificate_from_vendor_review(self) -> None:
        rows = [
            {
                "evidence_key": "cmvp-4985", "module_name": "OpenSSL FIPS Provider",
                "module_version": "3.1.2", "certificate_number": "#4985",
                "public_status": "active", "source_kind": "cmvp_certificate",
                "source_url": "https://csrc.nist.gov/projects/cryptographic-module-validation-program/certificate/4985",
                "source_title": "NIST certificate", "authority": "NIST CMVP",
                "payload_sha256": "a" * 64, "retrieved_on": date(2026, 9, 21), "limitations": [],
            },
            {
                "evidence_key": "openssl-3.5.4-submission", "module_name": "OpenSSL FIPS Object Module",
                "module_version": "3.5.4", "certificate_number": None,
                "public_status": "cmvp_review", "source_kind": "vendor_blog",
                "source_url": "https://openssl-library.org/post/2025-10-09-ossl3.5.4-fips-submission/",
                "source_title": "OpenSSL submission", "authority": "OpenSSL Corporation",
                "payload_sha256": "b" * 64, "retrieved_on": date(2026, 9, 21), "limitations": [],
            },
        ]
        with patch.object(api, "_active_public_module_evidence", return_value=rows):
            options = api._crypto_module_options()
        self.assertIn("CMVP #4985", options[0]["label"])
        self.assertEqual(options[0]["certificate_number"], "#4985")
        self.assertIn("Vendor-reported CMVP review; no certificate", options[1]["label"])
        self.assertIsNone(options[1]["certificate_number"])

    def test_lead_cannot_propose_for_an_unassigned_group(self) -> None:
        request = self._request(self._lead(), [{"access": "lead", "source_collection": "sse-cboms", "service_group": "brain"}])
        body = api.ServiceCatalogProposalCreate(
            source_collection="sse-cboms", service_group="dlp", expected_revision=0,
            owner="Owner", rationale="Please review this scoped catalog change.",
        )
        with patch.object(api, "_service_catalog_enabled", return_value=True), self.assertRaises(api.HTTPException) as error:
            api.create_service_catalog_proposal(body, request)
        self.assertEqual(error.exception.status_code, 403)

    def test_il5_change_requires_the_exact_defense_grant(self) -> None:
        request = self._request(self._lead(), [{
            "access": "lead", "source_collection": "sse-cboms", "service_group": "brain",
            "product_scope_id": "secure-access-government",
        }])
        body = api.ServiceCatalogProposalCreate(
            source_collection="sse-cboms", service_group="brain", expected_revision=0,
            il5_status="planned", rationale="Please review the IL5 planning update.",
        )
        with patch.object(api, "_service_catalog_enabled", return_value=True), self.assertRaises(api.HTTPException) as error:
            api.create_service_catalog_proposal(body, request)
        self.assertEqual(error.exception.status_code, 403)

    def test_stale_update_never_writes_a_catalog_entry(self) -> None:
        database = MagicMock()
        database.execute.return_value.fetchone.return_value = {"id": 9, "revision": 3}
        with self.assertRaises(api.HTTPException) as error:
            api._upsert_catalog_entry(
                database, collection={"source_collection_id": 1}, service_group="brain",
                catalog_service_group_id=7, change={"owner": "New owner"}, expected_revision=2,
                actor_user_id=11, operation="admin_update", reason="Correct owner assignment after review.",
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(database.execute.call_count, 1)

    def test_decision_rejects_self_approval_before_mutating_entry(self) -> None:
        principal = api.Principal(kind="human", subject="oidc:admin", role="admin", scopes=frozenset(), user_id=42)
        request = self._request(principal)
        database = MagicMock()
        database.execute.return_value.fetchone.return_value = {
            "id": "proposal-1", "source_collection_id": 1, "source_collection": "sse-cboms",
            "service_group": "brain", "submitted_by_user_id": 42, "base_revision": 0,
            "proposed_payload": {"owner": "Owner"}, "catalog_service_group_id": 7,
        }
        connection = MagicMock()
        connection.__enter__.return_value = database
        with (
            patch.object(api, "_service_catalog_enabled", return_value=True),
            patch.object(api, "_catalog_admin_human", return_value=principal),
            patch.object(api, "api_connection", return_value=connection),
            self.assertRaises(api.HTTPException) as error,
        ):
            api.decide_service_catalog_proposal(
                "proposal-1", api.ServiceCatalogProposalDecision(
                    decision="approved", decision_reason="Separate administrator review is required."
                ), request,
            )
        self.assertEqual(error.exception.status_code, 403)
        sql = "\n".join(str(call.args[0]) for call in database.execute.call_args_list)
        self.assertNotIn("UPDATE app_auth.service_catalog_entry", sql)
        self.assertIn("app_auth.audit_event", sql)

    def test_migration_keeps_new_groups_out_of_evidence_identity(self) -> None:
        ddl = (Path(__file__).resolve().parents[1] / "db" / "022_service_catalog_workflow.sql").read_text()
        entry = ddl.split("CREATE TABLE IF NOT EXISTS app_auth.service_catalog_entry", 1)[1].split(");", 1)[0]
        self.assertIn("catalog_service_group_id bigint REFERENCES service_group", entry)
        self.assertNotIn("service_group_id bigint PRIMARY KEY", entry)
        self.assertIn("service_catalog_entry_revision", ddl)

    def test_migration_enforces_a_separate_catalog_proposal_approver(self) -> None:
        ddl = (Path(__file__).resolve().parents[1] / "db" / "023_service_catalog_separate_approver.sql").read_text()
        self.assertIn("CREATE TRIGGER service_catalog_proposal_decision_separate_approver", ddl)
        self.assertIn("BEFORE INSERT ON app_auth.service_catalog_proposal_decision", ddl)
        self.assertIn("FROM app_auth.service_catalog_proposal", ddl)
        self.assertIn("NEW.decided_by_user_id = submitter_id", ddl)

    def test_group_mapping_options_do_not_require_migration_022_when_disabled(self) -> None:
        with (
            patch.object(api, "_service_catalog_enabled", return_value=False),
            patch.object(api, "_fetch_all", return_value=[]) as fetch,
        ):
            self.assertEqual(api._group_mapping_service_options(), [])
        self.assertEqual(fetch.call_count, 1)
        self.assertNotIn("service_catalog_entry", fetch.call_args.args[0])

    def test_catalog_query_overlays_a_pre_evidence_entry_by_collection_and_slug(self) -> None:
        """Source evidence adopts a control-plane row without duplicating it."""
        request = self._request(self._lead(), [{
            "access": "lead", "source_collection": "sse-cboms", "service_group": "brain",
        }])
        row = {
            "source_collection": "sse-cboms", "service_group": "brain", "catalog_display_name": "Brain",
            "revision": 1, "display_name": "Brain managed", "owner": None, "lead": None,
            "il2_status": None, "il2_target_date": None, "il5_status": None, "il5_target_date": None,
            "service_impact_risk": None, "comments": None, "attributes": {}, "overridden_fields": ["display_name"],
            "updated_at": None, "owner_user_id": None, "owner_user_email": None,
            "owner_user_display_name": None, "lead_user_id": None, "lead_user_email": None,
            "lead_user_display_name": None, "has_evidence": True,
        }
        with (
            patch.object(api, "_service_catalog_enabled", return_value=True),
            # Assigned leads make a second, independent pending-proposal query.
            # Keep the catalog-result mock scoped to the first call.
            patch.object(api, "_fetch_all", side_effect=[[row], []]) as fetch,
            patch.object(api, "_active_target_module_contract", return_value=None),
            patch.object(api, "_active_service_impact_map", return_value={}),
        ):
            result = api._catalog_rows(request)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["display_name"], "Brain managed")
        sql = fetch.call_args_list[0].args[0]
        self.assertIn("entry.source_collection_id = sc.id AND entry.service_group = sg.slug", sql)
        self.assertIn("NOT EXISTS (", sql)
        self.assertIn("source_group.slug = entry.service_group", sql)

    def test_exact_grant_sees_imported_metadata_for_reviewed_tracker_collection(self) -> None:
        request = self._request(self._lead(), [{
            "access": "lead", "source_collection": "sse-cboms", "service_group": "brain",
        }])
        row = self._catalog_row("sse-cboms", "brain")
        with (
            patch.object(api, "_service_catalog_enabled", return_value=True),
            patch.object(api, "_fetch_all", side_effect=[[row], []]),
            patch.object(api, "_active_target_module_contract", return_value=None),
            patch.object(api, "team_milestones", return_value=self._tracker_profiles()),
            patch.object(api, "_active_service_impact_map", return_value={
                "sse-cboms/brain": {"risk_category": "high", "comments": "Scoped impact comment"},
            }),
        ):
            result = api._catalog_rows(request)
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item["owner"], "Imported owner")
        self.assertEqual(item["lead"], "Imported lead")
        self.assertEqual(item["il2"], {"status": "dated", "date": "2027-01-15"})
        self.assertEqual(item["il5"], {"status": "dated", "date": "2027-03-01"})
        self.assertEqual(item["service_impact_risk"], "high")
        self.assertEqual(item["comments"], "Scoped impact comment")

    def test_same_slug_in_another_collection_does_not_inherit_tracker_metadata(self) -> None:
        request = self._request(self._lead(), [{
            "access": "lead", "source_collection": "other-collection", "service_group": "brain",
        }])
        row = self._catalog_row("other-collection", "brain")
        with (
            patch.object(api, "_service_catalog_enabled", return_value=True),
            patch.object(api, "_fetch_all", side_effect=[[row], []]),
            patch.object(api, "_active_target_module_contract", return_value=None),
            patch.object(api, "team_milestones", return_value=self._tracker_profiles()),
            patch.object(api, "_active_service_impact_map", return_value={
                "other-collection/brain": {"risk_category": "moderate", "comments": "Other collection impact"},
            }),
        ):
            item = api._catalog_rows(request)[0]
        self.assertIsNone(item["owner"])
        self.assertIsNone(item["lead"])
        self.assertEqual(item["il2"], {"status": "not_supplied", "date": None})
        self.assertEqual(item["il5"], {"status": "not_supplied", "date": None})
        # Service-impact provenance is already an exact collection/group key.
        self.assertEqual(item["service_impact_risk"], "moderate")
        self.assertEqual(item["comments"], "Other collection impact")

    def test_service_catalog_remains_unavailable_to_summary_access(self) -> None:
        request = SimpleNamespace(
            url=SimpleNamespace(path="/api/v1/service-catalog"), method="GET", query_params={},
        )
        self.assertFalse(api._request_within_assigned_scope(request, {
            "mode": "summary", "role": "summary", "summary_access": True, "grants": [],
        }))

    def test_mapping_options_hide_managed_entry_once_source_group_exists(self) -> None:
        """The mapping selector uses the same exact identity anti-join."""
        with (
            patch.object(api, "_service_catalog_enabled", return_value=True),
            patch.object(api, "_fetch_all", side_effect=[[], []]) as fetch,
        ):
            self.assertEqual(api._group_mapping_service_options(), [])
        managed_sql = fetch.call_args_list[1].args[0]
        self.assertIn("NOT EXISTS (", managed_sql)
        self.assertIn("source_group.source_collection_id = entry.source_collection_id", managed_sql)
        self.assertIn("source_group.slug = entry.service_group", managed_sql)

    def test_local_admin_uses_a_distinct_local_audit_actor(self) -> None:
        database = MagicMock()
        database.execute.return_value.fetchone.return_value = {
            "id": 99, "email": "local-service-catalog-admin@localhost.invalid", "display_name": "Local Service Catalog Admin",
        }
        local = api.Principal(kind="local", subject="local-development", role="admin", scopes=frozenset())
        with patch.object(api, "_production_mode", return_value=False):
            actor = api._catalog_actor_for(database, local)
        self.assertEqual(actor.user_id, 99)
        self.assertEqual(actor.email, "local-service-catalog-admin@localhost.invalid")
        self.assertIn("local-development", database.execute.call_args.args[0])

    def test_explicit_clear_hides_imported_owner_and_il2_date(self) -> None:
        """A managed NULL is rendered only when its field is in the override mask."""
        principal = api.Principal(kind="human", subject="oidc:admin", role="admin", scopes=frozenset(), user_id=1)
        request = SimpleNamespace(
            state=SimpleNamespace(
                principal=principal, request_id="request-1",
                assigned_scope={"mode": "portfolio", "role": "admin", "grants": []},
            ),
        )
        entry = {
            "source_collection": "sse-cboms", "service_group": "brain", "catalog_display_name": "Brain",
            "revision": 2, "display_name": None, "owner": None, "lead": None,
            "il2_status": None, "il2_target_date": None, "il5_status": None, "il5_target_date": None,
            "service_impact_risk": None, "comments": None, "attributes": {},
            "overridden_fields": ["owner", "il2_target_date"], "updated_at": None,
            "owner_user_id": None, "owner_user_email": None, "owner_user_display_name": None,
            "lead_user_id": None, "lead_user_email": None, "lead_user_display_name": None,
            "has_evidence": True,
        }
        imported = {"groups": [{
            "service_group": "brain", "owners": ["Imported owner"], "leads": ["Imported lead"],
            "tracker_rows": [{
                "il2": {"status": "planned", "date": "2027-01-15"},
                "il5": {"status": "in_progress", "date": "2027-03-01"},
            }],
        }]}
        with (
            patch.object(api, "_service_catalog_enabled", return_value=True),
            patch.object(api, "_fetch_all", return_value=[entry]),
            patch.object(api, "_active_target_module_contract", return_value=None),
            patch.object(api, "team_milestones", return_value=imported),
            patch.object(api, "_active_service_impact_map", return_value={"sse-cboms/brain": {"risk_category": "high", "comments": "Imported comment"}}),
        ):
            row = api._catalog_rows(request)[0]
        self.assertIsNone(row["owner"])
        self.assertIsNone(row["il2"]["date"])
        self.assertEqual(row["il2"]["status"], "dated")
        self.assertEqual(row["lead"], "Imported lead")
        self.assertEqual(row["comments"], "Imported comment")

    def test_migration_records_explicit_override_mask_and_revision_snapshot(self) -> None:
        ddl = (Path(__file__).resolve().parents[1] / "db" / "024_service_catalog_override_mask.sql").read_text()
        self.assertIn("ADD COLUMN IF NOT EXISTS overridden_fields text[]", ddl)
        self.assertIn("UPDATE app_auth.service_catalog_entry", ddl)
        self.assertIn("'il2_target_date'", ddl)
        self.assertEqual(
            api._catalog_overridden_fields({"owner": None, "il2_target_date": None}),
            ["owner", "il2_target_date"],
        )

    def test_catalog_revision_snapshots_encode_naive_and_utc_datetimes(self) -> None:
        """Both the create and update paths must store a JSON-safe revision snapshot."""
        cases = (
            (None, 1, datetime(2026, 9, 29, 12, 30, 45), "2026-09-29T12:30:45"),
            ({"id": 31, "revision": 1}, 2, datetime(2026, 9, 29, 12, 30, 45, tzinfo=timezone.utc), "2026-09-29T12:30:45+00:00"),
        )
        for current, revision, updated_at, expected_timestamp in cases:
            with self.subTest(existing=current is not None, updated_at=updated_at):
                database = MagicMock()
                current_cursor = MagicMock()
                current_cursor.fetchone.return_value = current
                write_cursor = MagicMock()
                write_cursor.fetchone.return_value = {"id": 31, "revision": revision, "updated_at": updated_at}
                snapshot_cursor = MagicMock()
                snapshot_cursor.fetchone.return_value = {
                    "revision": revision,
                    "display_name": "ADC",
                    "il2_target_date": date(2027, 1, 15),
                    "updated_at": updated_at,
                }
                database.execute.side_effect = [current_cursor, write_cursor, snapshot_cursor, MagicMock()]

                api._upsert_catalog_entry(
                    database,
                    collection={"source_collection_id": 7},
                    service_group="adc",
                    catalog_service_group_id=9,
                    change={"owner": "Example owner"},
                    expected_revision=0 if current is None else 1,
                    actor_user_id=42,
                    operation="create" if current is None else "admin_update",
                    reason="Verify a JSON-safe revision snapshot.",
                )

                revision_params = database.execute.call_args_list[-1].args[1]
                snapshot_json = revision_params[4]
                payload = json.loads(json.dumps(snapshot_json.obj))
                self.assertEqual(payload["il2_target_date"], "2027-01-15")
                self.assertEqual(payload["updated_at"], expected_timestamp)
