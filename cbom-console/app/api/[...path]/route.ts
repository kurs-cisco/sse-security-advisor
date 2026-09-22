import type { NextRequest } from "next/server";
import { verifyAlbOidcToken } from "@/app/lib/alb-oidc";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const HOP_BY_HOP = new Set(["connection", "content-encoding", "content-length", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"]);

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const origin = (process.env.CBOM_API_ORIGIN ?? "http://127.0.0.1:8000").replace(/\/$/, "");
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`, origin);
  const headers = new Headers();
  // This route is a JSON body proxy, not a browser cache. Do not forward
  // If-None-Match: an upstream 304 has no body and the client cannot reconstruct
  // the prior response across server instances or deployments.
  for (const name of ["accept", "content-type", "x-request-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("accept-encoding", "identity");
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
export const PATCH = proxy;
export const DELETE = proxy;
