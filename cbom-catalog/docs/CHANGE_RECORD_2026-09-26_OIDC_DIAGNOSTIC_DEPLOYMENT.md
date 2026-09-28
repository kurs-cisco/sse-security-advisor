# OIDC diagnostic deployment change record

On 2026-09-26, after owner approval, the staged API and console images were
deployed to the GovCloud development stack `cbom-workbench-dev` in account
`135124134289`, region `us-gov-east-1`. This was an application release and
claim diagnostic, not service-grant activation or source ingestion.

| Item | Deployed value |
| --- | --- |
| Catalog image | `deploy-20260926-1`, `sha256:0b05ae6cb5536a4bc322526cdf729a68419ad34d237465c45840238a7a7de74b` |
| Web image | `deploy-20260926-1`, `sha256:8bd3ca770bae4fa09cf8d937398a5f6a76efac78f5ba8abc4d64c7c97fe5fe3c` |
| CloudFormation template SHA-256 | `6034ba6aae54928980a5be18958d385647dbfc2062ea2a9a32289493ae43c799` |
| ECS web task definition | `cbom-workbench-web:17` (previous: `:16`) |
| Diagnostic | Enabled in both API and web; expires `2026-09-26T12:45:00Z` |
| Service groups, product detail, roster actions, evidence notes | All disabled |

The reviewed CDK diff changed only the ECS web and job task definitions: the
new immutable image tags, exact three-global-group policy, matching diagnostic
settings, and disabled capability flags. The initial `cdk deploy` stopped
before any stack update because its GovCloud bootstrap execution role could
not be assumed. The same synthesized template was then deployed through the
repository's direct CloudFormation path. CloudFormation reached
`UPDATE_COMPLETE`; ECS revision 17 became stable, both API and web containers
and both ALB targets were healthy, and public `/healthz` returned 200.

The API startup log skipped migrations 001–020 as already applied. No one-off
ingestion or import job was started for this release. The signed-in live
Overview still reports 40 service groups, 534 source files, 534 current
fingerprints, and zero ingest errors. Its summary and POA&M APIs return
aggregate counts only; candidate findings and deduplicated POA&M candidates
are zero pending the independent assessment verifier.

The first live signed session for the owner resolved to the exact matched
group `fedsse-scr2-leads`, effective role `summary`, zero service grants, and
no admin capability. The administrator-only diagnostic returned 403, as
designed. The same session saw only Overview and POA&M navigation. Direct
Inventory, Accountability, Reviews, and Admin pages showed access gates;
representative product-status, admin, review, operational-note, detailed
dashboard, and FIPS assessment APIs each returned 403. This is a **no-go for
service-grant activation** until MyID emits exact `fedsse-admins` in a fresh
signed OIDC session and the remaining role matrix passes. No raw token,
subject, cookie, or full claim response is recorded here.

Read-only inspection of the owner-supplied MyID SSO configuration confirmed
the `groups` scope and a `STARTS_WITH fedsse-` group-claim filter. MyID Groups
lists the exact `fedsse-admins` group and the owner as a member. A separate,
clean Chrome session then completed a new CBOM OIDC redirect and produced the
same summary-only policy fingerprint and matched group. The API policy already
gives `fedsse-admins` priority over `fedsse-scr2-leads` when both exact strings
arrive; the missing admin access is upstream of that priority decision. MyID
SSO claim emission or synchronization needs verification before retrying.

The diagnostic must be disabled by deploying the same images with
`enableOidcDiagnostic=false` after the restricted claim review, or when this
bounded attempt ends. Its expiry also makes the route stop serving claims
without a redeployment. Preserve the disabled service-access flags during
that change.

## Repeat read-only verification at 17:24 UTC

A new in-memory Chrome profile completed MyID Groups sign-in and opened the
exact `fedsse-admins` group. The directory showed two members, including the
owner's `kurs@cisco.com` identity. In the same clean profile, a new CBOM OIDC
redirect completed. `/api/v1/auth/me` again reported only
`matched_groups=["fedsse-scr2-leads"]`, effective role `summary`, zero grants,
and the same policy fingerprint recorded earlier. A fresh read of the **Stage**
MyID OIDC application showed the `groups` scope with a `STARTS_WITH fedsse-`
claim filter. The expired diagnostic returned 404 with `Cache-Control:
no-store` and did not reveal raw claims. This repeat check confirms directory
membership and application claim delivery are currently different; it does
not authorize changing CBOM's exact-group policy or activating service access.

After this verification, the expired diagnostic was explicitly disabled with
the same image tag and all service-access flags still false. The reviewed CDK
diff changed only the matching diagnostic flag and expiry values in the API
and web task environments. Direct CloudFormation deployment reached
`UPDATE_COMPLETE`; ECS web task definition `cbom-workbench-web:18` reached a
completed rollout, `/healthz` returned 200, and the signed browser received
404 with `Cache-Control: no-store` from the diagnostic route.

## 2026-09-27 direct MyID UserInfo comparison

