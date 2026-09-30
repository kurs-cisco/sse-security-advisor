import type { TeamTrackerRow } from "@/app/lib/team-milestones";
import { serviceGroupDisplayName } from "@/app/lib/utils";

type CatalogServiceGroup = {
  source_collection: string;
  service_group: string;
  display_name: string;
};

export type MilestoneRowDisplay = {
  team: string;
  mappedServiceGroups: string[];
};

/**
 * Team Tracker names are imported planning metadata. When a tracker row maps
 * to exactly one Service Catalog group, show the current authoritative
 * Catalog display name in the milestone register. Multiple-group teams retain
 * their tracker name, while every mapped group still receives the same display
 * normalization used elsewhere in the console.
 */
export function milestoneRowDisplay(
  row: TeamTrackerRow,
  catalog: CatalogServiceGroup[],
): MilestoneRowDisplay {
  const catalogNames = new Map(
    catalog
      .filter((entry) => entry.source_collection === "sse-cboms" && entry.display_name.trim())
      .map((entry) => [entry.service_group, entry.display_name]),
  );
  const mappedServiceGroups = (row.mapped_service_groups ?? []).map(
    (group) => catalogNames.get(group) ?? serviceGroupDisplayName(group),
  );
  return {
    team: mappedServiceGroups.length === 1
      ? mappedServiceGroups[0]
      : serviceGroupDisplayName(row.team),
    mappedServiceGroups,
  };
}
