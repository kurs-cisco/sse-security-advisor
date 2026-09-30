import assert from "node:assert/strict";
import test from "node:test";
import { getPortfolioOverview } from "./api";

test("portfolio overview retains only aggregate component categories", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json({
    counts: { source_files: 12, unique_documents: 9 },
    component_types: [
      { component_type: "library", count: 7 },
      { component_type: "application", count: 3 },
    ],
    // These are deliberately ignored even if an upstream response is extended.
    service_groups: [{ display_name: "internal-service-name" }],
    top_crypto_libraries: [{ name: "library-identifier", version: "1.2.3" }],
  });
  try {
    const result = await getPortfolioOverview();
    assert.equal(result.source, "api");
    assert.ok(result.data);
    assert.deepEqual(result.data.component_types, [
      { component_type: "library", unique_components: 0, component_occurrences: 7 },
      { component_type: "application", unique_components: 0, component_occurrences: 3 },
    ]);
    assert.deepEqual(result.data.service_groups, []);
    assert.deepEqual(result.data.top_crypto_libraries, []);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
