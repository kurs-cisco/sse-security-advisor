"use client";

import * as React from "react";
import { ChevronDown, RefreshCw, ShieldAlert } from "lucide-react";
import { fetchJson } from "@/app/lib/http";
import type { AssignedScopePair } from "@/app/lib/scope";
import { PRODUCT_SCOPES } from "@/app/lib/product-scopes";
import { serviceGroupDisplayName } from "@/app/lib/utils";

type ProductScopeId = NonNullable<AssignedScopePair["productScopeId"]>;
type BoundaryName = NonNullable<AssignedScopePair["boundaryName"]>;

type AssignedGrant = {
  source_collection: string;
  service_group: string;
  product_scope_id: ProductScopeId;
  boundary_name: BoundaryName;
  access: "lead" | "engineer";
  detail_state: "available" | "attribution_pending";
  assessment_authorization_reference?: string | null;
};

type AssignedUnionResponse = {
  items: AssignedGrant[];
  total: number;
  scope: "assigned-service-union";
  evidence_only: true;
};

type ServiceGroup = {
  key: string;
  sourceCollection: string;
  serviceGroup: string;
  grants: AssignedGrant[];
};

function productName(id: string) {
  return PRODUCT_SCOPES.find((entry) => entry.id === id)?.name ?? id;
}

function evidencePanelId(key: string) {
  // Keep the panel reference stable and safe for an HTML id without relying on
  // source-collection or service-group naming conventions.
  return `assigned-evidence-${Array.from(key, (character) => character.codePointAt(0)?.toString(16) ?? "0").join("-")}`;
}

function groupedGrants(grants: AssignedGrant[]): ServiceGroup[] {
  const groups = new Map<string, ServiceGroup>();
  for (const grant of grants) {
    const key = `${grant.source_collection}/${grant.service_group}`;
    const group = groups.get(key) ?? {
      key, sourceCollection: grant.source_collection,
      serviceGroup: grant.service_group, grants: [],
    };
    group.grants.push(grant);
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => a.key.localeCompare(b.key));
}

