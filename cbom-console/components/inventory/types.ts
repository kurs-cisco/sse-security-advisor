export type InventoryStatus = "ready" | "needs-evidence" | "no-data" | "attention";

export type ServiceGroupInventory = {
  group: string;
  documents: number;
  sourceFiles: number;
  cryptoComponents: number;
  uniqueLibraries: number;
  evidenceGaps: number;
  ingestIssues: number;
  formats: string[];
  status: InventoryStatus;
};

export type ServiceInventory = {
  id: string;
  service: string;
  group: string;
  kind: "CBOM" | "SBOM" | "CycloneDX" | "SPDX" | "Evidence" | "Tool summary";
  format: string;
  cryptoComponents: number;
  libraries: number;
  checksum: string;
  observedAt: string;
  provenance: string;
  status: InventoryStatus;
};

export type LibraryInventory = {
  id: string;
  library: string;
  version: string;
  purl: string;
  serviceGroups: number;
  serviceGroupNames: string[];
  services: number;
  occurrences: number;
  classification: "Explicit crypto" | "Candidate crypto inventory";
  lastObserved: string;
  checksum: string;
};
