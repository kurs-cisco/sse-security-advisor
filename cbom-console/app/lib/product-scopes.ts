export const PRODUCT_SCOPES = [
  {
    id: "secure-access-government",
    name: "Secure Access for Government",
    boundaryName: "FedRAMP High/IL2",
  },
  {
    id: "secure-access-defense",
    name: "Secure Access for Defense",
    boundaryName: "IL5",
  },
] as const;

export type ProductScopeId = (typeof PRODUCT_SCOPES)[number]["id"];

export const DEFAULT_PRODUCT_SCOPE_IDS: ProductScopeId[] = PRODUCT_SCOPES.map((scope) => scope.id);

export function productScopeLabel(ids: readonly string[] | null | undefined) {
  if (!ids?.length) return "Unassigned";
  const names = ids.map((id) => PRODUCT_SCOPES.find((scope) => scope.id === id)?.name).filter(Boolean);
  return names.length ? names.join(" + ") : "Evidence attribution pending";
}
