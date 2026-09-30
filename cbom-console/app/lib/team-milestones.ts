import { fetchJson } from "@/app/lib/http";
import { addScope, type AssignedScopePair } from "@/app/lib/scope";

export type TrackerMilestone = {
  label: "IL2" | "IL5";
  raw_value: string;
  status: "date" | "done" | "vendor_dependency" | "partial_date" | "not_supplied" | "not_applicable" | "unparseable_or_relative";
  date: string | null;
};

export type TargetModuleRecord = {
  team?: string | null;
  team_key?: string | null;
  current_module: string | null;
  current_version: string | null;
  used_by: string | null;
  target_module: string | null;
  target_version?: string | null;
  asserted_status: string | null;
  normalized_status: string;
  current_cmvp_cert: string | null;
  target_cmvp_cert: string | null;
  target_disposition: "active_certificate" | "cmvp_in_process" | "planned_unverified" | "not_supplied" | "not_applicable" | "not_determined";
  disposition_basis: string;
  /**
   * A non-persistent Service Catalog planning overlay. The imported tracker
   * assertion above remains intact; these fields only describe the selected
   * catalog plan and any exact public-reference match it has.
   */
  effective_target_module?: string | null;
  effective_target_version?: string | null;
  effective_target_cmvp_cert?: string | null;
  effective_target_disposition?: "active_certificate" | "cmvp_in_process" | "planned_unverified" | "not_supplied" | "not_applicable" | "not_determined";
  effective_disposition_basis?: string | null;
  planning_origin?: "catalog_only" | string | null;
  catalog_crypto_module_plan?: {
    source_record_sha256?: string | null;
    target_module?: string | null;
    target_version?: string | null;
    cmvp_certificate?: string | null;
    evidence_url?: string | null;
    effective_target_disposition?: string;
    effective_disposition_basis?: string;
    linked_public_evidence?: {
      source_kind?: string | null;
      url?: string | null;
      certificate_number?: string | null;
      module_name?: string | null;
      module_version?: string | null;
      public_status?: string | null;
    } | null;
    projection_scope?: "imported_record" | "catalog_only" | string;
  } | null;
  /** Exact public CMVP references offered for Catalog review; never a state override. */
  public_module_suggestions?: Array<{
    module_name?: string | null;
    module_version?: string | null;
    certificate_number?: string | null;
    public_status?: string | null;
    source_url?: string | null;
    source_title?: string | null;
    source_kind?: string | null;
    suggestion_basis?: string | null;
  }>;
  reason: string | null;
  evidence_grade: "user_asserted";
  review_required: boolean;
  record_sha256: string;
  assertion_subject_sha256?: string | null;
  verification?: {
    current_inventory_match: { state: string; evidence_count: number };
    target_public_status: { state: string; evidence_count: number };
    public_authority_alignment: { state: string; evidence_count: number };
    deployment_applicability: { state: string; evidence_count: number };
    overall: { state: string; review_required: boolean };
  };
  evidence_summary?: {
    evidence_count: number;
    corroborates: number;
    contradicts: number;
    partial: number;
    not_observed: number;
    unresolved_requirements: string[];
  };
  evidence?: Array<{
    evidence_id: number;
    claim_field: string;
    verdict: string;
    source_kind: string;
    source_title: string | null;
    source_url: string | null;
    source_payload_sha256: string;
  }>;
};

/**
 * Planning views show the approved Service Catalog overlay when present.
 * These helpers deliberately leave imported target-module fields available so
 * UI can distinguish a planning selection from deployment evidence.
 */
export function planningTargetModule(module: TargetModuleRecord) {
  return module.effective_target_module ?? module.target_module;
}

export function planningTargetVersion(module: TargetModuleRecord) {
  return module.effective_target_version ?? module.target_version;
}

export function planningTargetCertificate(module: TargetModuleRecord) {
  return module.effective_target_cmvp_cert ?? module.target_cmvp_cert;
}

export function planningTargetDisposition(module: TargetModuleRecord) {
  return module.effective_target_disposition ?? module.target_disposition;
}

export function planningDispositionBasis(module: TargetModuleRecord) {
  return module.effective_disposition_basis ?? module.disposition_basis;
}

export function hasCatalogPlanningOverlay(module: TargetModuleRecord) {
  return Boolean(module.catalog_crypto_module_plan || module.planning_origin === "catalog_only");
}

export type TeamTrackerRow = {
  team: string;
  owner: string | null;
  lead: string | null;
  il2: TrackerMilestone;
  il5: TrackerMilestone;
  cmvp_mapping?: string | null;
  cmvp_disposition?: {
    status: "active_certificate" | "cmvp_in_process" | "historical_or_legacy" | "not_determined";
    raw_value: string;
    evidence_grade: "user_asserted";
    review_required: boolean;
  };
  mapped_service_groups?: string[];
  source_teams?: string[];
  target_modules?: TargetModuleRecord[];
};

