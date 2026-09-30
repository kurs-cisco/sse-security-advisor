import assert from "node:assert/strict";
import test from "node:test";
import { serviceGroupDisplayName } from "./utils";

test("normalizes legacy Chromebook Client tracker labels to the Service Catalog display name", () => {
  for (const value of ["on-prem-clients", "ON-PREM-CLIENTS", "On Prem / Clients", "On Prem/Clients"]) {
    assert.equal(serviceGroupDisplayName(value), "Chromebook Client");
  }
});

test("normalizes an evidence-suffixed Chromebook Client service key", () => {
  assert.equal(serviceGroupDisplayName("on-prem-clients-no-cbom"), "Chromebook Client");
});
