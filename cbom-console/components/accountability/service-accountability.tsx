"use client";

import * as React from "react";
import {
  AlertTriangle, ArrowDown, ArrowUp, BookOpenCheck, Boxes, CalendarClock,
  ChevronRight, CircleAlert, ExternalLink, FileCode2, FilterX,
  LibraryBig, RefreshCw, Search, ShieldCheck, UserRound, UsersRound, X,
} from "lucide-react";
import { Badge } from "@/app/components/ui/badge";
import { getDocumentCryptoComponents, getServiceGroupDetail, getServiceGroupRegister } from "@/components/accountability/accountability-data";
import type { CatalogDocument, CryptoComponent, PlanningSummary, ServiceGroupDetail, ServiceGroupRegisterRow } from "@/components/accountability/types";

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

function PlanningCell({ plan, label }: { plan: PlanningSummary; label: string }) {
  const title = plan.entries.map((entry) => `${entry.team}: ${entry.raw_value || "Not supplied"}`).join("\n");
  if (plan.state !== "dated") return <span title={title} className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-amber-700 dark:text-amber-300"><CircleAlert className="size-3.5" />{plan.state === "not_applicable" ? "N/A" : "Date missing"}</span>;
  return <div title={title}><span className="whitespace-nowrap font-mono text-xs text-foreground">{formatDate(plan.farthest_date)}</span>{plan.explicit_dates.length > 1 ? <span className="mt-1 block text-[11px] text-muted-foreground">{plan.explicit_dates.length} {label} dates · farthest shown</span> : null}</div>;
}

function SortButton({ id, active, direction, children, onSort }: { id: SortKey; active: SortKey; direction: Direction; children: React.ReactNode; onSort: (id: SortKey) => void }) {
  const Icon = active === id && direction === "desc" ? ArrowDown : ArrowUp;
  return <button type="button" className="inline-flex items-center gap-1 whitespace-nowrap font-semibold tracking-[.07em] text-muted-foreground hover:text-foreground" onClick={() => onSort(id)}>{children}<Icon className={`size-3 ${active === id ? "opacity-100" : "opacity-25"}`} /></button>;
}

