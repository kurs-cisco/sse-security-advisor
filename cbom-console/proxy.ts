import { NextRequest, NextResponse } from "next/server";
import { authMode, DEV_AUTH_COOKIE, devAuthAllowed, safeReturnTo } from "@/app/lib/auth-config";
import { verifyAlbOidcToken } from "@/app/lib/alb-oidc";

const PUBLIC_PATHS = new Set(["/login", "/healthz", "/icon.svg", "/auth/dev-login"]);

function unauthenticated(request: NextRequest, reason: string): NextResponse {
  if (request.nextUrl.pathname.startsWith("/api/")) {
    return NextResponse.json({ detail: reason }, { status: 401, headers: { "Cache-Control": "no-store" } });
  }
  const login = new URL("/login", request.url);
  login.searchParams.set("returnTo", safeReturnTo(`${request.nextUrl.pathname}${request.nextUrl.search}`));
  login.searchParams.set("reason", reason);
  return NextResponse.redirect(login);
}

export async function proxy(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  if (PUBLIC_PATHS.has(pathname) || pathname.startsWith("/_next/")) return NextResponse.next();

  const mode = authMode();
  if (mode === "disabled") {
    if (process.env.NODE_ENV === "production") return unauthenticated(request, "Authentication cannot be disabled in production");
    return NextResponse.next();
  }
  if (mode === "dev") {
    if (!devAuthAllowed()) return unauthenticated(request, "Development authentication is disabled in production");
    if (request.cookies.get(DEV_AUTH_COOKIE)?.value !== "authenticated") return unauthenticated(request, "Sign in to continue");
    return NextResponse.next();
  }

  const token = request.headers.get("x-amzn-oidc-data");
  if (!token) return unauthenticated(request, "Cloud identity was not supplied by the load balancer");
  const verification = await verifyAlbOidcToken(token);
  if (!verification.ok) return unauthenticated(request, verification.reason);

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
