import assert from "node:assert/strict";
import test from "node:test";
import { planningLaneKey, planningLaneLabel, planningLaneStats } from "./poam-planning";

test("approved IL2 dates move active targets into their actual month", () => {
  assert.equal(planningLaneKey({ il2Status: "planned", il2Date: "2027-01-15", moduleDispositions: ["active_certificate"], namedPipelineVendor: false }), "date:2027-01");
  assert.equal(planningLaneLabel("date:2027-01").title, "January 2027 IL2 target");
});

test("not-applicable planning does not invent a validated module target", () => {
  assert.equal(planningLaneKey({ il2Status: "not_applicable", il2Date: null, moduleDispositions: ["not_applicable"], namedPipelineVendor: false }), "unclassified:not_applicable");
  assert.equal(planningLaneKey({ il2Status: "not_applicable", il2Date: null, moduleDispositions: ["active_certificate"], namedPipelineVendor: false }), "active:not_applicable");
});

test("pipeline targets without a named vendor remain visible", () => {
  assert.equal(planningLaneKey({ il2Status: "planned", il2Date: "2026-12-15", moduleDispositions: ["cmvp_in_process"], namedPipelineVendor: false }), "pipeline:unknown_vendor");
});

test("lane counts use the same critical and moderate impact buckets as POA&M", () => {
  const stats = planningLaneStats([
    { serviceKey: "sse-cboms/adc", risk: "critical", serviceRecords: 1 },
    { serviceKey: "sse-cboms/dlp", risk: "moderate", serviceRecords: 7 },
    { serviceKey: "sse-cboms/other", risk: "high", serviceRecords: 2 },
    { serviceKey: "sse-cboms/medium", risk: " Medium ", serviceRecords: 4 },
    { serviceKey: "sse-cboms/adc", risk: "critical", serviceRecords: 1 },
  ]);
  assert.deepEqual(stats.critical, { groups: 2, serviceRecords: 3 });
  assert.deepEqual(stats.moderate, { groups: 2, serviceRecords: 11 });
  assert.deepEqual(stats.total, { groups: 4, serviceRecords: 14 });
});
