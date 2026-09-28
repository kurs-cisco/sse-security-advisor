# Product-scoped catalog-detail activation — 2026-09-27

## Scope

Image `deploy-20260927-11` activates the existing
`CBOM_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED` application capability for the
GovCloud development deployment. It exposes read-only catalog evidence to a
signed Lead or Engineer only after the request names an exact verified
`(source_collection, service_group, product_scope_id)` grant. It does not
modify source files, user-authored planning, assessment records, POA&M records,
product-routing decisions, MyID membership, or the active Administrator group
mapping.

The evidence projection is default-deny. Each selected source file must be
present, have a current SHA-256, and have a latest append-only routing decision
for that same collection, service group, path, and checksum containing the
requested product scope. Changed, missing, legacy, and unassigned source files
do not appear. Direct document and component routes use the same scope
predicate.

## Deployment and signed verification

| Item | Recorded result |
| --- | --- |
| CloudFormation | `UPDATE_COMPLETE` |
| ECS web task | Revision 30 completed at 1/1 for initial activation; revision 31 completed at 1/1 for the tag13 follow-up |
| Product Lead session | `detail=true`; only DLP Government and Defense grants |
| Scoped catalog reads | 7 documents in each DLP product context; direct document ID 190 returned 200 in both contexts |
| Scope boundary | Unassigned service returned 403/404; Admin returned 403 in Product Lead mode |
| FIPS and candidate routes | FIPS detail, exports, and 20x preview returned 403 |
| Administrator mapping view after tag13 | HTTP 200; 40 rows, 534 current source files, and 5 zero-file groups, unchanged |

## Deployment delta

| Resource | Change |
| --- | --- |
| `WebTask` | Replacement to set `CBOM_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED=true` and use catalog/web image 11 |
| `JobTask` | Replacement to use catalog image 11 |
| `WebTaskTaskRoleDefaultPolicy` | Reference refresh because the policy constrains `ecs:RunTask` to the replacement `JobTask`; its permissions are unchanged |

No data store, subnet, security group, load balancer, OIDC configuration,
secret, source-routing decision, or IAM permission expansion is part of this
release.

## Tag13 UI and workflow follow-up

Image `deploy-20260927-13` reached CloudFormation `UPDATE_COMPLETE` and ECS
web task revision 31 at 1/1. It updates the product Lead review capability and
POA&M presentation without enabling a workflow or changing authoritative app
data. The API reports `review_proposals=true` only for an active human Product
Lead with an exact lead grant carrying an immutable authorization reference;
the UI still requires that capability and the per-scope reference before it
requests review history. The route independently validates the exact triple,
lead grant, and reference.

A clean signed Product Lead browser tab for both DLP Government and Defense
showed two verification-pending panels, zero UI console errors before
intentional API probes, no gated background requests in
`PerformanceResourceTiming`, and no export buttons. In that live session,
`/auth/me` returned `detail=true`, the two DLP grants, and
`review_proposals=false`. Deliberate probes returned: Lead and Engineer scoped
document reads 200 with total 7; unassigned documents 403; a wrong direct ID
404; FIPS and review proposals without the immutable reference 403; and an
Engineer Admin request 403.

The compliance review gate is **GO** for this evidence-only release: the
rendered controls match the server's default-deny scope and contract gates, and
the release makes no authorization, CMVP, FIPS, POA&M, or compliance conclusion.

Product routing and boundary display labels are not authorization, deployment,
CMVP, or FIPS evidence. Scoped FIPS routes additionally require a complete
product contract whose immutable authorization reference matches the verified
group-policy grant. The current release therefore keeps FIPS detail, candidate
POA&M output, exports, reportable 20x output, lead submissions, roster action,
and operational notes disabled. These remain separate from the enabled
evidence-only catalog view.

A single test identity with overlapping groups does not prove cross-user scope
isolation; that still needs two identities with disjoint service grants. The
signed test identity has no SaaS group grant, so SaaS scope rendering remains
unverified live.
