# Cloud authentication and AWS deployment assessment

This document records the read-only AWS assessment performed on 2026-09-18 and
the deployment boundary for CBOM Workbench. It intentionally contains no OIDC
client secret, database password, bearer token, or source inventory payload.

## Authentication modes

The Next.js console supports three explicit modes:

| Mode | Intended use | Behavior |
| --- | --- | --- |
| `dev` | local development only | Presents a single click-through login and sets an eight-hour, HTTP-only, SameSite cookie. Production blocks this mode unless the operator explicitly sets `CBOM_ALLOW_INSECURE_DEV_AUTH=true`. Do not set that override in AWS. |
| `alb-oidc` | any cloud environment, including dev | Requires and cryptographically verifies the ALB-signed `x-amzn-oidc-data` JWT. Verification checks ES256, expiry, client ID, expected ALB ARN, and the GovCloud regional ALB public key. |
| `disabled` | tests or local diagnostics only | Allowed outside production. Production fails closed. |

The public health endpoint is `/healthz`. The login page and local login action
are the only other unauthenticated application routes. The FastAPI service is a
separate trust boundary: in cloud mode it must use `CBOM_API_AUTH_MODE=bearer`
with a random token of at least 32 characters shared only with the Next.js
server. The API and PostgreSQL must not have public listeners.

The OIDC discovery configuration in the workspace resolves to an authorization
code provider supporting `openid` and `groups`. Configure the IdP callback as:

```text
https://<cbom-hostname>/oauth2/idpresponse
```

Runtime settings for the web workload:

```text
CBOM_AUTH_MODE=alb-oidc
CBOM_ALB_ARN=<the dedicated CBOM ALB ARN>
CBOM_OIDC_CLIENT_ID=<client ID from OIDC.md>
```

Store the OIDC client secret under the deployment-defined
`AUTH_KEYCLOAK_SECRET` key in AWS Secrets Manager. Never place it in an image,
Kubernetes manifest, shell history, `.env` file committed to source, or load
balancer annotation. Rotate the previously documented secret before cloud use,
as required by `OIDC.md`.

AWS requires a public-DNS OIDC provider, trusted TLS certificates, IPv4 access
from the ALB to the token and user-info endpoints, and an HTTPS listener. The
listener rule should run `authenticate-oidc` with `OnUnauthenticatedRequest` set
to `authenticate`, then forward to the web target group. Use a unique session
cookie such as `CBOMAWSELBAuthSessionCookie` and a suitably short dev session.

## Read-only AWS inventory assessment

The default CLI identity could read account `135124134289` in GovCloud region
`us-gov-east-1`. No AWS resources were created, changed, or deleted.

| Existing asset | Observation | Reuse decision |
| --- | --- | --- |
| Route 53 zone `swg.dev-umbrellagov.com` | Existing public hosted zone contains the NOTA alias. | Reuse the zone; create a distinct `cbom.swg.dev-umbrellagov.com` alias. Do not change the NOTA record. |
| NOTA ALB `k8s-nota-017e777ef9` | Active, internet-facing, owned by AWS Load Balancer Controller for EKS cluster `swg-dev-1a`; its HTTPS rule forwards directly and currently has no OIDC action. | Do not manually edit or share the controller-owned NOTA rule. Create a dedicated CBOM Ingress/ALB so reconciliation and outages remain isolated. |
| NOTA ACM certificate | Covers exactly `nota.swg.dev-umbrellagov.com`, not a wildcard. | Cannot secure the proposed CBOM hostname. Request a new ACM certificate validated through the reusable hosted zone. |
| EKS cluster `swg-dev-1a` | Active Kubernetes 1.34, private API endpoint, all control-plane log types enabled, in VPC `vpc-0ea02619196158906`. | Reusable with a dedicated namespace, service accounts, network policies, secrets, and Ingress. Deployment automation must run from a network that can reach the private endpoint. |
| EKS VPC/subnets | Three private data-plane subnets are already associated with the cluster. | Reuse after capacity, route, NAT, and security-group review. A new ALB may use the tagged public ingress subnets. |
| NOTA ECR repositories | Separate AES-256 repositories with scan-on-push. | Reuse the registry/account pattern, not the repositories. Create isolated `cbom-workbench/web`, `cbom-workbench/api`, and optionally `cbom-workbench/ingest` repositories. |
| Existing PostgreSQL RDS | PostgreSQL 14.19 instance belongs to TAAC and is in VPC `vpc-08b420570f2cb5276`, not the NOTA/EKS VPC. Local CBOM uses PostgreSQL 16. | Do not reuse. Provision a private, encrypted PostgreSQL 16 database in the workload VPC with its own subnet group, security group, credentials, backups, and ownership boundary. |

Recommended cloud-dev layout:

```text
Route 53 cbom alias -> dedicated HTTPS ALB + OIDC -> Next.js web
                                                    -> private FastAPI service
                                                    -> private PostgreSQL 16 RDS
```

Only the web service receives traffic from the ALB. Restrict web ingress to the
ALB security group, API ingress to the web workload, and database ingress to the
API/ingest workloads. This restriction is required even though the application
verifies the ALB signature. Enable ALB access logs, WAF as required by the
system boundary, container logs, RDS encryption/backups, and CloudWatch alarms.

If EKS Ingress is used, the AWS Load Balancer Controller expects the OIDC client
ID and client secret in a Kubernetes Secret in the same namespace. Populate that
Secret from AWS Secrets Manager using the approved secrets integration; do not
commit the Secret. A separate ALB managed outside the controller may instead use
a Secrets Manager dynamic reference in CloudFormation.

## Database snapshot and restore

The local PostgreSQL database is the authoritative normalized snapshot and
already includes source SHA-256 fingerprints. Export it from `cbom-catalog/`:

```bash
./scripts/export_db_snapshot.sh /secure/path/cbom-catalog.dump
```

This produces a PostgreSQL custom-format dump, a companion `.sha256` file, and
a `.manifest.json` containing migrations, latest ingest metadata, and acceptance
counts; all are mode `0600`. Upload the three-file bundle to a private,
versioned, KMS-encrypted S3 bucket over TLS. Do not use the source-data bucket
as a public distribution surface.

Restore only into a newly created, empty PostgreSQL 16 database from a one-shot
job that has network access to RDS:

```bash
DATABASE_URL='postgresql://user:password@private-rds:5432/cbom_catalog' \
  ./scripts/restore_db_snapshot.sh /secure/path/cbom-catalog.dump
```

The restore script verifies SHA-256 and refuses a database containing any user
tables. After restore, compare its printed counts with the manifest, run API
health checks, and compare document, artifact,
component, service-group, finding, and POA&M counts with the local source before
changing DNS. Keep the old database untouched until acceptance completes.
The full procedure is in [DATABASE_SNAPSHOTS.md](DATABASE_SNAPSHOTS.md).

## Deployment gate

Actual deployment is intentionally not performed by this assessment. Creating
the hostname, ACM certificate, ALB, ECR repositories, secrets, RDS instance,
Kubernetes resources, or restoring data changes externally shared and billable
infrastructure. Apply those changes only after approving the hostname and the
recommended dedicated-ALB/dedicated-database topology.
