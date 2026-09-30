import assert from "node:assert/strict";
import test from "node:test";
import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { CbomWorkbenchStack } from "../lib/cbom-workbench-stack";
import { OIDC_PRODUCT_SCOPES, OIDC_SERVICE_GROUPS } from "../lib/oidc-service-groups";

const baseContext: Record<string, unknown> = {
  account: "123456789012",
  region: "us-gov-east-1",
  vpcId: "vpc-0123456789abcdef0",
  hostedZoneId: "Z0123456789ABCDEFGHI",
  hostedZoneName: "example.test",
  hostname: "cbom.example.test",
  apiHostname: "api.cbom.example.test",
  imageTag: "test-image",
  availabilityZones: ["us-gov-east-1a"],
  publicSubnetIds: ["subnet-0123456789abcdef0"],
  publicSubnetRouteTableIds: ["rtb-0123456789abcdef0"],
  privateSubnetIds: ["subnet-0123456789abcdef1"],
  privateSubnetRouteTableIds: ["rtb-0123456789abcdef1"],
  activateServices: false,
  enableOidc: false,
  reuseRetainedBootstrapResources: true,
  oidcClientId: "test-client-id",
  oidcGroupScope: {
    version: "test.1",
    groups: {
      "fedsse-admins": { access: "admin" },
      "fedsse-external": { access: "summary" },
      "fedsse-scr2-leads": { access: "summary" },
    },
  },
  oidcIssuer: "https://idp.example.test/oidc/test-client-id",
  oidcAuthorizationEndpoint: "https://idp.example.test/authorize",
  oidcTokenEndpoint: "https://idp.example.test/token",
  oidcUserInfoEndpoint: "https://idp.example.test/userinfo",
  oidcSecretArn: "arn:aws-us-gov:secretsmanager:us-gov-east-1:123456789012:secret:cbom-oidc-test-AbCdEf",
  apiBearerSecretArn: "arn:aws-us-gov:secretsmanager:us-gov-east-1:123456789012:secret:cbom-bearer-test-AbCdEf",
  apiTokenPepperArn: "arn:aws-us-gov:secretsmanager:us-gov-east-1:123456789012:secret:cbom-pepper-test-AbCdEf",
};

type Container = { Name?: string; Environment?: Array<{ Name?: string; Value?: string }> };

function deploymentEnvironment(overrides: Record<string, unknown> = {}): Record<string, Record<string, string>> {
  const app = new cdk.App({ context: {
    ...baseContext,
    ...overrides,
  } });
  const stack = new CbomWorkbenchStack(app, "GroupPolicyStack", {
    env: { account: String(baseContext.account), region: String(baseContext.region) },
  });
  const resources = Template.fromStack(stack).findResources("AWS::ECS::TaskDefinition");
  const containers = Object.values(resources)
    .flatMap((resource) => (resource.Properties?.ContainerDefinitions ?? []) as Container[]);

  const environment = Object.fromEntries(containers.map((container) => [
    container.Name,
    Object.fromEntries((container.Environment ?? []).map((entry) => [entry.Name, entry.Value])),
  ]));
  assert.ok(environment.api, "API container must be synthesized");
  assert.ok(environment.web, "web container must be synthesized");
  return environment as Record<string, Record<string, string>>;
}

test("product detail and operational writes are disabled by default", () => {
  const environment = deploymentEnvironment();
  assert.equal(environment.api.CBOM_ADMIN_GROUP_MAPPING_ENABLED, "false");
  assert.equal(environment.api.CBOM_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED, "false");
  assert.equal(environment.api.CBOM_ACCESS_ROSTER_ENABLED, "false");
  assert.equal(environment.api.CBOM_LEAD_REVIEW_PROPOSALS_ENABLED, "false");
  assert.equal(environment.api.CBOM_OPERATIONAL_EVIDENCE_NOTES_ENABLED, "false");
  assert.equal(environment.api.CBOM_SERVICE_CATALOG_ENABLED, "false");
});

