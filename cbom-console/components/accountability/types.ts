export type PlanningState = "dated" | "done" | "vendor_dependency" | "not_supplied" | "not_applicable" | "non_date";

export type PlanningSummary = {
  state: PlanningState;
  farthest_date: string | null;
  explicit_dates: string[];
  entries: Array<{ team: string; raw_value: string; status: string; date: string | null }>;
};

export type ServiceGroupRegisterRow = {
  service_key: string;
  source_collection: string;
  service_group: string;
  display_name: string;
  mapping_status: "mapped" | "not_mapped";
  effective_owners: string[];
  owner_state: "multiple" | "supplied" | "not_supplied";
  leads: string[];
  lead_state: "multiple" | "supplied" | "not_supplied";
  il2: PlanningSummary;
  il5: PlanningSummary;
  poam_impact: string | null;
  risk_category: string | null;
  comments: string | null;
  service_impact_team: string | null;
  service_impact_evidence_grade: "user_asserted" | null;
  service_impact_review_required: boolean;
  service_impact_source: {
    source_filename: string;
    source_sha256: string;
    source_row: number;
    imported_at: string;
  } | null;
  source_files: number;
  documents: number;
  documents_with_fips_evidence: number;
  documents_without_fips_evidence: number;
  evidence_coverage_percent: number;
  ingest_issues: number;
  crypto_component_occurrences: number;
  candidate_crypto_assets: number;
  candidate_crypto_libraries: number;
  candidate_findings: number;
  review_observations: number;
  finding_count: number;
  coverage_gap_states: string[];
  coverage_gap_count: number;
  poam_candidate_ids: string[];
  poam_candidate_count: number;
  workstream_ids: string[];
  workstream_count: number;
  portfolio_poam_ids: string[];
  portfolio_poam_count: number;
  delivery_wave: {
    wave: "october_2026" | "december_2026" | "march_2027" | "uncommitted";
    label: string;
    target_date: string | null;
    farthest_explicit_il2_date: string | null;
    raw_il2_values: string[];
  };
};

export type RegisterResponse = {
  items: ServiceGroupRegisterRow[];
  total: number;
  limit: number;
  offset: number;
  filter_options: { owners: string[]; leads: string[] };
  disclaimer: string;
};

export type CatalogDocument = {
  document_id: number;
  sha256: string;
  document_kind: string;
  format_name: string;
  spec_version: string;
  generated_at_text: string | null;
  source_paths: string[];
  crypto_component_occurrences: number;
  unique_crypto_components: number;
  unique_crypto_libraries: number;
};

export type CryptoLibrary = {
  component_id: number;
  name: string;
  version: string | null;
  canonical_purl: string | null;
  document_count: number;
  occurrence_count: number;
};

export type CryptoComponent = {
  occurrence_id: number;
  component_id: number;
  component_type: string;
  name: string;
  version: string | null;
  canonical_purl: string | null;
  bom_ref: string | null;
  scope: string | null;
  crypto_properties: unknown;
  explicit_crypto: boolean;
};

export type TrackerProfile = {
  mapping_status: "mapped" | "not_mapped";
  owners: string[];
  leads: string[];
  tracker_rows: Array<{
    team: string;
    owner: string | null;
    lead: string | null;
    il2: { raw_value: string; status: string; date: string | null };
    il5: { raw_value: string; status: string; date: string | null };
    cmvp_mapping?: string;
    cmvp_disposition?: { status: string; label: string; basis: string };
  }>;
};

export type CandidateFinding = {
  finding_id: string;
  rule_id: string;
  assertion_state: string;
  title: string;
  weakness: string;
  subject_name: string;
  subject_identity: string;
  document_id: number;
  document_sha256: string;
  poam_eligible: boolean;
  poam_candidate_ids: string[];
  evidence: Array<{ evidence_kind?: string; property_name?: string; property_value?: string; observed_at?: string }>;
  limitations: string[];
};

export type CoverageGap = {
  observation_id: string;
  assertion_state: "evidence_gap" | "not_assessable";
  title: string;
  technical_observation: string;
  missing_required_facts: string[];
  poam_eligibility: false;
};

export type CandidatePoam = {
  poam_candidate_id: string;
  status: string;
  control_id: string;
  title: string;
  proposed_risk: string;
  responsible_owner: string;
  scheduled_completion_date: string | null;
  milestone_mitigation_date?: string | null;
  linked_finding_count: number;
  remediation_plan: string;
};

export type PoamWorkstream = {
  workstream_id: string;
  status: string;
  title: string;
  candidate_count: number;
  merge_decision: "review_required";
  merge_blockers: string[];
};

export type PortfolioPoam = {
  portfolio_poam_id: string;
  dimension: "active_certificate_migration" | "cmvp_in_test_or_in_progress";
  status: string;
  title: string;
  affected_service_group_count: number;
  affected_service_record_count: number;
  affected_library_count: number;
  scheduled_completion_date: string | null;
  mitigation_date_rule: string;
};

export type ServiceGroupDetail = {
  profile: ServiceGroupRegisterRow;
  tracker: {
    profile: TrackerProfile;
    source: { source?: string; source_file?: string; source_file_sha256?: string; source_commit?: string; observed_at?: string; url?: string };
    disclaimer: string;
  };
  documents: { items: CatalogDocument[]; total: number; limit: number; offset: number };
  libraries: { items: CryptoLibrary[]; total: number; limit: number; offset: number };
  assessment: {
    assessment_run_id: string;
    policy: { policy_version?: string; assessment_date?: string };
    coverage_gaps: CoverageGap[];
    findings: CandidateFinding[];
    poam_items: CandidatePoam[];
    poam_workstreams: PoamWorkstream[];
    portfolio_poam_items: PortfolioPoam[];
    disclaimer: string;
  };
  candidate_only: true;
};