export function AssignedServiceUnion({
  title, description, renderScope, headingLevel = 1,
}: {
  title: string;
  description: string;
  renderScope?: (scope: AssignedScopePair) => React.ReactNode;
  headingLevel?: 1 | 2;
}) {
  const [data, setData] = React.useState<AssignedUnionResponse | null>(null);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [revision, setRevision] = React.useState(0);
  const [filter, setFilter] = React.useState("");
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());

  React.useEffect(() => {
    const controller = new AbortController();
    void fetchJson<AssignedUnionResponse>("/api/v1/portfolio/assigned-service-groups", {
      signal: controller.signal, dedupe: false,
    }).then((next) => {
      if (controller.signal.aborted) return;
      setData(next);
      setError("");
    }).catch((reason: Error) => {
      if (reason.name !== "AbortError") setError(reason.message || "Assigned products are unavailable.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision]);

  const groups = React.useMemo(() => groupedGrants(data?.items ?? []), [data]);
  const term = filter.trim().toLocaleLowerCase();
  const visible = groups.filter((group) =>
    [group.key, serviceGroupDisplayName(group.serviceGroup), ...group.grants.map((grant) => productName(grant.product_scope_id))]
      .join(" ").toLocaleLowerCase().includes(term),
  );
  const canOpen = Boolean(renderScope && data?.items.some((grant) => grant.detail_state === "available"));

  return <div className="page-container">
    <section className="page-heading">
      <div><p className="eyebrow">Verified product access</p>{headingLevel === 2 ? <h2>{title}</h2> : <h1>{title}</h1>}<p className="page-subtitle">{description}</p></div>
      <div className="heading-actions"><button className="refresh-button" type="button" disabled={loading} onClick={() => { setLoading(true); setRevision((value) => value + 1); }}><RefreshCw size={17} className={loading ? "spin" : ""} />Refresh access</button></div>
    </section>
    {error ? <section className="rounded-2xl border border-danger/30 bg-card p-5 text-sm text-danger" role="alert">Unable to load assigned products: {error}</section> : null}
    {loading ? <p className="rounded-2xl border border-border bg-card p-6 text-muted-foreground" role="status">Loading verified product access…</p> : null}
    {data && !error ? <>
      <section className="rounded-2xl border border-border bg-card p-5 shadow-sm" aria-label="Assigned product coverage">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><p className="eyebrow">Combined access</p><h2 className="text-xl font-semibold">{groups.length} service group{groups.length === 1 ? "" : "s"} · {data.total} product grant{data.total === 1 ? "" : "s"}</h2><p className="mt-2 max-w-3xl text-sm text-muted-foreground">Groups and product contexts granted to this session.</p></div>
          <label className="text-sm font-medium">Find an assigned service <input className="mt-2 block w-full min-w-52 rounded-lg border border-border bg-background px-3 py-2 text-foreground" type="search" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="DLP, SaaS, SWG…" /></label>
        </div>
        {!canOpen ? <p className="mt-5 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-200"><ShieldAlert size={18} className="mt-0.5 shrink-0" />Detailed product evidence is unavailable for this session. The cards below show verified access grants only; they are not evidence counts.</p> : null}
      </section>
      <section className="mt-5 grid gap-4" aria-label="Assigned services">
        {visible.map((group) => {
          const open = expanded.has(group.key);
          const available = canOpen && group.grants.some((grant) => grant.detail_state === "available");
          const panelId = evidencePanelId(group.key);
          return <article key={group.key} className="rounded-2xl border border-border bg-card p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="text-lg font-semibold">{serviceGroupDisplayName(group.serviceGroup)}</h2><p className="mt-1 font-mono text-xs text-muted-foreground">{group.key}</p></div>{available ? <button className="secondary-button inline-flex items-center gap-2" type="button" aria-expanded={open} aria-controls={panelId} onClick={() => setExpanded((current) => { const next = new Set(current); if (next.has(group.key)) next.delete(group.key); else next.add(group.key); return next; })}>{open ? "Hide evidence" : "Open evidence"}<ChevronDown size={16} className={open ? "rotate-180" : ""} /></button> : <span className="rounded-full border border-amber-500/30 px-3 py-1 text-xs text-amber-700 dark:text-amber-300">Evidence detail pending</span>}</div>
            <ul className="mt-4 flex flex-wrap gap-2" aria-label={`${group.serviceGroup} product contexts`}>{group.grants.map((grant) => <li key={grant.product_scope_id} className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm"><strong>{productName(grant.product_scope_id)}</strong><span className="ml-2 text-muted-foreground">{grant.boundary_name}</span><span className="ml-2 font-medium">· {grant.access === "lead" ? "Lead access" : "Engineer: read only"}</span></li>)}</ul>
            <div id={panelId}>{open && available && renderScope ? <div className="mt-5 grid gap-6 border-t border-border pt-5">{group.grants.filter((grant) => grant.detail_state === "available").map((grant) => {
              const scope: AssignedScopePair = { sourceCollection: grant.source_collection, serviceGroup: grant.service_group, productScopeId: grant.product_scope_id, boundaryName: grant.boundary_name, access: grant.access, assessmentAuthorizationReference: grant.assessment_authorization_reference || undefined, key: `${grant.source_collection}/${grant.service_group}/${grant.product_scope_id}` };
              return <section key={scope.key} aria-label={`${productName(grant.product_scope_id)} evidence`}><h3 className="mb-3 text-base font-semibold">{productName(grant.product_scope_id)} · {grant.boundary_name}</h3>{renderScope(scope)}</section>;
            })}</div> : null}</div>
          </article>;
        })}
        {!visible.length ? <p className="rounded-2xl border border-border bg-card p-6 text-sm text-muted-foreground">No assigned service matches this search.</p> : null}
      </section>
    </> : null}
  </div>;
}
