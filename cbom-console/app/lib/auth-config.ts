export const DEV_AUTH_COOKIE = "cbom-dev-auth";

export type AuthMode = "local-admin" | "alb-oidc" | "disabled";

export function authMode(): AuthMode {
  const configured = process.env.CBOM_AUTH_MODE?.trim().toLowerCase();
  if (configured === "local-admin" || configured === "alb-oidc" || configured === "disabled") {
    return configured;
  }
  if (configured) return "disabled";
  return process.env.NODE_ENV === "development" ? "local-admin" : "alb-oidc";
}

export function localAdminAllowed(hostname: string): boolean {
  const loopback = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);
  return authMode() === "local-admin"
    && process.env.CBOM_ENVIRONMENT?.trim().toLowerCase() === "local"
    && loopback.has(hostname.toLowerCase());
}

export function localAdminRequestAllowed(headers: Headers): boolean {
  const host = headers.get("host");
  if (!host) return false;
  try {
    return localAdminAllowed(new URL(`http://${host}`).hostname);
  } catch {
    return false;
  }
}

export function safeReturnTo(candidate: string | null | undefined): string {
  if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//")) return "/";
  return candidate;
}
