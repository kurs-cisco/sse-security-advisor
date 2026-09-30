import assert from "node:assert/strict";
import test from "node:test";
import {
  hasCatalogPlanningOverlay,
  planningDispositionBasis,
  planningTargetCertificate,
  planningTargetDisposition,
  planningTargetModule,
  planningTargetVersion,
  type TargetModuleRecord,
} from "./team-milestones";

const imported: TargetModuleRecord = {
  current_module: "OpenSSL FIPS Provider",
  current_version: "3.0.8",
  used_by: null,
  target_module: "OpenSSL FIPS Provider",
  target_version: "3.0.8",
  asserted_status: "planned",
  normalized_status: "planned",
  current_cmvp_cert: "#4282",
  target_cmvp_cert: null,
  target_disposition: "planned_unverified",
  disposition_basis: "Imported tracker target requires review.",
  evidence_grade: "user_asserted",
  review_required: true,
  record_sha256: "imported-assertion",
  reason: null,
};

test("approved Service Catalog overlays drive Planning display without replacing imported assertions", () => {
  const targetRecord: TargetModuleRecord = {
    ...imported,
    effective_target_module: "OpenSSL FIPS Provider",
    effective_target_version: "3.1.2",
    effective_target_cmvp_cert: "#4985",
    effective_target_disposition: "active_certificate",
    effective_disposition_basis: "Catalog plan exactly matches linked CMVP certificate #4985; deployment evidence remains required.",
    catalog_crypto_module_plan: {
      projection_scope: "imported_record",
      target_module: "OpenSSL FIPS Provider",
      target_version: "3.1.2",
      cmvp_certificate: "#4985",
    },
  };

  assert.equal(planningTargetModule(targetRecord), "OpenSSL FIPS Provider");
  assert.equal(planningTargetVersion(targetRecord), "3.1.2");
  assert.equal(planningTargetCertificate(targetRecord), "#4985");
  assert.equal(planningTargetDisposition(targetRecord), "active_certificate");
  assert.match(planningDispositionBasis(targetRecord), /deployment evidence remains required/);
  assert.equal(hasCatalogPlanningOverlay(targetRecord), true);
  assert.equal(targetRecord.target_version, "3.0.8");
  assert.equal(targetRecord.target_disposition, "planned_unverified");
});

test("catalog-only plans are visible as CMVP pipeline planning, without creating an imported assertion", () => {
  const targetRecord: TargetModuleRecord = {
    ...imported,
    record_sha256: "",
    current_module: null,
    current_version: null,
    target_module: "Go Cryptographic Module",
    target_version: "v1.26.0",
    effective_target_disposition: "cmvp_in_process",
    effective_disposition_basis: "Catalog plan exactly matches linked public CMVP pipeline evidence; it is not an active validation certificate or deployment conclusion.",
    planning_origin: "catalog_only",
  };

  assert.equal(planningTargetDisposition(targetRecord), "cmvp_in_process");
  assert.equal(hasCatalogPlanningOverlay(targetRecord), true);
  assert.match(planningDispositionBasis(targetRecord), /not an active validation certificate or deployment conclusion/);
});

test("a public module suggestion remains separate from the imported planning disposition", () => {
  const targetRecord: TargetModuleRecord = {
    ...imported,
    public_module_suggestions: [{
      module_name: "OpenSSL FIPS Provider",
      module_version: "3.1.2",
      certificate_number: "#4985",
      public_status: "active",
      source_url: "https://csrc.nist.gov/projects/cryptographic-module-validation-program/certificate/4985",
      suggestion_basis: "Exact formal module and version match to an active public CMVP certificate.",
    }],
  };

  assert.equal(planningTargetDisposition(targetRecord), "planned_unverified");
  assert.equal(hasCatalogPlanningOverlay(targetRecord), false);
  assert.equal(targetRecord.public_module_suggestions?.[0].certificate_number, "#4985");
});
