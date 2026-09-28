# CBOM Workbench AWS infrastructure

This CDK application deploys the cloud-development environment to ECS Fargate
in `us-gov-east-1`. It imports the existing VPC and Route 53 hosted zone but
does not use or modify the NOTA EKS workloads, ALB, certificate, or database.

The account service-control policy denies creation of private Route 53 hosted
zones. Next.js and FastAPI run as separate containers in one Fargate task and
communicate over `127.0.0.1`. The application hostname reaches Next.js only
after ALB OIDC. The dedicated `api.cbom.swg.dev-umbrellagov.com` hostname
reaches FastAPI through a separate target group and accepts only scoped,
application-issued bearer credentials.

FastAPI can issue checksum-bound presigned uploads under
`transfer/ingestion/` and launch the existing one-off Fargate job definition.
Its task role is limited to that S3 prefix, the specific job task definition,
cluster, and pass-role targets. The job role remains read-only on `transfer/`.
Raw corpus objects expire under the temporary-transfer lifecycle and are neither
proxied through FastAPI nor stored in Git.

The stack applies a narrow S3 CORS rule allowing `PUT` only from the configured
application hostname with the content-type and checksum headers required by the
presigned request. The application task may read only the `job/job/*` streams in
the ingestion log group so Admin can display task output without exposing AWS
credentials to the browser.

`reuseRetainedBootstrapResources=true` imports the encrypted bucket, ECR
repositories, generated API token, OIDC placeholder, and log groups retained by
the initial failed Cloud Map deployment. These resources were created from this
same template and remain isolated to CBOM Workbench.

Deployment is deliberately staged:

1. deploy the stack with `activateServices=false` and `enableOidc=false`;
2. build and push immutable `web` and `catalog` image tags;
3. upload and restore the checksummed database snapshot with the one-shot job;
4. register `https://cbom.swg.dev-umbrellagov.com/oauth2/idpresponse` as the
   IdP callback and populate `/cbom-workbench/dev/oidc-client-secret` with a
   rotated value;
5. set both `activateServices=true` and `enableOidc=true`, then deploy once to
   start the service, install the authenticated listener rule, and create DNS;
6. verify OIDC login and invitation binding, application views and exports,
   scoped API credential creation/revocation, temporary overlay rollback,
   target health, ALB access logs, and CloudWatch logs.

The default HTTPS action returns `503` until OIDC is enabled. Only `/healthz`
is forwarded without authentication. The API hostname is internet-routable but
fails closed without a valid scoped credential; RDS remains private.

The OIDC issuer and endpoints in `cdk.json` were verified against the public
discovery document on 2026-09-22. The client secret is intentionally absent.
Populate it without placing it in shell history:

```bash
read -s CBOM_OIDC_SECRET
aws secretsmanager put-secret-value \
  --region us-gov-east-1 \
  --secret-id /cbom-workbench/dev/oidc-client-secret \
  --secret-string "$CBOM_OIDC_SECRET"
unset CBOM_OIDC_SECRET
```

`deploy-latest.sh` transfers source evidence, applies migrations, and runs
checksum-gated imports. Run it only from an authenticated shell after approving
those specific data transfers:

```bash
./deploy-latest.sh
```

If CloudFormation is already stuck in `UPDATE_IN_PROGRESS`, use the recovery
wrapper. It cancels only that in-progress update, waits for the prior stable
state, and then invokes the same checksum-gated deployment:

```bash
./recover-and-deploy-latest.sh
```

The API sidecar health probe uses the task-local API listener. The public ALB
health route remains `/healthz` and bypasses OIDC only for health monitoring.

The GovCloud Fargate environment rejected ARM64 task definitions, so deployment
images and task definitions use `linux/amd64`.

Never place the OIDC client secret, application API credentials, database dump,
or generated database credentials in this directory or in CDK context files.

## Staged OIDC group access policy

The deployed product-detail stage uses policy version `2026-09-27.2` with 83
exact groups: `fedsse-admins`, `fedsse-external`, `fedsse-scr2-leads`, and 80
generated service lead and engineer groups. The latter two global groups grant
numeric portfolio summaries only. The stack rejects placeholder service/ATO
grants. The 40 explicit catalog pairs in `lib/oidc-service-groups.ts` generate
the 80 exact service names, each with two grants. The grants use the stable
policy IDs
`secure-access-government` and `secure-access-defense`, with display boundary
labels `FedRAMP High/IL2` and `IL5`. The same MyID service group grants both
product contexts. These are deployment policy identifiers and display labels;
they are not proof of authorization. All 534 current `sse-cboms` files have
owner-approved, exact-SHA operational routing decisions for both products;
see the [change record](../cbom-catalog/docs/CHANGE_RECORD_2026-09-26_DUAL_PRODUCT_ROUTING.md).
This stage sets `enableOidcServiceGroups=true`,
`enableAdminGroupMapping=true`, and
`enableProductScopedDetailEvidence=true`. A verified service Lead or Engineer
can read catalog evidence only through an exact
`(source_collection, service_group, product_scope_id)` grant; current-source
checksum attribution is required by the query itself. The feature does not
enable FIPS detail, candidate output or exports, approved writes, roster
actions, or operational evidence notes. FIPS routes independently require a
complete matching product contract and immutable authorization reference, so
they remain closed for the current configuration. Other products gain no access
through this map.

`enableAdminGroupMapping=true` enables the Administrator mapping registry in
migration 021. It starts from the synthesized 83-group deployment baseline and
then uses the first published Administrator revision as the application policy.
Every mapping revision is append-only. Publishing requires a signed human
`fedsse-admins` Administrator, a registered catalog target, one or both
configured product scope IDs, a reason, and the current revision token. The
transaction uses compare-and-swap semantics and records actor, request ID,
before/after mapping, and content hashes in `app_auth.audit_event`. The global
Admin and summary groups remain protected, API credentials cannot access this
endpoint, and a missing active revision after a prior publish denies cloud
group access. This editor changes application mapping only; it never modifies
MyID membership, source files, routing decisions, planning records, assessment
records, or ATO/CMVP facts.

Before enabling detail or writes, review a new policy version and synthesized
API policy, then complete the remaining gates in
`../cbom-catalog/docs/GROUP_ACCESS_ROLLOUT.md`.

Do not use `deploy-latest.sh` for an access-only release: it also applies
migrations and runs evidence ingestion. Review an explicit CDK change set.
Operational migrations, the existing-file routing backfill, and the Service
Catalog migrations are release-specific evidence recorded in
[`CHANGE_RECORD_2026-09-28_UI_UX_ROLLOUT.md`](../cbom-catalog/docs/CHANGE_RECORD_2026-09-28_UI_UX_ROLLOUT.md).
The earlier diagnostic-stage application release used the direct CloudFormation
path with all service-access switches disabled. Its temporary diagnostic code
has since been removed from source; see the
[change record](../cbom-catalog/docs/CHANGE_RECORD_2026-09-26_OIDC_DIAGNOSTIC_DEPLOYMENT.md).
Never treat those changes as approval for source ingestion,
planning/assessment changes, or detailed service evidence and write activation.
