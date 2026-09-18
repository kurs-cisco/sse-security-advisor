# NOTA OIDC configuration

- Discovery URL: `https://sso-345c0691.sso.duosecurity.com/oidc/DIIYIKV2YSWCYEYECY3L/.well-known/openid-configuration`
- Client ID: `DIIYIKV2YSWCYEYECY3L`
- Client secret: supply through the deployment secret manager as `AUTH_KEYCLOAK_SECRET`; never store it in this repository.

The previously documented client secret must be rotated before this configuration is used outside local development.