After the Stage SSO application's `groups` selector was changed to `All`,
three new Duo sessions still matched only `fedsse-scr2-leads` in CBOM. MyID
Groups separately continued to list the owner as a direct member of the exact
`fedsse-admins` directory group. Directory membership alone did not establish
that the OIDC application released that group.

At 04:03 UTC, a fresh Duo session used a temporary, self-only diagnostic in
web image `diag-20260927-1` (ECR digest
`sha256:7a547610cc516af93a159cf8ff715c20dd1176e020bb9fc6001c9502b78ed6ee`,
ECS task definition `cbom-workbench-web:19`). The web container called the
fixed MyID UserInfo endpoint directly with the access token forwarded by the
ALB, required its subject to match the signature-verified ALB identity, and
returned only exact-group booleans and claim types. Its separate enablement
expired at `2026-09-27T05:00:00Z`; the raw-claims diagnostic and all service
access capability flags stayed disabled.

| Same-session source | Claim type | `fedsse-admins` present | `fedsse-scr2-leads` present |
| --- | --- | --- | --- |
| Direct MyID UserInfo | Array | No | Yes |
| Signature-verified ALB claims | Array | No | Yes |

The same browser session's `/api/v1/auth/me` resolved to `summary`, with no
service grants. The direct IdP response therefore lacks the exact admin group
before CBOM maps groups to permissions. The evidence points to MyID identity,
application assignment, claim release, or synchronization; it does not show a
CBOM group-priority defect. Keep the group-access rollout disabled until a new
direct UserInfo result contains exact `fedsse-admins` and a fresh CBOM session
resolves to admin. The `All` selector should return to the intended `fedsse-`
filter after MyID troubleshooting.

The service was then returned to task definition `cbom-workbench-web:18` with
the original API and web images. ECS reported one running task, zero pending
tasks, and its services-stable waiter completed. `/healthz` returned `ok`;
the temporary path no longer served the comparison and fell through to the
generic API scope denial. No ingestion, migration, source, planning,
assessment, POA&M, or other authoritative application data was changed. No
token, cookie, subject, email, or raw group list is recorded in this document.

## 2026-09-27 custom `memberships` scope test

The MyID Stage application had a custom scope named `memberships` with a claim
named `memberships`. Its configured group selector was `CONTAINS fedsee` as
observed in the application UI. The approved entitlement namespace is
`fedsse-`; those strings differ. The existing `groups` claim was still set to
`All`. A fresh login with the original ALB request, `openid email groups`,
again returned an array containing `fedsse-scr2-leads` but not
`fedsse-admins` from both direct MyID UserInfo and the signature-verified ALB
claim. The `memberships` claim was absent under that scope set.

For a bounded test of both claim names, web image `diag-20260927-2` (ECR digest
`sha256:3f0e7f1bd78d4d8fb39c3ea9b934e6a5117071935289465e3901e980638aa780`,
ECS task definition `cbom-workbench-web:20`) added a diagnostic-only
`memberships` comparison. It did not use that claim for authorization, and it
preserved the existing API image. The diagnostic expiry was
`2026-09-27T06:00:00Z`. Focused OIDC tests (16), console lint, typecheck,
production Docker build, and a same-session baseline browser check passed.

The dev ALB OIDC action temporarily requested
`openid email groups memberships`, preserving its issuer, endpoints, client,
cookie, timeout, forward target, and existing client secret. A clean Chrome
profile completed Duo authentication, but the ALB returned HTTP 500 at its
OIDC callback at 04:51:39 UTC. The filtered ALB access log recorded
`AuthUserinfoResponseSizeExceeded`; the request did not reach CBOM.
[AWS documents this error](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-access-logs.html)
as an IdP UserInfo claim response exceeding the ALB's 11 KB limit. The test
therefore cannot establish which `memberships` values were returned or whether
`fedsse-admins` was among them.

The ALB action was immediately restored to `openid email groups` and the web
service was returned to task definition `cbom-workbench-web:18`. A fresh
normal-scope Chrome sign-in succeeded and `/api/v1/auth/me` again resolved to
summary with `fedsse-scr2-leads`; `/healthz` returned 200. The listener rule
retained its original action order and target, and CloudFormation resource
drift detection reported `IN_SYNC` at 04:57:01 UTC. The source diagnostic is
not served by the restored web image. No authoritative corpus, assessment,
POA&M, planning, or application data was modified.

Before another live test, narrow the MyID `groups` claim from `All` to the
available `STARTS_WITH` operator with value `fedsse-` (or an equivalent exact
entitlement allowlist).
Correct the separate `memberships` filter if that custom scope remains in use,
but do not request a broad or duplicate membership claim through this ALB.
After an approved MyID configuration change, use a fresh OIDC session to
confirm that UserInfo fits the ALB limit and contains the exact
`fedsse-admins` value in the `groups` claim CBOM consumes. This failed
dual-scope test gives no basis for changing CBOM's authorization mapping or
enabling service grants.
