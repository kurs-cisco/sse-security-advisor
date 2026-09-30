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

function comparableGroupKey(value: string) {
  return serviceGroupDisplayName(value).toLocaleLowerCase().replaceAll(/[^a-z0-9]/g, "");
}

/**
 * Team Tracker names are curated imported planning metadata and remain the
 * Team-column source. A Catalog name replaces a tracker label only when it
 * differs meaningfully from the service-group key; raw-slug Catalog names do
 * not erase tracker labels such as ADC, APIX (Authsvc,APIGW), or SWG Proxy.
 * This gives the approved Chromebook Client name precedence for its legacy
 * group while preserving existing mapped-group keys elsewhere.
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
  const catalogLabel = (group: string) => {
    const catalogName = catalogNames.get(group)?.trim();
    return catalogName && catalogName !== group
      ? catalogName
      : serviceGroupDisplayName(group) === "Chromebook Client"
        ? "Chromebook Client"
        : group;
  };
  const mappedServiceGroups = (row.mapped_service_groups ?? []).map(catalogLabel);
  const mappedGroup = row.mapped_service_groups?.[0];
  const catalogTeamLabel = mappedGroup ? catalogNames.get(mappedGroup)?.trim() : null;
  // A label that only reformats the group key (for example APIX or SWG Proxy)
  // belongs in the mapped-group column. Keep the richer tracker Team label.
  const teamCatalogLabel = mappedServiceGroups.length === 1 && mappedGroup && catalogTeamLabel
    && comparableGroupKey(catalogTeamLabel) !== comparableGroupKey(mappedGroup)
    ? catalogTeamLabel
    : null;
  return {
    team: teamCatalogLabel ?? serviceGroupDisplayName(row.team),
    mappedServiceGroups,
  };
}
