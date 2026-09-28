"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import type { ColumnDef } from "@tanstack/react-table";
import { Boxes, Check, CircleAlert, Copy, FileKey2, FileWarning, LibraryBig, RefreshCw, Search, X } from "lucide-react";
import { InventoryDataTable } from "@/components/data-table/inventory-data-table";
import { fetchJson } from "@/app/lib/http";
import { addScope, type AssignedScopePair } from "@/app/lib/scope";
import { useConsoleAccess } from "@/app/components/console-shell";
import { AssignedServiceUnion } from "@/components/access/assigned-service-union";
import { getLibraryPage, getServicePage, useInventorySnapshot } from "@/components/inventory/inventory-data";
import type { InventoryStatus, LibraryInventory, ServiceGroupInventory, ServiceInventory } from "@/components/inventory/types";

type View = "coverage" | "services" | "libraries";
type ApiPage<T> = { items: T[]; total: number; limit: number; offset: number };
type ComponentOccurrence = { occurrence_id: number; component_id: number; component_type: string; name: string; version: string | null; canonical_purl: string | null; scope: string | null; explicit_crypto: boolean };
type ComponentUsage = { occurrence_id: number; document_id: number; document_kind: string; spec_version: string; service_groups: string[]; source_paths: string[]; scope: string | null; explicit_crypto: boolean };

const tabs: { id: View; label: string; detail: string }[] = [
  { id: "coverage", label: "Group coverage", detail: "Review selected-group catalog coverage and evidence-collection state" },
  { id: "services", label: "Services", detail: "Inspect records and every component in a service" },
  { id: "libraries", label: "Libraries", detail: "See every service using a crypto library" },
];

const statusStyles: Record<InventoryStatus, string> = {
  ready: "border-slate-500/25 bg-slate-500/10 text-slate-700 dark:text-slate-200",
  "needs-evidence": "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  attention: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300",
  "no-data": "border-slate-500/25 bg-slate-500/10 text-slate-600 dark:text-slate-300",
};

function StatusPill({ status }: { status: InventoryStatus }) {
  const label = status === "needs-evidence" ? "Evidence gap recorded" : status === "no-data" ? "No parsed records" : status === "ready" ? "No catalog issue reported" : "Ingestion issue";
  return <span className={`inline-flex whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-medium ${statusStyles[status]}`}>{label}</span>;
}

function CopyValue({ value, label = "Copy value" }: { value: string; label?: string }) {
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch { /* Clipboard access is optional; the complete value remains available to assistive tech. */ }
  };
  return <button type="button" className="copy-value" aria-label={copied ? "Copied" : label} onClick={() => void copy()}>{copied ? <Check size={14} /> : <Copy size={14} />}</button>;
}