export type PoamCandidate = {
  poam_candidate_id: string;
  status: string;
  control_id: string;
  title: string;
  proposed_risk: string;
  affected_services: string[];
  affected_service_count: number;
  remediation_plan: string;
  responsible_owner: string;
  scheduled_completion_date: string | null;
  milestone_mitigation_date?: string | null;
  linked_finding_count: number;
  source_sha256: string[];
  evidence_sha256: string[];
  team_tracker_milestones?: {
    group_milestones: Array<{
      service_group: string;
      owners: string[];
      leads: string[];
      tracker_rows: TeamTrackerRow[];
    }>;
    il2_explicit_dates: string[];
  };
  affected_service_groups?: string[];
  affected_service_records?: Array<{ document_id: number; name: string; source_path: string }>;
  affected_libraries?: Array<{ component_identity: string | null; name: string; version: string | null; document_id: number; occurrence_id: number | null }>;
  service_scope_links?: ServiceScopeLink[];
};

export type DeliveryWave = {
  wave: "october_2026" | "december_2026" | "march_2027" | "uncommitted";
  label: string;
  target_date: string | null;
  service_group_count: number;
  service_groups: Array<{
    service_group: string;
    owners: string[];
    leads: string[];
    farthest_explicit_il2_date: string | null;
    raw_il2_values: string[];
    cmvp_dispositions: string[];
  }>;
};

export type ServiceScopeLink = {
  service_record_id: string;
  service_record_name: string;
  document_id: number;
  document_sha256: string;
  source_collection: string;
  service_group: string;
  service_group_ref: string;
  source_path: string;
  source_sha256: string;
  subject_identity: string;
  subject_name: string;
  libraries: Array<{
    component_identity: string | null;
    name: string;
    version: string | null;
    occurrence_id: number | null;
    document_id: number;
  }>;
  planning?: {
    owners: string[];
    leads: string[];
    delivery_wave: Omit<DeliveryWave, "service_group_count" | "service_groups"> & { farthest_explicit_il2_date: string | null; raw_il2_values: string[] };
    tracker_rows: TeamTrackerRow[];
    target_modules?: TargetModuleRecord[];
    planning_source?: {
      source_file?: string;
      source_file_sha256?: string;
      retrieved_on?: string | null;
      evidence_grade?: "user_asserted";
    };
    eta_inheritance: string;
  };
};

export type PortfolioPoam = {
  portfolio_poam_id: string;
  dimension: "active_certificate_migration" | "cmvp_in_test_or_in_progress";
  title: string;
  condition: string;
  status: string;
  control_id: string;
  responsible_owners: string[];
  scheduled_completion_date: string | null;
  linked_candidate_ids: string[];
  linked_candidate_count: number;
  affected_service_groups: string[];
  affected_service_group_count: number;
  affected_service_records: Array<{ document_id: number; name: string; source_path: string }>;
  affected_service_record_count: number;
  affected_libraries: Array<{ component_identity: string; name: string; version: string | null }>;
  affected_library_count: number;
  target_modules?: TargetModuleRecord[];
  target_module_count?: number;
  target_module_source?: {
    source_file?: string;
    source_file_sha256?: string;
    retrieved_on?: string | null;
    evidence_grade?: "user_asserted";
  } | null;
  service_scope_links: ServiceScopeLink[];
  milestone_deliverables: DeliveryWave[];
  unclassified_candidate_count: number;
  merge_decision: "review_required";
  merge_blockers: string[];
};

export type PoamWorkstream = {
  workstream_id: string;
  status: string;
  title: string;
  issue_codes: string[];
  rule_ids: string[];
  control_id: string;
  proposed_risk: string;
  impact_assessment_status: "not_assessed";
  potential_adverse_impact: string | null;
  responsible_owner: string;
  milestone_mitigation_date: string | null;
  remediation_plan: string;
  candidate_count: number;
  subject_count: number;
  affected_service_count: number;
  affected_services: string[];
  candidate_ids: string[];
  tags: string[];
  merge_decision: "review_required";
  merge_blockers: string[];
  comments: string;
};

/** A coverage/evidence-request observation. It is expressly not a POA&M candidate. */
export type CoverageGap = {
  observation_id: string;
  output_type: "analyst_observation";
  assertion_state: "evidence_gap" | "not_assessable";
  poam_eligibility: false;
  title: string;
  technical_observation: string;
  scope: {
    source_collection: string;
    service_groups: string[];
    ato_boundary: string | null;
  };
  missing_required_facts: string[];
  evidence: unknown[];
  limitations: string[];
  review: {
    requires_authorized_assessor_review: true;
    requires_ao_review: true;
    requires_system_owner_attestation: true;
  };
};

/** Review-only output may contain more evidence detail than a coverage request. */
export type AnalystObservation = {
  observation_id: string;
  assertion_state?: string;
  title: string;
  technical_observation?: string;
  scope?: { source_collection?: string; service_groups?: string[]; ato_boundary?: string | null };
  missing_required_facts?: string[];
  evidence?: unknown[];
  limitations?: string[];
};

