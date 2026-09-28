"""Fail-closed FIPS candidate gate for a product-specific service scope.

Product routing choices and boundary display labels are not deployment evidence
or authorization decisions.  This module returns only assessment metadata and
noneligible observations until an exact immutable evidence contract is present.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from .product_scopes import PRODUCT_SCOPES

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _sha256(value: Any) -> str | None:
    candidate = _text(value)
    return candidate if candidate and _SHA256.fullmatch(candidate.casefold()) else None


def validate_product_fips_contract(
    contract: dict[str, Any] | None,
    *,
    source_collection: str,
    service_group: str,
    product_scope_id: str,
    primary_evidence_verifier: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Validate the immutable evidence required to emit product candidates.

    A boundary label, source routing decision, component version, or FIPS-mode
    signal cannot satisfy this contract.  A failure is represented as a
    noneligible observation, never as a candidate or authorization conclusion.
    """
    scope = {
        "source_collection": source_collection,
        "service_group": service_group,
        "product_scope_id": product_scope_id,
    }
    missing: list[str] = []
    conflicts: list[str] = []
    supplied = contract if isinstance(contract, dict) else {}
    if product_scope_id not in PRODUCT_SCOPES:
        missing.append("product_scope_id")
    for key, expected in scope.items():
        actual = _text(supplied.get(key))
        if actual is None:
            missing.append(key)
        elif actual != expected:
            conflicts.append(key)
    authorization_reference = _text(supplied.get("authorization_reference"))
    if authorization_reference is None:
        missing.append("authorization_reference")
    deployment = supplied.get("deployment_attestation")
    if not isinstance(deployment, dict):
        missing.append("deployment_attestation")
        deployment = {}
    if _sha256(deployment.get("deployed_artifact_sha256")) is None:
        missing.append("deployment_attestation.deployed_artifact_sha256")
    if _text(deployment.get("attestation_reference")) is None:
        missing.append("deployment_attestation.attestation_reference")
    if _sha256(deployment.get("attestation_sha256")) is None:
        missing.append("deployment_attestation.attestation_sha256")
    module = supplied.get("cryptographic_module")
    if not isinstance(module, dict):
        missing.append("cryptographic_module")
        module = {}
    if _text(module.get("identity")) is None:
        missing.append("cryptographic_module.identity")
    if _text(module.get("version")) is None:
        missing.append("cryptographic_module.version")
    cmvp = supplied.get("cmvp_evidence")
    if not isinstance(cmvp, dict):
        missing.append("cmvp_evidence")
        cmvp = {}
    if _text(cmvp.get("certificate_identifier")) is None:
        missing.append("cmvp_evidence.certificate_identifier")
    if _sha256(cmvp.get("security_policy_sha256")) is None:
        missing.append("cmvp_evidence.security_policy_sha256")
    if _text(cmvp.get("evidence_locator")) is None:
        missing.append("cmvp_evidence.evidence_locator")

    normalized = {
        "scope": scope,
        "supplied_scope": {
            key: _text(supplied.get(key))
            for key in ("source_collection", "service_group", "product_scope_id")
        },
        "authorization_reference": authorization_reference,
        "deployment_attestation": deployment,
        "cryptographic_module": module,
        "cmvp_evidence": cmvp,
    }
    fingerprint = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    complete = not missing and not conflicts
    primary_evidence_verified = False
    if complete and primary_evidence_verifier is not None:
        try:
            primary_evidence_verified = bool(primary_evidence_verifier(normalized))
        except Exception:
            primary_evidence_verified = False
    if complete and not primary_evidence_verified:
        missing.append("primary_evidence_verification")
    observation = None
    eligible = complete and primary_evidence_verified
    if not eligible:
        observation = {
            "state": "evidence_gap" if missing else "not_assessable",
            "scope": scope,
            "missing_required_facts": sorted(set(missing)),
            "conflicting_facts": sorted(set(conflicts)),
            "poam_eligibility": False,
            "reason": (
                "Product routing and boundary labels do not establish deployment, "
                "CMVP applicability, or authorization scope."
            ),
        }
    return {
        "complete": complete,
        "candidate_eligible": eligible,
        "exports_allowed": eligible,
        "scope": scope,
        "boundary_name": PRODUCT_SCOPES.get(product_scope_id),
        "authorization_reference": authorization_reference,
        "missing_required_facts": sorted(set(missing)),
        "conflicting_facts": sorted(set(conflicts)),
        "fingerprint": fingerprint,
        "observations": [] if observation is None else [observation],
    }


def suppress_product_candidates(
    validation: dict[str, Any], candidates: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Preserve the candidate gate in API/export shaping without source writes."""
    if validation.get("candidate_eligible") is True:
        return {"candidates": list(candidates or []), "exports_allowed": True, "observations": []}
    return {
        "candidates": [],
        "exports_allowed": False,
        "observations": list(validation.get("observations") or []),
    }
