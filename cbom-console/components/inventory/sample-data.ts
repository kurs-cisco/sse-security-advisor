import type { LibraryInventory, ServiceGroupInventory, ServiceInventory } from "@/components/inventory/types";

export const fallbackGroups: ServiceGroupInventory[] = [
  { group: "BRAIN", documents: 97, sourceFiles: 97, cryptoComponents: 1867, uniqueLibraries: 24, evidenceGaps: 0, ingestIssues: 0, formats: ["CycloneDX 1.6"], status: "ready" },
  { group: "SFCN-RAVPN", documents: 26, sourceFiles: 24, cryptoComponents: 1058, uniqueLibraries: 69, evidenceGaps: 0, ingestIssues: 0, formats: ["CycloneDX 1.6"], status: "ready" },
  { group: "SFCN-FIREWALL", documents: 60, sourceFiles: 60, cryptoComponents: 816, uniqueLibraries: 119, evidenceGaps: 0, ingestIssues: 0, formats: ["CycloneDX 1.6"], status: "ready" },
  { group: "DISCOVERY", documents: 8, sourceFiles: 8, cryptoComponents: 507, uniqueLibraries: 104, evidenceGaps: 0, ingestIssues: 0, formats: ["CycloneDX 1.6"], status: "ready" },
  { group: "SWG-PROXY", documents: 5, sourceFiles: 5, cryptoComponents: 442, uniqueLibraries: 198, evidenceGaps: 0, ingestIssues: 0, formats: ["CycloneDX 1.6"], status: "ready" },
  { group: "CONTRAAST", documents: 46, sourceFiles: 37, cryptoComponents: 239, uniqueLibraries: 35, evidenceGaps: 0, ingestIssues: 0, formats: ["CycloneDX 1.6"], status: "ready" },
  { group: "ZTA-CALP", documents: 54, sourceFiles: 30, cryptoComponents: 51, uniqueLibraries: 16, evidenceGaps: 0, ingestIssues: 0, formats: ["CycloneDX 1.6"], status: "ready" },
  { group: "FIS/SMA Threatgrid", documents: 11, sourceFiles: 11, cryptoComponents: 43, uniqueLibraries: 18, evidenceGaps: 0, ingestIssues: 0, formats: ["CycloneDX 1.6"], status: "ready" },
];

export const fallbackServices: ServiceInventory[] = [
  { id: "svc-cnhe-cortex", service: "cnhe-cortex-fips_0.1.121.698F", group: "CNHE", kind: "CBOM", format: "CycloneDX 1.6", cryptoComponents: 52, libraries: 0, checksum: "sha256:2b4da0b8dea1…", observedAt: "2026-09-17T18:22:09Z", provenance: "SSE_CBOMS/CNHE/cnhe-cortex-fips_0.1.121.698F-cbom.cdx.json", status: "attention" },
  { id: "svc-cnhe-datanode", service: "cnhe-datanode_2.0.91", group: "CNHE", kind: "CBOM", format: "CycloneDX 1.6", cryptoComponents: 52, libraries: 0, checksum: "sha256:4aa92f70fc95…", observedAt: "2026-09-17T18:22:08Z", provenance: "SSE_CBOMS/CNHE/cnhe-datanode_2.0.91-cbom.cdx.json", status: "needs-evidence" },
  { id: "svc-calp-design", service: "docs-cloudsec_zproxy_ztna_design", group: "ZTA-CALP", kind: "CBOM", format: "CycloneDX 1.6", cryptoComponents: 0, libraries: 0, checksum: "sha256:ad386267c98e…", observedAt: "2026-09-17T18:21:12Z", provenance: "SSE_CBOMS/ZTA-CALP/docs-cloudsec_zproxy_ztna_design-0-docs-cloudsec_zproxy_ztna_design.cbom.cdx.json", status: "needs-evidence" },
  { id: "svc-calp-monitor", service: "monitor-cloudsec_zproxy_tia_test_server", group: "ZTA-CALP", kind: "CBOM", format: "CycloneDX 1.6", cryptoComponents: 0, libraries: 0, checksum: "sha256:332c54cab063…", observedAt: "2026-09-17T18:21:13Z", provenance: "SSE_CBOMS/ZTA-CALP/monitor-cloudsec_zproxy_tia_test_server-0-monitor-cloudsec_zproxy_tia_test_server.cbom.cdx.json", status: "ready" },
];

export const fallbackLibraries: LibraryInventory[] = [
  { id: "libgcrypt20", library: "libgcrypt20", version: "1.9.4-3ubuntu3", purl: "No canonical PURL", serviceGroups: 1, serviceGroupNames: ["DISCOVERY"], services: 3, occurrences: 3, classification: "Explicit crypto", lastObserved: "2026-09-17T18:22:09Z", checksum: "—" },
  { id: "libcrypto3", library: "libcrypto3", version: "3.5.0-r0", purl: "No canonical PURL", serviceGroups: 3, serviceGroupNames: ["BRAIN", "SFCN-FIREWALL", "SFCN-RAVPN"], services: 2, occurrences: 2, classification: "Explicit crypto", lastObserved: "2026-09-17T18:22:09Z", checksum: "—" },
  { id: "libgnutls30", library: "libgnutls30", version: "3.7.3-4ubuntu1.5", purl: "No canonical PURL", serviceGroups: 1, serviceGroupNames: ["DISCOVERY"], services: 2, occurrences: 2, classification: "Explicit crypto", lastObserved: "2026-09-17T18:22:09Z", checksum: "—" },
  { id: "libssl3", library: "libssl3", version: "3.5.0-r0", purl: "No canonical PURL", serviceGroups: 3, serviceGroupNames: ["BRAIN", "SFCN-FIREWALL", "SFCN-RAVPN"], services: 2, occurrences: 2, classification: "Explicit crypto", lastObserved: "2026-09-17T18:22:09Z", checksum: "—" },
  { id: "openssl", library: "openssl", version: "3.5.0-r0", purl: "No canonical PURL", serviceGroups: 1, serviceGroupNames: ["BRAIN"], services: 2, occurrences: 2, classification: "Explicit crypto", lastObserved: "2026-09-17T18:22:09Z", checksum: "—" },
];
