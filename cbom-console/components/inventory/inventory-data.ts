"use client";

import * as React from "react";
import { fetchJson, type ApiPage } from "@/app/lib/http";
import { serviceGroupDisplayName, serviceGroupFromReference } from "@/app/lib/utils";
import type { InventoryStatus, LibraryInventory, ServiceGroupInventory, ServiceInventory } from "@/components/inventory/types";

export type InventorySnapshot =
  | { groups: ServiceGroupInventory[]; source: "api"; error?: never }
  | { groups: []; source: "unavailable"; error: string };

type ApiGroup = { slug: string; display_name: string; source_files: number; unique_documents: number; issues: number; crypto_component_occurrences?: number; unique_crypto_components?: number; unique_crypto_libraries?: number };
type ApiDocument = { document_id: number; sha256: string; document_kind: string; format_name: string; spec_version: string; generated_at_text: string | null; service_groups: string[]; source_paths: string[]; crypto_component_occurrences?: number; unique_crypto_libraries?: number };
type ApiComponent = { component_id: number; name: string; version: string | null; canonical_purl: string | null; document_count: number; occurrence_count?: number; service_groups: string[] };
type ApiOverview = { service_groups?: ApiGroup[] };

function baseName(path: string | undefined) { return path?.split("/").at(-1)?.replace(/\.json$/i, "") || "Untitled record"; }
function documentStatus(document: ApiDocument): InventoryStatus { return document.document_kind ? "ready" : "needs-evidence"; }

function mapDocument(document: ApiDocument): ServiceInventory {
  return {
    id: `doc-${document.document_id}`,
    service: baseName(document.source_paths?.[0]),
    group: serviceGroupFromReference(document.service_groups?.[0]),
    kind: document.document_kind === "cbom" ? "CBOM" : document.document_kind === "sbom" ? "SBOM" : document.document_kind === "cyclonedx" ? "CycloneDX" : document.document_kind === "spdx" ? "SPDX" : document.document_kind === "tool_summary" ? "Tool summary" : "Evidence",
    format: [document.format_name, document.spec_version].filter(Boolean).join(" ") || "Unspecified",
    cryptoComponents: document.crypto_component_occurrences ?? 0,
    libraries: document.unique_crypto_libraries ?? 0,
    checksum: document.sha256 ? `sha256:${document.sha256}` : "—",
    observedAt: document.generated_at_text ?? "",
    provenance: document.source_paths?.[0] ?? "—",
    status: documentStatus(document),
  };
}

function mapGroups(groups: ApiGroup[]): ServiceGroupInventory[] {
  return groups.map((group) => ({
      group: serviceGroupDisplayName(group.display_name || group.slug),
      documents: group.unique_documents ?? 0,
      services: group.unique_documents ?? 0,
      cryptoComponents: group.crypto_component_occurrences ?? 0,
      uniqueLibraries: group.unique_crypto_libraries ?? 0,
      evidenceGaps: group.issues ?? 0,
      formats: [],
      status: group.source_files === 0 ? "no-data" : group.issues > 0 ? "attention" : "ready",
    } satisfies ServiceGroupInventory));
}

function mapLibrary(component: ApiComponent): LibraryInventory {
  return {
    id: `component-${component.component_id}`,
    library: component.name,
    version: component.version ?? "Unspecified",
    purl: component.canonical_purl ?? "No canonical PURL",
    serviceGroups: new Set(component.service_groups?.map(serviceGroupFromReference)).size,
    serviceGroupNames: [...new Set(component.service_groups?.map(serviceGroupFromReference) ?? [])],
    services: component.document_count ?? 0,
    occurrences: component.occurrence_count ?? component.document_count ?? 0,
    classification: "Explicit crypto",
    lastObserved: "",
    checksum: "—",
  };
}

/** Uses deployed FastAPI endpoints and never substitutes demo inventory on request failure. */
export async function getInventorySnapshot(): Promise<InventorySnapshot> {
  try {
    const overview = await fetchJson<ApiOverview>("/api/v1/dashboard/overview");
    return { groups: mapGroups(overview.service_groups ?? []), source: "api" };
  } catch (error) {
    return {
      groups: [],
      source: "unavailable",
      error: error instanceof Error ? error.message : "Catalog API is unavailable",
    };
  }
}

export type InventoryPage<T> = { rows: T[]; total: number };
export type PageQuery = { page: number; pageSize: number; query: string; sort?: string; direction?: "asc" | "desc"; signal?: AbortSignal };

export async function getServicePage(options: PageQuery): Promise<InventoryPage<ServiceInventory>> {
  const params = new URLSearchParams({ limit: String(options.pageSize), offset: String(options.page * options.pageSize), sort: options.sort ?? "document_id", direction: options.direction ?? "asc" });
  if (options.query.trim()) params.set("query", options.query.trim());
  const result = await fetchJson<ApiPage<ApiDocument>>(`/api/v1/inventory/documents?${params}`, { signal: options.signal, dedupe: false });
  return { rows: result.items.map(mapDocument), total: result.total };
}

export async function getLibraryPage(options: PageQuery): Promise<InventoryPage<LibraryInventory>> {
  const params = new URLSearchParams({ limit: String(options.pageSize), offset: String(options.page * options.pageSize), sort: options.sort ?? "document_count", direction: options.direction ?? "desc" });
  if (options.query.trim()) params.set("query", options.query.trim());
  const result = await fetchJson<ApiPage<ApiComponent>>(`/api/v1/inventory/libraries?${params}`, { signal: options.signal, dedupe: false });
  return { rows: result.items.map(mapLibrary), total: result.total };
}

export function useInventorySnapshot() {
  const [snapshot, setSnapshot] = React.useState<InventorySnapshot>({ groups: [], source: "unavailable", error: "Catalog request has not completed" });
  const [loading, setLoading] = React.useState(true);
  const reload = React.useCallback(async () => {
    setLoading(true);
    const next = await getInventorySnapshot();
    setSnapshot(next);
    setLoading(false);
  }, []);
  React.useEffect(() => {
    let active = true;
    void getInventorySnapshot().then((next) => {
      if (!active) return;
      setSnapshot(next);
      setLoading(false);
    });
    return () => { active = false; };
  }, []);
  return { ...snapshot, loading, reload };
}
