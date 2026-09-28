"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, BookOpenCheck, Boxes, CalendarClock, ChevronRight, CircleAlert, ClipboardList, ExternalLink, FileCode2, LibraryBig, ShieldCheck, UsersRound, X } from "lucide-react";
import { Badge } from "@/app/components/ui/badge";
import { getDocumentCryptoComponents, getServiceGroupDetail } from "@/components/accountability/accountability-data";
import type { CatalogDocument, CryptoComponent, ServiceGroupDetail, ServiceGroupRegisterRow, TargetModulePlanningRecord } from "@/components/accountability/types";

function formatDate(value: string | null | undefined) {
  if (!value) return "Not supplied";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`));
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