export function ServiceAccountability() {
  const [rows, setRows] = React.useState<ServiceGroupRegisterRow[]>([]);
  const [total, setTotal] = React.useState(0);
  const [owners, setOwners] = React.useState<string[]>([]);
  const [leads, setLeads] = React.useState<string[]>([]);
  const [query, setQuery] = React.useState("");
  const [owner, setOwner] = React.useState("");
  const [lead, setLead] = React.useState("");
  const [il2State, setIl2State] = React.useState("");
  const [il5State, setIl5State] = React.useState("");
  const [action, setAction] = React.useState("");
  const [sort, setSort] = React.useState<SortKey>("effective_owner");
  const [direction, setDirection] = React.useState<Direction>("asc");
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [selected, setSelected] = React.useState<ServiceGroupRegisterRow | null>(null);
  const [revision, setRevision] = React.useState(0);
  const linkedGroup = React.useRef<string | null>(null);

  React.useEffect(() => {
    const group = new URLSearchParams(window.location.search).get("group");
    if (!group) return;
    linkedGroup.current = group;
    const timer = window.setTimeout(() => setQuery(group), 0);
    return () => window.clearTimeout(timer);
  }, []);

  React.useEffect(() => {
    if (!linkedGroup.current || selected) return;
    const match = rows.find((row) => row.service_group === linkedGroup.current);
    if (match) {
      setSelected(match);
      linkedGroup.current = null;
    }
  }, [rows, selected]);

  React.useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true); setError("");
      void getServiceGroupRegister({ query, owner, lead, il2State, il5State, action, sort, direction, page: 0, pageSize: 250, signal: controller.signal })
        .then((result) => { setRows(result.items); setTotal(result.total); setOwners(result.filter_options.owners); setLeads(result.filter_options.leads); })
        .catch((reason: Error) => { if (reason.name !== "AbortError") { setRows([]); setError(reason.message); } })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, query ? 250 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [query, owner, lead, il2State, il5State, action, sort, direction, revision]);

  const grouped = React.useMemo(() => {
    const groups = new Map<string, ServiceGroupRegisterRow[]>();
    for (const row of rows) {
      const key = ownerLabel(row);
      groups.set(key, [...(groups.get(key) ?? []), row]);
    }
    return [...groups.entries()];
  }, [rows]);
  const hasFilters = Boolean(query || owner || lead || il2State || il5State || action);
  const toggleSort = (next: SortKey) => { if (sort === next) setDirection((value) => value === "asc" ? "desc" : "asc"); else { setSort(next); setDirection(next === "findings" || next === "poam" || next === "documents" || next === "libraries" ? "desc" : "asc"); } };
  const reset = () => { setQuery(""); setOwner(""); setLead(""); setIl2State(""); setIl5State(""); setAction(""); };

  return <div className="accountability-workbench">
    <section className="page-heading inventory-heading">
      <div><p className="eyebrow">Ownership and remediation intelligence</p><h1>Service accountability</h1><p className="page-subtitle">Trace each scoped service group from Team Tracker planning context to catalog evidence, candidate crypto libraries, findings, and draft POA&amp;M mappings.</p></div>
      <div className="heading-actions"><Badge tone={error ? "danger" : loading ? "neutral" : "success"}>{error ? "Data unavailable" : loading ? "Loading register" : "Live catalog"}</Badge><button className="refresh-button" type="button" disabled={loading} onClick={() => setRevision((value) => value + 1)}><RefreshCw className={loading ? "spin" : ""} size={17} />Refresh</button></div>
    </section>

    <section className="rounded-2xl border border-border bg-card shadow-sm" aria-label="Service accountability register">
      <div className="accountability-toolbar">
        <label className="accountability-search"><Search /><span className="sr-only">Search service accountability</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search group, owner, lead, POA&M or workstream…" /></label>
        <select aria-label="Filter by executive owner" value={owner} onChange={(event) => setOwner(event.target.value)}><option value="">All executive owners</option><option value="__missing__">Owner not supplied</option>{owners.map((value) => <option key={value}>{value}</option>)}</select>
        <select aria-label="Filter by lead" value={lead} onChange={(event) => setLead(event.target.value)}><option value="">All leads</option><option value="__missing__">Lead not supplied</option>{leads.map((value) => <option key={value}>{value}</option>)}</select>
        <select aria-label="Filter by IL2 plan" value={il2State} onChange={(event) => setIl2State(event.target.value)}><option value="">All IL2 plans</option><option value="dated">Explicit date</option><option value="not_supplied">Date missing</option><option value="non_date">Non-date value</option><option value="not_applicable">Not applicable</option></select>
        <select aria-label="Filter by IL5 plan" value={il5State} onChange={(event) => setIl5State(event.target.value)}><option value="">All IL5 plans</option><option value="dated">Explicit date</option><option value="not_supplied">Date missing</option><option value="non_date">Non-date value</option><option value="not_applicable">Not applicable</option></select>
        <select aria-label="Filter by candidate action" value={action} onChange={(event) => setAction(event.target.value)}><option value="">All candidate actions</option><option value="has_poam">Has draft POA&amp;M</option><option value="has_findings">Has findings</option><option value="review_only">Needs evidence review</option><option value="no_action">No mapped action</option></select>
        <button type="button" className="secondary-button" disabled={!hasFilters} onClick={reset}><FilterX size={15} />Clear</button>
      </div>
      <div className="flex items-center justify-between border-b border-border px-5 py-3 text-xs text-muted-foreground"><span><strong className="text-foreground">{total}</strong> scoped service groups</span><span>Grouped by Executive owner <span className="hidden sm:inline">(effective owner from Team Tracker)</span></span></div>
      <div className="overflow-x-auto">
        <table className="accountability-table">
          <thead><tr><th><SortButton id="service_group" active={sort} direction={direction} onSort={toggleSort}>Service group</SortButton></th><th><SortButton id="lead" active={sort} direction={direction} onSort={toggleSort}>Lead</SortButton></th><th><SortButton id="il2" active={sort} direction={direction} onSort={toggleSort}>IL2 plan</SortButton></th><th><SortButton id="il5" active={sort} direction={direction} onSort={toggleSort}>IL5 plan</SortButton></th><th><SortButton id="documents" active={sort} direction={direction} onSort={toggleSort}>Catalog evidence</SortButton></th><th><SortButton id="libraries" active={sort} direction={direction} onSort={toggleSort}>Crypto assets</SortButton></th><th><SortButton id="findings" active={sort} direction={direction} onSort={toggleSort}>Findings</SortButton></th><th><SortButton id="poam" active={sort} direction={direction} onSort={toggleSort}>Draft POA&amp;M</SortButton></th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{grouped.map(([groupOwner, items]) => <React.Fragment key={groupOwner}><tr className="owner-group-row"><td colSpan={9}><div><UserRound className="size-4" /><span>Executive owner</span><strong>{groupOwner}</strong><small>{items.length} service group{items.length === 1 ? "" : "s"}</small></div></td></tr>{items.map((row) => <tr key={row.service_key} className="accountability-row"><td><button type="button" className="text-left" onClick={() => setSelected(row)}><strong>{row.display_name}</strong><span className="mono">{row.service_key}</span></button></td><td>{row.leads.length ? <span className="text-sm text-foreground">{row.leads.join(", ")}</span> : <span className="missing-value">Not supplied</span>}</td><td><PlanningCell plan={row.il2} label="IL2" /></td><td><PlanningCell plan={row.il5} label="IL5" /></td><td><button type="button" className="metric-link" onClick={() => setSelected(row)}><FileCode2 /><span><strong>{row.documents}</strong><small>{row.documents_with_fips_evidence}/{row.documents} with FIPS signals</small></span></button></td><td><div className="table-count"><strong>{row.candidate_crypto_assets}</strong><small>{row.candidate_crypto_libraries} librar{row.candidate_crypto_libraries === 1 ? "y" : "ies"}</small></div></td><td><div className="table-count"><strong className={row.finding_count ? "text-amber-700 dark:text-amber-300" : ""}>{row.finding_count}</strong><small>{row.review_observations} review-only</small></div></td><td><div className="table-count"><strong className={row.poam_candidate_count ? "text-primary" : ""}>{row.poam_candidate_count}</strong><small>{row.workstream_count} workstream{row.workstream_count === 1 ? "" : "s"}</small></div></td><td><button type="button" className="table-action" onClick={() => setSelected(row)}>Open <ChevronRight className="size-3.5" /></button></td></tr>)}</React.Fragment>)}</tbody>
        </table>
        {!loading && !rows.length ? <div className="px-6 py-16 text-center text-sm text-muted-foreground">{error ? <span role="alert" className="text-danger">Unable to load the live register: {error}</span> : "No service groups match the current filters."}</div> : null}
        {loading ? <div className="px-6 py-16 text-center text-sm text-muted-foreground">Loading service accountability…</div> : null}
      </div>
    </section>
    <p className="mt-3 flex items-start gap-2 text-xs leading-5 text-muted-foreground"><ShieldCheck className="mt-0.5 size-4 shrink-0" />Owners and IL2/IL5 values are Team Tracker planning metadata. Candidate findings and draft POA&amp;M mappings require authorized assessor and AO review.</p>
    {selected ? <ServiceGroupDrawer row={selected} onClose={() => setSelected(null)} /> : null}
  </div>;
}

