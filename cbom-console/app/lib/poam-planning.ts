export type PlanningLaneKey =
  | `date:${string}`
  | "active:complete"
  | "active:not_applicable"
  | "active:blocked"
  | "active:undated"
  | "pipeline:vendor"
  | "pipeline:unknown_vendor"
  | "unclassified:not_applicable"
  | "unclassified:other";

export type LaneInput = {
  il2Status: string | null | undefined;
  il2Date: string | null | undefined;
  moduleDispositions: string[];
  namedPipelineVendor: boolean;
};

/** Owner planning determines the date lane; module assertions determine its evidence lane. */
export function planningLaneKey(input: LaneInput): PlanningLaneKey {
  const status = (input.il2Status || "").toLowerCase();
  const active = input.moduleDispositions.includes("active_certificate");
  const pipeline = input.moduleDispositions.includes("cmvp_in_process");
  if (active) {
    if (status === "not_applicable") return "active:not_applicable";
    if (status === "complete" || status === "done") return "active:complete";
    if (status === "blocked") return "active:blocked";
    const month = input.il2Date?.slice(0, 7);
    if (month && /^\d{4}-(0[1-9]|1[0-2])$/.test(month)) return `date:${month}`;
    return "active:undated";
  }
  if (pipeline) return input.namedPipelineVendor ? "pipeline:vendor" : "pipeline:unknown_vendor";
  return status === "not_applicable" ? "unclassified:not_applicable" : "unclassified:other";
}

export function planningLaneLabel(key: PlanningLaneKey): { eyebrow: string; title: string } {
  if (key.startsWith("date:")) {
    const [year, month] = key.slice(5).split("-").map(Number);
    return {
      eyebrow: "Service Catalog module plan",
      title: `${new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(year, month - 1, 1)))} IL2 target`,
    };
  }
  const labels: Record<Exclude<PlanningLaneKey, `date:${string}`>, { eyebrow: string; title: string }> = {
    "active:complete": { eyebrow: "Service Catalog module plan", title: "IL2 reported complete" },
    "active:not_applicable": { eyebrow: "Service Catalog module plan", title: "IL2 marked not applicable" },
    "active:blocked": { eyebrow: "Service Catalog module plan", title: "IL2 blocked" },
    "active:undated": { eyebrow: "Service Catalog module plan", title: "IL2 date not supplied" },
    "pipeline:vendor": { eyebrow: "Vendor-reported CMVP review", title: "Named vendor dependency" },
    "pipeline:unknown_vendor": { eyebrow: "Vendor-reported CMVP review", title: "Provider not identified" },
    "unclassified:not_applicable": { eyebrow: "Module target not established", title: "IL2 marked not applicable" },
    "unclassified:other": { eyebrow: "Module target not established", title: "No supported module target" },
  };
  return labels[key as Exclude<PlanningLaneKey, `date:${string}`>];
}

export type LaneStatInput = { serviceKey: string; risk: string | null | undefined; serviceRecords: number };
export type LaneStat = { groups: number; serviceRecords: number };

/** Counts group-linked document records; never represents unique deployments. */
export function planningLaneStats(rows: LaneStatInput[]) {
  const buckets: Record<"critical" | "moderate" | "other" | "total", LaneStat> = {
    critical: { groups: 0, serviceRecords: 0 },
    moderate: { groups: 0, serviceRecords: 0 },
    other: { groups: 0, serviceRecords: 0 },
    total: { groups: 0, serviceRecords: 0 },
  };
  const seen = new Set<string>();
  for (const row of rows) {
    if (seen.has(row.serviceKey)) continue;
    seen.add(row.serviceKey);
    const risk = (row.risk || "").trim().toLowerCase();
    const key = risk === "critical" || risk === "high" ? "critical" : risk === "moderate" || risk === "medium" ? "moderate" : "other";
    const records = Math.max(0, row.serviceRecords);
    buckets[key].groups += 1;
    buckets[key].serviceRecords += records;
    buckets.total.groups += 1;
    buckets.total.serviceRecords += records;
  }
  return buckets;
}
