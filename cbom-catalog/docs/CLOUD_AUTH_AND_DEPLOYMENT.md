# Cloud authentication and AWS deployment assessment

This document records the AWS assessment performed on 2026-09-18 and the staged
ECS deployment performed on 2026-09-22. It intentionally contains no OIDC
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
server for browser traffic. A separate host-authenticated ALB rule exposes
`api.cbom.swg.dev-umbrellagov.com` to FastAPI for application-issued scoped
credentials. It returns `401` without a credential and never accepts the OIDC
browser cookie. PostgreSQL has no public listener.

The OIDC discovery configuration in the workspace resolves to an authorization
code provider. The deployed rule requests `openid email groups` so an invited
email can be bound to the verified issuer and subject. Configure the callback as:

```text
https://<cbom-hostname>/oauth2/idpresponse
```

Runtime settings for the web workload:

```text
CBOM_AUTH_MODE=alb-oidc
CBOM_ALB_ARN=<the dedicated CBOM ALB ARN>
CBOM_OIDC_CLIENT_ID=<client ID from OIDC.md>
```

Store the rotated OIDC client secret in AWS Secrets Manager at
`/cbom-workbench/dev/oidc-client-secret`. Never place it in an image,
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
`us-gov-east-1`. The table below preserves the pre-deployment observations that
informed the isolated ECS design; it is not a statement of current stack state.

| Existing asset | Observation | Reuse decision |
| --- | --- | --- |
| Route 53 zone `swg.dev-umbrellagov.com` | Existing public hosted zone contains the NOTA alias. | Reuse the zone; create a distinct `cbom.swg.dev-umbrellagov.com` alias. Do not change the NOTA record. |
| NOTA ALB `k8s-nota-017e777ef9` | Active, internet-facing, owned by AWS Load Balancer Controller for EKS cluster `swg-dev-1a`; its HTTPS rule forwards directly and currently has no OIDC action. | Do not manually edit or share the controller-owned NOTA rule. A dedicated CBOM ALB was created so reconciliation and outages remain isolated. |
| NOTA ACM certificate | Covers exactly `nota.swg.dev-umbrellagov.com`, not a wildcard. | Cannot secure the proposed CBOM hostname. Request a new ACM certificate validated through the reusable hosted zone. |
| EKS cluster `swg-dev-1a` | Active Kubernetes 1.34, private API endpoint, all control-plane log types enabled, in VPC `vpc-0ea02619196158906`. | Not reused. The approved design uses ECS Fargate and leaves the NOTA cluster untouched. |
| VPC/subnets | Public ingress and private NAT subnets exist in the selected VPC. | Reused for a dedicated CBOM ALB and private ECS/RDS placement after route and security-group review. |
| NOTA ECR repositories | Separate AES-256 repositories with scan-on-push. | Reuse the registry/account pattern, not the repositories. Isolated `cbom-workbench/web` and `cbom-workbench/catalog` repositories were created. |
| Existing PostgreSQL RDS | PostgreSQL 14.19 instance belongs to TAAC and is in VPC `vpc-08b420570f2cb5276`, not the NOTA/EKS VPC. Local CBOM uses PostgreSQL 16. | Do not reuse. Provision a private, encrypted PostgreSQL 16 database in the workload VPC with its own subnet group, security group, credentials, backups, and ownership boundary. |

Deployed cloud-dev layout:

```text
Route 53 cbom alias ----> HTTPS ALB + OIDC ----> Next.js :3000 --internal bearer--+
Route 53 api.cbom alias -> HTTPS ALB + API token -> FastAPI :8000 <-------------+
                                                        |
                                                        +-> private PostgreSQL 16 RDS
```

The ALB reaches Next.js only on port 3000 and FastAPI only on port 8000. The
browser path uses a generated internal bearer token shared through Secrets
Manager; the API hostname accepts separately generated, scoped and expiring
application credentials whose plaintext is never stored. RDS permits PostgreSQL
only from the task and restore-job security groups. The deployment uses ECS
Fargate rather than EKS and does not modify the
NOTA cluster, controller-owned ALB, certificate, database, or DNS record. WAF is
not part of this approved dev deployment; add it only if the system boundary or
organizational policy requires it.

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

## Current deployment status

The `cbom-workbench-dev` CloudFormation stack is deployed in account
`135124134289`, region `us-gov-east-1`, with termination protection enabled.
The ECS service is active at desired/running count 1 on an immutable
`deploy-20260922-8` image tag. Both targets are healthy, `/healthz` returns 200,
and unauthenticated application requests redirect to the configured OIDC
provider.

The encrypted snapshot was restored after SHA-256 verification. The canonical
manifest/API metrics are 39 service groups, 534 present source files, 533
unique present documents, 341 artifacts, 59,263 unique components, 282,688
component occurrences, and 609 fingerprint records. Raw `COPY` counts printed
by `pg_restore` are table-row counts and must not be compared directly with
these deduplicated API metrics.

The September 22 service-impact planning import is checksum-gated at
`5c481b5941d081b537c8f88805b78820fddfbe8d42af6bc9138d2dedce055ecc`.
It contributes only POA&M impact, risk category, and comments for 20 team rows
mapped to 22 service groups. The source remains a private transfer object and is
not committed to Git; owner, lead, CBOM flags, IL2, and IL5 are not imported.

The application hostname is `https://cbom.swg.dev-umbrellagov.com/`; the scoped
automation endpoint is `https://api.cbom.swg.dev-umbrellagov.com/`. The IdP
callback is:

```text
https://cbom.swg.dev-umbrellagov.com/oauth2/idpresponse
```

The API hostname fails closed without a valid scoped application credential.
Do not disable OIDC, disclose credentials, or add a path that bypasses scope
enforcement. See [ACCESS_CONTROL_AND_OVERLAYS.md](ACCESS_CONTROL_AND_OVERLAYS.md).
