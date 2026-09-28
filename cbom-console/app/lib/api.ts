import type { OverviewResponse } from "@/app/lib/contracts";
import { fetchJson } from "@/app/lib/http";
import { scopeQuery, type AssignedScopePair } from "@/app/lib/scope";

export type OverviewResult =
  | { data: OverviewResponse; source: "api"; error?: never }
  | { data: null; source: "unavailable"; error: string };

/** Never substitutes sample metrics for an unavailable catalog endpoint. */
export async function getOverview(scope: AssignedScopePair): Promise<OverviewResult> {
  try {
    return { data: await fetchJson<OverviewResponse>(`/api/v1/dashboard/overview?${scopeQuery(scope)}`), source: "api" };
  } catch (error) {
    return {
      data: null,
      source: "unavailable",
      error: error instanceof Error ? error.message : "Catalog API is unavailable",
    };
  }
}

/** Summary-only identities receive this deliberately aggregate response. */
export async function getPortfolioOverview(): Promise<OverviewResult> {
  try {
    const summary = await fetchJson<{
      counts: OverviewResponse["counts"];
      format_coverage?: Array<{ format?: string; count?: number }>;
    }>("/api/v1/portfolio/overview-summary");
    // Portfolio summaries deliberately discard identifier-bearing collections.
    // Detailed records are loaded only from a selected service-scope endpoint.
    return {
      data: {
        scope: { source_collection: null, service_group: null },
        counts: summary.counts,
        format_coverage: (summary.format_coverage ?? []).map((item) => ({
          document_kind: item.format ?? "Unspecified format",
          format_name: item.format ?? "Unspecified format",
          spec_version: "",
          unique_documents: item.count ?? 0,
          source_files: item.count ?? 0,
          component_occurrences: 0,
        })),
        component_types: [],
        top_crypto_libraries: [],
        service_groups: [],
      },
      source: "api",
    };
  } catch (error) {
    return {
      data: null,
      source: "unavailable",
      error: error instanceof Error ? error.message : "Catalog API is unavailable",
    };
  }
}
