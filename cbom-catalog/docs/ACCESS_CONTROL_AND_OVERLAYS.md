# Application access, API credentials, and overlays

CBOM Workbench uses two authentication paths in cloud mode. Interactive users
enter through `https://cbom.swg.dev-umbrellagov.com`, where the application ALB
performs OIDC authentication. Automation uses bearer credentials only at
`https://api.cbom.swg.dev-umbrellagov.com`. PostgreSQL has no public endpoint.

## Users and roles

Application identities live in the private `app_auth` schema and are separate
from the imported evidence catalog. A verified OIDC issuer and subject become
the stable identity; email is used only to match an invitation on first login.

- `viewer` can browse the catalog and candidate assessments.
- `admin` can manage users, issue or revoke scoped API credentials, and create
  versioned administrative overlays.
- `invited` becomes `active` when the matching verified OIDC identity first
  signs in. Disabled identities fail closed.

Migration 012 bootstraps `kurs@cisco.com` as an invited administrator. The
invitation does not contain a password and cannot be claimed without the IdP's
signed email claim. An administrator cannot demote or disable their own active
account through the API.

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

The administrator page does not expose a standalone overlay editor. Overlay
editing can be added later as contextual inline actions on the relevant tables
and entity detail views; until then, the authenticated API remains the only
overlay-writing surface.

Shareable database snapshots explicitly exclude `app_auth`; they therefore do
not distribute identities, credential digests, overlays, or access audit data.
Apply migrations after restore and bootstrap administrators separately for the
receiving environment.
