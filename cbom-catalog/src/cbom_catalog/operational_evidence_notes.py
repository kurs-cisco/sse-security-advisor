"""Append-only finding observations; never POA&M or authorization decisions."""
from __future__ import annotations
import hashlib
import json
import re
from typing import Any
_SHA = re.compile(r"^[0-9a-f]{64}$")
class OperationalEvidenceNoteError(ValueError): pass
_SOURCE_KEYS = ('source_collection','service_group','product_scope_id','source_path','source_sha256')
def canonical_source_tuple_digest(sources: list[dict[str, Any]]) -> str:
    """Digest every exact source assigned to the selected product finding."""
    normalized = []
    for source in sources:
        if not isinstance(source, dict) or any(not isinstance(source.get(k), str) or not source[k].strip() for k in _SOURCE_KEYS) or not _SHA.fullmatch(source['source_sha256']):
            raise OperationalEvidenceNoteError('Invalid server-derived finding source tuple')
        normalized.append({k: source[k].strip() for k in _SOURCE_KEYS})
    if not normalized or len({tuple(row.values()) for row in normalized}) != len(normalized):
        raise OperationalEvidenceNoteError('Finding source tuple is incomplete or duplicated')
    return hashlib.sha256(json.dumps(sorted(normalized, key=lambda row: tuple(row[k] for k in _SOURCE_KEYS)), separators=(',', ':'), sort_keys=True).encode()).hexdigest()
def validate_current(*, current_sources: list[dict[str, Any]], stored_digest: str, current_finding_observation_digest: str, stored_finding_observation_digest: str, current_policy_fingerprint: str, stored_policy_fingerprint: str, current_assessment_revision: str, stored_assessment_revision: str) -> None:
    if (canonical_source_tuple_digest(current_sources) != stored_digest or current_finding_observation_digest != stored_finding_observation_digest or current_policy_fingerprint != stored_policy_fingerprint or str(current_assessment_revision) != str(stored_assessment_revision)):
        raise OperationalEvidenceNoteError('Finding evidence is stale or reassigned')
def validate_submission(payload: dict[str, Any]) -> None:
    forbidden = {'finding_fingerprint','evidence_fingerprint','routing_fingerprint','source_sha256','source_tuple_digest'}
    if forbidden.intersection(payload) or payload.get('product_scope_id') not in {'secure-access-government','secure-access-defense'} or len(str(payload.get('note') or '').strip()) < 8 or len(str(payload.get('lead_rationale') or '').strip()) < 8:
        raise OperationalEvidenceNoteError('Invalid operational evidence observation')