function ServiceGroupDrawer({ row, onClose }: { row: ServiceGroupRegisterRow; onClose: () => void }) {
  const [detail, setDetail] = React.useState<ServiceGroupDetail | null>(null);
  const [error, setError] = React.useState("");
  const [selectedDocument, setSelectedDocument] = React.useState<CatalogDocument | null>(null);
  const [components, setComponents] = React.useState<CryptoComponent[]>([]);
  const [componentsLoading, setComponentsLoading] = React.useState(false);
  const panelRef = React.useRef<HTMLElement>(null);
  const titleId = React.useId();

  React.useEffect(() => {
    const controller = new AbortController();
    void getServiceGroupDetail(row.source_collection, row.service_group, controller.signal).then(setDetail).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); });
    return () => controller.abort();
  }, [row]);
  React.useEffect(() => {
    if (!selectedDocument) return;
    const controller = new AbortController();
    void getDocumentCryptoComponents(selectedDocument.document_id, controller.signal).then(setComponents).catch(() => setComponents([])).finally(() => { if (!controller.signal.aborted) setComponentsLoading(false); });
    return () => controller.abort();
  }, [selectedDocument]);
  React.useEffect(() => {
    const prior = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panelRef.current?.focus(); document.body.style.overflow = "hidden";
    const keydown = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", keydown);
    return () => { document.removeEventListener("keydown", keydown); document.body.style.overflow = ""; prior?.focus(); };
  }, [onClose]);

  return <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}><aside ref={panelRef} tabIndex={-1} className="service-drawer" role="dialog" aria-modal="true" aria-labelledby={titleId}>
    <header className="service-drawer-header"><div><p className="eyebrow">Scoped service-group record</p><h2 id={titleId}>{row.display_name}</h2><p>{row.service_key}</p></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close service details"><X /></button></header>
    <div className="service-drawer-body">{error ? <div className="detail-error" role="alert">Unable to load service details: {error}</div> : !detail ? <div className="drawer-loading">Loading scoped evidence and planning context…</div> : <>
      <DrawerSection icon={BookOpenCheck} title="Scope and catalog coverage" subtitle="Coverage is inventory evidence, not proof of deployment or compliance.">
        <div className="drawer-metric-grid"><DrawerMetric label="Catalog documents" value={String(detail.profile.documents)} /><DrawerMetric label="FIPS signal coverage" value={`${detail.profile.evidence_coverage_percent}%`} /><DrawerMetric label="Candidate crypto assets" value={String(detail.profile.candidate_crypto_assets)} /><DrawerMetric label="Ingest issues" value={String(detail.profile.ingest_issues)} /></div>
        <div className="provenance-strip"><span>Assessment run <strong>{detail.assessment.assessment_run_id}</strong></span><span>Policy <strong>{detail.assessment.policy?.policy_version || "Not supplied"}</strong></span></div>
      </DrawerSection>

      <DrawerSection icon={UsersRound} title="Ownership and planning context" subtitle="Effective owner and lead are derived from the reviewed Team Tracker mapping.">
        <div className="owner-summary"><div><span>Executive owner</span><strong>{detail.profile.effective_owners.join(", ") || "Not supplied"}</strong></div><div><span>Lead</span><strong>{detail.profile.leads.join(", ") || "Not supplied"}</strong></div><div><span>Mapping</span><strong>{detail.profile.mapping_status === "mapped" ? "Mapped" : "Not mapped"}</strong></div></div>
        <div className="tracker-list">{detail.tracker.profile.tracker_rows.length ? detail.tracker.profile.tracker_rows.map((tracker) => <article key={`${tracker.team}-${tracker.lead}`}><div><strong>{tracker.team}</strong><span>{tracker.owner || "Owner not supplied"} · {tracker.lead || "Lead not supplied"}</span></div><PlanDetail label="IL2" value={tracker.il2} /><PlanDetail label="IL5" value={tracker.il5} /></article>) : <div className="drawer-empty"><AlertTriangle />No Team Tracker row is mapped to this service group.</div>}</div>
        <p className="source-note">Source: {detail.tracker.source.source_file || "Team Tracker"} · <span className="font-mono">{detail.tracker.source.source_file_sha256?.slice(0, 16) || "checksum unavailable"}…</span>{detail.tracker.source.url ? <a href={detail.tracker.source.url} target="_blank" rel="noreferrer">Open tracker <ExternalLink /></a> : null}</p>
      </DrawerSection>

      <DrawerSection icon={LibraryBig} title="Candidate crypto libraries" subtitle="Library/framework records with explicit crypto metadata; other crypto asset types remain visible in each CBOM record below.">
        <div className="library-list">{detail.libraries.items.slice(0, 12).map((library) => <article key={library.component_id}><div><strong>{library.name}</strong><span>{library.version || "Version not supplied"}</span></div><div><b>{library.document_count}</b><span>documents</span></div><div><b>{library.occurrence_count}</b><span>occurrences</span></div><code title={library.canonical_purl || ""}>{library.canonical_purl || "No canonical PURL"}</code></article>)}{!detail.libraries.items.length ? <div className="drawer-empty"><LibraryBig />No explicitly classified crypto libraries were returned.</div> : null}</div>
      </DrawerSection>

      <DrawerSection icon={FileCode2} title="Catalog documents and CBOM links" subtitle="Open a source record to inspect its candidate crypto components and provenance.">
        <div className="document-list">{detail.documents.items.map((document) => <button type="button" key={document.document_id} className={selectedDocument?.document_id === document.document_id ? "selected" : ""} onClick={() => { setComponents([]); setComponentsLoading(true); setSelectedDocument(document); }}><span className="document-kind">{document.document_kind}</span><span><strong>{document.source_paths?.[0]?.split("/").at(-1) || `Document ${document.document_id}`}</strong><small>{document.format_name} {document.spec_version} · {document.unique_crypto_components} crypto asset{document.unique_crypto_components === 1 ? "" : "s"} ({document.unique_crypto_libraries} librar{document.unique_crypto_libraries === 1 ? "y" : "ies"})</small></span><ChevronRight /></button>)}</div>
        {selectedDocument ? <DocumentInspector document={selectedDocument} components={components} loading={componentsLoading} onClose={() => { setSelectedDocument(null); setComponents([]); }} /> : null}
      </DrawerSection>

      <DrawerSection icon={CircleAlert} title="Assessment observations and candidate findings" subtitle="Evidence requests remain separate from POA&M-eligible candidate findings.">
        {detail.assessment.coverage_gaps.length ? <div className="evidence-request-list"><h4>Evidence requests — not POA&amp;M eligible</h4>{detail.assessment.coverage_gaps.map((gap) => <article key={gap.observation_id}><Badge tone="warning">{gap.assertion_state.replaceAll("_", " ")}</Badge><strong>{gap.title}</strong><p>{gap.technical_observation}</p></article>)}</div> : null}
        <div className="finding-list">{detail.assessment.findings.slice(0, 30).map((finding) => <article key={finding.finding_id}><div><Badge tone={finding.poam_eligible ? "warning" : "neutral"}>{finding.assertion_state.replaceAll("_", " ")}</Badge><code>{finding.rule_id}</code></div><strong>{finding.title}</strong><p>{finding.subject_name} · {finding.finding_id}</p>{finding.poam_candidate_ids.length ? <span>Mapped draft candidate: {finding.poam_candidate_ids.join(", ")}</span> : <span>No POA&amp;M mapping — evidence review only</span>}</article>)}{!detail.assessment.findings.length && !detail.assessment.coverage_gaps.length ? <div className="drawer-empty"><ShieldCheck />No candidate findings or evidence requests were returned for this scope.</div> : null}</div>
      </DrawerSection>

      <DrawerSection icon={CalendarClock} title="Draft POA&M mapping" subtitle="Candidate rows and operational workstreams require authorized merge and disposition review.">
        <div className="poam-map-list">{detail.assessment.poam_items.map((item) => <article key={item.poam_candidate_id}><div><code>{item.poam_candidate_id}</code><Badge tone="info">{item.control_id}</Badge></div><strong>{item.title}</strong><p>{item.linked_finding_count} linked finding{item.linked_finding_count === 1 ? "" : "s"} · Proposed {item.proposed_risk} risk</p><span>IL2 mitigation date: {formatDate(item.milestone_mitigation_date || item.scheduled_completion_date)}</span></article>)}{!detail.assessment.poam_items.length ? <div className="drawer-empty"><ShieldCheck />No draft POA&amp;M candidate is mapped to this scope.</div> : null}</div>
        {detail.assessment.poam_workstreams.length ? <div className="workstream-list"><h4>Operational grouping — merge review required</h4>{detail.assessment.poam_workstreams.map((item) => <article key={item.workstream_id}><code>{item.workstream_id}</code><strong>{item.title}</strong><span>{item.candidate_count} candidate rows · {item.status}</span></article>)}</div> : null}
      </DrawerSection>
    </>}</div>
  </aside></div>;
}