function formatObserved(value: string) {
  if (!value || Number.isNaN(Date.parse(value))) return "—";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function numericId(value: string) { return Number(value.split("-").at(-1)); }

const groupColumns: ColumnDef<ServiceGroupInventory>[] = [
  { accessorKey: "group", header: "Service group", cell: ({ row }) => <span className="font-medium text-foreground">{row.original.group}</span> },
  { accessorKey: "documents", header: "Records", cell: ({ row }) => <span className="font-mono">{row.original.documents}</span> },
  { accessorKey: "cryptoComponents", header: "Crypto components", cell: ({ row }) => <span className="font-mono">{row.original.cryptoComponents}</span> },
  { accessorKey: "evidenceGaps", header: "Coverage requests", cell: ({ row }) => <span className="font-mono">{row.original.evidenceGaps}</span> },
  { accessorKey: "ingestIssues", header: "Ingest issues", cell: ({ row }) => <span className="font-mono">{row.original.ingestIssues}</span> },
  { accessorKey: "status", header: "Catalog evidence state", cell: ({ row }) => <StatusPill status={row.original.status} /> },
];

function SectionHeading({ icon: Icon, title, description }: { icon: typeof Boxes; title: string; description: string }) {
  return <div className="inventory-section-heading"><div className="section-icon"><Icon className="size-5" /></div><div><h2>{title}</h2><p>{description}</p></div></div>;
}

function SummaryMetric({ icon: Icon, label, value, detail }: { icon: typeof Boxes; label: string; value: string; detail: string }) {
  return <div className="inventory-summary-card"><Icon /><div><p>{label}</p><strong>{value}</strong><span>{detail}</span></div></div>;
}

export function InventoryWorkbench() {
  const access = useConsoleAccess();
  if (!access.isAdmin && (!access.detailAccess || access.pairs.length !== 1)) {
    return <AssignedServiceUnion title="Inventory across assigned products" description="Every verified service group and product context appears together. Open a service to inspect its exact attributed evidence when detail access is available." renderScope={access.detailAccess ? (scope) => <InventoryScopeWorkbench scope={scope} /> : undefined} />;
  }
  return <InventoryScopeWorkbench scope={access.isAdmin ? undefined : access.selected} />;
}

function InventoryScopeWorkbench({ scope }: { scope?: AssignedScopePair }) {
  const [activeView, setActiveView] = React.useState<View>("coverage");
  const [serviceDetail, setServiceDetail] = React.useState<ServiceInventory | null>(null);
  const [libraryDetail, setLibraryDetail] = React.useState<LibraryInventory | null>(null);
  const { groups, source, error, loading, reload } = useInventorySnapshot(scope);
  const [services, setServices] = React.useState<ServiceInventory[]>([]);
  const [serviceTotal, setServiceTotal] = React.useState(0);
  const [servicePage, setServicePage] = React.useState(0);
  const [servicePageSize, setServicePageSize] = React.useState(16);
  const [serviceQuery, setServiceQuery] = React.useState("");
  const [serviceSort, setServiceSort] = React.useState("document_id");
  const [serviceDirection, setServiceDirection] = React.useState<"asc" | "desc">("asc");
  const [serviceLoading, setServiceLoading] = React.useState(false);
  const [serviceError, setServiceError] = React.useState("");
  const [libraries, setLibraries] = React.useState<LibraryInventory[]>([]);
  const [libraryTotal, setLibraryTotal] = React.useState(0);
  const [libraryPage, setLibraryPage] = React.useState(0);
  const [libraryPageSize, setLibraryPageSize] = React.useState(16);
  const [libraryQuery, setLibraryQuery] = React.useState("");
  const [librarySort, setLibrarySort] = React.useState("document_count");
  const [libraryDirection, setLibraryDirection] = React.useState<"asc" | "desc">("desc");
  const [libraryLoading, setLibraryLoading] = React.useState(false);
  const [libraryError, setLibraryError] = React.useState("");
  const [refreshVersion, setRefreshVersion] = React.useState(0);
  const tabRefs = React.useRef<Record<View, HTMLButtonElement | null>>({ coverage: null, services: null, libraries: null });

  const updateViewLocation = React.useCallback((view: View, mode: "push" | "replace") => {
    const params = new URLSearchParams(window.location.search);
    params.set("view", view);
    const query = view === "services" ? serviceQuery : view === "libraries" ? libraryQuery : "";
    if (query) params.set("query", query); else params.delete("query");
    const next = `${window.location.pathname}?${params.toString()}${window.location.hash}`;
    if (mode === "push") window.history.pushState(window.history.state, "", next);
    else window.history.replaceState(window.history.state, "", next);
  }, [libraryQuery, serviceQuery]);

  const selectView = React.useCallback((view: View) => {
    if (view === activeView) return;
    updateViewLocation(view, "push");
    setActiveView(view);
  }, [activeView, updateViewLocation]);

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const view = params.get("view");
    const query = params.get("query") ?? "";
    if (view !== "services" && view !== "libraries" && view !== "coverage") return;
    const timer = window.setTimeout(() => {
      setActiveView(view);
      if (view === "services") setServiceQuery(query);
      if (view === "libraries") setLibraryQuery(query);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  React.useEffect(() => {
    const restoreViewFromHistory = () => {
      const params = new URLSearchParams(window.location.search);
      const view = params.get("view");
      const query = params.get("query") ?? "";
      if (view !== "services" && view !== "libraries" && view !== "coverage") return;
      setActiveView(view);
      if (view === "services") setServiceQuery(query);
      if (view === "libraries") setLibraryQuery(query);
    };
    window.addEventListener("popstate", restoreViewFromHistory);
    return () => window.removeEventListener("popstate", restoreViewFromHistory);
  }, []);

  React.useEffect(() => {
    updateViewLocation(activeView, "replace");
  }, [activeView, updateViewLocation]);

  const selectAdjacentTab = (current: View, direction: -1 | 1) => {
    const currentIndex = tabs.findIndex((tab) => tab.id === current);
    const next = tabs[(currentIndex + direction + tabs.length) % tabs.length].id;
    selectView(next);
    tabRefs.current[next]?.focus();
  };

  React.useEffect(() => {
    if (activeView !== "services") return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setServiceLoading(true);
      setServiceError("");
      void getServicePage({ page: servicePage, pageSize: servicePageSize, query: serviceQuery, scope, sort: serviceSort, direction: serviceDirection, signal: controller.signal })
        .then((result) => { setServices(result.rows); setServiceTotal(result.total); })
        .catch((reason: Error) => { if (reason.name !== "AbortError") { setServices([]); setServiceTotal(0); setServiceError(`Unable to load service records: ${reason.message}`); } })
        .finally(() => { if (!controller.signal.aborted) setServiceLoading(false); });
    }, serviceQuery ? 250 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [activeView, servicePage, servicePageSize, serviceQuery, scope, serviceSort, serviceDirection, refreshVersion]);

  React.useEffect(() => {
    if (activeView !== "libraries") return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLibraryLoading(true);
      setLibraryError("");
      void getLibraryPage({ page: libraryPage, pageSize: libraryPageSize, query: libraryQuery, scope, sort: librarySort, direction: libraryDirection, signal: controller.signal })
        .then((result) => { setLibraries(result.rows); setLibraryTotal(result.total); })
        .catch((reason: Error) => { if (reason.name !== "AbortError") { setLibraries([]); setLibraryTotal(0); setLibraryError(`Unable to load library usage: ${reason.message}`); } })
        .finally(() => { if (!controller.signal.aborted) setLibraryLoading(false); });
    }, libraryQuery ? 250 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [activeView, libraryPage, libraryPageSize, libraryQuery, scope, librarySort, libraryDirection, refreshVersion]);
  const evidenceNeeded = groups.filter((group) => group.evidenceGaps > 0).length;
  const ingestAttention = groups.filter((group) => group.ingestIssues > 0).length;
  const noSourceEvidence = Boolean(scope && groups.length === 1 && groups[0].documents === 0);
  const scopedEvidenceGapMessage = noSourceEvidence
    ? "No source evidence was observed for this exact assigned service scope. This is an evidence gap; it does not establish absence of crypto, a compliant posture, or zero risk."
    : undefined;

  const serviceColumns = React.useMemo<ColumnDef<ServiceInventory>[]>(() => [
    { accessorKey: "service", header: "Source record", cell: ({ row }) => <div className="min-w-[180px]"><p className="font-medium text-foreground">{row.original.service}</p><p className="mt-1 max-w-[280px] truncate font-mono text-xs text-muted-foreground" title={row.original.provenance}>{row.original.provenance}</p></div> },
    { accessorKey: "group", header: "Service groups", cell: ({ row }) => <span title={row.original.groups.join(", ")}>{row.original.groups.join(", ") || "Unassigned"}</span> },
    { accessorKey: "kind", header: "Record", cell: ({ row }) => <div><span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-foreground">{row.original.kind}</span><p className="mt-2 text-xs text-muted-foreground">{row.original.format}</p></div> },
    { accessorKey: "cryptoComponents", header: "Crypto / libraries", enableSorting: false, cell: ({ row }) => <span className="font-mono">{row.original.cryptoComponents} / {row.original.libraries}</span> },
    { accessorKey: "observedAt", header: "Observed", cell: ({ row }) => <span className="whitespace-nowrap text-sm text-muted-foreground">{formatObserved(row.original.observedAt)}</span> },
    { id: "actions", header: "Details", enableSorting: false, cell: ({ row }) => <button className="table-action" type="button" aria-label={`View components for ${row.original.service}`} onClick={() => setServiceDetail(row.original)}>Components</button> },
  ], []);

  const libraryColumns = React.useMemo<ColumnDef<LibraryInventory>[]>(() => [
    { accessorKey: "library", header: "Library", cell: ({ row }) => <div><p className="font-medium text-foreground">{row.original.library}</p><p className="mt-1 font-mono text-xs text-muted-foreground">{row.original.version}</p></div> },
    { accessorKey: "serviceGroups", header: "Explicit groups", enableSorting: false, cell: ({ row }) => <div><span className="font-mono">{row.original.serviceGroups}</span><p className="mt-1 max-w-[220px] truncate text-xs text-muted-foreground" title={row.original.serviceGroupNames.join(", ")}>{row.original.serviceGroupNames.join(", ") || "—"}</p></div> },
    { accessorKey: "services", header: "Explicit documents", cell: ({ row }) => <span className="font-mono">{row.original.services}</span> },
    { accessorKey: "occurrences", header: "Explicit occurrences", cell: ({ row }) => <span className="font-mono">{row.original.occurrences}</span> },
    { id: "actions", header: "Details", enableSorting: false, cell: ({ row }) => <button className="table-action" type="button" aria-label={`View usage for ${row.original.library} ${row.original.version ?? ""}`.trim()} onClick={() => setLibraryDetail(row.original)}>Usage</button> },
  ], []);

  return <div className="inventory-workbench">
    <section className="page-heading inventory-heading">
      <div><p className="eyebrow">Evidence catalog</p><h1>Inventory workbench</h1><p className="page-subtitle">{scope ? `Catalog evidence for ${scope.sourceCollection}/${scope.serviceGroup} in ${scope.boundaryName}.` : "Catalog service groups, source records, and explicitly tagged crypto inventory."}</p></div>
      <div className="heading-actions"><span className="source-state">{loading ? "Loading catalog…" : source === "api" ? "Catalog loaded" : "Catalog unavailable"}</span><button className="refresh-button" type="button" onClick={() => { void reload(); setRefreshVersion((value) => value + 1); }} disabled={loading || serviceLoading || libraryLoading}><RefreshCw size={17} className={loading || serviceLoading || libraryLoading ? "spin" : ""} />Refresh active data</button></div>
    </section>

    {!loading && source === "unavailable" ? <div className="catalog-unavailable" role="alert"><FileWarning size={21} /><div><h2>Live inventory is unavailable</h2><p>No sample groups, services, libraries, or inventory totals are shown. Restore the catalog API, then refresh this page.</p><code>{error}</code></div></div> : null}

    {source === "api" ? <><section className="inventory-tabs" role="tablist" aria-label="Inventory views">
      {tabs.map((tab) => <button key={tab.id} id={`inventory-tab-${tab.id}`} ref={(node) => { tabRefs.current[tab.id] = node; }} type="button" role="tab" aria-selected={activeView === tab.id} aria-controls="inventory-tabpanel" tabIndex={activeView === tab.id ? 0 : -1} onClick={() => selectView(tab.id)} onKeyDown={(event) => { if (event.key === "ArrowLeft") { event.preventDefault(); selectAdjacentTab(tab.id, -1); } else if (event.key === "ArrowRight") { event.preventDefault(); selectAdjacentTab(tab.id, 1); } else if (event.key === "Home") { event.preventDefault(); selectView(tabs[0].id); tabRefs.current[tabs[0].id]?.focus(); } else if (event.key === "End") { event.preventDefault(); const last = tabs.at(-1)!.id; selectView(last); tabRefs.current[last]?.focus(); } }} className={activeView === tab.id ? "active" : ""}><span>{tab.label}</span><small>{tab.detail}</small></button>)}
    </section>

    <div id="inventory-tabpanel" role="tabpanel" aria-labelledby={`inventory-tab-${activeView}`}>
      {activeView === "coverage" ? <CoverageView groups={groups} scope={scope} /> : null}
      {activeView === "services" ? <section className="inventory-primary-view"><SectionHeading icon={FileKey2} title="Source records" description="Search all source paths and service memberships, then open a record for component evidence and provenance." />{noSourceEvidence && scope ? <ScopeEvidenceGap scope={scope} /> : null}<InventoryDataTable tableLabel="Source records" columns={serviceColumns} data={services} filterColumn="service" searchPlaceholder="Search source records…" emptyMessage={scopedEvidenceGapMessage} loading={serviceLoading} errorMessage={serviceError} remote={{ total: serviceTotal, query: serviceQuery, page: servicePage, pageSize: servicePageSize, onQueryChange: (value) => { setServiceQuery(value); setServicePage(0); }, onPageChange: setServicePage, onPageSizeChange: (value) => { setServicePageSize(value); setServicePage(0); }, onSortChange: (column, direction) => { const map: Record<string, string> = { service: "service", group: "group", kind: "kind", observedAt: "observed_at" }; setServiceSort(map[column] ?? "document_id"); setServiceDirection(direction); setServicePage(0); } }} /></section> : null}
      {activeView === "libraries" ? <section className="inventory-primary-view"><SectionHeading icon={LibraryBig} title="Explicit crypto-library inventory" description="Catalog observations explicitly tagged as crypto-related. Counts do not establish deployed use, CMVP validation, approved mode, or compliance." />{noSourceEvidence && scope ? <ScopeEvidenceGap scope={scope} /> : null}<InventoryDataTable tableLabel="Explicit crypto-library inventory" columns={libraryColumns} data={libraries} filterColumn="library" searchPlaceholder="Search library name or PURL…" emptyMessage={scopedEvidenceGapMessage} loading={libraryLoading} errorMessage={libraryError} remote={{ total: libraryTotal, query: libraryQuery, page: libraryPage, pageSize: libraryPageSize, onQueryChange: (value) => { setLibraryQuery(value); setLibraryPage(0); }, onPageChange: setLibraryPage, onPageSizeChange: (value) => { setLibraryPageSize(value); setLibraryPage(0); }, onSortChange: (column, direction) => { const map: Record<string, string> = { library: "library", services: "document_count", occurrences: "occurrence_count" }; setLibrarySort(map[column] ?? "document_count"); setLibraryDirection(direction); setLibraryPage(0); } }} /></section> : null}
    </div>

    {activeView === "coverage" ? <section className="inventory-summary-grid" aria-label="Inventory summary">
      <SummaryMetric icon={Boxes} label={scope ? "Catalog records" : "Group-document mappings"} value={groups.reduce((sum, group) => sum + group.documents, 0).toLocaleString()} detail={scope ? "Parsed catalog records" : "A document may appear in several groups"} />
      <SummaryMetric icon={CircleAlert} label="Evidence-collection requests" value={String(evidenceNeeded)} detail="Not vulnerabilities or POA&M candidates" />
      <SummaryMetric icon={FileWarning} label="Groups with ingestion issues" value={String(ingestAttention)} detail="Catalog processing requires review" />
    </section> : null}
    </> : null}

    {serviceDetail ? <ServiceComponentsDialog service={serviceDetail} scope={scope} onClose={() => setServiceDetail(null)} /> : null}
    {libraryDetail ? <LibraryUsageDialog library={libraryDetail} scope={scope} onClose={() => setLibraryDetail(null)} /> : null}
  </div>;
}

function ScopeEvidenceGap({ scope }: { scope: AssignedScopePair }) {
  return <section className="inventory-empty-state" aria-labelledby="scope-evidence-gap-title">
    <strong id="scope-evidence-gap-title">No source evidence observed</strong>
    <p>This exact assigned scope, <code>{scope.sourceCollection}/{scope.serviceGroup}</code>, returned no current CBOM, SBOM, or other parsed source records. This is an evidence gap. It does not establish absence of cryptography, a compliant posture, or zero risk.</p>
  </section>;
}

function CoverageView({ groups, scope }: { groups: ServiceGroupInventory[]; scope?: AssignedScopePair }) {
  const actionGroups = [...groups].filter((group) => group.evidenceGaps > 0 || group.ingestIssues > 0 || group.documents === 0).sort((a, b) => (b.evidenceGaps + b.ingestIssues) - (a.evidenceGaps + a.ingestIssues) || a.documents - b.documents);
  return <section className="inventory-primary-view">
    <SectionHeading icon={CircleAlert} title="Catalog attention" description="Evidence-collection requests, ingestion issues, and empty registered groups. This is a processing queue, not a compliance determination." />
    {scope && groups.length === 1 && groups[0].documents === 0 ? <ScopeEvidenceGap scope={scope} /> : null}
    {actionGroups.length ? <div className="coverage-heatmap-grid">{actionGroups.map((group) => <article key={group.group} className="heatmap-tile"><div className="heatmap-tile-heading"><strong>{group.group}</strong><StatusPill status={group.status} /></div><div className="heatmap-values"><div><strong>{group.evidenceGaps + group.ingestIssues}</strong><span>catalog attention item{group.evidenceGaps + group.ingestIssues === 1 ? "" : "s"}</span></div><p>{group.evidenceGaps} coverage request{group.evidenceGaps === 1 ? "" : "s"} · {group.ingestIssues} ingestion issue{group.ingestIssues === 1 ? "" : "s"} · {group.documents} parsed record{group.documents === 1 ? "" : "s"}</p></div></article>)}</div> : <p className="inventory-empty-state">No evidence-collection requests, ingestion issues, or empty registered groups need attention.</p>}
    <SectionHeading icon={Boxes} title={scope ? "Selected service group" : "All service groups"} description="Review parsed records, evidence-collection requests, and ingestion quality. Crypto counts are catalog inventory signals only." />
    <InventoryDataTable tableLabel="All service groups" columns={groupColumns} data={groups} filterColumn="group" searchPlaceholder="Search service groups…" />
  </section>;
}

function ModalFrame({ title, subtitle, onClose, children, footer }: { title: string; subtitle: string; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode }) {
  const dialogRef = React.useRef<HTMLElement>(null);
  const titleId = React.useId();
  React.useEffect(() => {
    const prior = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const main = document.getElementById("main-content");
    const previousOverflow = document.body.style.overflow;
    main?.setAttribute("inert", "");
    document.body.style.overflow = "hidden";
    const initialFocus = dialogRef.current?.querySelector<HTMLElement>("input, button:not([disabled]), select, [tabindex]:not([tabindex='-1'])");
    (initialFocus ?? dialogRef.current)?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab" && dialogRef.current) {
        const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>('button, input, select, a[href], [tabindex]:not([tabindex="-1"])')].filter((item) => !item.hasAttribute("disabled"));
        if (!focusable.length) return;
        const first = focusable[0]; const last = focusable.at(-1)!;
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("keydown", close); main?.removeAttribute("inert"); document.body.style.overflow = previousOverflow; prior?.focus(); };
  }, [onClose]);
  if (typeof document === "undefined") return null;
  return createPortal(<div className="detail-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}><section ref={dialogRef} tabIndex={-1} className="detail-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={`${titleId}-description`}><header><div><h2 id={titleId}>{title}</h2><p id={`${titleId}-description`}>{subtitle}</p></div><button type="button" className="icon-button" aria-label="Close details" onClick={onClose}><X /></button></header><div className="detail-dialog-body">{children}</div>{footer ? <footer>{footer}</footer> : null}</section></div>, document.body);
}

function ServiceComponentsDialog({ service, scope, onClose }: { service: ServiceInventory; scope?: AssignedScopePair; onClose: () => void }) {
  const [rows, setRows] = React.useState<ComponentOccurrence[]>([]);
  const [total, setTotal] = React.useState(0);
  const [totalKnown, setTotalKnown] = React.useState(true);
  const [hasMore, setHasMore] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [cryptoOnly, setCryptoOnly] = React.useState(false);
  const [page, setPage] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const pageSize = 100;
  React.useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ limit: String(pageSize), offset: String(page * pageSize), crypto_only: String(cryptoOnly) });
    if (scope) addScope(params, scope);
    if (query.trim()) params.set("query", query.trim());
    const timer = window.setTimeout(() => {
      params.set("include_total", "true");
      void fetchJson<ApiPage<ComponentOccurrence> | ComponentOccurrence[]>(`/api/v1/documents/${numericId(service.id)}/components?${params}`, { signal: controller.signal, dedupe: false }).then((result) => {
        const items = Array.isArray(result) ? result : result.items;
        setRows(items);
        setTotal(Array.isArray(result) ? page * pageSize + items.length : result.total);
        setTotalKnown(!Array.isArray(result) || items.length < pageSize);
        setHasMore(Array.isArray(result) ? items.length === pageSize : (page + 1) * pageSize < result.total);
      }).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [service.id, query, cryptoOnly, page, scope]);
  return <ModalFrame title={service.service} subtitle={`${service.groups.join(", ") || "Unassigned"} · ${service.kind} · ${service.format}`} onClose={onClose} footer={<div className="detail-pagination"><span>{rows.length ? totalKnown ? `${page * pageSize + 1}–${page * pageSize + rows.length} of ${total} components` : `${page * pageSize + 1}–${page * pageSize + rows.length} components · total unavailable` : "0 components"}</span><div><button type="button" disabled={page === 0 || loading} onClick={() => { setLoading(true); setError(""); setPage((value) => Math.max(0, value - 1)); }}>Previous</button><button type="button" disabled={loading || !hasMore} onClick={() => { setLoading(true); setError(""); setPage((value) => value + 1); }}>Next</button></div></div>}>
    <div className="detail-toolbar"><label><span className="sr-only">Search components</span><Search /><input value={query} onChange={(event) => { setLoading(true); setError(""); setQuery(event.target.value); setPage(0); }} placeholder="Search component, version, or PURL" /></label><label className="detail-checkbox"><input type="checkbox" checked={cryptoOnly} onChange={(event) => { setLoading(true); setError(""); setCryptoOnly(event.target.checked); setPage(0); }} /> Explicit crypto only</label></div>
    <p className="detail-provenance"><strong>Sources:</strong> {service.provenancePaths.join(", ") || "—"}<br /><strong>SHA-256:</strong> <span className="font-mono">{service.checksum}</span> {service.checksum !== "—" ? <CopyValue value={service.checksum} label="Copy SHA-256" /> : null}</p>
    {error ? <p className="detail-error" role="alert">Unable to load components: {error}</p> : <div className="detail-table-wrap"><table><caption className="sr-only">Components in this source record</caption><thead><tr><th>Component</th><th>Type</th><th>Scope</th><th>Classification</th><th>PURL</th></tr></thead><tbody>{rows.map((row) => <tr key={row.occurrence_id}><td><strong>{row.name}</strong><span>{row.version || "Version not supplied"}</span></td><td>{row.component_type || "—"}</td><td>{row.scope || "—"}</td><td>{row.explicit_crypto === true ? <span className="classification-pill">Explicit crypto</span> : row.explicit_crypto === false ? "Inventory component" : "Classification unavailable"}</td><td><span className="detail-purl" title={row.canonical_purl || ""}>{row.canonical_purl || "—"}</span>{row.canonical_purl ? <CopyValue value={row.canonical_purl} label={`Copy PURL for ${row.name}`} /> : null}</td></tr>)}{!loading && !rows.length ? <tr><td colSpan={5} className="detail-empty">No components match this view.</td></tr> : null}</tbody></table>{loading ? <p className="detail-loading" aria-live="polite">Loading components…</p> : null}</div>}
  </ModalFrame>;
}

function LibraryUsageDialog({ library, scope, onClose }: { library: LibraryInventory; scope?: AssignedScopePair; onClose: () => void }) {
  const [rows, setRows] = React.useState<ComponentUsage[]>([]);
  const [total, setTotal] = React.useState(0);
  const [totalKnown, setTotalKnown] = React.useState(true);
  const [hasMore, setHasMore] = React.useState(false);
  const [usageClassificationAvailable, setUsageClassificationAvailable] = React.useState(true);
  const [explicitOnly, setExplicitOnly] = React.useState(true);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [page, setPage] = React.useState(0);
  const pageSize = 100;
  React.useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ limit: String(pageSize), offset: String(page * pageSize), include_total: "true", explicit_crypto_only: String(explicitOnly) });
      if (scope) addScope(params, scope);
      void fetchJson<ApiPage<ComponentUsage> | ComponentUsage[]>(`/api/v1/components/${numericId(library.id)}/usage?${params}`, { signal: controller.signal, dedupe: false }).then((result) => {
        const items = Array.isArray(result) ? result : result.items;
        setRows(items);
        setTotal(Array.isArray(result) ? page * pageSize + items.length : result.total);
        setTotalKnown(!Array.isArray(result) || items.length < pageSize);
        setHasMore(Array.isArray(result) ? items.length === pageSize : (page + 1) * pageSize < result.total);
        setUsageClassificationAvailable(!Array.isArray(result));
      }).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [library.id, page, explicitOnly, scope]);
  const showingExplicit = explicitOnly && usageClassificationAvailable;
  return <ModalFrame title={library.library} subtitle={`${library.version} · ${library.occurrences.toLocaleString()} explicitly classified occurrence${library.occurrences === 1 ? "" : "s"} in the list`} onClose={onClose} footer={<div className="detail-pagination"><span>{rows.length ? totalKnown ? `${page * pageSize + 1}–${page * pageSize + rows.length} of ${total} ${showingExplicit ? "explicit" : "all"} usages` : `${page * pageSize + 1}–${page * pageSize + rows.length} ${showingExplicit ? "explicit" : "all"} usages · total unavailable` : "0 usages"}</span><div><button type="button" disabled={page === 0 || loading} onClick={() => { setLoading(true); setPage((value) => Math.max(0, value - 1)); }}>Previous</button><button type="button" disabled={loading || !hasMore} onClick={() => { setLoading(true); setPage((value) => value + 1); }}>Next</button></div></div>}>
    <div className="detail-toolbar"><label className="detail-checkbox"><input type="checkbox" checked={showingExplicit} disabled={!usageClassificationAvailable} onChange={(event) => { setLoading(true); setError(""); setExplicitOnly(event.target.checked); setPage(0); }} /> {usageClassificationAvailable ? "Explicit crypto usages only" : "Explicit-only filter unavailable from current API"}</label></div>
    <p className="detail-provenance"><strong>Canonical package:</strong> <span className="font-mono">{library.purl}</span>{library.purl !== "No canonical PURL" ? <CopyValue value={library.purl} label="Copy canonical PURL" /> : null}<br /><span>{!usageClassificationAvailable ? "The current API returned all observed usages without per-usage classification; the aggregate list above remains explicit-only." : showingExplicit ? "This matches the aggregate list semantics. Clear the filter to inspect every observed usage." : "All observed usages are shown; this may exceed the explicitly classified aggregate above."}</span></p>
    {error ? <p className="detail-error" role="alert">Unable to load service usage: {error}</p> : <div className="detail-table-wrap"><table><caption className="sr-only">Library usage by source record</caption><thead><tr><th>Service group</th><th>Source record</th><th>Document</th><th>Scope</th><th>Classification</th></tr></thead><tbody>{rows.map((row) => <tr key={row.occurrence_id}><td><strong>{row.service_groups?.join(", ") || "Unassigned"}</strong></td><td><span className="detail-purl" title={row.source_paths?.join(", ")}>{row.source_paths?.join(", ") || "—"}</span>{row.source_paths?.[0] ? <CopyValue value={row.source_paths.join("\n")} label="Copy source paths" /> : null}</td><td>{row.document_kind} {row.spec_version}</td><td>{row.scope || "—"}</td><td>{row.explicit_crypto === true ? <span className="classification-pill">Explicit crypto</span> : row.explicit_crypto === false ? "Inventory component" : "Classification unavailable"}</td></tr>)}{!loading && !rows.length ? <tr><td colSpan={5} className="detail-empty">No service usage matches this view.</td></tr> : null}</tbody></table>{loading ? <p className="detail-loading" aria-live="polite">Loading service usage…</p> : null}</div>}
  </ModalFrame>;
}
