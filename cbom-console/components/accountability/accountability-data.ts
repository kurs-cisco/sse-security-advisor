import { fetchJson } from "@/app/lib/http";
import { addScope, type AssignedScopePair } from "@/app/lib/scope";
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
  offset?: number;
  scope?: AssignedScopePair;
  signal?: AbortSignal;
};

export function getServiceGroupRegister(options: RegisterQuery) {
  const params = new URLSearchParams({
    limit: String(options.pageSize),
    offset: String(options.offset ?? options.page * options.pageSize),
    sort: options.sort,
    direction: options.direction,
  });
  if (options.scope) addScope(params, options.scope);
  if (options.query.trim()) params.set("query", options.query.trim());
  if (options.owner) params.set("owner", options.owner);
  if (options.lead) params.set("lead", options.lead);
  if (options.il2State) params.set("il2_state", options.il2State);
  if (options.il5State) params.set("il5_state", options.il5State);
  if (options.action) params.set("action", options.action);
  return fetchJson<RegisterResponse>(`/api/v1/inventory/service-groups?${params}`, { signal: options.signal, dedupe: false });
}

export type ServiceGroupDetailQuery = {
  documentLimit?: number;
  documentOffset?: number;
  libraryLimit?: number;
  libraryOffset?: number;
};

export function getServiceGroupDetail(sourceCollection: string, serviceGroup: string, options?: ServiceGroupDetailQuery & { productScopeId?: string }, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (options?.documentLimit !== undefined) params.set("document_limit", String(options.documentLimit));
  if (options?.documentOffset !== undefined) params.set("document_offset", String(options.documentOffset));
  if (options?.libraryLimit !== undefined) params.set("library_limit", String(options.libraryLimit));
  if (options?.libraryOffset !== undefined) params.set("library_offset", String(options.libraryOffset));
  if (options?.productScopeId) params.set("product_scope_id", options.productScopeId);
  const query = params.size ? `?${params}` : "";
  return fetchJson<ServiceGroupDetail>(`/api/v1/inventory/service-groups/${encodeURIComponent(sourceCollection)}/${encodeURIComponent(serviceGroup)}${query}`, { signal, dedupe: false });
}

export function getDocumentCryptoComponents(documentId: number, scope: AssignedScopePair, signal?: AbortSignal) {
  const params = new URLSearchParams({ crypto_only: "true", limit: "100" });
  addScope(params, scope);
  return fetchJson<CryptoComponent[]>(`/api/v1/documents/${documentId}/components?${params}`, { signal, dedupe: false });
}
