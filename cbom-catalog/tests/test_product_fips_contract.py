from __future__ import annotations

from cbom_catalog.product_fips_contract import (
    suppress_product_candidates,
    validate_product_fips_contract,
)
from cbom_catalog import api
from fastapi import HTTPException
import json
from types import SimpleNamespace
from unittest.mock import patch


def _contract() -> dict:
    return {
        "source_collection": "sse-cboms",
        "service_group": "brain",
        "product_scope_id": "secure-access-government",
        "authorization_reference": "immutable-package-reference-1",
        "deployment_attestation": {
            "deployed_artifact_sha256": "a" * 64,
            "attestation_reference": "deployment-attestation-1",
            "attestation_sha256": "b" * 64,
        },
        "cryptographic_module": {"identity": "OpenSSL FIPS Provider", "version": "3.0.8"},
        "cmvp_evidence": {
            "certificate_identifier": "CMVP-0000",
            "security_policy_sha256": "c" * 64,
            "evidence_locator": "cmvp://certificate/CMVP-0000",
        },
    }


def test_product_contract_requires_exact_scope_and_immutable_evidence() -> None:
    result = validate_product_fips_contract(
        _contract(), source_collection="sse-cboms", service_group="brain",
        product_scope_id="secure-access-government", primary_evidence_verifier=lambda _: True,
    )
    assert result["complete"] is True
    assert result["candidate_eligible"] is True
    assert result["exports_allowed"] is True


def test_boundary_label_or_routing_without_evidence_produces_only_observation() -> None:
    result = validate_product_fips_contract(
        {
            "source_collection": "sse-cboms", "service_group": "brain",
            "product_scope_id": "secure-access-government",
            "boundary_name": "FedRAMP High/IL2",
        },
        source_collection="sse-cboms", service_group="brain",
        product_scope_id="secure-access-government",
    )
    shaped = suppress_product_candidates(result, [{"poam_candidate_id": "candidate-1"}])
    assert result["complete"] is False
    assert result["observations"][0]["poam_eligibility"] is False
    assert shaped == {
        "candidates": [], "exports_allowed": False, "observations": result["observations"],
    }


def test_scope_conflict_blocks_candidates_and_changes_fingerprint() -> None:
    complete = validate_product_fips_contract(
        _contract(), source_collection="sse-cboms", service_group="brain",
        product_scope_id="secure-access-government", primary_evidence_verifier=lambda _: True,
    )
    conflicting_contract = _contract()
    conflicting_contract["product_scope_id"] = "secure-access-defense"
    conflicting = validate_product_fips_contract(
        conflicting_contract, source_collection="sse-cboms", service_group="brain",
        product_scope_id="secure-access-government",
    )
    assert conflicting["candidate_eligible"] is False
    assert conflicting["conflicting_facts"] == ["product_scope_id"]
    assert conflicting["fingerprint"] != complete["fingerprint"]


def test_api_scoped_assessment_suppresses_candidates_without_primary_verifier() -> None:
    assessment = {
        "assessment_contract": {"complete": True, "fingerprint": "assessment"},
        "summary": {
            "deduplicated_poam_candidates": 1,
            "proposed_remediation_workstreams": 1,
            "portfolio_poam_candidates": 1,
        },
        "poam_items": [{"poam_candidate_id": "candidate-1"}],
        "poam_candidate_records": [{"poam_candidate_id": "candidate-1"}],
        "poam_workstreams": [{"workstream_id": "workstream-1"}],
        "portfolio_poam_items": [{"poam_candidate_id": "candidate-1"}],
        "findings": [{
            "finding_id": "finding-1", "poam_eligible": True,
            "poam_candidate_id": "candidate-1", "disposition": "candidate",
            "remediation": "Replace module", "risk_rationale": "risk",
            "proposed_risk": "high", "finding_key": "internal-key",
        }],
    }
    with (
        patch.object(api, "_fips_assessment_contract", return_value=_contract()),
        patch.object(api, "_cached_fips_assessment", return_value=(assessment, 1, False)),
        patch.object(api, "_active_overlay_map", return_value={}),
    ):
        response = api.fips_assessment(
            SimpleNamespace(headers={}),
            source_collection="sse-cboms", service_group="brain",
            product_scope_id="secure-access-government",
            include_findings=True,
            poam_limit=20,
            poam_offset=0,
        )
    payload = response.body.decode()
    assert '"poam_items":[]' in payload
    assert '"deduplicated_poam_candidates":0' in payload
    assert '"candidate_eligible":false' in payload
    assert '"poam_eligible":false' in payload
    assert '"poam_candidate_id"' not in payload
    assert '"disposition"' not in payload
    assert '"remediation"' not in payload
    assert '"finding_key"' not in payload