test("deployment cannot activate detail-dependent writes without their scope prerequisites", () => {
  assert.throws(
    () => deploymentEnvironment({ enableLeadReviewProposals: true }),
    /Lead review proposals require product-scoped detail/,
  );
  assert.throws(
    () => deploymentEnvironment({ enableAdminGroupMapping: true }),
    /Administrator group mapping requires exact OIDC service-group grants/,
  );
  assert.throws(
    () => deploymentEnvironment({ enableAccessRoster: true }),
    /Access roster requires exact OIDC service-group grants/,
  );
  assert.throws(
    () => deploymentEnvironment({ enableProductScopedDetailEvidence: true }),
    /Product detail requires exact OIDC service-group grants/,
  );
  assert.throws(
    () => deploymentEnvironment({ enableOperationalEvidenceNotes: true }),
    /Operational evidence notes require product-scoped detail/,
  );
  assert.throws(
    () => deploymentEnvironment({ enableServiceCatalog: true }),
    /Service Catalog requires exact OIDC service-group grants/,
  );
});

test("Service Catalog activation reaches the API only with exact group policy", () => {
  const environment = deploymentEnvironment({ enableOidcServiceGroups: true, enableServiceCatalog: true });
  assert.equal(environment.api.CBOM_SERVICE_CATALOG_ENABLED, "true");
  assert.equal(environment.web.CBOM_SERVICE_CATALOG_ENABLED, undefined);
});

test("access roster activation reaches only the API with exact group policy", () => {
  const environment = deploymentEnvironment({ enableOidcServiceGroups: true, enableAccessRoster: true });
  assert.equal(environment.api.CBOM_ACCESS_ROSTER_ENABLED, "true");
  assert.equal(environment.web.CBOM_ACCESS_ROSTER_ENABLED, undefined);
});

test("Admin mapping registry is explicitly enabled only with exact service-group policy", () => {
  const environment = deploymentEnvironment({ enableOidcServiceGroups: true, enableAdminGroupMapping: true });
  assert.equal(environment.api.CBOM_ADMIN_GROUP_MAPPING_ENABLED, "true");
  assert.equal(environment.web.CBOM_ADMIN_GROUP_MAPPING_ENABLED, undefined);
});

test("the API task receives the exact approved group policy", () => {
  const environment = deploymentEnvironment();
  const policy = JSON.parse(environment.api.CBOM_OIDC_GROUP_SCOPE_JSON);
  assert.equal(policy.version, "test.1");
  assert.deepEqual(Object.keys(policy.groups).sort(), [
    "fedsse-admins", "fedsse-external", "fedsse-scr2-leads",
  ]);
  assert.equal(environment.web.CBOM_OIDC_GROUP_SCOPE_JSON, undefined);
});

test("activation generates both product-scope grants for each exact lead and engineer group", () => {
  assert.equal(OIDC_SERVICE_GROUPS.length, 40);
  const environment = deploymentEnvironment({
    enableOidcServiceGroups: true,
  });
  const policy = JSON.parse(environment.api.CBOM_OIDC_GROUP_SCOPE_JSON);
  assert.equal(Object.keys(policy.groups).length, 83);
  assert.deepEqual(policy.product_scopes, OIDC_PRODUCT_SCOPES);
  const triples = new Set<string>();
  for (const service of OIDC_SERVICE_GROUPS) {
    for (const [suffix, access] of [["leads", "lead"], ["engineers", "engineer"]] as const) {
      const entry = policy.groups[`fedsse-${service.service_key}-${suffix}`];
      assert.deepEqual(entry, {
        access,
        service_key: service.service_key,
        grants: OIDC_PRODUCT_SCOPES.map((productScope) => ({
          source_collection: service.source_collection,
          service_group: service.service_group,
          product_scope_id: productScope.product_scope_id,
          boundary_name: productScope.boundary_name,
        })),
      });
      for (const grant of entry.grants) {
        const triple = `${grant.source_collection}\u0000${grant.service_group}\u0000${grant.product_scope_id}`;
        assert.ok(!triples.has(`${suffix}\u0000${triple}`), `duplicate ${suffix} grant ${triple}`);
        triples.add(`${suffix}\u0000${triple}`);
      }
    }
  }
  assert.equal(policy.groups["fedsse-apix-leads"].grants[0].service_group, "apix-no-cbom");
  assert.equal(policy.groups["fedsse-on-prem-clients-engineers"].grants[0].service_group, "on-prem-clients");
  assert.deepEqual(policy.groups["fedsse-scr2-leads"], { access: "summary" });
});