function DrawerSection({ icon: Icon, title, subtitle, children }: { icon: typeof Boxes; title: string; subtitle: string; children: React.ReactNode }) {
  return <section className="drawer-section"><header><span><Icon /></span><div><h3>{title}</h3><p>{subtitle}</p></div></header>{children}</section>;
}

function DrawerMetric({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }

function PlanDetail({ label, value }: { label: string; value: { raw_value: string; status: string; date: string | null } }) {
  return <div className={value.date ? "plan-detail" : "plan-detail plan-missing"}><span>{label}</span><strong>{value.date ? formatDate(value.date) : value.raw_value || "Not supplied"}</strong><small>{value.status.replaceAll("_", " ")}</small></div>;
}

function DocumentInspector({ document, components, loading, onClose }: { document: CatalogDocument; components: CryptoComponent[]; loading: boolean; onClose: () => void }) {
  return <div className="document-inspector"><header><div><span>Selected source record</span><strong>{document.source_paths?.[0] || `Document ${document.document_id}`}</strong></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close document inspector"><X /></button></header><div className="document-provenance"><span>SHA-256 <code>{document.sha256}</code></span><span>Observed <strong>{document.generated_at_text ? new Date(document.generated_at_text).toLocaleString() : "Not supplied"}</strong></span></div>{loading ? <p className="drawer-loading">Loading candidate crypto components…</p> : <div className="component-list">{components.map((component) => <article key={component.occurrence_id}><div><strong>{component.name}</strong><span>{component.version || "Version not supplied"} · {component.component_type}</span></div><code title={component.canonical_purl || component.bom_ref || ""}>{component.canonical_purl || component.bom_ref || "No PURL or BOM reference"}</code></article>)}{!components.length ? <div className="drawer-empty"><LibraryBig />No explicit crypto components were returned for this document.</div> : null}</div>}</div>;
}
