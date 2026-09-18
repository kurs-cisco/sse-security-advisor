"use client";

import * as React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Boxes, CircleAlert, FileKey2, FileWarning, Layers3, LibraryBig, RefreshCw, Search, ShieldAlert, X } from "lucide-react";
import { InventoryDataTable } from "@/components/data-table/inventory-data-table";
import { fetchJson } from "@/app/lib/http";
import { getLibraryPage, getServicePage, useInventorySnapshot } from "@/components/inventory/inventory-data";
import type { InventoryStatus, LibraryInventory, ServiceGroupInventory, ServiceInventory } from "@/components/inventory/types";

type View = "coverage" | "services" | "libraries";
type ComponentOccurrence = { occurrence_id: number; component_id: number; component_type: string; name: string; version: string | null; canonical_purl: string | null; scope: string | null; explicit_crypto: boolean };
type ComponentUsage = { occurrence_id: number; document_id: number; document_kind: string; spec_version: string; service_groups: string[]; source_paths: string[]; scope: string | null };

const tabs: { id: View; label: string; detail: string }[] = [
  { id: "coverage", label: "Group coverage", detail: "Compare portfolio coverage and evidence posture" },
  { id: "services", label: "Services", detail: "Inspect records and every component in a service" },
  { id: "libraries", label: "Libraries", detail: "See every service using a crypto library" },
];

const statusStyles: Record<InventoryStatus, string> = {
  ready: "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  "needs-evidence": "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  attention: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300",
  "no-data": "border-slate-500/25 bg-slate-500/10 text-slate-600 dark:text-slate-300",
};

function StatusPill({ status }: { status: InventoryStatus }) {
  const label = status === "needs-evidence" ? "Evidence needed" : status === "no-data" ? "No catalog data" : status === "ready" ? "Evidence present" : "Attention";
  return <span className={`inline-flex whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-medium ${statusStyles[status]}`}>{label}</span>;
}

function CompactHash({ hash }: { hash: string }) {
  const display = hash.length > 24 ? `${hash.slice(0, 19)}…${hash.slice(-6)}` : hash;
  return <span title={hash} className="font-mono text-xs text-muted-foreground">{display}</span>;
}

