import type { NextRequest } from "next/server";
import { verifyAlbOidcToken } from "@/app/lib/alb-oidc";
import { forwardedClientHeaders } from "@/app/lib/api-proxy-headers";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const HOP_BY_HOP = new Set(["connection", "content-encoding", "content-length", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"]);

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const origin = (process.env.CBOM_API_ORIGIN ?? "http://127.0.0.1:8000").replace(/\/$/, "");
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`, origin);
  const headers = forwardedClientHeaders(request.headers);
  const token = process.env.CBOM_API_BEARER_TOKEN;
  if (token) headers.set("authorization", `Bearer ${token}`);
  const oidcToken = request.headers.get("x-amzn-oidc-data");
  if (oidcToken) {
    const verification = await verifyAlbOidcToken(oidcToken);
    if (!verification.ok) {
      return Response.json({ detail: verification.reason }, { status: 401, headers: { "Cache-Control": "no-store" } });
    }
    headers.set("x-cbom-user-sub", verification.identity.subject);
    headers.set("x-cbom-user-email", verification.identity.email);
    headers.set("x-cbom-user-issuer", process.env.CBOM_OIDC_ISSUER ?? "");
    if (verification.identity.name) headers.set("x-cbom-user-name", verification.identity.name);
    // Forward the exact, already signature-verified entitlement values. The
    // catalog API owns group-to-capability mapping; this proxy must not infer
    // permissions from a prefix or collapse multi-service memberships.
    headers.set("x-cbom-user-groups", JSON.stringify(verification.identity.groups));
    headers.set("x-cbom-user-groups-claim-type", verification.identity.groupsClaimType);
  }

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
    const responseHeaders = new Headers();
    upstream.headers.forEach((value, name) => { if (!HOP_BY_HOP.has(name.toLowerCase())) responseHeaders.set(name, value); });
    return new Response(request.method === "HEAD" ? null : upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch (error) {
    const detail = error instanceof Error && error.name === "TimeoutError" ? "Catalog API timed out" : "Catalog API is unavailable";
    return Response.json({ detail }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}

export const GET = proxy;
export const HEAD = proxy;
export const OPTIONS = proxy;
export const POST = proxy;
// Service Catalog maintains authoritative administrative metadata with PUT.
// Keep this catch-all route's verb exports aligned with the FastAPI surface;
// otherwise Next.js returns 405 before the request reaches the API.
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
