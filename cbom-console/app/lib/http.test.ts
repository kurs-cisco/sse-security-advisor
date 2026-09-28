import assert from "node:assert/strict";
import test from "node:test";
import { ACCESS_MODE_STORAGE_KEY, accessModeHeaders, isAccessMode, selectedAccessMode } from "./http";

function installSessionStorage(value: string | null) {
  const prior = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: {
    sessionStorage: { getItem: (key: string) => key === ACCESS_MODE_STORAGE_KEY ? value : null },
  } });
  return () => {
    if (prior) Object.defineProperty(globalThis, "window", prior);
    else delete (globalThis as { window?: unknown }).window;
  };
}

test("only documented access modes can be sent to the API proxy", () => {
  for (const mode of ["admin", "product_lead", "product_engineer", "summary"]) assert.equal(isAccessMode(mode), true);
  for (const mode of [null, "lead", "engineer", "administrator", "product_lead ", "<script>"]) assert.equal(isAccessMode(mode), false);
});

test("access mode header preserves caller headers and forwards a valid session mode", () => {
  const restore = installSessionStorage("product_lead");
  try {
    const headers = accessModeHeaders({ Accept: "application/json", "X-Request-Id": "request-1" });
    assert.equal(selectedAccessMode(), "product_lead");
    assert.equal(headers.get("x-cbom-access-mode"), "product_lead");
    assert.equal(headers.get("accept"), "application/json");
    assert.equal(headers.get("x-request-id"), "request-1");
  } finally { restore(); }
});

test("invalid stored modes are omitted rather than forwarded", () => {
  const restore = installSessionStorage("admin,product_lead");
  try {
    assert.equal(selectedAccessMode(), null);
    assert.equal(accessModeHeaders({ "X-CBOM-Access-Mode": "admin" }).has("x-cbom-access-mode"), false);
  } finally { restore(); }
});
