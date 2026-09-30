import assert from "node:assert/strict";
import test from "node:test";
import { NextRequest } from "next/server";
import { PUT } from "../api/[...path]/route";

test("catch-all proxy forwards a Service Catalog PUT to the catalog API", async () => {
  const originalFetch = globalThis.fetch;
  const originalOrigin = process.env.CBOM_API_ORIGIN;
  let received: { url: string; init?: RequestInit } | undefined;
  process.env.CBOM_API_ORIGIN = "http://catalog-route-test.invalid";
  globalThis.fetch = async (input, init) => {
    received = { url: String(input), init };
    return Response.json({ updated: true });
  };
  try {
    const request = new NextRequest("https://console.invalid/api/v1/admin/service-catalog/sse-cboms/adc", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-CBOM-Access-Mode": "admin" },
      body: JSON.stringify({ expected_revision: 1, reason: "Correct the service owner." }),
    });
    const response = await PUT(request, {
      params: Promise.resolve({ path: ["v1", "admin", "service-catalog", "sse-cboms", "adc"] }),
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { updated: true });
    assert.equal(received?.url, "http://catalog-route-test.invalid/api/v1/admin/service-catalog/sse-cboms/adc");
    assert.equal(received?.init?.method, "PUT");
    assert.equal(new Headers(received?.init?.headers).get("x-cbom-access-mode"), "admin");
    assert.equal(await new Response(received?.init?.body).text(), '{"expected_revision":1,"reason":"Correct the service owner."}');
  } finally {
    globalThis.fetch = originalFetch;
    if (originalOrigin === undefined) delete process.env.CBOM_API_ORIGIN;
    else process.env.CBOM_API_ORIGIN = originalOrigin;
  }
});