export type PoamAssessment = {
  /** Additive API metadata; the console makes absence visible rather than inferring it. */
  policy?: {
    policy_version?: string;
    assessor_version?: string;
    assessment_date?: string;
    assessment_as_of?: string;
    assessment_timezone?: string;
    authoritative_sources?: Array<{ title?: string; url?: string; retrieved_on?: string }>;
  };
  scope?: { source_collection?: string | null; service_group?: string | string[] | null };
  assessment_contract?: {
    complete?: boolean;
    missing_required_facts?: string[];
    fingerprint?: string;
    reporting_profile?: string;
    authority_register_path?: string;
    authority_register_sha256?: string;
    authority_retrieved_on?: string;
    authority_freshness_state?: "reviewed_for_assessment" | "incomplete";
    authority_freshness_review?: {
      reviewed_at?: string;
      reviewed_by?: string;
      reference?: string;
      sha256?: string;
    };
  };
  assessment_run?: {
    assessment_run_id?: string;
    assessment_as_of?: string;
    authority_register?: { path?: string; sha256?: string; retrieved_at?: string };
    authority_freshness_review?: {
      reviewed_at?: string;
      reviewed_by?: string;
      reference?: string;
      sha256?: string;
    };
  };
  assessment_run_id?: string;
  assessment_run_eligibility?: boolean;
  analyst_observations?: AnalystObservation[];
  poam_items: PoamCandidate[];
  poam_workstreams?: PoamWorkstream[];
  portfolio_poam_items?: PortfolioPoam[];
  portfolio_delivery_waves?: DeliveryWave[];
  coverage_gaps?: CoverageGap[];
  service_groups?: Array<{
    service: string;
    service_group_name: string;
    source_files: number;
    ingest_issues: number;
    documents: number;
    documents_with_fips_evidence: number;
    documents_without_fips_evidence: number;
  }>;
  disclaimer: string;
  summary: {
    deduplicated_poam_candidates: number;
    candidate_gap_findings: number;
    needs_review_findings: number;
    proposed_remediation_workstreams?: number;
    portfolio_poam_candidates?: number;
  };
  summary_metric_metadata?: Record<string, {
    label: string;
    unit: string;
    interpretation: string;
  }>;
  coverage_metric_metadata?: Record<string, {
    label: string;
    unit: string;
    interpretation: string;
  }>;
  poam_page?: { total: number; limit: number; offset: number };
};

export type TeamMilestoneProfile = {
  service_group: string;
  mapping_status: "mapped" | "not_mapped";
  empty_service_category: boolean;
  owners: string[];
  leads: string[];
  delivery_wave: Omit<DeliveryWave, "service_group_count" | "service_groups"> & {
    farthest_explicit_il2_date: string | null;
    raw_il2_values: string[];
  };
  target_modules: TargetModuleRecord[];
  tracker_rows: TeamTrackerRow[];
};

export type TeamMilestones = {
  disclaimer: string;
  groups: TeamMilestoneProfile[];
  all_tracker_rows: Array<TeamTrackerRow & { mapping_status: "mapped" | "retained_unmapped" }>;
};

export type LiveResult<T> =
  | { source: "api"; data: T; error?: never }
  | { source: "unavailable"; data: null; error: string };

async function fetchLive<T>(path: string, label: string, signal?: AbortSignal): Promise<LiveResult<T>> {
  try {
    return { source: "api", data: await fetchJson<T>(path, { signal, dedupe: !signal }) };
  } catch (error) {
    return {
      source: "unavailable",
      data: null,
      error: error instanceof Error ? error.message : `${label} is unavailable`,
    };
  }
}

/** Never substitutes demo records for an unavailable assessment endpoint. */
export function getPoamAssessment(options: { page?: number; pageSize?: number; query?: string; scope?: AssignedScopePair; signal?: AbortSignal }): Promise<LiveResult<PoamAssessment>> {
  const pageSize = options.pageSize ?? 20;
  const params = new URLSearchParams({
    poam_limit: String(pageSize),
    poam_offset: String((options.page ?? 0) * pageSize),
  });
  if (options.scope) addScope(params, options.scope);
  if (options.query?.trim()) params.set("query", options.query.trim());
  return fetchLive<PoamAssessment>(`/api/v1/fips/assessment?${params}`, "Catalog API", options.signal);
}

/** Planning is portfolio-only until imports carry source collection provenance. */
export function getTeamMilestones(scope?: AssignedScopePair): Promise<LiveResult<TeamMilestones>> {
  if (scope) return Promise.resolve({ source: "unavailable", data: null, error: "Team Tracker data lacks source collection provenance for the selected pair" });
  return fetchLive<TeamMilestones>("/api/v1/fips/team-milestones", "Catalog API");
}

/** Never substitutes demo team data for an unavailable milestone endpoint. */
