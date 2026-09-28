/** Narrow client-header allowlist for the browser-to-catalog API proxy. */
const CLIENT_HEADER_ALLOWLIST = ["accept", "content-type", "x-request-id", "x-cbom-access-mode"] as const;

export function forwardedClientHeaders(requestHeaders: Headers): Headers {
  const forwarded = new Headers();
  for (const name of CLIENT_HEADER_ALLOWLIST) {
    const value = requestHeaders.get(name);
    if (value) forwarded.set(name, value);
  }
  // The JSON proxy cannot reconstruct a cached 304 body.
  forwarded.set("accept-encoding", "identity");
  return forwarded;
}
