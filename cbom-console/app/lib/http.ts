import type { AccessMode } from "@/app/lib/contracts";

type RequestOptions = RequestInit & {
  timeoutMs?: number;
  dedupe?: boolean;
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

function combinedSignal(signal: AbortSignal | null | undefined, timeoutMs: number) {
  const timeout = AbortSignal.timeout(timeoutMs);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

export const ACCESS_MODE_STORAGE_KEY = "cbom-access-mode";

export function isAccessMode(value: string | null): value is AccessMode {
  return value === "admin" || value === "product_lead" || value === "product_engineer" || value === "summary";
}

export function selectedAccessMode(): AccessMode | null {
  if (typeof window === "undefined") return null;
  const value = window.sessionStorage.getItem(ACCESS_MODE_STORAGE_KEY);
  return isAccessMode(value) ? value : null;
}

export function accessModeHeaders(headers?: HeadersInit): Headers {
  const next = new Headers(headers);
  // Callers cannot smuggle a mode through a generic fetchJson header object.
  // The only mode source is the validated session value selected by this UI.
  next.delete("X-CBOM-Access-Mode");
  const mode = selectedAccessMode();
  if (mode) next.set("X-CBOM-Access-Mode", mode);
  return next;
}

export async function fetchJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { timeoutMs = 25_000, dedupe: _dedupe, signal, ...init } = options;
  return (async () => {
    const response = await fetch(path, {
      ...init,
      // API payloads are already revision-cached by the catalog service. Using
      // `no-cache` here makes browsers send If-None-Match and can surface a 304
      // to this JSON-only client, which has no response body to parse. Always
      // request a body and let the API's in-process cache keep it inexpensive.
      cache: init.cache ?? "no-store",
      signal: combinedSignal(signal, timeoutMs),
      headers: accessModeHeaders({ Accept: "application/json", ...init.headers }),
    });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json() as { detail?: unknown };
        if (typeof body.detail === "string") detail = body.detail;
        else if (Array.isArray(body.detail)) {
          const messages = body.detail.map((item: unknown) => {
            if (!item || typeof item !== "object") return null;
            const issue = item as { loc?: unknown; msg?: unknown };
            const location = Array.isArray(issue.loc) ? issue.loc.filter((part) => part !== "query").join(".") : "";
            return typeof issue.msg === "string" ? `${location ? `${location}: ` : ""}${issue.msg}` : null;
          }).filter((message): message is string => Boolean(message));
          if (messages.length) detail = messages.join("; ");
        }
      } catch {
        // Keep the status when the upstream response is not JSON.
      }
      throw new ApiError(detail, response.status);
    }
    return await response.json() as T;
  })();
}

export type ApiPage<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};
