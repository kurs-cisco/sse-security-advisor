import assert from "node:assert/strict";
import test from "node:test";
import { authMode, localAdminAllowed, localAdminRequestAllowed } from "./auth-config";

const KEYS = ["CBOM_AUTH_MODE", "CBOM_ENVIRONMENT", "CBOM_ALLOW_INSECURE_DEV_AUTH", "NODE_ENV"] as const;
const environment = process.env as Record<string, string | undefined>;

function withEnvironment(values: Partial<Record<(typeof KEYS)[number], string>>, check: () => void) {
  const previous = Object.fromEntries(KEYS.map((key) => [key, environment[key]]));
  try {
    for (const key of KEYS) {
      if (key in values) environment[key] = values[key];
      else delete environment[key];
    }
    check();
  } finally {
    for (const key of KEYS) {
      const value = previous[key];
      if (value === undefined) delete environment[key];
      else environment[key] = value;
    }
  }
}

test("production-built localhost container can use explicit local admin", () => {
  withEnvironment({ CBOM_AUTH_MODE: "local-admin", CBOM_ENVIRONMENT: "local", NODE_ENV: "production" }, () => {
    assert.equal(authMode(), "local-admin");
    assert.equal(localAdminAllowed("127.0.0.1"), true);
    assert.equal(localAdminAllowed("localhost"), true);
    assert.equal(localAdminAllowed("[::1]"), true);
    assert.equal(localAdminAllowed("workstation.example"), false);
    assert.equal(localAdminRequestAllowed(new Headers({ host: "localhost:3000" })), true);
    assert.equal(localAdminRequestAllowed(new Headers({ host: "127.0.0.1:3000" })), true);
    assert.equal(localAdminRequestAllowed(new Headers({ host: "workstation.example" })), false);
    assert.equal(localAdminRequestAllowed(new Headers({ host: "localhost@workstation.example" })), false);
    assert.equal(localAdminRequestAllowed(new Headers()), false);
  });
});

test("legacy insecure override cannot enable cloud local login", () => {
  withEnvironment({ CBOM_AUTH_MODE: "local-admin", CBOM_ENVIRONMENT: "production", CBOM_ALLOW_INSECURE_DEV_AUTH: "true", NODE_ENV: "production" }, () => {
    assert.equal(localAdminAllowed("localhost"), false);
    assert.equal(localAdminRequestAllowed(new Headers({ host: "localhost:3000" })), false);
  });
});

test("disabled or cloud OIDC modes cannot use local login", () => {
  for (const mode of ["disabled", "alb-oidc", "dev", "typo"]) {
    withEnvironment({ CBOM_AUTH_MODE: mode, CBOM_ENVIRONMENT: "local", NODE_ENV: "development" }, () => {
      assert.equal(localAdminAllowed("localhost"), false);
    });
  }
});
