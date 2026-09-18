import type { OverviewResponse } from "@/app/lib/contracts";

// Shown only when the API is unavailable, so the UI remains reviewable in a local checkout.
export const overviewFallback: OverviewResponse = {
  scope: { source_collection: null, service_group: null },
  counts: { source_collections: 1, service_groups: 39, empty_service_groups: 4, source_files: 534, pending_source_files: 0, fingerprinted_source_files: 534, fingerprint_versions: 535, unique_documents: 533, artifacts: 341, unique_components: 59263, component_occurrences: 282688, unique_crypto_components: 717, crypto_component_occurrences: 6169, dependency_edges: 198, vulnerabilities: 0, external_records: 1, ingest_errors: 0 },
  format_coverage: [
    { document_kind: "cyclonedx", format_name: "CycloneDX", spec_version: "1.6", unique_documents: 532, source_files: 533, component_occurrences: 282294 },
    { document_kind: "cyclonedx", format_name: "CycloneDX", spec_version: "1.7", unique_documents: 1, source_files: 1, component_occurrences: 394 },
  ],
  component_types: [
    { component_type: "file", unique_components: 47872, component_occurrences: 198229 },
    { component_type: "library", unique_components: 10170, component_occurrences: 76921 },
    { component_type: "cryptographic-asset", unique_components: 857, component_occurrences: 6676 },
    { component_type: "application", unique_components: 247, component_occurrences: 713 },
    { component_type: "container", unique_components: 86, component_occurrences: 89 },
    { component_type: "operating-system", unique_components: 31, component_occurrences: 60 },
  ],
  top_crypto_libraries: [
    { component_id: -1, name: "libgcrypt20", version: "1.9.4-3ubuntu3", canonical_purl: "pkg:deb/ubuntu/libgcrypt20@1.9.4-3ubuntu3?arch=amd64&distro=ubuntu-22.04", occurrence_count: 3, service_count: 3, service_group_count: 5, classification_basis: "explicit_crypto_metadata" },
    { component_id: -2, name: "libcrypto3", version: "3.5.0-r0", canonical_purl: "pkg:apk/alpine/libcrypto3@3.5.0-r0?arch=x86_64&distro=alpine-3.22.0&upstream=openssl", occurrence_count: 2, service_count: 2, service_group_count: 3, classification_basis: "explicit_crypto_metadata" },
    { component_id: -3, name: "libgnutls30", version: "3.7.3-4ubuntu1.5", canonical_purl: "pkg:deb/ubuntu/libgnutls30@3.7.3-4ubuntu1.5?arch=amd64&distro=ubuntu-22.04&upstream=gnutls28", occurrence_count: 2, service_count: 2, service_group_count: 1, classification_basis: "explicit_crypto_metadata" },
    { component_id: -4, name: "libssl3", version: "3.0.2-0ubuntu1.18", canonical_purl: "pkg:deb/ubuntu/libssl3@3.0.2-0ubuntu1.18?arch=amd64&distro=ubuntu-22.04&upstream=openssl", occurrence_count: 2, service_count: 2, service_group_count: 1, classification_basis: "explicit_crypto_metadata" },
    { component_id: -5, name: "libssl3", version: "3.5.0-r0", canonical_purl: "pkg:apk/alpine/libssl3@3.5.0-r0?arch=x86_64&distro=alpine-3.22.0&upstream=openssl", occurrence_count: 2, service_count: 2, service_group_count: 3, classification_basis: "explicit_crypto_metadata" },
  ],
  service_groups: [
    { source_collection: "sse-cboms", slug: "brain", display_name: "BRAIN", source_files: 97, unique_documents: 97, crypto_component_occurrences: 1867, unique_crypto_components: 24, issues: 0 },
    { source_collection: "sse-cboms", slug: "sfcn-firewall", display_name: "SFCN-FIREWALL", source_files: 60, unique_documents: 60, crypto_component_occurrences: 816, unique_crypto_components: 119, issues: 1 },
    { source_collection: "sse-cboms", slug: "zta-calp", display_name: "ZTA-CALP", source_files: 51, unique_documents: 51, crypto_component_occurrences: 35, unique_crypto_components: 16, issues: 0 },
    { source_collection: "sse-cboms", slug: "contraast", display_name: "CONTRAAST", source_files: 46, unique_documents: 46, crypto_component_occurrences: 239, unique_crypto_components: 35, issues: 0 },
    { source_collection: "sse-cboms", slug: "knex", display_name: "KNEX", source_files: 31, unique_documents: 31, crypto_component_occurrences: 137, unique_crypto_components: 13, issues: 0 },
  ],
};
