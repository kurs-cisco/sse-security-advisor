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
