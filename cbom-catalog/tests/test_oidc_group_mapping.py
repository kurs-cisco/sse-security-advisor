from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from cbom_catalog import api
from cbom_catalog.oidc_group_mapping import (
    GroupMappingError, changed_service_groups, policy_sha256, service_rows,
)


def _groups() -> dict:
    grant = {"source_collection": "sse-cboms", "service_group": "dlp",
             "product_scope_id": "secure-access-government", "boundary_name": "FedRAMP High/IL2"}
    return {
        "fedsse-admins": {"access": "admin"},
        "fedsse-external": {"access": "summary"},
        "fedsse-scr2-leads": {"access": "summary"},
        "fedsse-dlp-leads": {"access": "lead", "service_key": "dlp", "grants": [grant]},
        "fedsse-dlp-engineers": {"access": "engineer", "service_key": "dlp", "grants": [dict(grant)]},
    }


class GroupMappingPolicyTests(TestCase):
    def test_pair_is_projected_without_changing_idp_membership(self) -> None:
        rows = service_rows(_groups())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lead_group"], "fedsse-dlp-leads")
        self.assertEqual(rows[0]["product_scope_ids"], ["secure-access-government"])

    def test_replace_is_exact_and_preserves_protected_groups(self) -> None:
        old = _groups()
        changed = changed_service_groups(
            old, action="replace", service_key="dlp", source_collection="sse-cboms",
            service_group="saasapi", product_scope_ids=["secure-access-government", "secure-access-defense"],
        )
        self.assertEqual(old["fedsse-dlp-leads"]["grants"][0]["service_group"], "dlp")
        self.assertEqual(changed["fedsse-admins"], old["fedsse-admins"])
        self.assertEqual(len(changed["fedsse-dlp-leads"]["grants"]), 2)
        self.assertEqual(changed["fedsse-dlp-leads"]["grants"][0]["service_group"], "saasapi")

    def test_new_or_retired_group_is_paired(self) -> None:
        added = changed_service_groups(
            _groups(), action="add", service_key="saasapi", source_collection="sse-cboms",
            service_group="saasapi", product_scope_ids=["secure-access-defense"],
        )
        self.assertIn("fedsse-saasapi-leads", added)
        self.assertIn("fedsse-saasapi-engineers", added)
        retired = changed_service_groups(added, action="retire", service_key="saasapi")
        self.assertNotIn("fedsse-saasapi-leads", retired)
        self.assertEqual(retired, _groups())

    def test_malformed_or_duplicate_mapping_fails_closed(self) -> None:
        with self.assertRaises(GroupMappingError):
            changed_service_groups(_groups(), action="retire", service_key="admins")
        with self.assertRaises(GroupMappingError):
            changed_service_groups(_groups(), action="add", service_key="*", source_collection="sse-cboms",
                                   service_group="saasapi", product_scope_ids=["secure-access-defense"])
        with self.assertRaises(GroupMappingError):
            changed_service_groups(_groups(), action="add", service_key="saasapi", source_collection="sse-cboms",
                                   service_group="dlp", product_scope_ids=["secure-access-defense"])
        with self.assertRaises(GroupMappingError):
            changed_service_groups(_groups(), action="replace", service_key="dlp", source_collection="sse-cboms",
                                   service_group="dlp", product_scope_ids=["unknown-product"])

    def test_assessment_reference_is_preserved_only_for_same_exact_grant(self) -> None:
        old = _groups()
        for name in ("fedsse-dlp-leads", "fedsse-dlp-engineers"):
            old[name]["grants"][0]["assessment_authorization_reference"] = "owner-approved-ref"
        same = changed_service_groups(old, action="replace", service_key="dlp", source_collection="sse-cboms",
                                      service_group="dlp", product_scope_ids=["secure-access-government", "secure-access-defense"])
        self.assertEqual(same["fedsse-dlp-leads"]["grants"][1]["assessment_authorization_reference"], "owner-approved-ref")
        moved = changed_service_groups(old, action="replace", service_key="dlp", source_collection="sse-cboms",
                                       service_group="saasapi", product_scope_ids=["secure-access-government"])
        self.assertNotIn("assessment_authorization_reference", moved["fedsse-dlp-leads"]["grants"][0])

    def test_paired_roles_cannot_disagree_about_authorization_reference(self) -> None:
        groups = _groups()
        groups["fedsse-dlp-leads"]["grants"][0]["assessment_authorization_reference"] = "reference-one"
        with self.assertRaises(GroupMappingError):
            service_rows(groups)

    def test_active_admin_revision_cannot_change_protected_groups(self) -> None:
        baseline = {"version": "test", "groups": _groups()}
        changed = _groups()
        changed["fedsse-admins"] = {"access": "summary"}
        row = {"id": 4, "policy_sha256": policy_sha256(changed), "groups": changed}
        database = SimpleNamespace(execute=lambda _: SimpleNamespace(fetchone=lambda: row))
        with patch.dict(os.environ, {
            "CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(baseline), "CBOM_ADMIN_GROUP_MAPPING_ENABLED": "true",
        }):
            with self.assertRaises(api.AssignedScopeError):
                api._oidc_policy_document(database)

    def test_revision_token_changes_even_if_policy_content_returns_to_prior_value(self) -> None:
        baseline = {"version": "test", "groups": _groups()}
        content = policy_sha256(_groups())
        with patch.dict(os.environ, {
            "CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(baseline), "CBOM_ADMIN_GROUP_MAPPING_ENABLED": "true",
        }):
            tokens = []
            for revision_id in (4, 6):
                row = {"id": revision_id, "policy_sha256": content, "groups": _groups()}
                database = SimpleNamespace(execute=lambda _: SimpleNamespace(fetchone=lambda: row))
                _, _, token = api._oidc_policy_document(database)
                tokens.append(token)
            self.assertNotEqual(tokens[0], tokens[1])
            self.assertEqual(tokens[0], hashlib.sha256(f"4:{content}".encode()).hexdigest())

    def test_missing_active_pointer_after_publish_denies_instead_of_restoring_seed(self) -> None:
        baseline = {"version": "test", "groups": _groups()}
        database = SimpleNamespace(execute=lambda sql: SimpleNamespace(
            fetchone=lambda: {"has_revisions": True} if "SELECT EXISTS" in sql else None,
        ))
        with patch.dict(os.environ, {
            "CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(baseline), "CBOM_ADMIN_GROUP_MAPPING_ENABLED": "true",
        }):
            with self.assertRaisesRegex(api.AssignedScopeError, "revision is missing"):
                api._oidc_policy_document(database)

    def test_api_credentials_cannot_read_admin_mapping(self) -> None:
        self.assertEqual(
            api.read_scope_for_path("/api/v1/admin/service-group-mappings"),
            "__human_admin_group_policy_only__",
        )

    def test_admin_publish_is_atomic_versioned_and_audited(self) -> None:
        baseline = {"version": "test", "groups": _groups()}
        old_revision = policy_sha256(baseline["groups"])
        statements: list[tuple[str, tuple]] = []

        class Database:
            committed = False

            def execute(self, sql, params=()):
                statements.append((sql, params))
                if "FROM app_auth.oidc_group_policy_active" in sql:
                    return SimpleNamespace(fetchone=lambda: None)
                if "SELECT EXISTS" in sql:
                    return SimpleNamespace(fetchone=lambda: {"has_revisions": False})
                if "SELECT 1 FROM source_collection" in sql:
                    return SimpleNamespace(fetchone=lambda: {"exists": True})
                if "INSERT INTO app_auth.oidc_group_policy_revision" in sql:
                    return SimpleNamespace(fetchone=lambda: {"id": 7})
                return SimpleNamespace(fetchone=lambda: None)

            def commit(self):
                self.committed = True

        database = Database()

        @contextmanager
        def connection():
            yield database

        request = SimpleNamespace(state=SimpleNamespace(request_id="test-request"))
        principal = api.Principal(kind="human", subject="oidc:admin", role="admin",
                                  scopes=frozenset(), user_id=9)
        with patch.dict(os.environ, {
            "CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(baseline), "CBOM_ADMIN_GROUP_MAPPING_ENABLED": "true",
        }), patch.object(api, "api_connection", connection), patch.object(api, "_audit_event") as audit:
            response = api._publish_service_group_mapping(
                request, principal, action="replace", service_key="dlp",
                reason="Approved DLP remap", expected_revision=old_revision,
                source_collection="sse-cboms", service_group="saasapi",
                product_scope_ids=["secure-access-government", "secure-access-defense"],
            )
        self.assertTrue(database.committed)
        self.assertTrue(any("INSERT INTO app_auth.oidc_group_policy_revision" in sql for sql, _ in statements))
        self.assertTrue(any("INSERT INTO app_auth.oidc_group_policy_active" in sql for sql, _ in statements))
        revision_insert = next(params for sql, params in statements if "INSERT INTO app_auth.oidc_group_policy_revision" in sql)
        self.assertEqual(revision_insert[1], old_revision)
        self.assertEqual(response["policy_version"].split(":")[1], "7")
        self.assertEqual(audit.call_args.kwargs["before_state"]["mapping"]["service_group"], "dlp")
        self.assertEqual(audit.call_args.kwargs["after_state"]["mapping"]["service_group"], "saasapi")

    def test_stale_mapping_revision_cannot_publish(self) -> None:
        baseline = {"version": "test", "groups": _groups()}
        statements: list[str] = []

        class Database:
            def execute(self, sql, params=()):
                statements.append(sql)
                if "SELECT EXISTS" in sql:
                    return SimpleNamespace(fetchone=lambda: {"has_revisions": False})
                return SimpleNamespace(fetchone=lambda: None)

        @contextmanager
        def connection():
            yield Database()

        request = SimpleNamespace(state=SimpleNamespace(request_id="test-request"))
        principal = api.Principal(kind="human", subject="oidc:admin", role="admin",
                                  scopes=frozenset(), user_id=9)
        with patch.dict(os.environ, {
            "CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(baseline), "CBOM_ADMIN_GROUP_MAPPING_ENABLED": "true",
        }), patch.object(api, "api_connection", connection):
            with self.assertRaises(api.HTTPException) as error:
                api._publish_service_group_mapping(
                    request, principal, action="retire", service_key="dlp",
                    reason="Approved retirement", expected_revision="0" * 64,
                )
        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(any("INSERT INTO" in sql for sql in statements))

    def test_two_publishes_chain_policy_content_hashes_not_revision_tokens(self) -> None:
        baseline = {"version": "test", "groups": _groups()}
        inserts: list[tuple] = []

        class Database:
            active = None
            pending = None
            next_id = 7

            def execute(self, sql, params=()):
                if "FROM app_auth.oidc_group_policy_active" in sql:
                    return SimpleNamespace(fetchone=lambda: self.active)
                if "SELECT EXISTS" in sql:
                    return SimpleNamespace(fetchone=lambda: {"has_revisions": False})
                if "SELECT 1 FROM source_collection" in sql:
                    return SimpleNamespace(fetchone=lambda: {"exists": True})
                if "INSERT INTO app_auth.oidc_group_policy_revision" in sql:
                    inserts.append(params)
                    self.pending = {"id": self.next_id, "policy_sha256": params[0], "groups": params[2].obj}
                    self.next_id += 1
                    return SimpleNamespace(fetchone=lambda: {"id": self.pending["id"]})
                if "INSERT INTO app_auth.oidc_group_policy_active" in sql:
                    self.active = self.pending
                return SimpleNamespace(fetchone=lambda: None)

            def commit(self):
                pass

        database = Database()

        @contextmanager
        def connection():
            yield database

        request = SimpleNamespace(state=SimpleNamespace(request_id="test-request"))
        principal = api.Principal(kind="human", subject="oidc:admin", role="admin",
                                  scopes=frozenset(), user_id=9)
        with patch.dict(os.environ, {
            "CBOM_OIDC_GROUP_SCOPE_JSON": json.dumps(baseline), "CBOM_ADMIN_GROUP_MAPPING_ENABLED": "true",
        }), patch.object(api, "api_connection", connection), patch.object(api, "_audit_event"):
            first = api._publish_service_group_mapping(
                request, principal, action="replace", service_key="dlp",
                reason="Approved first edit", expected_revision=policy_sha256(baseline["groups"]),
                source_collection="sse-cboms", service_group="saasapi",
                product_scope_ids=["secure-access-government", "secure-access-defense"],
            )
            second = api._publish_service_group_mapping(
                request, principal, action="replace", service_key="dlp",
                reason="Approved second edit", expected_revision=first["revision"],
                source_collection="sse-cboms", service_group="saasapi",
                product_scope_ids=["secure-access-government"],
            )
        self.assertNotEqual(first["revision"], second["revision"])
        self.assertEqual(inserts[1][1], inserts[0][0])
        self.assertNotEqual(inserts[1][1], first["revision"])
