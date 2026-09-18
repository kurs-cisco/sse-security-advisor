import { fetchJson } from "@/app/lib/http";
import type { CryptoComponent, RegisterResponse, ServiceGroupDetail } from "@/components/accountability/types";

export type RegisterQuery = {
  query: string;
  owner: string;
  lead: string;
  il2State: string;
  il5State: string;
  action: string;
  sort: string;
  direction: "asc" | "desc";
  page: number;
  pageSize: number;
  signal?: AbortSignal;
};

export function getServiceGroupRegister(options: RegisterQuery) {
  const params = new URLSearchParams({
    limit: String(options.pageSize),
    offset: String(options.page * options.pageSize),
    sort: options.sort,
    direction: options.direction,
  });
  if (options.query.trim()) params.set("query", options.query.trim());
  if (options.owner) params.set("owner", options.owner);
  if (options.lead) params.set("lead", options.lead);
  if (options.il2State) params.set("il2_state", options.il2State);
  if (options.il5State) params.set("il5_state", options.il5State);
  if (options.action) params.set("action", options.action);
  return fetchJson<RegisterResponse>(`/api/v1/inventory/service-groups?${params}`, { signal: options.signal, dedupe: false });
}

export function getServiceGroupDetail(sourceCollection: string, serviceGroup: string, signal?: AbortSignal) {
  return fetchJson<ServiceGroupDetail>(`/api/v1/inventory/service-groups/${encodeURIComponent(sourceCollection)}/${encodeURIComponent(serviceGroup)}`, { signal, dedupe: false });
}

export function getDocumentCryptoComponents(documentId: number, signal?: AbortSignal) {
  return fetchJson<CryptoComponent[]>(`/api/v1/documents/${documentId}/components?crypto_only=true&limit=100`, { signal, dedupe: false });
}