test("enabled grants cannot bypass the exact service registry", () => {
  assert.throws(() => deploymentEnvironment({
    enableOidcServiceGroups: true,
    oidcGroupScope: {
      ...baseContext.oidcGroupScope as object,
      groups: {
        ...(baseContext.oidcGroupScope as { groups: object }).groups,
        "fedsse-other-product-leads": {
          access: "lead", service_key: "other-product",
          grants: [{
            source_collection: "sse-cboms", service_group: "other-product",
            product_scope_id: "secure-access-government", boundary_name: "FedRAMP High/IL2",
          }],
        },
      },
    },
  }), /only from the exact OIDC service registry/);
});

test("deployment rejects placeholder service and ATO grants", () => {
  assert.throws(() => deploymentEnvironment({
    oidcGroupScope: {
      ...baseContext.oidcGroupScope as object,
      groups: {
        ...(baseContext.oidcGroupScope as { groups: object }).groups,
        "fedsse-example-leads": {
          access: "lead",
          service_key: "example",
          grants: [{ source_collection: "sse-cboms", service_group: "Example", product_scope_id: "secure-access-government", boundary_name: "TBD" }],
        },
      },
    },
  }), /Invalid boundary_name/);
});

test("deployment rejects a group name that does not match its service key", () => {
  assert.throws(() => deploymentEnvironment({
    oidcGroupScope: {
      ...baseContext.oidcGroupScope as object,
      groups: {
        ...(baseContext.oidcGroupScope as { groups: object }).groups,
        "fedsse-example-leads": {
          access: "lead",
          service_key: "different-service",
          grants: [{ source_collection: "sse-cboms", service_group: "Example", product_scope_id: "secure-access-government", boundary_name: "ATO-A" }],
        },
      },
    },
  }), /Service group key must exactly match/);
});

test("deployment rejects duplicate collection/service/product grants", () => {
  assert.throws(() => deploymentEnvironment({
    oidcGroupScope: {
      ...baseContext.oidcGroupScope as object,
      groups: {
        ...(baseContext.oidcGroupScope as { groups: object }).groups,
        "fedsse-example-leads": {
          access: "lead",
          service_key: "example",
          grants: [
            { source_collection: "sse-cboms", service_group: "example", product_scope_id: "secure-access-government", boundary_name: "FedRAMP High/IL2" },
            { source_collection: "sse-cboms", service_group: "example", product_scope_id: "secure-access-government", boundary_name: "FedRAMP High/IL2" },
          ],
        },
      },
    },
  }), /Duplicate collection\/service\/product grant/);
});

test("deployment rejects an unknown product scope or mismatched boundary name", () => {
  assert.throws(() => deploymentEnvironment({
    oidcGroupScope: {
      ...baseContext.oidcGroupScope as object,
      groups: {
        ...(baseContext.oidcGroupScope as { groups: object }).groups,
        "fedsse-example-leads": {
          access: "lead",
          service_key: "example",
          grants: [{
            source_collection: "sse-cboms", service_group: "example",
            product_scope_id: "other-product", boundary_name: "FedRAMP High/IL2",
          }],
        },
      },
    },
  }), /exact approved product scope and boundary name/);
});
