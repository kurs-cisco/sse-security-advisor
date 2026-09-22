# CBOM Workbench AWS infrastructure

This CDK application deploys the cloud-development environment to ECS Fargate
in `us-gov-east-1`. It imports the existing VPC and Route 53 hosted zone but
does not use or modify the NOTA EKS workloads, ALB, certificate, or database.

The account service-control policy denies creation of private Route 53 hosted
zones. Next.js and FastAPI therefore run as separate containers in one Fargate
task and communicate over `127.0.0.1`; FastAPI has no load-balancer target or
public listener.

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
6. verify the OIDC redirect/login, all application views, exports, target
   health, and CloudWatch logs before declaring the environment ready.

The default HTTPS action returns `503` until OIDC is enabled. Only `/healthz`
is forwarded without authentication. The API and RDS instance remain private.

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

For the reviewed September 21 release, `deploy-latest.sh` verifies the three
source/evidence SHA-256 values, uploads them only to the private encrypted CBOM
bucket, applies migrations 009–011, runs the checksum-gated imports, deploys the
OIDC/DNS/ECS change, and waits for ECS stability. Run it from an authenticated
shell only after approving those specific data transfers:

```bash
./deploy-latest.sh
```

If CloudFormation is already stuck in `UPDATE_IN_PROGRESS` because an earlier
web task used the loopback ECS health probe, use the recovery wrapper instead.
It cancels only that in-progress stack update, waits for the prior stable state,
and then invokes the same checksum-gated deployment:

```bash
./recover-and-deploy-latest.sh
```

The corrected task definition probes the hostname to which the standalone
Next.js server binds inside Fargate. The public ALB health route remains
`/healthz` and bypasses OIDC only for health monitoring.

The GovCloud Fargate environment rejected ARM64 task definitions, so deployment
images and task definitions use `linux/amd64`.

Never place the OIDC client secret, database dump, or generated database
credentials in this directory or in CDK context files.
