export const DEV_AUTH_COOKIE = "cbom-dev-auth";
export const ALB_AUTH_COOKIE = "CBOMAWSELBAuthSessionCookie";

export type AuthMode = "dev" | "alb-oidc" | "disabled";

export function authMode(): AuthMode {
  const configured = process.env.CBOM_AUTH_MODE?.trim().toLowerCase();
  if (configured === "dev" || configured === "alb-oidc" || configured === "disabled") {
    return configured;
  }
  return process.env.NODE_ENV === "development" ? "dev" : "alb-oidc";
}

export function devAuthAllowed(): boolean {
  return process.env.NODE_ENV === "development" || process.env.CBOM_ALLOW_INSECURE_DEV_AUTH === "true";
}

export function safeReturnTo(candidate: string | null | undefined): string {
  if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//")) return "/";
  return candidate;
}