function formatObserved(value: string) {
  if (!value || Number.isNaN(Date.parse(value))) return "—";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function numericId(value: string) { return Number(value.split("-").at(-1)); }

const groupColumns: ColumnDef<ServiceGroupInventory>[] = [
  { accessorKey: "group", header: "Service group", cell: ({ row }) => <span className="font-medium text-foreground">{row.original.group}</span> },
  { accessorKey: "documents", header: "Records", cell: ({ row }) => <span className="font-mono">{row.original.documents}</span> },
  { accessorKey: "services", header: "Services", cell: ({ row }) => <span className="font-mono">{row.original.services}</span> },
  { accessorKey: "cryptoComponents", header: "Crypto components", cell: ({ row }) => <span className="font-mono">{row.original.cryptoComponents}</span> },
  { accessorKey: "uniqueLibraries", header: "Unique libraries", cell: ({ row }) => <span className="font-mono">{row.original.uniqueLibraries}</span> },
  { accessorKey: "evidenceGaps", header: "Evidence gaps", cell: ({ row }) => <span className="font-mono">{row.original.evidenceGaps}</span> },
  { accessorKey: "status", header: "Posture", cell: ({ row }) => <StatusPill status={row.original.status} /> },
];

function SectionHeading({ icon: Icon, title, description }: { icon: typeof Boxes; title: string; description: string }) {
  return <div className="inventory-section-heading"><div className="section-icon"><Icon className="size-5" /></div><div><h2>{title}</h2><p>{description}</p></div></div>;
}

function SummaryMetric({ icon: Icon, label, value, detail }: { icon: typeof Boxes; label: string; value: string; detail: string }) {
  return <div className="inventory-summary-card"><Icon /><div><p>{label}</p><strong>{value}</strong><span>{detail}</span></div></div>;
}

export function InventoryWorkbench() {
  const [activeView, setActiveView] = React.useState<View>("coverage");
  const [serviceDetail, setServiceDetail] = React.useState<ServiceInventory | null>(null);
  const [libraryDetail, setLibraryDetail] = React.useState<LibraryInventory | null>(null);
  const { groups, source, error, loading, reload } = useInventorySnapshot();
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
  const tabRefs = React.useRef<Record<View, HTMLButtonElement | null>>({ coverage: null, services: null, libraries: null });

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

  const selectAdjacentTab = (current: View, direction: -1 | 1) => {
    const currentIndex = tabs.findIndex((tab) => tab.id === current);
    const next = tabs[(currentIndex + direction + tabs.length) % tabs.length].id;
    setActiveView(next);
    tabRefs.current[next]?.focus();
  };

  React.useEffect(() => {
    if (activeView !== "services") return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setServiceLoading(true);
      setServiceError("");
      void getServicePage({ page: servicePage, pageSize: servicePageSize, query: serviceQuery, sort: serviceSort, direction: serviceDirection, signal: controller.signal })
        .then((result) => { setServices(result.rows); setServiceTotal(result.total); })
        .catch((reason: Error) => { if (reason.name !== "AbortError") { setServices([]); setServiceTotal(0); setServiceError(`Unable to load service records: ${reason.message}`); } })
        .finally(() => { if (!controller.signal.aborted) setServiceLoading(false); });
    }, serviceQuery ? 250 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [activeView, servicePage, servicePageSize, serviceQuery, serviceSort, serviceDirection]);

  React.useEffect(() => {
    if (activeView !== "libraries") return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLibraryLoading(true);
      setLibraryError("");
      void getLibraryPage({ page: libraryPage, pageSize: libraryPageSize, query: libraryQuery, sort: librarySort, direction: libraryDirection, signal: controller.signal })
        .then((result) => { setLibraries(result.rows); setLibraryTotal(result.total); })
        .catch((reason: Error) => { if (reason.name !== "AbortError") { setLibraries([]); setLibraryTotal(0); setLibraryError(`Unable to load library usage: ${reason.message}`); } })
        .finally(() => { if (!controller.signal.aborted) setLibraryLoading(false); });
    }, libraryQuery ? 250 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [activeView, libraryPage, libraryPageSize, libraryQuery, librarySort, libraryDirection]);
  const totalCrypto = groups.reduce((sum, group) => sum + group.cryptoComponents, 0);
  const noData = groups.filter((group) => group.status === "no-data").length;
  const evidenceNeeded = groups.filter((group) => group.status === "needs-evidence" || group.status === "attention").length;

  const serviceColumns = React.useMemo<ColumnDef<ServiceInventory>[]>(() => [
    { accessorKey: "service", header: "Service", cell: ({ row }) => <div><p className="font-medium text-foreground">{row.original.service}</p><p className="mt-1 font-mono text-xs text-muted-foreground">{row.original.id}</p></div> },
    { accessorKey: "group", header: "Service group" },
    { accessorKey: "kind", header: "Record type", cell: ({ row }) => <span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-foreground">{row.original.kind}</span> },
    { accessorKey: "format", header: "Format" },
    { accessorKey: "cryptoComponents", header: "Crypto", enableSorting: false, cell: ({ row }) => <span className="font-mono">{row.original.cryptoComponents}</span> },
    { accessorKey: "libraries", header: "Libraries", enableSorting: false, cell: ({ row }) => <span className="font-mono">{row.original.libraries}</span> },
    { accessorKey: "checksum", header: "Checksum", enableSorting: false, cell: ({ row }) => <CompactHash hash={row.original.checksum} /> },
    { accessorKey: "observedAt", header: "Observed", cell: ({ row }) => <span className="whitespace-nowrap text-sm text-muted-foreground">{formatObserved(row.original.observedAt)}</span> },
    { id: "actions", header: "", enableSorting: false, cell: ({ row }) => <button className="table-action" type="button" onClick={() => setServiceDetail(row.original)}>View components</button> },
  ], []);

  const libraryColumns = React.useMemo<ColumnDef<LibraryInventory>[]>(() => [
    { accessorKey: "library", header: "Library", cell: ({ row }) => <div><p className="font-medium text-foreground">{row.original.library}</p><p className="mt-1 font-mono text-xs text-muted-foreground">{row.original.version}</p></div> },
    { accessorKey: "serviceGroups", header: "Groups", enableSorting: false, cell: ({ row }) => <div><span className="font-mono">{row.original.serviceGroups}</span><p className="mt-1 max-w-[220px] truncate text-xs text-muted-foreground" title={row.original.serviceGroupNames.join(", ")}>{row.original.serviceGroupNames.join(", ") || "—"}</p></div> },
    { accessorKey: "services", header: "Services", cell: ({ row }) => <span className="font-mono">{row.original.services}</span> },
    { accessorKey: "occurrences", header: "Occurrences", cell: ({ row }) => <span className="font-mono">{row.original.occurrences}</span> },
    { accessorKey: "classification", header: "Classification", enableSorting: false, cell: ({ row }) => <span className="inline-flex rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-xs text-sky-700 dark:text-sky-300">{row.original.classification}</span> },
    { accessorKey: "purl", header: "PURL", enableSorting: false, cell: ({ row }) => <span className="block max-w-[300px] truncate font-mono text-xs text-muted-foreground" title={row.original.purl}>{row.original.purl}</span> },
    { id: "actions", header: "", enableSorting: false, cell: ({ row }) => <button className="table-action" type="button" onClick={() => setLibraryDetail(row.original)}>View services</button> },
  ], []);

  return <div className="inventory-workbench">
    <section className="page-heading inventory-heading">
      <div><p className="eyebrow">Catalog intelligence</p><h1>Inventory workbench</h1><p className="page-subtitle">Move from service-group coverage to source records, then inspect the exact components and usage behind each row.</p></div>
      <div className="heading-actions"><span className="source-state">{loading ? "Loading catalog…" : source === "api" ? "Live catalog" : "Catalog unavailable"}</span><button className="refresh-button" type="button" onClick={() => void reload()} disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} />Refresh data</button></div>
    </section>

    {!loading && source === "unavailable" ? <div className="catalog-unavailable" role="alert"><FileWarning size={21} /><div><h2>Live inventory is unavailable</h2><p>No sample groups, services, libraries, or inventory totals are shown. Restore the catalog API, then refresh this page.</p><code>{error}</code></div></div> : null}

    {source === "api" ? <><section className="inventory-tabs" role="tablist" aria-label="Inventory views">
      {tabs.map((tab) => <button key={tab.id} id={`inventory-tab-${tab.id}`} ref={(node) => { tabRefs.current[tab.id] = node; }} type="button" role="tab" aria-selected={activeView === tab.id} aria-controls="inventory-tabpanel" tabIndex={activeView === tab.id ? 0 : -1} onClick={() => setActiveView(tab.id)} onKeyDown={(event) => { if (event.key === "ArrowLeft") { event.preventDefault(); selectAdjacentTab(tab.id, -1); } else if (event.key === "ArrowRight") { event.preventDefault(); selectAdjacentTab(tab.id, 1); } else if (event.key === "Home") { event.preventDefault(); setActiveView(tabs[0].id); tabRefs.current[tabs[0].id]?.focus(); } else if (event.key === "End") { event.preventDefault(); const last = tabs.at(-1)!.id; setActiveView(last); tabRefs.current[last]?.focus(); } }} className={activeView === tab.id ? "active" : ""}><span>{tab.label}</span><small>{tab.detail}</small></button>)}
    </section>

    <div id="inventory-tabpanel" role="tabpanel" aria-labelledby={`inventory-tab-${activeView}`}>
      {activeView === "coverage" ? <CoverageView groups={groups} /> : null}
      {activeView === "services" ? <section className="inventory-primary-view"><SectionHeading icon={FileKey2} title="Service records" description="Filter the catalog, verify provenance and fingerprint, then open a record to inspect every component." /><InventoryDataTable columns={serviceColumns} data={services} filterColumn="service" searchPlaceholder="Search service name…" loading={serviceLoading} errorMessage={serviceError} remote={{ total: serviceTotal, query: serviceQuery, page: servicePage, pageSize: servicePageSize, onQueryChange: (value) => { setServiceQuery(value); setServicePage(0); }, onPageChange: setServicePage, onPageSizeChange: (value) => { setServicePageSize(value); setServicePage(0); }, onSortChange: (column, direction) => { const map: Record<string, string> = { service: "service", group: "group", kind: "kind", format: "format", observedAt: "observed_at" }; setServiceSort(map[column] ?? "document_id"); setServiceDirection(direction); setServicePage(0); } }} /></section> : null}
      {activeView === "libraries" ? <section className="inventory-primary-view"><SectionHeading icon={LibraryBig} title="Library usage" description="Deduplicated package identities with a direct drill-in to every source record that uses the library." /><InventoryDataTable columns={libraryColumns} data={libraries} filterColumn="library" searchPlaceholder="Search library name…" loading={libraryLoading} errorMessage={libraryError} remote={{ total: libraryTotal, query: libraryQuery, page: libraryPage, pageSize: libraryPageSize, onQueryChange: (value) => { setLibraryQuery(value); setLibraryPage(0); }, onPageChange: setLibraryPage, onPageSizeChange: (value) => { setLibraryPageSize(value); setLibraryPage(0); }, onSortChange: (column, direction) => { const map: Record<string, string> = { library: "library", services: "document_count", occurrences: "occurrence_count" }; setLibrarySort(map[column] ?? "document_count"); setLibraryDirection(direction); setLibraryPage(0); } }} /></section> : null}
    </div>

    <section className="inventory-summary-grid" aria-label="Inventory summary">
      <SummaryMetric icon={Boxes} label="Catalog records" value={groups.reduce((sum, group) => sum + group.documents, 0).toLocaleString()} detail="Parsed service evidence" />
      <SummaryMetric icon={LibraryBig} label="Crypto occurrences" value={totalCrypto.toLocaleString()} detail="Candidate inventory" />
      <SummaryMetric icon={CircleAlert} label="Groups needing review" value={String(evidenceNeeded)} detail="Evidence or ingestion gaps" />
      <SummaryMetric icon={ShieldAlert} label="Empty categories" value={String(noData)} detail="Registered groups without current files" />
    </section>
    </> : null}

    {serviceDetail ? <ServiceComponentsDialog service={serviceDetail} onClose={() => setServiceDetail(null)} /> : null}
    {libraryDetail ? <LibraryUsageDialog library={libraryDetail} onClose={() => setLibraryDetail(null)} /> : null}
  </div>;
}

function CoverageView({ groups }: { groups: ServiceGroupInventory[] }) {
  const visibleHeatmap = [...groups].sort((a, b) => b.cryptoComponents - a.cryptoComponents).filter((group, index) => index < 12 || group.status === "no-data");
  const maxCrypto = Math.max(...visibleHeatmap.map((group) => group.cryptoComponents), 1);
  return <section className="inventory-primary-view">
    <SectionHeading icon={Boxes} title="Service-group matrix" description="Sort and filter the complete portfolio by coverage, candidate crypto volume, format, or evidence posture." />
    <InventoryDataTable columns={groupColumns} data={groups} filterColumn="group" searchPlaceholder="Search service groups…" />
    <div className="coverage-heatmap-card"><SectionHeading icon={Layers3} title="Coverage heatmap" description="Top candidate-crypto footprints plus every empty category. Intensity is volume, not compliance." /><div className="coverage-heatmap-grid">{visibleHeatmap.map((group) => { const amount = Math.max(3, Math.round((group.cryptoComponents / maxCrypto) * 100)); return <article key={group.group} className="heatmap-tile"><div className="heatmap-tile-heading"><strong>{group.group}</strong><StatusPill status={group.status} /></div><div className="heatmap-values"><div><strong>{group.cryptoComponents.toLocaleString()}</strong><span>crypto occurrence{group.cryptoComponents === 1 ? "" : "s"}</span></div><p>{group.services} service{group.services === 1 ? "" : "s"} · {group.uniqueLibraries} librar{group.uniqueLibraries === 1 ? "y" : "ies"}</p></div><div className="heatmap-track"><span style={{ width: `${amount}%` }} /></div></article>; })}</div></div>
  </section>;
}

function ModalFrame({ title, subtitle, onClose, children, footer }: { title: string; subtitle: string; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode }) {
  const dialogRef = React.useRef<HTMLElement>(null);
  const titleId = React.useId();
  React.useEffect(() => {
    const prior = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialogRef.current?.focus();
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
    return () => { document.removeEventListener("keydown", close); prior?.focus(); };
  }, [onClose]);
  return <div className="detail-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}><section ref={dialogRef} tabIndex={-1} className="detail-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}><header><div><h2 id={titleId}>{title}</h2><p>{subtitle}</p></div><button type="button" className="icon-button" aria-label="Close details" onClick={onClose}><X /></button></header><div className="detail-dialog-body">{children}</div>{footer ? <footer>{footer}</footer> : null}</section></div>;
}

