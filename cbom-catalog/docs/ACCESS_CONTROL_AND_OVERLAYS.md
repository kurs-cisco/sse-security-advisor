# Application access, API credentials, and overlays

CBOM Workbench uses two authentication paths in cloud mode. Interactive users
enter through `https://cbom.swg.dev-umbrellagov.com`, where the application ALB
performs OIDC authentication. Automation uses bearer credentials only at
`https://api.cbom.swg.dev-umbrellagov.com`. PostgreSQL has no public endpoint.

## Users and roles

Application identities live in the private `app_auth` schema and are separate
from the imported evidence catalog. A verified OIDC issuer and subject become
the stable identity; email is used only to match an invitation on first login.
The stored application role is `viewer` or `admin`; it is not by itself a
cloud-data entitlement.

Cloud browser access is derived from the exact verified `fedsse-` group policy
and the selected verified mode:

- `admin` has portfolio and Administrator access.
- `summary` has aggregate Overview and POA&M access only.
- `product_lead` and `product_engineer` have only their exact
  `(source_collection, service_group, product_scope_id)` grants; Engineer is
  read only.

Candidate assessments and exports require their separate assessment-contract
gate even for an exact product grant. `invited` becomes `active` when the
matching verified OIDC identity first signs in. Disabled identities fail closed.

The ALB requests `openid email groups`; only the signature-verified `groups`
claim is authorized. Group matching is exact and case-sensitive. A custom MyID
`memberships` claim, stored historical role, or roster row cannot confer cloud
access. `fedsse-admins` takes precedence when a verified claim contains more
than one recognized mode.

Migration 012 bootstraps the initial invited administrator. The invitation does
not contain a password and cannot be claimed without the IdP's signed email
claim. An administrator cannot demote or disable their own active account
through the API.

## API credentials

The administrator workspace displays each credential exactly once at creation.
The database stores an HMAC-SHA-256 digest, never the bearer value. The HMAC
pepper is generated and retained in AWS Secrets Manager. Credentials are bound
to an active administrator, expire in at most 90 days, can be revoked, and use
least-privilege scopes.

Administrative ingestion adds two scopes. `ingestion:read` lists batches and
reports status; `ingestion:write` creates checksum manifests, issues private
presigned uploads, and submits ECS jobs. Both require a credential owned by an
active administrator. The internal viewer/service bearer cannot invoke them.

Example read:

```bash
curl -H "Authorization: Bearer $CBOM_API_TOKEN" \
  https://api.cbom.swg.dev-umbrellagov.com/api/v1/stats
```

Never put a credential in source control, screenshots, shell history, URLs, or
support tickets. Revoke verification credentials after testing.

## Immutable evidence and editable overlays

Source documents, normalized records, source fingerprints, and source SHA-256
values remain immutable. An edit creates a new `app_auth.admin_overlay` version
for a stable resource key. The prior overlay becomes inactive but remains in
history. Each change records its actor, rationale, before/after state, request
ID, and timestamp in `app_auth.audit_event`.

Supported overlays cover service-group ownership and IL2/IL5 dates, POA&M
candidate ownership and mitigation date, and reviewed annotations. They do not
turn candidate findings into assessor conclusions, prove CMVP validation, or
authorize POA&M closure.

Active POA&M candidate overlays are applied consistently to API responses, the
candidate CSV export, and the candidate member of the compliance ZIP. The
underlying assessment evidence, workstream grouping, and source hashes remain
unchanged.

The administrator page does not expose a standalone `admin_overlay` editor.
Those overlay writes use the authenticated API. Service Catalog metadata uses
the separate managed-revision workflow below.

Service Catalog metadata is edited contextually in the Service Catalog:
Administrators may publish managed metadata, while Product Leads can submit an
exact-scope proposal for a separate Administrator to approve or reject with a
reason. Product Engineers cannot write. Each published change records an
optimistic revision, a JSON-safe snapshot with ISO date and time values, actor,
rationale, request ID, and before/after state. An approved intentional clear is
distinct from an unchanged imported field.

Shareable database snapshots explicitly exclude `app_auth`; they therefore do
not distribute identities, credential digests, overlays, or access audit data.
Apply migrations after restore and bootstrap administrators separately for the
receiving environment.
