from cbom_catalog.operational_evidence_notes import OperationalEvidenceNoteError, canonical_source_tuple_digest, validate_current, validate_submission
import pytest
from pydantic import ValidationError
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from starlette.requests import Request

from cbom_catalog import api
from cbom_catalog.access_control import Principal
from cbom_catalog.api import OperationalEvidenceNoteCreate

SOURCES=[{'source_collection':'sse-cboms','service_group':'brain','product_scope_id':'secure-access-government','source_path':'a.json','source_sha256':'a'*64},{'source_collection':'sse-cboms','service_group':'brain','product_scope_id':'secure-access-government','source_path':'b.json','source_sha256':'b'*64}]
def test_complete_tuple_is_sorted_and_detects_every_change():
 d=canonical_source_tuple_digest(SOURCES); assert d==canonical_source_tuple_digest(list(reversed(SOURCES)))
 for changed in (SOURCES[:1], SOURCES+[{'source_collection':'sse-cboms','service_group':'brain','product_scope_id':'secure-access-government','source_path':'c.json','source_sha256':'c'*64}], [{**SOURCES[0],'source_sha256':'d'*64},SOURCES[1]], [{**SOURCES[0],'product_scope_id':'secure-access-defense'},SOURCES[1]]):
  with pytest.raises(OperationalEvidenceNoteError): validate_current(current_sources=changed,stored_digest=d,current_finding_observation_digest='f'*64,stored_finding_observation_digest='f'*64,current_policy_fingerprint='p'*64,stored_policy_fingerprint='p'*64,current_assessment_revision='1',stored_assessment_revision='1')
def test_same_sources_reject_changed_finding_policy_or_revision():
 d=canonical_source_tuple_digest(SOURCES)
 for finding, policy, revision in [('x'*64,'p'*64,'1'),('f'*64,'q'*64,'1'),('f'*64,'p'*64,'2')]:
  with pytest.raises(OperationalEvidenceNoteError): validate_current(current_sources=SOURCES,stored_digest=d,current_finding_observation_digest=finding,stored_finding_observation_digest='f'*64,current_policy_fingerprint=policy,stored_policy_fingerprint='p'*64,current_assessment_revision=revision,stored_assessment_revision='1')
def test_client_fingerprints_rejected_and_rationale_required():
 validate_submission({'product_scope_id':'secure-access-government','note':'Observed evidence needs review.','lead_rationale':'Lead reviewed the source evidence.'})
 with pytest.raises(OperationalEvidenceNoteError): validate_submission({'product_scope_id':'secure-access-government','note':'Observed evidence needs review.','lead_rationale':'Lead reviewed the source evidence.','source_tuple_digest':'a'*64})


def test_api_body_rejects_client_supplied_fingerprints():
    body = {
        "source_collection": "sse-cboms",
        "service_group": "brain",
        "product_scope_id": "secure-access-government",
        "finding_id": "FIPSF-EXAMPLE",
        "note": "Observed evidence needs review.",
        "lead_rationale": "Lead reviewed the source evidence.",
    }
    OperationalEvidenceNoteCreate.model_validate(body)
    with pytest.raises(ValidationError):
        OperationalEvidenceNoteCreate.model_validate({**body, "source_tuple_digest": "a" * 64})


def test_unprovisioned_human_lead_is_denied_before_note_insert():
    principal = Principal(kind="human", subject="test-lead", role="lead", scopes=frozenset())
    with patch.object(api, "_request_principal", return_value=principal):
        with pytest.raises(HTTPException) as error:
            api._evidence_note_scope_grant(object(), "sse-cboms", "brain", "secure-access-government")
    assert error.value.status_code == 403


def test_self_decision_records_denied_audit_before_403():
    request = Request({"type": "http", "method": "POST", "path": "/"})
    request.state.request_id = "self-decision-test"
    principal = Principal(kind="human", subject="test-admin", role="admin", scopes=frozenset(), user_id=7)
    database = MagicMock()
    database.execute.return_value.fetchone.return_value = {
        "id": "note-1", "submitted_by_user_id": 7,
    }
    with (
        patch.object(api, "_operational_evidence_notes_enabled", return_value=True),
        patch.object(api, "_admin_principal", return_value=principal),
        patch.object(api, "api_connection", return_value=nullcontext(database)),
    ):
        with pytest.raises(HTTPException) as error:
            api.decide_operational_evidence_note(
                "note-1",
                api.OperationalEvidenceNoteDecisionCreate(decision="approved", reason="Reviewed evidence."),
                request,
            )
    assert error.value.status_code == 403
    audit_sql, audit_params = database.execute.call_args_list[-1].args
    assert "app_auth.audit_event" in audit_sql
    assert audit_params[3] == "operational_evidence_note.decision_denied"
    assert audit_params[-1] == "denied"
    database.commit.assert_called_once()