function ServiceComponentsDialog({ service, onClose }: { service: ServiceInventory; onClose: () => void }) {
  const [rows, setRows] = React.useState<ComponentOccurrence[]>([]);
  const [query, setQuery] = React.useState("");
  const [cryptoOnly, setCryptoOnly] = React.useState(false);
  const [page, setPage] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const pageSize = 100;
  React.useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ limit: String(pageSize), offset: String(page * pageSize), crypto_only: String(cryptoOnly) });
    if (query.trim()) params.set("query", query.trim());
    const timer = window.setTimeout(() => {
      void fetchJson<ComponentOccurrence[]>(`/api/v1/documents/${numericId(service.id)}/components?${params}`, { signal: controller.signal, dedupe: false }).then(setRows).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [service.id, query, cryptoOnly, page]);
  return <ModalFrame title={service.service} subtitle={`${service.group} · ${service.kind} · ${service.format}`} onClose={onClose} footer={<div className="detail-pagination"><span>Page {page + 1} · up to {pageSize} components</span><div><button type="button" disabled={page === 0} onClick={() => { setLoading(true); setError(""); setPage((value) => Math.max(0, value - 1)); }}>Previous</button><button type="button" disabled={rows.length < pageSize} onClick={() => { setLoading(true); setError(""); setPage((value) => value + 1); }}>Next</button></div></div>}>
    <div className="detail-toolbar"><label><Search /><input value={query} onChange={(event) => { setLoading(true); setError(""); setQuery(event.target.value); setPage(0); }} placeholder="Search component, version, or PURL" /></label><label className="detail-checkbox"><input type="checkbox" checked={cryptoOnly} onChange={(event) => { setLoading(true); setError(""); setCryptoOnly(event.target.checked); setPage(0); }} /> Explicit crypto only</label></div>
    <p className="detail-provenance"><strong>Source:</strong> {service.provenance}<br /><strong>SHA-256:</strong> <span className="font-mono">{service.checksum}</span></p>
    {error ? <p className="detail-error">{error}</p> : <div className="detail-table-wrap"><table><thead><tr><th>Component</th><th>Type</th><th>Scope</th><th>Classification</th><th>PURL</th></tr></thead><tbody>{rows.map((row) => <tr key={row.occurrence_id}><td><strong>{row.name}</strong><span>{row.version || "Version not supplied"}</span></td><td>{row.component_type || "—"}</td><td>{row.scope || "—"}</td><td>{row.explicit_crypto ? <span className="classification-pill">Explicit crypto</span> : "Inventory component"}</td><td><span className="detail-purl" title={row.canonical_purl || ""}>{row.canonical_purl || "—"}</span></td></tr>)}{!loading && !rows.length ? <tr><td colSpan={5} className="detail-empty">No components match this view.</td></tr> : null}</tbody></table>{loading ? <p className="detail-loading">Loading components…</p> : null}</div>}
  </ModalFrame>;
}

