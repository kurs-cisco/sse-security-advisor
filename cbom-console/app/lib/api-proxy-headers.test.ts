import assert from "node:assert/strict";
import test from "node:test";
import { forwardedClientHeaders } from "./api-proxy-headers";

test("proxy forwards the mode selection and no caller-supplied identity headers", () => {
  const headers = forwardedClientHeaders(new Headers({
    Accept: "application/json",
    "Content-Type": "application/json",
    "X-Request-Id": "request-1",
    "X-CBOM-Access-Mode": "product_engineer",
    "X-CBOM-User-Groups": "[\"fedsse-admins\"]",
    Authorization: "Bearer browser-value",
    Cookie: "unrelated=value",
  }));
  assert.equal(headers.get("x-cbom-access-mode"), "product_engineer");
  assert.equal(headers.get("x-cbom-user-groups"), null);
  assert.equal(headers.get("authorization"), null);
  assert.equal(headers.get("cookie"), null);
  assert.equal(headers.get("accept-encoding"), "identity");
});
