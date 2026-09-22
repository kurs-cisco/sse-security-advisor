#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { CbomWorkbenchStack } from "../lib/cbom-workbench-stack";

const app = new cdk.App();
const account = String(app.node.tryGetContext("account"));
const region = String(app.node.tryGetContext("region"));

new CbomWorkbenchStack(app, "CbomWorkbenchDev", {
  env: { account, region },
  stackName: "cbom-workbench-dev",
  terminationProtection: true,
  description: "CBOM Workbench cloud-development ECS, data, and OIDC boundary",
});