function LibraryUsageDialog({ library, onClose }: { library: LibraryInventory; onClose: () => void }) {
  const [rows, setRows] = React.useState<ComponentUsage[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [page, setPage] = React.useState(0);
  const pageSize = 100;
  React.useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void fetchJson<ComponentUsage[]>(`/api/v1/components/${numericId(library.id)}/usage?limit=${pageSize}&offset=${page * pageSize}`, { signal: controller.signal, dedupe: false }).then(setRows).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [library.id, page]);
  return <ModalFrame title={library.library} subtitle={`${library.version} · ${library.occurrences.toLocaleString()} occurrence${library.occurrences === 1 ? "" : "s"}`} onClose={onClose} footer={<div className="detail-pagination"><span>Page {page + 1} · up to {pageSize} usages</span><div><button type="button" disabled={page === 0} onClick={() => { setLoading(true); setPage((value) => Math.max(0, value - 1)); }}>Previous</button><button type="button" disabled={rows.length < pageSize} onClick={() => { setLoading(true); setPage((value) => value + 1); }}>Next</button></div></div>}>
    <p className="detail-provenance"><strong>Canonical package:</strong> <span className="font-mono">{library.purl}</span></p>
    {error ? <p className="detail-error">{error}</p> : <div className="detail-table-wrap"><table><thead><tr><th>Service group</th><th>Source record</th><th>Document</th><th>Scope</th></tr></thead><tbody>{rows.map((row) => <tr key={row.occurrence_id}><td><strong>{row.service_groups?.join(", ") || "Unassigned"}</strong></td><td><span className="detail-purl" title={row.source_paths?.join(", ")}>{row.source_paths?.join(", ") || "—"}</span></td><td>{row.document_kind} {row.spec_version}</td><td>{row.scope || "—"}</td></tr>)}{!loading && !rows.length ? <tr><td colSpan={4} className="detail-empty">No service usage was returned.</td></tr> : null}</tbody></table>{loading ? <p className="detail-loading">Loading service usage…</p> : null}</div>}
  </ModalFrame>;
}
