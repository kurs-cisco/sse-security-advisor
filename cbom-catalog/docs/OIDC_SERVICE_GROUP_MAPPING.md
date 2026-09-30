# MyID service-group mapping

See the [dual product scope implementation plan](DUAL_ATO_SCOPE_PLAN.md) for
the three-part authorization key, evidence attribution gate, and rollout order.

**Deployed read-only catalog detail.** The exact 40 service identities are in
`infra/lib/oidc-service-groups.ts`. The deployment policy generates two product
grants for each exact `(source_collection, service_group)` pair. Evidence routing
and migrations 016–021 are applied and verified in GovCloud development. The
deployed API recognizes exact service claims, exposes verified grant metadata,
and returns read-only catalog detail only when the exact collection, service
group, product context, and current-file routing all match. FIPS candidates and
exports retain their separate assessment-contract gate; legacy Lead review,
roster changes, and operational evidence-note actions remain disabled. Service
Catalog metadata proposals have separate exact-grant and approver controls.
Migration 021 introduces
the separately audited Admin-maintained mapping registry; it is not a change to
MyID membership or source evidence.

The product OIDC contract uses the standard `groups` scope and claim. The ALB
requests `openid email groups`, and CBOM authorizes only exact group names from
the verified `groups` claim. The custom `memberships` scope and claim were used
for diagnosis and are not consumed by CBOM. Retain `groups`, narrow its MyID
selector to `STARTS_WITH fedsse-`, and remove the application-specific
`memberships` mapping after a fresh login confirms the filtered `groups`
array. The 2026-09-27 direct MyID check already confirmed exact admin, DLP
lead, and SCR2 summary names before that narrowing.

For every approved row below, the deployment policy recognizes two group names:
`fedsse-<stem>-leads` and `fedsse-<stem>-engineers`. The collection is
`sse-cboms` for all 40 rows. The grant's `service_group` must use the API key in
this table, not the display name. The owner confirmed that each exact service
lead or engineer MyID group covers both product contexts. Its two grants use
the same collection and API key, with `secure-access-government` mapped to
boundary name `FedRAMP High/IL2` and `secure-access-defense` mapped to `IL5`.
The owner also directed that existing and new files default to both products;
an authorized uploader can choose one or both for a new batch. Attribution
must be recorded against exact file SHA-256 values and cannot be inferred from
CBOM or planning records. This portfolio is intended to support both contexts:
Secure Access for Government in **Cisco Security for Government — FedRAMP High
baseline context**, and Secure Access for Defense in **Cisco Security for
Defense — DoD Impact Level 5 (IL5) context**. These are owner-supplied display
labels; the configured policy identifiers route access metadata only. They are
not immutable package identifiers or proof of authorization. The 2026-09-26
routing baseline
recorded exact-SHA default-both operational decisions for 534 then-current
source files. Every service grant is available as profile and grant metadata
and can render read-only, product-filtered catalog detail through the
exact-triple gate. That evidence access does not itself enable FIPS detail,
candidate output, exports, or operational writes.

Source-status cells below describe the 2026-09-18 inventory baseline, except
`on-prem-clients`, which was registered afterward without source evidence. The
exact-triple routing and access contract above applies to each registered key;
the table is not a claim about a later live corpus, authorization decision, or
compliance result.

| MyID stem | API `service_group` | Catalog display | Source status (2026-09-18) |
| --- | --- | --- | --- |
| `adc` | `adc` | ADC | present |
| `android-no-cbom` | `android-no-cbom` | ANDROID-NO_CBOM | retained, no data |
| `apix` | `apix-no-cbom` | APIX | present |
| `app-control` | `app-control` | App-Control | present |
| `avengers` | `avengers` | Avengers | present |
| `brain` | `brain` | BRAIN | present |
| `cnhe` | `cnhe` | CNHE | present |
| `contraast` | `contraast` | CONTRAAST | present |
| `data-platform` | `data-platform` | DATA-PLATFORM | present |
| `discovery` | `discovery` | Discovery | present |
| `disthost` | `disthost` | DISTHOST | present |
| `dlp` | `dlp` | DLP | present |
| `dns-platform` | `dns-platform` | DNS-PLATFORM | present |
| `download-service` | `download-service` | Download Service | present |
| `dw-volt` | `dw-volt` | DW_VOLT | present |
| `fis-sma-threatgrid` | `fis-sma-threatgrid` | FIS/SMA Threatgrid | present |
| `frouter` | `frouter` | FROUTER | present |
| `identity-apps` | `identity-apps` | IDENTITY-APPS | present |
| `identity-core` | `identity-core` | IDENTITY-CORE | present |
| `ios-no-cbom` | `ios-no-cbom` | IOS-NO_CBOM | retained, no data |
| `knex` | `knex` | KNEX | present |
| `landers` | `landers` | LANDERS | present |
| `metering` | `metering` | METERING | present |
| `on-prem-clients` | `on-prem-clients` | On Prem / Clients | added after baseline, no source data |
| `opc` | `opc` | OPC | present |
| `ovd-app-discovery` | `ovd-app-discovery` | OVD-APP-Discovery | present |
| `pac-cbom` | `pac-cbom` | PAC-cbom | present |
| `reporting` | `reporting` | REPORTING | present |
| `rsm-secure-client-no-cbom` | `rsm-secure-client-no-cbom` | RSM-SECURE_CLIENT-NO_CBOM | retained, no data |
| `saasapi` | `saasapi` | SAASAPI | present |
| `scc-backend` | `scc-backend` | SCC-Backend | present |
| `sfcn-firewall` | `sfcn-firewall` | SFCN-FIREWALL | present |
| `sfcn-ravpn` | `sfcn-ravpn` | SFCN-RAVPN | present |
| `swg-proxy` | `swg-proxy` | SWG-PROXY | present |
| `swg-roaming-client-no-cbom` | `swg-roaming-client-no-cbom` | SWG-ROAMING-CLIENT-NO_CBOM | retained, no data |
| `taac-cbom` | `taac-cbom` | TAAC-cbom | present |
| `unified-policy` | `unified-policy` | UNIFIED-POLICY | present |
| `va` | `va` | VA | present |
| `zta-bap` | `zta-bap` | ZTA-BAP | present |
| `zta-calp` | `zta-calp` | ZTA-CALP | present |

`APIX` is intentionally mapped to API key `apix-no-cbom` by the catalog alias
registry despite having two files in the 2026-09-18 baseline. The table includes
the retained
`on-prem-clients` category, which is absent from the 2026-09-18 historical
inventory baseline. The five retained no-data categories are
included in the configured grants at the owner's request. Their pages must say
"no source evidence observed" and must not imply an absence of crypto risk.
`fedsse-scr2-leads` remains a summary-only exception and is not a service row.

The enabled product-scoped catalog-detail routes use the audited current-file
routing decisions. Verify the literal group strings emitted in the signed
MyID `groups` claim after the `fedsse-` filter change, then review the generated
CDK policy and test disjoint lead, engineer, external, SCR2, and admin sessions.
The routing backfill is applied under the scope and data-boundary controls in
[DUAL_ATO_SCOPE_PLAN.md](DUAL_ATO_SCOPE_PLAN.md). Query `app_auth` for current
operational state. Access-control work does not change source or planning
evidence.
