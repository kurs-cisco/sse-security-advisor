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

test("Team milestones retains curated tracker team labels and original mapped-group keys", () => {
  const examples: Array<[string, string, string]> = [
    ["ADC", "adc", "ADC"],
    ["APIX (Authsvc,APIGW)", "apix-no-cbom", "APIX (Authsvc,APIGW)"],
    ["SWG Proxy", "swg-proxy", "SWG Proxy"],
  ];
  for (const [team, group, expected] of examples) {
    assert.deepEqual(milestoneRowDisplay({ ...row, team, mapped_service_groups: [group] }, [
      { source_collection: "sse-cboms", service_group: group, display_name: group },
    ]), { team: expected, mappedServiceGroups: [group] });
  }
});

test("Team milestones keeps the detailed APIX tracker label when Catalog only formats the group key", () => {
  assert.deepEqual(milestoneRowDisplay({ ...row, team: "APIX (Authsvc,APIGW)", mapped_service_groups: ["apix-no-cbom"] }, [
    { source_collection: "sse-cboms", service_group: "apix-no-cbom", display_name: "APIX" },
  ]), { team: "APIX (Authsvc,APIGW)", mappedServiceGroups: ["APIX"] });
});

test("Team milestones applies a meaningful Catalog rename while retaining a multi-group tracker label", () => {
  assert.deepEqual(milestoneRowDisplay({ ...row, team: "APIX (Authsvc,APIGW)", mapped_service_groups: ["apix-no-cbom"] }, [
    { source_collection: "sse-cboms", service_group: "apix-no-cbom", display_name: "API Experience" },
  ]), { team: "API Experience", mappedServiceGroups: ["API Experience"] });
  assert.deepEqual(milestoneRowDisplay({ ...row, team: "Shared platform", mapped_service_groups: ["adc", "swg-proxy"] }, [
    { source_collection: "sse-cboms", service_group: "adc", display_name: "ADC" },
    { source_collection: "sse-cboms", service_group: "swg-proxy", display_name: "SWG Proxy" },
  ]), { team: "Shared platform", mappedServiceGroups: ["ADC", "SWG Proxy"] });
});
