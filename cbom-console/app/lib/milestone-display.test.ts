import assert from "node:assert/strict";
import test from "node:test";
import { milestoneRowDisplay } from "./milestone-display";
import type { TeamTrackerRow } from "./team-milestones";

const row: TeamTrackerRow = {
  team: "On Prem/Clients",
  owner: null,
  lead: null,
  il2: { label: "IL2", raw_value: "", status: "not_supplied", date: null },
  il5: { label: "IL5", raw_value: "", status: "not_supplied", date: null },
  mapped_service_groups: ["on-prem-clients"],
};

test("Team milestones renders the authoritative Service Catalog name for a singly mapped tracker row", () => {
  assert.deepEqual(
    milestoneRowDisplay(row, [{ source_collection: "sse-cboms", service_group: "on-prem-clients", display_name: "Chromebook Client" }]),
    { team: "Chromebook Client", mappedServiceGroups: ["Chromebook Client"] },
  );
});

test("Team milestones normalizes a legacy service-group label when no Catalog row is available", () => {
  assert.deepEqual(milestoneRowDisplay(row, []), {
    team: "Chromebook Client",
    mappedServiceGroups: ["Chromebook Client"],
  });
});
