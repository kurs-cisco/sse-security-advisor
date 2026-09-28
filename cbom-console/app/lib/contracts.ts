export type OverviewCounts = {
  source_collections?: number;
  service_groups?: number;
  empty_service_groups?: number;
  source_files?: number;
  pending_source_files?: number;
  fingerprinted_source_files?: number;
  fingerprint_versions?: number;
  unique_documents?: number;
  artifacts?: number;
  unique_components?: number;
  component_occurrences?: number;
  unique_crypto_components?: number;
  crypto_component_occurrences?: number;
  dependency_edges?: number;
  vulnerabilities?: number;
  external_records?: number;
  ingest_errors?: number;
};

export type FormatCoverage = {
  document_kind: string;
  format_name: string;
  spec_version: string;
  unique_documents: number;
  source_files: number;
  component_occurrences: number;
};

export type ServiceGroupSummary = {
  source_collection: string;
  slug: string;
  display_name: string;
  source_files: number;
  unique_documents: number;
  crypto_component_occurrences?: number;
  unique_crypto_components?: number;
  unique_crypto_libraries?: number;
  issues: number;
};

export type OverviewResponse = {
  scope: { source_collection: string | null; service_group: string | null };
  counts: OverviewCounts;
  format_coverage: FormatCoverage[];
  component_types: Array<{ component_type: string; unique_components: number; component_occurrences: number }>;
  top_crypto_libraries: Array<{
    component_id: number;
    name: string;
    version: string | null;
    canonical_purl: string | null;
    occurrence_count: number;
    service_count: number;
    service_group_count: number;
    classification_basis: "explicit_crypto_metadata";
  }>;
  service_groups: ServiceGroupSummary[];
};

/** The API, rather than the browser, determines effective authorization. */
export type EffectiveAccessGrant = {
  source_collection: string;
  service_group: string;
  product_scope_id: "secure-access-government" | "secure-access-defense";
  boundary_name: "FedRAMP High/IL2" | "IL5";
  assessment_authorization_reference?: string;
  ato_boundary: string | null;
  access: "lead" | "engineer";
};

export type EffectiveAccess = {
  policy_version: string;
  group_fingerprint: string | null;
  effective_role: "admin" | "lead" | "engineer" | "summary" | "none";
  summary_access: boolean;
  grants: EffectiveAccessGrant[];
  revoked: boolean;
  matched_groups?: string[];
  /** Exact mode identifiers returned by the API for this verified identity. */
  available_modes?: AccessMode[];
  /** Strongest verified mode; shown until the user chooses a different allowed mode. */
  default_mode?: AccessMode;
  /** Mode applied by the API for this request. It is never inferred by the browser. */
  active_mode?: AccessMode;
};

export type AccessMode = "admin" | "product_lead" | "product_engineer" | "summary";

export type AuthMeResponse = {
  kind: string;
  email: string | null;
  display_name: string | null;
  role?: string;
  can_edit?: boolean;
  capabilities?: { roster_revoke_restore?: boolean; operational_evidence_notes?: boolean; review_proposals?: boolean };
  access?: EffectiveAccess;
};