def test_incomplete_product_assessment_is_evidence_only_even_with_portfolio_run() -> None:
    contract = _contract()
    del contract["deployment_attestation"]
    assessment = {
        "assessment_run_id": "portfolio-run-1",
        "assessment_run": {"assessment_run_id": "portfolio-run-1"},
        "assessment_run_eligibility": True,
        "assessment_contract": {"complete": True, "fingerprint": "portfolio-contract"},
        "summary": {
            "candidate_gap_findings": 2,
            "needs_review_findings": 1,
            "deduplicated_poam_candidates": 1,
            "proposed_remediation_workstreams": 1,
            "portfolio_poam_candidates": 1,
            "coverage_gap_observations": 1,
        },
        "service_groups": [{
            "service": "sse-cboms/brain", "documents": 2,
            "poam_candidate_findings": 2, "finding_count": 3,
            "needs_review_findings": 1,
        }],
        "coverage_gaps": [{"service": "sse-cboms/brain", "assertion_state": "not_assessable"}],
        "analyst_observations": [{"observation_id": "observation-1"}],
        "poam_items": [{"poam_candidate_id": "candidate-1"}],
        "poam_candidate_records": [{"poam_candidate_id": "candidate-1"}],
        "poam_workstreams": [{"workstream_id": "workstream-1"}],
        "portfolio_poam_items": [{"poam_candidate_id": "candidate-1"}],
        "portfolio_delivery_waves": [{"wave": "near-term"}],
        "findings": [{
            "finding_id": "finding-1", "title": "Catalog signal",
            "poam_eligible": True, "poam_candidate_id": "candidate-1",
            "status": "candidate", "disposition": "draft", "remediation": "replace",
            "risk_rationale": "proposed risk", "workstream_id": "workstream-1",
        }],
    }
    with (
        patch.object(api, "_fips_assessment_contract", return_value=contract),
        patch.object(api, "_cached_fips_assessment", return_value=(assessment, 1, False)),
        patch.object(api, "_active_overlay_map", return_value={}),
    ):
        for include_findings in (False, True):
            response = api.fips_assessment(
                SimpleNamespace(headers={}),
                source_collection="sse-cboms", service_group="brain",
                product_scope_id="secure-access-government",
                include_findings=include_findings,
                poam_limit=20, poam_offset=0,
            )
            payload = json.loads(response.body)
            assert payload["assessment_contract"]["complete"] is True
            assert payload["assessment_run"] is None
            assert payload["assessment_run_id"] is None
            assert payload["assessment_run_eligibility"] is False
            assert payload["product_assessment_contract"]["candidate_eligible"] is False
            assert "deployment_attestation" in payload["product_assessment_contract"]["missing_required_facts"]
            for key in (
                "poam_items", "poam_candidate_records", "poam_workstreams",
                "portfolio_poam_items", "portfolio_delivery_waves",
            ):
                assert payload[key] == []
            for key in (
                "candidate_gap_findings", "needs_review_findings",
                "deduplicated_poam_candidates", "proposed_remediation_workstreams",
                "portfolio_poam_candidates",
            ):
                assert payload["summary"][key] == 0
            assert payload["summary"]["coverage_gap_observations"] == 1
            assert payload["service_groups"] == [{
                "service": "sse-cboms/brain", "documents": 2,
                "poam_candidate_findings": 0, "finding_count": 0,
                "needs_review_findings": 0,
            }]
            assert len(payload["coverage_gaps"]) == 1
            assert len(payload["analyst_observations"]) == 1
            if include_findings:
                assert payload["findings"] == [{
                    "finding_id": "finding-1", "title": "Catalog signal",
                    "assertion_state": "evidence_observation", "poam_eligible": False,
                }]
            else:
                assert "findings" not in payload


def test_api_scoped_export_requires_primary_verifier() -> None:
    assessment = {"assessment_contract": {"complete": True}}
    with (
        patch.object(api, "_fips_assessment_contract", return_value=_contract()),
        patch.object(api, "_cached_fips_assessment", return_value=(assessment, 1, False)),
    ):
        try:
            api.fips_poam_export(
                source_collection="sse-cboms", service_group="brain",
                product_scope_id="secure-access-government",
            )
        except HTTPException as error:
            assert error.status_code == 422
            assert error.detail["product_assessment_contract"]["exports_allowed"] is False
        else:
            raise AssertionError("scoped export must fail without a primary evidence verifier")
