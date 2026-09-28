"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle, ArrowDown, ArrowUp, BookOpenCheck, Boxes, CalendarClock,
  ChevronRight, CircleAlert, ClipboardList, ExternalLink, FileCode2, FilterX,
  ChevronsDownUp,
  LibraryBig, RefreshCw, Search, ShieldCheck, UserRound, UsersRound, X,
} from "lucide-react";
import { Badge } from "@/app/components/ui/badge";
import { useConsoleAccess } from "@/app/components/console-shell";
import { AssignedServiceUnion } from "@/components/access/assigned-service-union";
import { getDocumentCryptoComponents, getServiceGroupDetail, getServiceGroupRegister } from "@/components/accountability/accountability-data";
import type { AssignedScopePair } from "@/app/lib/scope";
import type { CatalogDocument, CryptoComponent, PlanningSummary, RegisterResponse, ServiceGroupDetail, ServiceGroupRegisterRow, TargetModulePlanningRecord } from "@/components/accountability/types";

type Direction = "asc" | "desc";
type SortKey = "effective_owner" | "service_group" | "lead" | "il2" | "il5" | "documents" | "libraries" | "findings" | "poam";

function formatDate(value: string | null | undefined) {
  if (!value) return "Not supplied";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`));
}

function ownerLabel(row: ServiceGroupRegisterRow) {
  if (!row.effective_owners.length) return "Not supplied";
  if (row.effective_owners.length > 1) return `Multiple — ${row.effective_owners.join(", ")}`;
  return row.effective_owners[0];
}

function ownerGroupId(owner: string) {
  const slug = owner.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return `accountability-owner-${slug || "unknown"}`;
}

function PlanningCell({ plan, label }: { plan: PlanningSummary; label: string }) {
  const title = plan.entries.map((entry) => `${entry.team}: ${entry.raw_value || "Not supplied"}`).join("\n");
  // Tracker values are planning assertions.  They must not look like a CBOM
  // assessment conclusion or a verified migration outcome.
  if (plan.state === "done") return <Badge tone="neutral">{label}: Done</Badge>;
  if (plan.state === "vendor_dependency") return <Badge tone="warning">VENDOR DEPENDENCY</Badge>;
  if (plan.state === "not_applicable") return <Badge tone="neutral">NA</Badge>;
  if (plan.state !== "dated") return <span title={title} className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-amber-700 dark:text-amber-300"><CircleAlert className="size-3.5" />Date missing</span>;
  return <div title={title}><span className="whitespace-nowrap font-mono text-xs text-foreground">{label}: {formatDate(plan.explicit_dates[0])}</span>{plan.explicit_dates.length > 1 ? <span className="mt-1 block text-[11px] text-muted-foreground">Latest {label}: {formatDate(plan.farthest_date)} · {plan.explicit_dates.length} dates</span> : null}</div>;
}

function verificationTone(value: string | undefined): "success" | "warning" | "danger" | "neutral" {
  if (value === "corroborated") return "success";
  if (value === "contradicted" || value === "conflicting_evidence") return "danger";
  if (value === "partially_corroborated" || value === "not_observed") return "warning";
  return "neutral";
}

function targetPlanningConcerns(modules: TargetModulePlanningRecord[]) {
  return modules.filter((module) => module.normalized_status === "asserted_not_compliant" || ["contradicted", "conflicting_evidence"].includes(module.verification?.overall?.state || ""));
}

function TargetPlanningAssertions({ modules }: { modules: TargetModulePlanningRecord[] }) {
  const concerns = targetPlanningConcerns(modules);
  if (!concerns.length) return null;
  return <div className="workstream-list"><h4>Target-module planning assertions — not assessment findings</h4>{concerns.map((module, index) => {
    const verification = module.verification?.overall?.state || "not_assessable";
    return <article key={module.record_sha256 || `${module.team}-${index}`}><div><Badge tone="warning">User asserted</Badge><Badge tone={verificationTone(verification)}>{verification.replaceAll("_", " ")}</Badge></div><strong>{module.current_module || "Current module not supplied"} → {module.target_module || "Target module not supplied"}</strong><span>{module.team || "Team not supplied"} · {module.asserted_status || module.normalized_status.replaceAll("_", " ")}</span></article>;
  })}</div>;
}

function riskTone(value: string | null): "neutral" | "info" | "warning" | "danger" | "success" {
  switch (value?.trim().toLowerCase()) {
    case "critical": return "danger";
    case "high": return "warning";
    case "moderate": return "info";
    case "low": return "success";
    default: return "neutral";
  }
}

function SortButton({ id, active, direction, children, onSort }: { id: SortKey; active: SortKey; direction: Direction; children: React.ReactNode; onSort: (id: SortKey) => void }) {
  const Icon = active === id && direction === "desc" ? ArrowDown : ArrowUp;
  return <button type="button" aria-label={`Sort by ${typeof children === "string" ? children : "column"}${active === id ? `, ${direction === "asc" ? "ascending" : "descending"}` : ""}`} className="inline-flex items-center gap-1 whitespace-nowrap font-semibold tracking-[.07em] text-muted-foreground hover:text-foreground" onClick={() => onSort(id)}>{children}<Icon className={`size-3 ${active === id ? "opacity-100" : "opacity-25"}`} /></button>;
}

export function ServiceAccountability() {
  const access = useConsoleAccess();
  if (access.isAdmin) return <AdminServiceAccountability />;
  if (!access.detailAccess || access.pairs.length !== 1) {
    return <AssignedServiceUnion title="Accountability across assigned products" description="All service groups granted by your verified product groups appear together. Planning and POA&M decisions remain unavailable without collection provenance." renderScope={access.detailAccess ? (scope) => <ScopedServiceAccountability scope={scope} /> : undefined} />;
  }
  if (!access.selected) return <section className="scope-gate scope-gate-unavailable" role="alert"><AlertTriangle />A verified service scope is required.</section>;
  return <ScopedServiceAccountability scope={access.selected} />;
}

function AdminServiceAccountability() {
  const pageSize = 250;
  const [register, setRegister] = React.useState<RegisterResponse | null>(null);
  const [error, setError] = React.useState<{ offset: number; message: string } | null>(null);
  const [selected, setSelected] = React.useState<ServiceGroupRegisterRow | null>(null);
  const [offset, setOffset] = React.useState(0);
  const [revision, setRevision] = React.useState(0);
  React.useEffect(() => {
    const controller = new AbortController();
    void getServiceGroupRegister({ query: "", owner: "", lead: "", il2State: "", il5State: "", action: "", sort: "service_group", direction: "asc", page: 0, pageSize, offset, signal: controller.signal })
      .then(setRegister)
      .catch((reason: Error) => { if (reason.name !== "AbortError") setError({ offset, message: reason.message || "The portfolio register request failed." }); });
    return () => controller.abort();
  }, [offset, revision]);
  const currentRegister = register?.offset === offset ? register : null;
  const currentError = error?.offset === offset ? error.message : "";
  const loading = !currentRegister && !currentError;
  const rangeStart = currentRegister?.total ? currentRegister.offset + 1 : 0;
  const rangeEnd = currentRegister ? Math.min(currentRegister.offset + currentRegister.items.length, currentRegister.total) : 0;
  return <div className="accountability-workbench">
    <section className="page-heading inventory-heading"><div><p className="eyebrow">Administrative portfolio register</p><h1>Service accountability</h1><p className="page-subtitle">Full planning and candidate context is available only to verified administrators. Planning values remain user-authored assertions and require review.</p></div><div className="heading-actions"><Badge tone={currentError ? "danger" : "neutral"}>{currentError ? "Data unavailable" : loading ? "Loading register" : "Register available"}</Badge><button className="refresh-button" type="button" disabled={loading} onClick={() => { setRegister(null); setError(null); setRevision((value) => value + 1); }}><RefreshCw className={loading ? "spin" : ""} size={17} />Refresh</button></div></section>
    {currentError ? <section className="rounded-2xl border border-danger/30 bg-card p-6 text-sm text-danger" role="alert">Unable to load the portfolio register: {currentError}</section> : null}
    {loading ? <section className="rounded-2xl border border-border bg-card p-10 text-center text-sm text-muted-foreground">Loading the administrative portfolio register…</section> : null}
    {currentRegister ? <section className="rounded-2xl border border-border bg-card shadow-sm" aria-label="Administrative service accountability register"><div className="accountability-summary"><span><strong className="text-foreground">{rangeStart}–{rangeEnd}</strong> of {currentRegister.total} service groups</span><span className="text-xs text-muted-foreground">Planning is user-authored. Candidate output requires authorized assessor and AO review.</span></div><p className="table-scroll-hint" id="admin-accountability-scroll-hint">Scroll horizontally to review ownership, planning, evidence, review signals, and actions.</p><div className="accountability-table-scroll" aria-describedby="admin-accountability-scroll-hint"><table className="accountability-table"><thead><tr><th>Service group</th><th>Owner and lead</th><th>Planning dates</th><th>Evidence</th><th>Review signals</th><th>Open</th></tr></thead><tbody>{currentRegister.items.map((row) => <tr key={row.service_key} className="accountability-row"><td><strong>{row.display_name}</strong><span className="mono">{row.service_key}</span></td><td><strong className="text-sm">{ownerLabel(row)}</strong><span className="text-xs text-muted-foreground">{row.leads.join(", ") || "Lead not supplied"}</span></td><td><PlanningCell plan={row.il2} label="IL2" /><PlanningCell plan={row.il5} label="IL5" /></td><td><div className="table-count"><strong>{row.documents}</strong><small>{row.documents_with_fips_evidence}/{row.documents} documents with FIPS-related evidence · {row.candidate_crypto_assets} crypto assets</small></div></td><td><div className="table-count"><strong>{row.finding_count}</strong><small>{row.review_observations} evidence review · {row.poam_candidate_count} draft POA&amp;M</small></div></td><td><button type="button" className="table-action" onClick={() => setSelected(row)} aria-label={`Open details for ${row.display_name}`}>Details <ChevronRight className="size-3.5" /></button></td></tr>)}</tbody></table></div>{currentRegister.total > currentRegister.limit ? <nav className="accountability-pagination" aria-label="Administrative portfolio register pages"><button type="button" className="secondary-button" disabled={loading || currentRegister.offset === 0} onClick={() => setOffset(Math.max(0, currentRegister.offset - currentRegister.limit))}>Previous</button><span>Showing {rangeStart}–{rangeEnd} of {currentRegister.total}</span><button type="button" className="secondary-button" disabled={loading || rangeEnd >= currentRegister.total} onClick={() => setOffset(currentRegister.offset + currentRegister.limit)}>Next</button></nav> : null}</section> : null}
    {selected ? <ServiceGroupDrawer row={selected} onClose={() => setSelected(null)} /> : null}
  </div>;
}

type ScopedAccountabilityView = "summary" | "documents" | "libraries" | "observations";

const scopedAccountabilityTabs: Array<{ id: ScopedAccountabilityView; label: string; detail: string }> = [
  { id: "summary", label: "Summary", detail: "Catalog evidence at a glance" },
  { id: "documents", label: "Documents", detail: "Scoped source evidence" },
  { id: "libraries", label: "Libraries", detail: "Explicit crypto metadata" },
  { id: "observations", label: "Observations", detail: "Evidence requests and review-only observations" },
];

function scopedAccountabilityView(value: string | null): ScopedAccountabilityView {
  return scopedAccountabilityTabs.some((tab) => tab.id === value) ? value as ScopedAccountabilityView : "summary";
}

function ScopedServiceAccountability({ scope }: { scope: AssignedScopePair }) {
  const pageSize = 50;
  const tabBase = React.useId().replaceAll(":", "");
  const [detail, setDetail] = React.useState<ServiceGroupDetail | null>(null);
  const [error, setError] = React.useState<{ key: string; message: string } | null>(null);
  const [pagination, setPagination] = React.useState({ scopeKey: "", documentOffset: 0, libraryOffset: 0 });
  const [revision, setRevision] = React.useState(0);
  const [activeView, setActiveView] = React.useState<ScopedAccountabilityView>(() => typeof window === "undefined" ? "summary" : scopedAccountabilityView(new URLSearchParams(window.location.search).get("view")));
  const tabRefs = React.useRef<Record<ScopedAccountabilityView, HTMLButtonElement | null>>({ summary: null, documents: null, libraries: null, observations: null });
  const activePagination = pagination.scopeKey === scope.key ? pagination : { scopeKey: scope.key, documentOffset: 0, libraryOffset: 0 };
  const requestKey = `${scope.key}:${activePagination.documentOffset}:${activePagination.libraryOffset}`;

  const selectView = React.useCallback((view: ScopedAccountabilityView, historyMode: "push" | "replace" = "push") => {
    setActiveView(view);
    const params = new URLSearchParams(window.location.search);
    params.set("view", view);
    const next = `${window.location.pathname}?${params.toString()}${window.location.hash}`;
    window.history[historyMode === "push" ? "pushState" : "replaceState"](window.history.state, "", next);
    window.dispatchEvent(new CustomEvent<ScopedAccountabilityView>("accountability-viewchange", { detail: view }));
  }, []);

  React.useEffect(() => {
    const onPopState = () => setActiveView(scopedAccountabilityView(new URLSearchParams(window.location.search).get("view")));
    const onViewChange = (event: Event) => setActiveView((event as CustomEvent<ScopedAccountabilityView>).detail);
    window.addEventListener("popstate", onPopState);
    window.addEventListener("accountability-viewchange", onViewChange);
    return () => { window.removeEventListener("popstate", onPopState); window.removeEventListener("accountability-viewchange", onViewChange); };
  }, []);

  const selectAdjacentTab = (current: ScopedAccountabilityView, direction: -1 | 1) => {
    const currentIndex = scopedAccountabilityTabs.findIndex((tab) => tab.id === current);
    const next = scopedAccountabilityTabs[(currentIndex + direction + scopedAccountabilityTabs.length) % scopedAccountabilityTabs.length].id;
    selectView(next);
    tabRefs.current[next]?.focus();
  };
  React.useEffect(() => {
    const controller = new AbortController();
    void getServiceGroupDetail(scope.sourceCollection, scope.serviceGroup, {
      documentLimit: pageSize,
      documentOffset: activePagination.documentOffset,
      libraryLimit: pageSize,
      libraryOffset: activePagination.libraryOffset,
      productScopeId: scope.productScopeId,
    }, controller.signal)
      .then(setDetail)
      .catch((reason: Error) => { if (reason.name !== "AbortError") setError({ key: requestKey, message: reason.message || "The scoped evidence request failed." }); });
    return () => controller.abort();
  }, [activePagination.documentOffset, activePagination.libraryOffset, requestKey, scope.productScopeId, scope.sourceCollection, scope.serviceGroup, revision]);

  const scopedDetail = detail?.profile.source_collection === scope.sourceCollection && detail.profile.service_group === scope.serviceGroup && detail.documents.offset === activePagination.documentOffset && detail.libraries.offset === activePagination.libraryOffset ? detail : null;
  const scopedError = error?.key === requestKey ? error.message : "";
  const loading = !scopedDetail && !scopedError;
  const observations = (scopedDetail?.assessment.findings ?? []).filter((finding) => !finding.poam_eligible);
  const evidenceRequests = scopedDetail?.assessment.coverage_gaps ?? [];

  return <div className="accountability-workbench">
    <section className="page-heading inventory-heading">
      <div><p className="eyebrow">Scoped catalog evidence</p><h1>Service accountability</h1><p className="page-subtitle">Evidence-only view for {scope.key}. Planning ownership, dates, risk assertions, and candidate disposition are withheld because they do not carry provenance for this selected pair.</p></div>
      <div className="heading-actions"><Badge tone={scopedError ? "danger" : "neutral"}>{scopedError ? "Data unavailable" : loading ? "Loading evidence" : "Evidence available"}</Badge><button className="refresh-button" type="button" disabled={loading} onClick={() => { setDetail(null); setError(null); setRevision((value) => value + 1); }}><RefreshCw className={loading ? "spin" : ""} size={17} />Refresh</button></div>
    </section>
    {scopedError ? <section className="rounded-2xl border border-danger/30 bg-card p-6 text-sm text-danger" role="alert">Unable to load scoped evidence: {scopedError}</section> : null}
    {loading ? <section className="rounded-2xl border border-border bg-card p-10 text-center text-sm text-muted-foreground">Loading evidence for the selected service group…</section> : null}
    {scopedDetail ? <>
      <section className="accountability-tabs" role="tablist" aria-label="Scoped accountability views">
        {scopedAccountabilityTabs.map((tab) => <button key={tab.id} id={`${tabBase}-accountability-tab-${tab.id}`} ref={(node) => { tabRefs.current[tab.id] = node; }} type="button" role="tab" aria-selected={activeView === tab.id} aria-controls={`${tabBase}-accountability-tabpanel`} tabIndex={activeView === tab.id ? 0 : -1} onClick={() => selectView(tab.id)} onKeyDown={(event) => { if (event.key === "ArrowLeft") { event.preventDefault(); selectAdjacentTab(tab.id, -1); } else if (event.key === "ArrowRight") { event.preventDefault(); selectAdjacentTab(tab.id, 1); } else if (event.key === "Home") { event.preventDefault(); selectView(scopedAccountabilityTabs[0].id); tabRefs.current.summary?.focus(); } else if (event.key === "End") { event.preventDefault(); const last = scopedAccountabilityTabs.at(-1)!.id; selectView(last); tabRefs.current[last]?.focus(); } }} className={activeView === tab.id ? "active" : ""}><span>{tab.label}</span><small>{tab.detail}</small></button>)}
      </section>
      <div id={`${tabBase}-accountability-tabpanel`} role="tabpanel" aria-labelledby={`${tabBase}-accountability-tab-${activeView}`}>
        {activeView === "summary" ? <section className="rounded-2xl border border-border bg-card p-6 shadow-sm" aria-label="Scoped evidence summary"><div className="drawer-metric-grid"><DrawerMetric label="Catalog documents" value={String(scopedDetail.profile.documents)} /><DrawerMetric label="Documents with FIPS-related evidence" value={`${scopedDetail.profile.documents_with_fips_evidence}/${scopedDetail.profile.documents}`} /><DrawerMetric label="Crypto asset occurrences" value={String(scopedDetail.profile.crypto_component_occurrences)} /><DrawerMetric label="Evidence observations" value={String(observations.length + evidenceRequests.length)} /></div><p className="mt-5 text-xs leading-5 text-muted-foreground"><ShieldCheck className="mr-2 inline size-4 align-text-bottom" />These records are catalog evidence for {scope.key}. They do not establish CMVP validation, deployment state, compliance, remediation completion, or an authorized POA&amp;M.</p></section> : null}
        {activeView === "documents" ? <section className="rounded-2xl border border-border bg-card p-6 shadow-sm"><div className="card-heading"><div><p className="eyebrow">Catalog documents</p><h2>Scoped source evidence</h2><p>Showing {scopedDetail.documents.total ? `${scopedDetail.documents.offset + 1}–${Math.min(scopedDetail.documents.offset + scopedDetail.documents.items.length, scopedDetail.documents.total)}` : "0"} of {scopedDetail.documents.total} documents. Only the selected source collection, service group, and product context are included.</p></div></div><div className="document-list">{scopedDetail.documents.items.map((document) => <div key={document.document_id} className="rounded-lg border border-border px-4 py-3"><strong>{document.source_paths?.[0]?.split("/").at(-1) || `Document ${document.document_id}`}</strong><small className="mt-1 block">{document.document_kind} · {document.format_name} {document.spec_version} · {document.unique_crypto_components} crypto assets</small><code className="mt-2 block text-xs">SHA-256 {document.sha256}</code></div>)}{!scopedDetail.documents.items.length ? <div className="drawer-empty"><FileCode2 />No catalog documents were returned for this selected pair.</div> : null}</div>{scopedDetail.documents.total > scopedDetail.documents.limit ? <nav className="accountability-pagination" aria-label="Scoped catalog document pages"><button type="button" className="secondary-button" disabled={scopedDetail.documents.offset === 0} onClick={() => setPagination((value) => ({ scopeKey: scope.key, documentOffset: Math.max(0, scopedDetail.documents.offset - scopedDetail.documents.limit), libraryOffset: value.scopeKey === scope.key ? value.libraryOffset : 0 }))}>Previous</button><span>Showing {scopedDetail.documents.offset + 1}–{Math.min(scopedDetail.documents.offset + scopedDetail.documents.items.length, scopedDetail.documents.total)} of {scopedDetail.documents.total}</span><button type="button" className="secondary-button" disabled={scopedDetail.documents.offset + scopedDetail.documents.items.length >= scopedDetail.documents.total} onClick={() => setPagination((value) => ({ scopeKey: scope.key, documentOffset: scopedDetail.documents.offset + scopedDetail.documents.limit, libraryOffset: value.scopeKey === scope.key ? value.libraryOffset : 0 }))}>Next</button></nav> : null}</section> : null}
        {activeView === "libraries" ? <section className="rounded-2xl border border-border bg-card p-6 shadow-sm"><div className="card-heading"><div><p className="eyebrow">Explicit crypto metadata</p><h2>Scoped libraries</h2><p>Showing {scopedDetail.libraries.total ? `${scopedDetail.libraries.offset + 1}–${Math.min(scopedDetail.libraries.offset + scopedDetail.libraries.items.length, scopedDetail.libraries.total)}` : "0"} of {scopedDetail.libraries.total} libraries. These catalog metadata records need evidence review.</p></div></div><div className="library-list">{scopedDetail.libraries.items.map((library) => <article key={library.component_id}><div><strong>{library.name}</strong><span>{library.version || "Version not supplied"}</span></div><div><b>{library.document_count}</b><span>documents</span></div><code title={library.canonical_purl || ""}>{library.canonical_purl || "No canonical PURL"}</code></article>)}{!scopedDetail.libraries.items.length ? <div className="drawer-empty"><LibraryBig />No explicit crypto libraries were returned.</div> : null}</div>{scopedDetail.libraries.total > scopedDetail.libraries.limit ? <nav className="accountability-pagination" aria-label="Scoped library pages"><button type="button" className="secondary-button" disabled={scopedDetail.libraries.offset === 0} onClick={() => setPagination((value) => ({ scopeKey: scope.key, documentOffset: value.scopeKey === scope.key ? value.documentOffset : 0, libraryOffset: Math.max(0, scopedDetail.libraries.offset - scopedDetail.libraries.limit) }))}>Previous</button><span>Showing {scopedDetail.libraries.offset + 1}–{Math.min(scopedDetail.libraries.offset + scopedDetail.libraries.items.length, scopedDetail.libraries.total)} of {scopedDetail.libraries.total}</span><button type="button" className="secondary-button" disabled={scopedDetail.libraries.offset + scopedDetail.libraries.items.length >= scopedDetail.libraries.total} onClick={() => setPagination((value) => ({ scopeKey: scope.key, documentOffset: value.scopeKey === scope.key ? value.documentOffset : 0, libraryOffset: scopedDetail.libraries.offset + scopedDetail.libraries.limit }))}>Next</button></nav> : null}</section> : null}
        {activeView === "observations" ? <section className="rounded-2xl border border-border bg-card p-6 shadow-sm"><div className="card-heading"><div><p className="eyebrow">Review-only</p><h2>Evidence observations</h2><p>Observations and evidence requests are not POA&amp;M candidates.</p></div></div>{evidenceRequests.length ? <div className="evidence-request-list"><h4>Evidence requests</h4>{evidenceRequests.map((gap) => <article key={gap.observation_id}><Badge tone="warning">{gap.assertion_state.replaceAll("_", " ")}</Badge><strong>{gap.title}</strong><p>{gap.technical_observation}</p></article>)}</div> : null}<div className="finding-list">{observations.map((finding) => <article key={finding.finding_id}><div><Badge tone="neutral">{finding.assertion_state.replaceAll("_", " ")}</Badge><code>{finding.rule_id}</code></div><strong>{finding.title}</strong><p>{finding.subject_name}</p><span>Evidence review only</span></article>)}{!observations.length && !evidenceRequests.length ? <div className="drawer-empty"><ShieldCheck />No evidence observations were returned for this selected pair.</div> : null}</div></section> : null}
      </div>
    </> : null}
  </div>;
}

type DrawerView = "summary" | "evidence" | "findings" | "planning";

const drawerViews: Array<{ id: DrawerView; label: string; detail: string }> = [
  { id: "summary", label: "Summary", detail: "Scope and catalog facts" },
  { id: "evidence", label: "Evidence", detail: "Libraries and documents" },
  { id: "findings", label: "Findings", detail: "Evidence requests and candidates" },
  { id: "planning", label: "Planning", detail: "Owners and target assertions" },
];

export function ServiceGroupDrawer({ row, onClose }: { row: Pick<ServiceGroupRegisterRow, "service_key" | "source_collection" | "service_group" | "display_name">; onClose: () => void }) {
  const [detail, setDetail] = React.useState<ServiceGroupDetail | null>(null);
  const [error, setError] = React.useState("");
  const [selectedDocument, setSelectedDocument] = React.useState<CatalogDocument | null>(null);
  const [components, setComponents] = React.useState<CryptoComponent[]>([]);
  const [componentsLoading, setComponentsLoading] = React.useState(false);
  const [componentsError, setComponentsError] = React.useState("");
  const [showAllLibraries, setShowAllLibraries] = React.useState(false);
  const [showAllFindings, setShowAllFindings] = React.useState(false);
  const [activeView, setActiveView] = React.useState<DrawerView>("summary");
  const panelRef = React.useRef<HTMLElement>(null);
  const tabRefs = React.useRef<Record<DrawerView, HTMLButtonElement | null>>({ summary: null, evidence: null, findings: null, planning: null });
  const titleId = React.useId();
  const descriptionId = React.useId();
  const tabBase = React.useId().replaceAll(":", "");

  React.useEffect(() => {
    const controller = new AbortController();
    void getServiceGroupDetail(row.source_collection, row.service_group, undefined, controller.signal).then(setDetail).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); });
    return () => controller.abort();
  }, [row]);
  React.useEffect(() => {
    if (!selectedDocument) return;
    const controller = new AbortController();
    void getDocumentCryptoComponents(selectedDocument.document_id, {
      sourceCollection: row.source_collection,
      serviceGroup: row.service_group,
      key: row.service_key,
    }, controller.signal).then(setComponents).catch((reason: Error) => { if (reason.name !== "AbortError") { setComponents([]); setComponentsError(reason.message || "The component request failed."); } }).finally(() => { if (!controller.signal.aborted) setComponentsLoading(false); });
    return () => controller.abort();
  }, [row.source_collection, row.service_group, row.service_key, selectedDocument]);
  React.useEffect(() => {
    const prior = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const appRoot = document.querySelector("main");
    const priorOverflow = document.body.style.overflow;
    const priorPadding = document.body.style.paddingRight;
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = "hidden";
    if (scrollbarWidth) document.body.style.paddingRight = `${scrollbarWidth}px`;
    appRoot?.setAttribute("inert", "");
    const focusable = () => Array.from(panelRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? []).filter((node) => !node.hasAttribute("hidden"));
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab") return;
      const nodes = focusable();
      if (!nodes.length) { event.preventDefault(); panelRef.current?.focus(); return; }
      const first = nodes[0]; const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", keydown);
    window.setTimeout(() => focusable()[0]?.focus() ?? panelRef.current?.focus(), 0);
    return () => { document.removeEventListener("keydown", keydown); document.body.style.overflow = priorOverflow; document.body.style.paddingRight = priorPadding; appRoot?.removeAttribute("inert"); prior?.focus(); };
  }, [onClose]);

  const findings = detail?.assessment.findings ?? [];
  const hasCandidateFindings = findings.some((finding) => finding.poam_eligible);
  const hasEvidenceObservations = findings.some((finding) => !finding.poam_eligible);
  const findingRecordLabel = !hasCandidateFindings ? "evidence observations" : hasEvidenceObservations ? "assessment records" : "candidate findings";
  const findingSectionTitle = !hasCandidateFindings ? "Evidence observations" : hasEvidenceObservations ? "Assessment records" : "Candidate findings";
  const findingSectionSubtitle = !hasCandidateFindings ? "Evidence observations are not POA&M eligible." : "Evidence requests remain separate from POA&M-eligible candidate findings.";
  const selectAdjacentView = (view: DrawerView, direction: -1 | 1) => {
    const current = drawerViews.findIndex((item) => item.id === view);
    const next = drawerViews[(current + direction + drawerViews.length) % drawerViews.length].id;
    setActiveView(next);
    tabRefs.current[next]?.focus();
  };

  const drawer = <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}><aside ref={panelRef} tabIndex={-1} className="service-drawer" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}>
    <header className="service-drawer-header"><div><p className="eyebrow">Scoped service-group record</p><h2 id={titleId}>{row.display_name}</h2><p id={descriptionId}>{row.service_key}. Planning metadata and candidate analysis require authorized review.</p></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close service details"><X /></button></header>
    <div className="service-drawer-body">{error ? <div className="detail-error" role="alert">Unable to load service details: {error}</div> : !detail ? <div className="drawer-loading">Loading scoped evidence and planning context…</div> : <>
      <section className="accountability-tabs" role="tablist" aria-label="Service detail views">
        {drawerViews.map((view) => <button key={view.id} id={`${tabBase}-drawer-tab-${view.id}`} ref={(node) => { tabRefs.current[view.id] = node; }} type="button" role="tab" aria-selected={activeView === view.id} aria-controls={`${tabBase}-drawer-panel`} tabIndex={activeView === view.id ? 0 : -1} className={activeView === view.id ? "active" : ""} onClick={() => setActiveView(view.id)} onKeyDown={(event) => { if (event.key === "ArrowLeft") { event.preventDefault(); selectAdjacentView(view.id, -1); } else if (event.key === "ArrowRight") { event.preventDefault(); selectAdjacentView(view.id, 1); } else if (event.key === "Home") { event.preventDefault(); setActiveView("summary"); tabRefs.current.summary?.focus(); } else if (event.key === "End") { event.preventDefault(); setActiveView("planning"); tabRefs.current.planning?.focus(); } }}><span>{view.label}</span><small>{view.detail}</small></button>)}
      </section>
      <div id={`${tabBase}-drawer-panel`} role="tabpanel" aria-labelledby={`${tabBase}-drawer-tab-${activeView}`}>
      {activeView === "summary" ? <>
      <DrawerSection icon={BookOpenCheck} title="Scope and catalog summary" subtitle="Catalog counts describe parsed records only; they are not proof of deployment or compliance.">
        <div className="drawer-metric-grid"><DrawerMetric label="Catalog documents" value={String(detail.profile.documents)} /><DrawerMetric label="Documents with FIPS/CMVP-related records" value={`${detail.profile.documents_with_fips_evidence}/${detail.profile.documents}`} /><DrawerMetric label="Candidate crypto assets" value={String(detail.profile.candidate_crypto_assets)} /><DrawerMetric label="Ingest issues" value={String(detail.profile.ingest_issues)} /></div>
        <p className="source-note">FIPS/CMVP-related records are catalog metadata only. They do not establish CMVP validation, deployment state, approved mode, or compliance.</p>
        <div className="provenance-strip"><span>Internal analysis ID <strong>{detail.assessment.assessment_run_id || "Not supplied"}</strong></span><span>Assessment run <strong>{detail.assessment.canonical_assessment_run_id || "Not established"}</strong></span><span>Policy <strong>{detail.assessment.policy?.policy_version || "Not supplied"}</strong></span></div>
      </DrawerSection>
      </> : null}

      {activeView === "planning" ? <>
      <DrawerSection icon={UsersRound} title="Ownership and planning context" subtitle="Effective owner and lead are derived from the reviewed Team Tracker mapping.">
        <div className="owner-summary"><div><span>Executive owner</span><strong>{detail.profile.effective_owners.join(", ") || "Not supplied"}</strong></div><div><span>Lead</span><strong>{detail.profile.leads.join(", ") || "Not supplied"}</strong></div><div><span>Mapping</span><strong>{detail.profile.mapping_status === "mapped" ? "Mapped" : "Not mapped"}</strong></div></div>
        <div className="tracker-list">{detail.tracker.profile.tracker_rows.length ? detail.tracker.profile.tracker_rows.map((tracker) => <article key={`${tracker.team}-${tracker.lead}`}><div><strong>{tracker.team}</strong><span>{tracker.owner || "Owner not supplied"} · {tracker.lead || "Lead not supplied"}</span></div><PlanDetail label="IL2" value={tracker.il2} /><PlanDetail label="IL5" value={tracker.il5} /></article>) : <div className="drawer-empty"><AlertTriangle />No Team Tracker row is mapped to this service group.</div>}</div>
        <p className="source-note">Source: {detail.tracker.source.source_file || detail.tracker.source.source || "Authoritative planning input"} · <span className="font-mono">{detail.tracker.source.source_file_sha256?.slice(0, 16) || detail.tracker.source.source_commit?.slice(0, 16) || "source identifier unavailable"}…</span>{detail.tracker.source.url ? <a href={detail.tracker.source.url} target="_blank" rel="noreferrer">Open source <ExternalLink /></a> : null}</p>
      </DrawerSection>

      <DrawerSection icon={ClipboardList} title="Imported service-impact context" subtitle="User-asserted planning context from the selected spreadsheet columns; review required.">
        <div className="service-impact-summary"><div><span>POA&amp;M impact</span><strong>{detail.profile.poam_impact || "Not supplied"}</strong></div><div><span>Service impact risk</span>{detail.profile.risk_category ? <Badge tone={riskTone(detail.profile.risk_category)}>{detail.profile.risk_category}</Badge> : <strong>Not supplied</strong>}</div><div><span>Comments</span><strong>{detail.profile.comments || "Not supplied"}</strong></div></div>
        {detail.profile.risk_authority ? <p className="source-note">Risk authority: {detail.profile.risk_authority.authority} · approved {detail.profile.risk_authority.approved_on} · <span className="font-mono">{detail.profile.risk_authority.source_sha256.slice(0, 16)}…</span></p> : null}
        {detail.profile.service_impact_source ? <p className="source-note">Source: {detail.profile.service_impact_source.source_filename} · row {detail.profile.service_impact_source.source_row} · <span className="font-mono">{detail.profile.service_impact_source.source_sha256.slice(0, 16)}…</span></p> : <p className="source-note">No service-impact row is mapped to this service group.</p>}
      </DrawerSection>
      <DrawerSection icon={CalendarClock} title="Target-module planning assertions" subtitle="Planning assertions are separate from assessment findings and require review.">
        <TargetPlanningAssertions modules={detail.tracker.profile.target_modules ?? []} />
        {!targetPlanningConcerns(detail.tracker.profile.target_modules ?? []).length ? <div className="drawer-empty"><CalendarClock />No target-module planning concern was returned for this scope.</div> : null}
      </DrawerSection>
      </> : null}

      {activeView === "evidence" ? <>
      <DrawerSection icon={LibraryBig} title="Candidate crypto libraries" subtitle="Library/framework records with explicit crypto metadata; other crypto asset types remain visible in each CBOM record below.">
        <div className="library-list">{detail.libraries.items.slice(0, showAllLibraries ? undefined : 12).map((library) => <article key={library.component_id}><div><strong>{library.name}</strong><span>{library.version || "Version not supplied"}</span></div><div><b>{library.document_count}</b><span>documents</span></div><div><b>{library.occurrence_count}</b><span>occurrences</span></div><code title={library.canonical_purl || ""}>{library.canonical_purl || "No canonical PURL"}</code></article>)}{!detail.libraries.items.length ? <div className="drawer-empty"><LibraryBig />No explicitly classified crypto libraries were returned.</div> : null}</div>{detail.libraries.items.length > 12 ? <button type="button" className="drawer-show-all" onClick={() => setShowAllLibraries((value) => !value)}>{showAllLibraries ? "Show first 12 libraries" : `Show all ${detail.libraries.items.length} libraries`}</button> : null}
      </DrawerSection>

      <DrawerSection icon={FileCode2} title="Catalog documents and CBOM links" subtitle="Open a source record to inspect its candidate crypto components and provenance.">
        <div className="document-list">{detail.documents.items.map((document) => <button type="button" key={document.document_id} className={selectedDocument?.document_id === document.document_id ? "selected" : ""} onClick={() => { setComponents([]); setComponentsError(""); setComponentsLoading(true); setSelectedDocument(document); }}><span className="document-kind">{document.document_kind}</span><span><strong>{document.source_paths?.[0]?.split("/").at(-1) || `Document ${document.document_id}`}</strong><small>{document.format_name} {document.spec_version} · {document.unique_crypto_components} crypto asset{document.unique_crypto_components === 1 ? "" : "s"} ({document.unique_crypto_libraries} librar{document.unique_crypto_libraries === 1 ? "y" : "ies"})</small></span><ChevronRight /></button>)}</div>
        {selectedDocument ? <DocumentInspector document={selectedDocument} components={components} loading={componentsLoading} error={componentsError} onClose={() => { setSelectedDocument(null); setComponents([]); setComponentsError(""); }} /> : null}
      </DrawerSection>
      </> : null}

      {activeView === "findings" ? <>
      <DrawerSection icon={CircleAlert} title={findingSectionTitle} subtitle={findingSectionSubtitle}>
        {detail.assessment.coverage_gaps.length ? <div className="evidence-request-list"><h4>Evidence requests — not POA&amp;M eligible</h4>{detail.assessment.coverage_gaps.map((gap) => <article key={gap.observation_id}><Badge tone="warning">{gap.assertion_state.replaceAll("_", " ")}</Badge><strong>{gap.title}</strong><p>{gap.technical_observation}</p></article>)}</div> : null}
        <div className="finding-list">{findings.slice(0, showAllFindings ? undefined : 30).map((finding) => <article key={finding.finding_id}><div><Badge tone={finding.poam_eligible ? "warning" : "neutral"}>{finding.assertion_state.replaceAll("_", " ")}</Badge><code>{finding.rule_id}</code></div><strong>{finding.title}</strong><p>{finding.subject_name} · {finding.finding_id}</p>{finding.poam_candidate_ids.length ? <span>Mapped draft candidate: {finding.poam_candidate_ids.join(", ")}</span> : <span>No POA&amp;M mapping — evidence review only</span>}</article>)}{!findings.length && !detail.assessment.coverage_gaps.length ? <div className="drawer-empty"><ShieldCheck />No candidate findings or evidence requests were returned for this scope.</div> : null}</div>{findings.length > 30 ? <button type="button" className="drawer-show-all" onClick={() => setShowAllFindings((value) => !value)}>{showAllFindings ? `Show first 30 ${findingRecordLabel}` : `Show all ${findings.length} ${findingRecordLabel}`}</button> : null}
      </DrawerSection>

      <DrawerSection icon={CalendarClock} title="Draft POA&M mapping" subtitle="Candidate rows and operational workstreams require authorized merge and disposition review.">
        <div className="poam-map-list">{detail.assessment.poam_items.map((item) => <article key={item.poam_candidate_id}><div><code>{item.poam_candidate_id}</code><Badge tone="info">{item.control_id}</Badge></div><strong>{item.title}</strong><p>{item.linked_finding_count} linked finding{item.linked_finding_count === 1 ? "" : "s"} across {item.affected_service_count ?? item.affected_services.length} service group{(item.affected_service_count ?? item.affected_services.length) === 1 ? "" : "s"} · Proposed {item.proposed_risk} risk</p><span>IL2 mitigation date: {formatDate(item.milestone_mitigation_date || item.scheduled_completion_date)}</span></article>)}{!detail.assessment.poam_items.length ? <div className="drawer-empty"><ShieldCheck />No draft POA&amp;M candidate is mapped to this scope.</div> : null}</div>
        {detail.assessment.poam_workstreams.length ? <div className="workstream-list"><h4>Operational grouping — merge review required</h4>{detail.assessment.poam_workstreams.map((item) => <article key={item.workstream_id}><code>{item.workstream_id}</code><strong>{item.title}</strong><span>{item.candidate_count} candidate rows · {item.status}</span></article>)}</div> : null}
      </DrawerSection>
      </> : null}
      </div>
    </>}</div>
  </aside></div>;
  // The console main element is inert while a dialog is open. Rendering this
  // dialog beneath it made its own close control inert as well.
  return typeof document === "undefined" ? null : createPortal(drawer, document.body);
}

function DrawerSection({ icon: Icon, title, subtitle, children }: { icon: typeof Boxes; title: string; subtitle: string; children: React.ReactNode }) {
  return <section className="drawer-section"><header><span><Icon /></span><div><h3>{title}</h3><p>{subtitle}</p></div></header>{children}</section>;
}

function DrawerMetric({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }

function PlanDetail({ label, value }: { label: string; value: { raw_value: string; status: string; date: string | null } }) {
  return <div className={value.date ? "plan-detail" : "plan-detail plan-missing"}><span>{label}</span><strong>{value.date ? formatDate(value.date) : value.raw_value || "Not supplied"}</strong><small>{value.status.replaceAll("_", " ")}</small></div>;
}

function DocumentInspector({ document, components, loading, error, onClose }: { document: CatalogDocument; components: CryptoComponent[]; loading: boolean; error: string; onClose: () => void }) {
  return <div className="document-inspector"><header><div><span>Selected source record</span><strong>{document.source_paths?.[0] || `Document ${document.document_id}`}</strong></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close document inspector"><X /></button></header><div className="document-provenance"><span>SHA-256 <code>{document.sha256}</code></span><span>Observed <strong>{document.generated_at_text ? new Date(document.generated_at_text).toLocaleString() : "Not supplied"}</strong></span></div>{loading ? <p className="drawer-loading">Loading candidate crypto components…</p> : error ? <div className="detail-error" role="alert">Unable to load candidate crypto components: {error}</div> : <div className="component-list">{components.map((component) => <article key={component.occurrence_id}><div><strong>{component.name}</strong><span>{component.version || "Version not supplied"} · {component.component_type}</span></div><code title={component.canonical_purl || component.bom_ref || ""}>{component.canonical_purl || component.bom_ref || "No PURL or BOM reference"}</code></article>)}{!components.length ? <div className="drawer-empty"><LibraryBig />No explicit crypto components were returned for this document.</div> : null}</div>}</div>;
}
