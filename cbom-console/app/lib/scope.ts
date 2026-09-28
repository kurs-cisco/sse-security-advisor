export type AssignedScopePair = {
  sourceCollection: string;
  serviceGroup: string;
  productScopeId?: "secure-access-government" | "secure-access-defense";
  boundaryName?: "FedRAMP High/IL2" | "IL5";
  assessmentAuthorizationReference?: string;
  /** Server-derived capability for this exact source/service/product grant. */
  access?: "lead" | "engineer";
  key: string;
};

export function scopeQuery(scope: AssignedScopePair) {
  const params = new URLSearchParams({ source_collection: scope.sourceCollection, service_group: scope.serviceGroup });
  if (scope.productScopeId) params.set("product_scope_id", scope.productScopeId);
  return params;
}

export function addScope(params: URLSearchParams, scope: AssignedScopePair) {
  params.set("source_collection", scope.sourceCollection);
  params.set("service_group", scope.serviceGroup);
  if (scope.productScopeId) params.set("product_scope_id", scope.productScopeId);
  return params;
}
