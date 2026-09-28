/** Exact catalog identities used to generate MyID lead and engineer grants.
 *
 * The group key is an IdP label. The service_group is the catalog API slug;
 * these differ for APIX. All entries remain inactive until the deployment
 * explicitly enables service grants.
 */
export const OIDC_SERVICE_GROUPS = [
  { service_key: "adc", source_collection: "sse-cboms", service_group: "adc" },
  { service_key: "android-no-cbom", source_collection: "sse-cboms", service_group: "android-no-cbom" },
  { service_key: "apix", source_collection: "sse-cboms", service_group: "apix-no-cbom" },
  { service_key: "app-control", source_collection: "sse-cboms", service_group: "app-control" },
  { service_key: "avengers", source_collection: "sse-cboms", service_group: "avengers" },
  { service_key: "brain", source_collection: "sse-cboms", service_group: "brain" },
  { service_key: "cnhe", source_collection: "sse-cboms", service_group: "cnhe" },
  { service_key: "contraast", source_collection: "sse-cboms", service_group: "contraast" },
  { service_key: "data-platform", source_collection: "sse-cboms", service_group: "data-platform" },
  { service_key: "discovery", source_collection: "sse-cboms", service_group: "discovery" },
  { service_key: "disthost", source_collection: "sse-cboms", service_group: "disthost" },
  { service_key: "dlp", source_collection: "sse-cboms", service_group: "dlp" },
  { service_key: "dns-platform", source_collection: "sse-cboms", service_group: "dns-platform" },
  { service_key: "download-service", source_collection: "sse-cboms", service_group: "download-service" },
  { service_key: "dw-volt", source_collection: "sse-cboms", service_group: "dw-volt" },
  { service_key: "fis-sma-threatgrid", source_collection: "sse-cboms", service_group: "fis-sma-threatgrid" },
  { service_key: "frouter", source_collection: "sse-cboms", service_group: "frouter" },
  { service_key: "identity-apps", source_collection: "sse-cboms", service_group: "identity-apps" },
  { service_key: "identity-core", source_collection: "sse-cboms", service_group: "identity-core" },
  { service_key: "ios-no-cbom", source_collection: "sse-cboms", service_group: "ios-no-cbom" },
  { service_key: "knex", source_collection: "sse-cboms", service_group: "knex" },
  { service_key: "landers", source_collection: "sse-cboms", service_group: "landers" },
  { service_key: "metering", source_collection: "sse-cboms", service_group: "metering" },
  { service_key: "on-prem-clients", source_collection: "sse-cboms", service_group: "on-prem-clients" },
  { service_key: "opc", source_collection: "sse-cboms", service_group: "opc" },
  { service_key: "ovd-app-discovery", source_collection: "sse-cboms", service_group: "ovd-app-discovery" },
  { service_key: "pac-cbom", source_collection: "sse-cboms", service_group: "pac-cbom" },
  { service_key: "reporting", source_collection: "sse-cboms", service_group: "reporting" },
  { service_key: "rsm-secure-client-no-cbom", source_collection: "sse-cboms", service_group: "rsm-secure-client-no-cbom" },
  { service_key: "saasapi", source_collection: "sse-cboms", service_group: "saasapi" },
  { service_key: "scc-backend", source_collection: "sse-cboms", service_group: "scc-backend" },
  { service_key: "sfcn-firewall", source_collection: "sse-cboms", service_group: "sfcn-firewall" },
  { service_key: "sfcn-ravpn", source_collection: "sse-cboms", service_group: "sfcn-ravpn" },
  { service_key: "swg-proxy", source_collection: "sse-cboms", service_group: "swg-proxy" },
  { service_key: "swg-roaming-client-no-cbom", source_collection: "sse-cboms", service_group: "swg-roaming-client-no-cbom" },
  { service_key: "taac-cbom", source_collection: "sse-cboms", service_group: "taac-cbom" },
  { service_key: "unified-policy", source_collection: "sse-cboms", service_group: "unified-policy" },
  { service_key: "va", source_collection: "sse-cboms", service_group: "va" },
  { service_key: "zta-bap", source_collection: "sse-cboms", service_group: "zta-bap" },
  { service_key: "zta-calp", source_collection: "sse-cboms", service_group: "zta-calp" },
] as const;

/**
 * Product contexts are deployment policy, never inferred from catalog evidence.
 *
 * The identifiers are stable API values. `boundary_name` is a user-supplied
 * display label that identifies the intended authorization context; it is not
 * proof that a source file belongs to that context. The API must enforce the
 * uploader's file-level attribution before returning evidence for either one.
 */
export const OIDC_PRODUCT_SCOPES = [
  {
    product_scope_id: "secure-access-government",
    display_name: "Secure Access for Government",
    boundary_name: "FedRAMP High/IL2",
  },
  {
    product_scope_id: "secure-access-defense",
    display_name: "Secure Access for Defense",
    boundary_name: "IL5",
  },
] as const;
