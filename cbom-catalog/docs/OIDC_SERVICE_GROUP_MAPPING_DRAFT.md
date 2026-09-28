# Draft MyID service groups

See the [dual product scope implementation plan](DUAL_ATO_SCOPE_PLAN.md) for
the three-part authorization key, evidence attribution gate, and rollout order.

**Deployed read-only catalog detail.** The exact 40 service identities are in
`infra/lib/oidc-service-groups.ts`. The deployment policy generates two product
grants for each exact `(source_collection, service_group)` pair. Evidence routing
and migrations 016–021 are applied and verified in GovCloud development. The
deployed API recognizes exact service claims, exposes verified grant metadata,
and returns read-only catalog detail only when the exact collection, service
group, product context, and current-file routing all match. Candidates, exports,
observations, roster actions, notes, proposals, and other operational writes
remain disabled or fail closed. Migration 021 introduces
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

For every approved row below, the two proposed exact MyID names are
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
labels; the configured policy identifiers route access metadata only. They are not immutable
package identifiers or proof of authorization. All 534 current source files
have exact-SHA default-both operational routing decisions. Every service grant
is available as profile and grant metadata, and can render read-only,
product-filtered catalog detail through the exact-triple gate. This does not
enable FIPS detail, candidate output, exports, observations, roster actions,
notes, proposals, or any operational write.

| MyID stem | API `service_group` | Catalog display | Source status | Owner-declared product context |
| --- | --- | --- | --- | --- |
| `adc` | `adc` | ADC | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `android-no-cbom` | `android-no-cbom` | ANDROID-NO_CBOM | retained, no data | no source evidence; exact-triple read-only catalog detail enabled |
| `apix` | `apix-no-cbom` | APIX | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `app-control` | `app-control` | App-Control | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `avengers` | `avengers` | Avengers | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `brain` | `brain` | BRAIN | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `cnhe` | `cnhe` | CNHE | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `contraast` | `contraast` | CONTRAAST | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `data-platform` | `data-platform` | DATA-PLATFORM | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `discovery` | `discovery` | Discovery | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `disthost` | `disthost` | DISTHOST | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `dlp` | `dlp` | DLP | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `dns-platform` | `dns-platform` | DNS-PLATFORM | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `download-service` | `download-service` | Download Service | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `dw-volt` | `dw-volt` | DW_VOLT | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `fis-sma-threatgrid` | `fis-sma-threatgrid` | FIS/SMA Threatgrid | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `frouter` | `frouter` | FROUTER | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `identity-apps` | `identity-apps` | IDENTITY-APPS | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `identity-core` | `identity-core` | IDENTITY-CORE | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `ios-no-cbom` | `ios-no-cbom` | IOS-NO_CBOM | retained, no data | no source evidence; exact-triple read-only catalog detail enabled |
| `knex` | `knex` | KNEX | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `landers` | `landers` | LANDERS | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `metering` | `metering` | METERING | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `on-prem-clients` | `on-prem-clients` | On Prem / Clients | retained, no data | no source evidence; exact-triple read-only catalog detail enabled |
| `opc` | `opc` | OPC | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `ovd-app-discovery` | `ovd-app-discovery` | OVD-APP-Discovery | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `pac-cbom` | `pac-cbom` | PAC-cbom | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `reporting` | `reporting` | REPORTING | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `rsm-secure-client-no-cbom` | `rsm-secure-client-no-cbom` | RSM-SECURE_CLIENT-NO_CBOM | retained, no data | no source evidence; exact-triple read-only catalog detail enabled |
| `saasapi` | `saasapi` | SAASAPI | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `scc-backend` | `scc-backend` | SCC-Backend | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `sfcn-firewall` | `sfcn-firewall` | SFCN-FIREWALL | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `sfcn-ravpn` | `sfcn-ravpn` | SFCN-RAVPN | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `swg-proxy` | `swg-proxy` | SWG-PROXY | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `swg-roaming-client-no-cbom` | `swg-roaming-client-no-cbom` | SWG-ROAMING-CLIENT-NO_CBOM | retained, no data | no source evidence; exact-triple read-only catalog detail enabled |
| `taac-cbom` | `taac-cbom` | TAAC-cbom | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `unified-policy` | `unified-policy` | UNIFIED-POLICY | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `va` | `va` | VA | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `zta-bap` | `zta-bap` | ZTA-BAP | present | current files routed to both; exact-triple read-only catalog detail enabled |
| `zta-calp` | `zta-calp` | ZTA-CALP | present | current files routed to both; exact-triple read-only catalog detail enabled |

`APIX` is intentionally mapped to API key `apix-no-cbom` by the catalog alias
registry despite having two current files. The table includes the retained
`on-prem-clients` category, which is absent from the older
`docs/service-groups.csv` inventory. The five retained no-data categories are
included in the staged grants at the owner's request. Their pages must say
"no source evidence observed" and must not imply an absence of crypto risk.
`fedsse-scr2-leads` remains a summary-only exception and is not a service row.

The enabled product-scoped catalog-detail routes use the audited current-file
routing decisions. Verify the literal group strings emitted in the signed
MyID `groups` claim after the `fedsse-` filter change, then review the generated
CDK policy and test disjoint lead, engineer, external, SCR2, and admin sessions.
Migrations 016–020 and the routing backfill are applied and verified live; see
the [routing change record](CHANGE_RECORD_2026-09-26_DUAL_PRODUCT_ROUTING.md)
and [operational-access schema change record](CHANGE_RECORD_2026-09-26_OPERATIONAL_ACCESS_SCHEMA.md).
The proposal, roster, and observation tables contain no records, and
source/planning evidence was not changed.
