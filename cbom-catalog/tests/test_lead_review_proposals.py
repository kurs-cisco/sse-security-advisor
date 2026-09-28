from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    from cbom_catalog import api
except ModuleNotFoundError as exc:
    if exc.name not in {"fastapi", "psycopg", "psycopg_pool"}:
        raise
    api = None


@unittest.skipIf(api is None, "install project dependencies to run API tests")
class LeadReviewProposalTests(unittest.TestCase):
    _PRODUCT_SCOPE = "secure-access-government"
    _AUTH_REFERENCE = "government-package-ref-v1"

    def setUp(self) -> None:
        # Each positive route test models an explicitly enabled operational
        # workflow. Default-deny behavior is exercised separately below.
        self._review_feature = patch.object(
            api, "_lead_review_proposals_enabled", return_value=True,
        )
        self._review_feature.start()

    def tearDown(self) -> None:
        self._review_feature.stop()

    def _grant(self) -> dict[str, str]:
        return {
            "source_collection": "sse-cboms", "service_group": "brain",
            "product_scope_id": self._PRODUCT_SCOPE,
            "boundary_name": "FedRAMP High/IL2", "access": "lead",
            "assessment_authorization_reference": self._AUTH_REFERENCE,
        }
    def _request(self, principal: object, query_params: dict[str, str] | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            state=SimpleNamespace(principal=principal, request_id="request-1"),
            query_params=query_params or {},
        )

    def _lead(self) -> object:
        return api.Principal(
            kind="human", subject="oidc:lead", role="lead", scopes=frozenset(),
            user_id=42, email="lead@example.test",
        )

    def test_routes_are_default_deny_when_operational_reviews_are_disabled(self) -> None:
        request = self._request(self._lead())
        body = api.LeadReviewProposalCreate(
            source_collection="sse-cboms", service_group="brain", product_scope_id=self._PRODUCT_SCOPE,
            resource_type="finding", resource_key="FINDING-1",
            proposed_note="Please verify runtime evidence before any disposition.",
            rationale="The scoped service owner needs an administrator review.",
        )
        with patch.object(api, "_lead_review_proposals_enabled", return_value=False):
            with self.assertRaises(api.HTTPException) as read_error:
                api.lead_review_proposals(request, "sse-cboms", "brain", self._PRODUCT_SCOPE)
            with self.assertRaises(api.HTTPException) as write_error:
                api.create_lead_review_proposal(body, request)
        self.assertEqual(read_error.exception.status_code, 403)
        self.assertEqual(write_error.exception.status_code, 403)

    def test_lead_scope_requires_exact_lead_grant(self) -> None:
        request = self._request(self._lead())
        assigned = {"grants": [self._grant()]}
        request.state.assigned_scope = assigned
        principal, grant, assigned_scope = api._lead_scope_grant(
            request, "sse-cboms", "brain", self._PRODUCT_SCOPE
        )
        self.assertEqual(principal.user_id, 42)
        self.assertEqual(grant["product_scope_id"], self._PRODUCT_SCOPE)
        self.assertEqual(assigned_scope["grants"][0]["service_group"], "brain")
        with self.assertRaises(api.HTTPException) as denied:
            api._lead_scope_grant(request, "sse-cboms", "apix-no-cbom", self._PRODUCT_SCOPE)
        self.assertEqual(denied.exception.status_code, 403)

    def test_resource_must_exist_in_the_lead_scoped_assessment(self) -> None:
        assessment = {
            "poam_items": [{"poam_candidate_id": "POAM-1"}],
            "findings": [{"finding_id": "FINDING-1"}],
        }
        with patch.object(api, "_cached_fips_assessment", return_value=(assessment, 1, False)):
            self.assertIsNotNone(api._lead_review_resource_snapshot("sse-cboms", "brain", "poam_candidate", "POAM-1", self._PRODUCT_SCOPE))
            self.assertIsNotNone(api._lead_review_resource_snapshot("sse-cboms", "brain", "finding", "FINDING-1", self._PRODUCT_SCOPE))
            self.assertIsNone(api._lead_review_resource_snapshot("sse-cboms", "brain", "finding", "POAM-1", self._PRODUCT_SCOPE))

    def test_submission_writes_only_proposal_and_audit_records(self) -> None:
        principal = self._lead()
        request = self._request(principal, {"source_collection": "sse-cboms", "service_group": "brain", "product_scope_id": self._PRODUCT_SCOPE})
        body = api.LeadReviewProposalCreate(
            source_collection="sse-cboms", service_group="brain", product_scope_id=self._PRODUCT_SCOPE,
            resource_type="finding", resource_key="FINDING-1",
            proposed_note="Please verify runtime evidence before any disposition.",
            rationale="The scoped service owner needs an administrator review.",
        )
        database = MagicMock()
        database.execute.return_value.fetchone.return_value = {
            "id": "proposal-1", "source_collection": "sse-cboms", "service_group": "brain",
            "resource_type": "finding", "resource_key": "FINDING-1",
            "proposed_note": body.proposed_note,
            "rationale": body.rationale,
        }
        connection = MagicMock()
        connection.__enter__.return_value = database
        with (
            patch.object(api, "_lead_scope_grant", return_value=(principal, self._grant(), {"policy_version": "test", "fingerprint": "a" * 64})),
            patch.object(api, "_lead_review_resource_snapshot", return_value=(1, "b" * 64)),
            patch.object(api, "api_connection", return_value=connection),
        ):
            result = api.create_lead_review_proposal(body, request)
        self.assertEqual(result["status"], "pending")
        sql = "\n".join(str(call.args[0]) for call in database.execute.call_args_list)
        self.assertIn("app_auth.lead_review_proposal", sql)
        self.assertIn("app_auth.audit_event", sql)
        self.assertNotIn("app_auth.admin_overlay", sql)
        database.commit.assert_called_once()

    def test_approval_is_append_only_and_never_updates_an_overlay(self) -> None:
        principal = api.Principal(
            kind="human", subject="oidc:admin", role="admin", scopes=frozenset(),
            user_id=7, email="admin@example.test",
        )
        request = self._request(principal)
        body = api.LeadReviewDecisionCreate(
            decision="approved",
            decision_reason="Approved as an operational note for follow-up.",
        )
        proposal = {
            "id": "proposal-1", "source_collection": "sse-cboms", "service_group": "brain",
            "resource_type": "finding", "resource_key": "FINDING-1",
            "proposed_note": "Please verify runtime evidence before any disposition.",
            "rationale": "Owner request.",
            "submitted_by_user_id": 42,
            "assessment_revision": 1, "assessment_fingerprint": "b" * 64,
            "product_scope_id": self._PRODUCT_SCOPE,
            "assessment_authorization_reference": self._AUTH_REFERENCE,
        }
        decision = {
            "proposal_id": "proposal-1", "decision": "approved",
            "decision_reason": body.decision_reason,
        }
        database = MagicMock()
        database.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=proposal)),
            MagicMock(fetchone=MagicMock(return_value=decision)),
            MagicMock(),
        ]
        connection = MagicMock()
        connection.__enter__.return_value = database
        with (
            patch.object(api, "_admin_principal", return_value=principal),
            patch.object(api, "_product_fips_validation", return_value={"authorization_reference": self._AUTH_REFERENCE}),
            patch.object(api, "_lead_review_resource_snapshot", return_value=(1, "b" * 64)),
            patch.object(api, "api_connection", return_value=connection),
        ):
            result = api.decide_lead_review_proposal("proposal-1", body, request)
        self.assertEqual(result["status"], "approved")
        sql = "\n".join(str(call.args[0]) for call in database.execute.call_args_list)
        self.assertIn("app_auth.lead_review_decision", sql)
        self.assertIn("app_auth.audit_event", sql)
        self.assertNotIn("app_auth.admin_overlay", sql)
        self.assertNotIn("UPDATE app_auth.lead_review_proposal", sql)
        database.commit.assert_called_once()

    def test_submitter_cannot_approve_their_own_proposal(self) -> None:
        principal = self._lead()
        request = self._request(principal)
        body = api.LeadReviewDecisionCreate(
            decision="approved",
            decision_reason="This must be decided by a different administrator.",
        )
        database = MagicMock()
        database.execute.return_value.fetchone.return_value = {
            "id": "proposal-1", "submitted_by_user_id": 42,
        }
        connection = MagicMock()
        connection.__enter__.return_value = database
        with (
            patch.object(api, "_admin_principal", return_value=principal),
            patch.object(api, "api_connection", return_value=connection),
            self.assertRaises(api.HTTPException) as denied,
        ):
            api.decide_lead_review_proposal("proposal-1", body, request)
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(database.execute.call_count, 2)
        self.assertIn("app_auth.audit_event", str(database.execute.call_args_list[-1].args[0]))
        database.commit.assert_called_once()

    def test_decision_rejects_a_stale_scoped_assessment_item(self) -> None:
        principal = api.Principal(
            kind="human", subject="oidc:admin", role="admin", scopes=frozenset(), user_id=7,
        )
        request = self._request(principal)
        body = api.LeadReviewDecisionCreate(decision="approved", decision_reason="Administrator review completed.")
        proposal = {
            "id": "proposal-1", "source_collection": "sse-cboms", "service_group": "brain",
            "resource_type": "finding", "resource_key": "FINDING-1", "submitted_by_user_id": 42,
            "assessment_revision": 1, "assessment_fingerprint": "b" * 64,
            "product_scope_id": self._PRODUCT_SCOPE,
            "assessment_authorization_reference": self._AUTH_REFERENCE,
        }
        database = MagicMock()
        database.execute.return_value.fetchone.return_value = proposal
        connection = MagicMock()
        connection.__enter__.return_value = database
        with (
            patch.object(api, "_admin_principal", return_value=principal),
            patch.object(api, "_product_fips_validation", return_value={"authorization_reference": self._AUTH_REFERENCE}),
            patch.object(api, "_lead_review_resource_snapshot", return_value=(2, "c" * 64)),
            patch.object(api, "api_connection", return_value=connection),
            self.assertRaises(api.HTTPException) as stale,
        ):
            api.decide_lead_review_proposal("proposal-1", body, request)
        self.assertEqual(stale.exception.status_code, 409)
        self.assertIn("app_auth.audit_event", str(database.execute.call_args_list[-1].args[0]))
        database.commit.assert_called_once()

    def test_submission_requires_query_scope_to_match_body(self) -> None:
        principal = self._lead()
        request = self._request(principal, {"source_collection": "sse-cboms", "service_group": "apix-no-cbom", "product_scope_id": self._PRODUCT_SCOPE})
        body = api.LeadReviewProposalCreate(
            source_collection="sse-cboms", service_group="brain", product_scope_id=self._PRODUCT_SCOPE,
            resource_type="finding", resource_key="FINDING-1",
            proposed_note="Please verify runtime evidence before any disposition.",
            rationale="The scoped service owner needs an administrator review.",
        )
        with self.assertRaises(api.HTTPException) as invalid:
            api.create_lead_review_proposal(body, request)
        self.assertEqual(invalid.exception.status_code, 400)

    def test_large_compound_catalog_revision_is_stored_as_text(self) -> None:
        principal = self._lead()
        request = self._request(principal, {"source_collection": "sse-cboms", "service_group": "brain", "product_scope_id": self._PRODUCT_SCOPE})
        body = api.LeadReviewProposalCreate(
            source_collection="sse-cboms", service_group="brain", product_scope_id=self._PRODUCT_SCOPE,
            resource_type="finding", resource_key="FINDING-1",
            proposed_note="Please verify runtime evidence before any disposition.",
            rationale="The scoped service owner needs an administrator review.",
        )
        large_revision = 10 ** 42
        database = MagicMock()
        database.execute.return_value.fetchone.return_value = {"id": "proposal-1"}
        connection = MagicMock()
        connection.__enter__.return_value = database
        with (
            patch.object(api, "_lead_scope_grant", return_value=(principal, self._grant(), {"policy_version": "test", "fingerprint": "a" * 64})),
            patch.object(api, "_lead_review_resource_snapshot", return_value=(large_revision, "b" * 64)),
            patch.object(api, "api_connection", return_value=connection),
        ):
            api.create_lead_review_proposal(body, request)
        insert_params = database.execute.call_args_list[0].args[1]
        self.assertIn(str(large_revision), insert_params)

    def test_already_decided_conflict_is_audited(self) -> None:
        principal = api.Principal(kind="human", subject="oidc:admin", role="admin", scopes=frozenset(), user_id=7)
        request = self._request(principal)
        body = api.LeadReviewDecisionCreate(decision="approved", decision_reason="Administrator review completed.")
        proposal = {
            "id": "proposal-1", "source_collection": "sse-cboms", "service_group": "brain",
            "resource_type": "finding", "resource_key": "FINDING-1", "submitted_by_user_id": 42,
            "assessment_revision": "1", "assessment_fingerprint": "b" * 64,
            "product_scope_id": self._PRODUCT_SCOPE,
            "assessment_authorization_reference": self._AUTH_REFERENCE,
        }
        database = MagicMock()
        database.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=proposal)),
            MagicMock(fetchone=MagicMock(return_value=None)),
            MagicMock(),
        ]
        connection = MagicMock()
        connection.__enter__.return_value = database
        with (
            patch.object(api, "_admin_principal", return_value=principal),
            patch.object(api, "_product_fips_validation", return_value={"authorization_reference": self._AUTH_REFERENCE}),
            patch.object(api, "_lead_review_resource_snapshot", return_value=(1, "b" * 64)),
            patch.object(api, "api_connection", return_value=connection),
            self.assertRaises(api.HTTPException) as conflict,
        ):
            api.decide_lead_review_proposal("proposal-1", body, request)
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertIn("app_auth.audit_event", str(database.execute.call_args_list[-1].args[0]))
        database.commit.assert_called_once()

    def test_api_credential_cannot_decide_a_lead_review_request(self) -> None:
        principal = api.Principal(
            kind="token", subject="token:credential", role="viewer",
            scopes=frozenset({"annotations:write"}), user_id=7, credential_id="credential",
        )
        request = self._request(principal)
        body = api.LeadReviewDecisionCreate(decision="approved", decision_reason="Administrator review completed.")
        with (
            patch.object(api, "_admin_principal", return_value=principal),
            self.assertRaises(api.HTTPException) as denied,
        ):
            api.decide_lead_review_proposal("proposal-1", body, request)
        self.assertEqual(denied.exception.status_code, 403)

    def test_migration_requires_a_human_user_for_a_decision(self) -> None:
        ddl = (Path(__file__).resolve().parents[1] / "db" / "016_lead_review_proposals.sql").read_text()
        decision_ddl = ddl.split("CREATE TABLE IF NOT EXISTS app_auth.lead_review_decision", 1)[1].split(");", 1)[0]
        self.assertIn("decided_by_user_id bigint NOT NULL", decision_ddl)
        self.assertNotIn("decided_by_credential_id", decision_ddl)

    def test_portfolio_admin_receives_catalog_pairs_without_new_grants(self) -> None:
        principal = api.Principal(kind="local", subject="local-development", role="admin", scopes=frozenset())
        request = SimpleNamespace(state=SimpleNamespace(principal=principal, assigned_scope={
            "mode": "portfolio", "role": "admin", "grants": [],
        }))
        with patch.object(api, "_fetch_all", return_value=[
            {"source_collection": "sse-cboms", "service_group": "brain"},
            {"source_collection": "sse-cboms", "service_group": "apix-no-cbom"},
        ]):
            result = api.current_user(request)
        self.assertEqual(result["access"]["grants"], [])
        self.assertEqual(result["assigned_scope"]["service_groups"], [
            "sse-cboms/brain", "sse-cboms/apix-no-cbom",
        ])
