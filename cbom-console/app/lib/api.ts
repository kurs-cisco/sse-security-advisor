import type { OverviewResponse } from "@/app/lib/contracts";
import { fetchJson } from "@/app/lib/http";

export type OverviewResult =
  | { data: OverviewResponse; source: "api"; error?: never }
  | { data: null; source: "unavailable"; error: string };

/** Never substitutes sample metrics for an unavailable catalog endpoint. */
export async function getOverview(): Promise<OverviewResult> {
  try {
    return { data: await fetchJson<OverviewResponse>("/api/v1/dashboard/overview"), source: "api" };
  } catch (error) {
    return {
      data: null,
      source: "unavailable",
      error: error instanceof Error ? error.message : "Catalog API is unavailable",
    };
  }
}
