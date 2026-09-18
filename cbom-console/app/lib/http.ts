type RequestOptions = RequestInit & {
  timeoutMs?: number;
  dedupe?: boolean;
};

const inflight = new Map<string, Promise<unknown>>();

function combinedSignal(signal: AbortSignal | null | undefined, timeoutMs: number) {
  const timeout = AbortSignal.timeout(timeoutMs);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

export async function fetchJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { timeoutMs = 25_000, dedupe = true, signal, ...init } = options;
  const method = (init.method ?? "GET").toUpperCase();
  const key = `${method}:${path}`;
  const existing = method === "GET" && dedupe ? inflight.get(key) : undefined;
  if (existing) return existing as Promise<T>;

  const request = (async () => {
    const response = await fetch(path, {
      ...init,
      cache: init.cache ?? "no-cache",
      signal: combinedSignal(signal, timeoutMs),
      headers: { Accept: "application/json", ...init.headers },
    });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json() as { detail?: string };
        detail = body.detail ?? detail;
      } catch {
        // Keep the status when the upstream response is not JSON.
      }
      throw new Error(detail);
    }
    return await response.json() as T;
  })();

  if (method === "GET" && dedupe) inflight.set(key, request);
  try {
    return await request;
  } finally {
    if (inflight.get(key) === request) inflight.delete(key);
  }
}

export type ApiPage<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};
