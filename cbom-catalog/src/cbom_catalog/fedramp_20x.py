"""Read-only FedRAMP 20x reporting readiness, never a submitted report.

The CBOM/FIPS catalog does not contain provider vulnerability evaluations or
reporting governance. Keep those missing facts explicit instead of deriving
IRV, LEV, PAIN, acceptance, or disposition from component observations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


VER_RULE_URL = (
    "https://preview.fedramp.gov/2026/reference/20x/c/"
    "vulnerability-evaluation-and-reporting/"
)

# VER-RPT-VDT lists these details for detected vulnerabilities when applicable.
# The accepted-vulnerability branch has separate VER-RPT-AVI requirements.
VER_DETAIL_FACTS = (
    ("provider_tracking_id", "Provider tracking ID"),
    ("detected_at", "Detection time"),
    ("detection_source", "Detection source"),
    ("evaluated_at", "Completed evaluation time"),
    ("internet_reachable", "Internet-reachability determination"),
    ("likely_exploitable", "Likely-exploitability determination"),
    ("current_pain", "Current Potential Agency Impact N-rating"),
    ("historical_pain", "Historical Potential Agency Impact N-rating"),
    ("completed_pain_reductions", "Each completed reduction time and N-rating"),
    ("next_reduction", "Next reduction target N-rating and time"),
    ("overdue_state", "Current or likely overdue state and explanation"),
    ("supplementary_risk_context", "Supplementary agency-risk information"),
    ("final_disposition", "Final vulnerability disposition"),
)

ACCEPTED_FACTS = (
    ("accepted_determination", "Authorized accepted-vulnerability determination"),
    ("acceptance_rationale", "Acceptance rationale"),
)

# These establish whether a provider report can be prepared and routed. They
# are readiness facts, not per-vulnerability VER-RPT-VDT fields.
REPORTING_GOVERNANCE_FACTS = (
    ("certification_class", "Provider certification class"),
    ("applicability_basis", "20x applicability or adoption basis"),
    ("reporting_period", "Reporting period start and end"),
    ("prior_report_reference", "Prior report reference"),
    ("necessary_parties", "Necessary-party routing"),
    ("immutable_provenance", "Immutable provenance for supplied evaluations"),
)


def _not_supplied(facts: tuple[tuple[str, str], ...], rule_id: str) -> list[dict[str, str]]:
    return [
        {"field": field, "label": label, "rule_id": rule_id, "state": "not_supplied"}
        for field, label in facts
    ]


def build_20x_readiness_preview(
    assessment: Mapping[str, Any], catalog_revision: int
) -> dict[str, Any]:
    """Describe missing 20x facts without creating a VDR/VER record.

    Even a complete FIPS assessment contract or a POA&M candidate is not a
    provider vulnerability evaluation. No 20x authoritative input is accepted
    by this adapter, so its output always remains nonreportable.
    """
    manifest = assessment.get("assessment_run")
    run_id = manifest.get("assessment_run_id") if isinstance(manifest, Mapping) else None
    contract = assessment.get("assessment_contract") or {}
    detail_checks = _not_supplied(VER_DETAIL_FACTS, "VER-RPT-VDT")
    governance_checks = _not_supplied(REPORTING_GOVERNANCE_FACTS, "VER-RPT-PER")
    return {
        "kind": "20x readiness — evidence missing",
        "reportable": False,
        "submission": False,
        "record_generated": False,
        "official_rule_url": VER_RULE_URL,
        "assessment_run_id": run_id,
        "internal_analysis_id": assessment.get("assessment_run_id"),
        "assessment_contract": contract,
        "analysis_candidate_count": len(assessment.get("poam_candidate_records") or []),
        "evaluation_record_count": 0,
        "missing_required_20x_fields": [check["label"] for check in detail_checks],
        "missing_reporting_governance_fields": [check["label"] for check in governance_checks],
        "vulnerability_detail_readiness": detail_checks,
        "reporting_governance_readiness": governance_checks,
        "accepted_vulnerability_readiness": {
            "state": "not_assessed",
            "note": (
                "Accepted-vulnerability fields are not applicable until an "
                "authorized disposition is supplied."
            ),
            "conditional_fields": _not_supplied(ACCEPTED_FACTS, "VER-RPT-AVI"),
        },
        "catalog_revision": catalog_revision,
        "disclaimer": (
            "No VDR/VER record was generated. FIPS catalog observations and "
            "POA&M candidates do not establish provider vulnerability "
            "evaluations, reportability, acceptance, or a submission."
        ),
    }
