"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { Check, FilePenLine, Plus, RefreshCw, X } from "lucide-react";
import { Badge } from "@/app/components/ui/badge";
import { useConsoleAccess } from "@/app/components/console-shell";
import { fetchJson } from "@/app/lib/http";
import { ServiceGroupDrawer } from "@/components/accountability/service-group-drawer";

type Plan = { status: string; date: string | null };
type CryptoModulePlan = {
  id: string;
  current_module: string;
  current_version: string;
  target_preset_id: string;
  custom_target_module: string;
  custom_target_version: string;
  source_record_sha256: string;
  supporting_url: string;
  evidence_basis: "" | "cmvp_certificate" | "cmvp_in_process" | "vendor_recommendation" | "other";
  note: string;
};
type SavedCryptoModulePlan = Omit<CryptoModulePlan, "id"> & {
  /**
   * Read-only projection from the current public-evidence reconciliation.
   * These fields are deliberately not included in editor drafts or writes.
   */
  evidence_state?: string | null;
  planning_disposition?: string | null;
  disposition_basis?: string | null;
  target_module?: string | null;
  target_version?: string | null;
  evidence_url?: string | null;
};
type CryptoModuleOption = { id: string; label: string; module_name: string; module_version: string | null; certificate_number: string | null; public_status: string; source_url: string | null; source_kind: string; limitations: string[] };
type ImportedTargetModule = { record_sha256: string; current_module: string | null; current_version: string | null; target_module: string | null; target_disposition: string };
type CatalogRow = {
  service_key: string;
  source_collection: string;
  service_group: string;
  display_name: string;
  owner: string | null;
  lead: string | null;
  owner_profile?: { email?: string | null; display_name?: string | null } | null;
  lead_profile?: { email?: string | null; display_name?: string | null } | null;
  il2: Plan;
  il5: Plan;
  service_impact_risk: string | null;
  comments: string | null;
  attributes?: Record<string, string | null>;
  crypto_module_plans?: SavedCryptoModulePlan[];
  imported_target_modules?: ImportedTargetModule[];
  approval_status: "authoritative" | "approved" | "pending" | "imported" | "rejected";
  pending_proposals?: number;
  has_evidence?: boolean;
  revision?: number | null;
  updated_at?: string | null;
  can_edit: boolean;
  can_approve: boolean;
};
type CatalogProposal = { id: string; source_collection: string; service_group: string; proposed_payload?: { display_name?: string }; submitted_at?: string; submitted_by_email?: string; rationale: string; base_revision?: number | null; status: "pending" | "approved" | "rejected"; decision_reason?: string | null; decided_at?: string | null; decided_by_email?: string | null };
type CatalogResponse = { items: CatalogRow[]; total: number; crypto_module_options?: CryptoModuleOption[] };
type CatalogDraft = {
  source_collection: string;
  service_group: string;
  display_name: string;
  owner: string;
  owner_profile_email: string;
  lead: string;
  lead_profile_email: string;
  il2_status: string;
  il2_date: string;
  il5_status: string;
  il5_date: string;
  service_impact_risk: string;
  comments: string;
  rationale: string;
  attributes_text: string;
  crypto_module_plans: CryptoModulePlan[];
};

const emptyDraft = (): CatalogDraft => ({ source_collection: "sse-cboms", service_group: "", display_name: "", owner: "", owner_profile_email: "", lead: "", lead_profile_email: "", il2_status: "not_supplied", il2_date: "", il5_status: "not_supplied", il5_date: "", service_impact_risk: "", comments: "", rationale: "", attributes_text: "", crypto_module_plans: [] });
const planStatuses = ["not_supplied", "planned", "in_progress", "complete", "not_applicable", "blocked"];
const riskOptions = ["", "low", "moderate", "high", "critical"];

function draftFromRow(row: CatalogRow): CatalogDraft {
  return {
    source_collection: row.source_collection, service_group: row.service_group, display_name: row.display_name,
    owner: row.owner ?? "", owner_profile_email: row.owner_profile?.email ?? "", lead: row.lead ?? "", lead_profile_email: row.lead_profile?.email ?? "",
    il2_status: row.il2.status === "unavailable" ? "" : row.il2.status || "not_supplied", il2_date: row.il2.date ?? "",
    il5_status: row.il5.status === "unavailable" ? "" : row.il5.status || "not_supplied", il5_date: row.il5.date ?? "",
    service_impact_risk: row.service_impact_risk?.toLowerCase() ?? "", comments: row.comments ?? "", rationale: "", attributes_text: row.attributes && Object.keys(row.attributes).length ? JSON.stringify(row.attributes, null, 2) : "", crypto_module_plans: (row.crypto_module_plans ?? []).map((plan) => ({ id: crypto.randomUUID(), current_module: plan.current_module ?? "", current_version: plan.current_version ?? "", target_preset_id: plan.target_preset_id ?? "", custom_target_module: plan.custom_target_module ?? "", custom_target_version: plan.custom_target_version ?? "", source_record_sha256: plan.source_record_sha256 ?? "", supporting_url: plan.supporting_url ?? "", evidence_basis: plan.evidence_basis ?? "", note: plan.note ?? "" })),
  };
}

function newCryptoModulePlan(): CryptoModulePlan {
  return { id: crypto.randomUUID(), current_module: "", current_version: "", target_preset_id: "", custom_target_module: "", custom_target_version: "", source_record_sha256: "", supporting_url: "", evidence_basis: "", note: "" };
}

function serializeCryptoModulePlans(plans: CryptoModulePlan[]): SavedCryptoModulePlan[] {
  return plans.map(({ id: _id, ...plan }) => ({
    current_module: plan.current_module.trim(),
    current_version: plan.current_version.trim(),
    target_preset_id: plan.target_preset_id || "",
    custom_target_module: plan.custom_target_module.trim(),
    custom_target_version: plan.custom_target_version.trim(),
    source_record_sha256: plan.source_record_sha256 || "",
    supporting_url: plan.supporting_url.trim(),
    evidence_basis: plan.evidence_basis,
    note: plan.note.trim(),
  }));
}

function titleCase(value: string) { return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function planText(plan: Plan) { return <><strong>{titleCase(plan.status || "not supplied")}</strong><small>{plan.date || "No target date"}</small></>; }
function cryptoEvidenceExplanation(plan: SavedCryptoModulePlan) {
  if (plan.evidence_state === "current") return "A current public certificate or pipeline reference supports planning only. It does not establish deployed FIPS validation.";
  if (plan.evidence_state === "evidence_superseded") return "The referenced public evidence has changed. This target remains unverified until it is reviewed again.";
  if (plan.evidence_state === "user_asserted_unverified") return "The supporting record was supplied for planning. This target remains unverified.";
  return "Evidence has not been reconciled. This target remains unverified.";
}
function cryptoPlanTarget(plan: SavedCryptoModulePlan, option: CryptoModuleOption | undefined) {
  const savedTarget = [plan.target_module, plan.target_version].filter((part): part is string => Boolean(part?.trim())).join(" ");
  if (savedTarget) return savedTarget;
  if (option) return option.label;
  return `${plan.custom_target_module || "Target not supplied"}${plan.custom_target_version ? ` ${plan.custom_target_version}` : ""}`;
}
function proposalValue(value: unknown) { return value === null ? "Cleared" : typeof value === "object" ? JSON.stringify(value) : String(value); }
function proposalChanges(proposal: CatalogProposal) {
  return Object.entries(proposal.proposed_payload ?? {}).map(([field, value]) => <span key={field}><strong>{titleCase(field)}:</strong> {proposalValue(value)}</span>);
}
function formatCatalogTimestamp(value: string | null | undefined) {
  if (!value) return "Time not recorded";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Time not recorded" : date.toLocaleString();
}
function approvalTone(status: CatalogRow["approval_status"]): "success" | "warning" | "neutral" | "danger" {
  if (status === "approved" || status === "authoritative") return "neutral";
  if (status === "pending") return "warning";
  if (status === "rejected") return "danger";
  return "neutral";
}
function approvalLabel(row: CatalogRow) {
  if ((row.pending_proposals ?? 0) > 0) return "Pending change";
  if (row.approval_status === "authoritative" || row.approval_status === "approved") return "Published";
  return row.approval_status === "imported" ? "Imported planning" : titleCase(row.approval_status);
}

function useCatalogDialogAccessibility(onClose: () => void, busy: boolean) {
  const panelRef = React.useRef<HTMLElement>(null);
  const busyRef = React.useRef(busy);

  React.useEffect(() => { busyRef.current = busy; }, [busy]);

  React.useEffect(() => {
    const prior = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const panel = panelRef.current;
    if (!panel) return;
    const appRoot = document.getElementById("main-content");
    const priorOverflow = document.body.style.overflow;
    const priorPadding = document.body.style.paddingRight;
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = "hidden";
    if (scrollbarWidth) document.body.style.paddingRight = `${scrollbarWidth}px`;
    appRoot?.setAttribute("inert", "");
    const focusable = () => Array.from(panel.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )).filter((node) => !node.hasAttribute("hidden"));
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab") return;
      const nodes = focusable();
      if (!nodes.length) { event.preventDefault(); panel.focus(); return; }
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", keydown);
    const focusTimer = window.setTimeout(() => focusable()[0]?.focus() ?? panel.focus(), 0);
    return () => { document.removeEventListener("keydown", keydown); window.clearTimeout(focusTimer); document.body.style.overflow = priorOverflow; document.body.style.paddingRight = priorPadding; appRoot?.removeAttribute("inert"); prior?.focus(); };
  }, [onClose]);

  return panelRef;
}

/**
 * Administrator-only queue for lead proposals.  This is deliberately
 * independent of the assessment and POA&M operational-review feature flags:
 * Service Catalog proposals are planning metadata and have their own audited
 * decision endpoints.
 */
export function ServiceCatalogApprovalQueue() {
  const access = useConsoleAccess();
  const [proposals, setProposals] = React.useState<CatalogProposal[]>([]);
  const [decision, setDecision] = React.useState<{ proposal: CatalogProposal; value: "approved" | "rejected"; reason: string } | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  const load = React.useCallback(async (signal?: AbortSignal) => {
    if (!access.isAdmin) return;
    setLoading(true);
    setError("");
    try {
      const page = await fetchJson<{ items: CatalogProposal[] }>("/api/v1/admin/service-catalog/proposals", { signal });
      setProposals(page.items);
    } catch (reason) {
      if ((reason as Error).name !== "AbortError") setError((reason as Error).message || "Unable to load Service Catalog approvals.");
    } finally {
      setLoading(false);
    }
  }, [access.isAdmin]);

  React.useEffect(() => {
    const controller = new AbortController();
    const request = window.setTimeout(() => { void load(controller.signal); }, 0);
    return () => { window.clearTimeout(request); controller.abort(); };
  }, [load]);

  const saveDecision = async () => {
    if (!decision || decision.reason.trim().length < 8) return;
    setSaving(true);
    setError("");
    try {
      await fetchJson(`/api/v1/admin/service-catalog/proposals/${encodeURIComponent(decision.proposal.id)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: decision.value, decision_reason: decision.reason.trim() }),
      });
      setNotice(`Proposal ${decision.value}.`);
      setDecision(null);
      await load();
    } catch (reason) {
      setError((reason as Error).message || "Unable to record the proposal decision.");
    } finally {
      setSaving(false);
    }
  };

  if (!access.isAdmin) return null;
  const pending = proposals.filter((proposal) => proposal.status === "pending");
  const history = proposals.filter((proposal) => proposal.status !== "pending");
  return <section className="catalog-proposal-queue rounded-2xl border border-border bg-card shadow-sm" aria-label="Service Catalog approvals">
    <div className="card-heading"><div><p className="eyebrow">Approvals · Service Catalog</p><h2>Pending service changes</h2><p className="admin-card-note">This workflow updates service ownership and planning metadata only. It does not approve POA&amp;Ms, ATOs, CMVP or FIPS status, deployments, or access.</p></div><div className="heading-actions"><Badge tone={pending.length ? "warning" : "neutral"}>{loading ? "Loading" : `${pending.length} pending`}</Badge><button type="button" className="refresh-button" disabled={loading || saving} onClick={() => void load()}><RefreshCw size={16} className={loading ? "spin" : ""} />Refresh</button></div></div>
    {notice ? <p className="catalog-notice" role="status"><Check size={16} />{notice}</p> : null}
    {error ? <p className="admin-error" role="alert">{error}</p> : null}
    {loading && !proposals.length ? <p className="review-empty">Loading service change proposals…</p> : null}
    {!loading && !error && !pending.length ? <p className="review-empty">No Service Catalog changes are awaiting approval.</p> : null}
    {pending.map((proposal) => <article key={proposal.id}><div><strong>{proposal.source_collection}/{proposal.service_group}</strong><span>{proposal.submitted_by_email || "Service lead"} · {proposal.rationale}</span><div className="catalog-proposal-changes">{proposalChanges(proposal)}</div></div><div><button type="button" className="secondary-button" onClick={() => setDecision({ proposal, value: "rejected", reason: "" })}>Reject</button><button type="button" className="primary-button" onClick={() => setDecision({ proposal, value: "approved", reason: "" })}>Approve</button></div></article>)}
    {history.length ? <details className="catalog-decision-history"><summary>Decision history ({history.length})</summary>{history.map((proposal) => <article key={proposal.id}><div><strong>{proposal.source_collection}/{proposal.service_group}</strong><span>{titleCase(proposal.status)} by {proposal.decided_by_email || "Administrator"} · {formatCatalogTimestamp(proposal.decided_at)}</span><small>Proposed against revision {proposal.base_revision ?? 0} · {proposal.decision_reason || "No decision reason recorded"}</small><div className="catalog-proposal-changes">{proposalChanges(proposal)}</div></div><Badge tone={proposal.status === "approved" ? "success" : "danger"}>{titleCase(proposal.status)}</Badge></article>)}</details> : null}
    {decision ? <DecisionDialog decision={decision} saving={saving} error={error} onChange={(reason) => setDecision((current) => current ? { ...current, reason } : null)} onClose={() => { if (!saving) setDecision(null); }} onSave={() => void saveDecision()} /> : null}
  </section>;
}

export function ServiceCatalog({ initialGroup = "" }: { initialGroup?: string }) {
  const access = useConsoleAccess();
  const [catalog, setCatalog] = React.useState<CatalogResponse | null>(null);
  const [error, setError] = React.useState("");
  const [query, setQuery] = React.useState(initialGroup);
  const [editor, setEditor] = React.useState<{ row?: CatalogRow; draft: CatalogDraft; baseline: CatalogDraft } | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [notice, setNotice] = React.useState("");
  const [evidenceRow, setEvidenceRow] = React.useState<CatalogRow | null>(null);
  const [summaryRow, setSummaryRow] = React.useState<CatalogRow | null>(null);
  const [page, setPage] = React.useState(0);
  const pageSize = 12;
  const closeEditor = React.useCallback(() => setEditor(null), []);
  const load = React.useCallback(async (signal?: AbortSignal) => {
    setError("");
    try {
      const next = await fetchJson<CatalogResponse>("/api/v1/service-catalog", { signal });
      setCatalog(next);
    }
    catch (reason) { if ((reason as Error).name !== "AbortError") setError((reason as Error).message || "Unable to load the Service Catalog."); }
  }, []);
  React.useEffect(() => {
    const controller = new AbortController();
    const request = window.setTimeout(() => { void load(controller.signal); }, 0);
    return () => { window.clearTimeout(request); controller.abort(); };
  }, [load]);

  const rows = React.useMemo(() => (catalog?.items ?? []).filter((row) => {
    const needle = query.trim().toLocaleLowerCase();
    return !needle || [row.display_name, row.service_group, row.owner, row.lead, row.lead_profile?.email].filter(Boolean).some((value) => String(value).toLocaleLowerCase().includes(needle));
  }), [catalog, query]);
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const currentPage = Math.min(page, pageCount - 1);
  const visibleRows = rows.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
  const canCreate = access.isAdmin;
  const openCreate = () => { const draft = emptyDraft(); setNotice(""); setError(""); setEditor({ draft, baseline: draft }); };
  const openEdit = (row: CatalogRow) => { const draft = draftFromRow(row); setNotice(""); setError(""); setEditor({ row, draft, baseline: draft }); };
  const save = async () => {
    if (!editor) return;
    const draft = editor.draft;
    if (!draft.service_group.trim() || !draft.display_name.trim()) { setError("Service group key and display name are required."); return; }
    setSaving(true); setError("");
    let attributes: Record<string, unknown> | undefined;
    try {
      const parsed: unknown = draft.attributes_text.trim() ? JSON.parse(draft.attributes_text) : undefined;
      if (parsed !== undefined && (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))) throw new Error("Operational attributes must be a JSON object.");
      attributes = parsed as Record<string, unknown> | undefined;
    } catch (reason) { setError((reason as Error).message || "Operational attributes must be valid JSON."); setSaving(false); return; }
    const { il2_date, il5_date, attributes_text: _attributesText, crypto_module_plans, ...draftFields } = draft;
    const body = {
      ...draftFields, source_collection: draft.source_collection.trim(), service_group: draft.service_group.trim(), display_name: draft.display_name.trim(),
      il2_target_date: il2_date || null, il5_target_date: il5_date || null, crypto_module_plans: serializeCryptoModulePlans(crypto_module_plans), ...(attributes === undefined ? {} : { attributes }),
    };
    try {
      if (access.isAdmin) {
        if (!draft.rationale.trim() || draft.rationale.trim().length < 8) { setError("Provide a change reason of at least 8 characters."); setSaving(false); return; }
        const { source_collection, service_group, rationale: _rationale, ...allFields } = body;
        const changed = <K extends keyof CatalogDraft>(key: K) => draft[key] !== editor.baseline[key];
        const change: Record<string, unknown> = editor.row ? {} : { ...allFields };
        if (editor.row) {
          const fields: Array<keyof CatalogDraft> = ["display_name", "owner", "owner_profile_email", "lead", "lead_profile_email", "il2_status", "il5_status", "service_impact_risk", "comments"];
          for (const field of fields) if (changed(field)) change[field] = draft[field] || null;
          if (changed("il2_date")) change.il2_target_date = draft.il2_date || null;
          if (changed("il5_date")) change.il5_target_date = draft.il5_date || null;
          if (changed("attributes_text")) change.attributes = attributes ?? {};
          if (changed("crypto_module_plans")) change.crypto_module_plans = body.crypto_module_plans;
          if (!Object.keys(change).length) { setError("Change at least one service attribute before saving."); setSaving(false); return; }
        }
        const path = editor.row ? `/api/v1/admin/service-catalog/${encodeURIComponent(source_collection)}/${encodeURIComponent(service_group)}` : "/api/v1/admin/service-catalog";
        const payload = editor.row
          ? { ...change, expected_revision: editor.row.revision ?? 0, reason: draft.rationale.trim() }
          : { ...change, source_collection, service_group, reason: draft.rationale.trim() };
        await fetchJson(path, { method: editor.row ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        setNotice(editor.row ? "Service group updated and approved." : "Service group created and approved.");
      } else {
        if (draft.rationale.trim().length < 8) { setError("Explain the reason for this proposed change in at least 8 characters."); setSaving(false); return; }
        const changed = <K extends keyof CatalogDraft>(key: K) => draft[key] !== editor.baseline[key];
        const proposal: Record<string, unknown> = {
          source_collection: draft.source_collection, service_group: draft.service_group,
          expected_revision: editor.row?.revision ?? 0, rationale: draft.rationale.trim(),
        };
        const fields: Array<keyof CatalogDraft> = ["display_name", "owner", "owner_profile_email", "lead", "lead_profile_email", "il2_status", "il5_status", "service_impact_risk", "comments"];
        for (const field of fields) if (changed(field)) proposal[field] = draft[field] || null;
        if (changed("il2_date")) proposal.il2_target_date = draft.il2_date || null;
        if (changed("il5_date")) proposal.il5_target_date = draft.il5_date || null;
        if (changed("attributes_text")) proposal.attributes = attributes ?? {};
        if (changed("crypto_module_plans")) proposal.crypto_module_plans = body.crypto_module_plans;
        if (Object.keys(proposal).length === 4) { setError("Change at least one service attribute before submitting."); setSaving(false); return; }
        await fetchJson("/api/v1/service-catalog/proposals", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(proposal) });
        setNotice("Change proposal submitted for administrator approval.");
      }
      setEditor(null); await load();
    } catch (reason) { setError((reason as Error).message || "Unable to save the service group."); }
    finally { setSaving(false); }
  };

  return <div className="service-catalog-workbench">
    <section className="page-heading inventory-heading"><div><p className="eyebrow">Service register</p><h1>Service Catalog</h1><p className="page-subtitle">Service ownership, planning, and impact metadata for the catalog. {access.isAdmin ? "Administrators can maintain approved records." : access.activeMode === "product_lead" ? "Submit changes for administrator approval." : "Read-only access."}</p></div><div className="heading-actions"><button type="button" className="refresh-button" onClick={() => void load()}><RefreshCw size={17} />Refresh</button>{canCreate ? <button type="button" className="primary-button" onClick={openCreate}><Plus size={17} />Add service group</button> : null}</div></section>
    {notice ? <p className="catalog-notice" role="status"><Check size={16} />{notice}</p> : null}
    {error && !editor ? <p className="admin-error" role="alert">{error}</p> : null}
    <section className="rounded-2xl border border-border bg-card shadow-sm" aria-label="Service Catalog">
      <div className="catalog-toolbar"><label>Search service groups<input value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} placeholder="Service, owner, lead, or profile" /></label><span>{rows.length} of {catalog?.total ?? 0} service groups · operational planning records</span></div>
      <p className="table-scroll-hint" id="catalog-scroll-hint">Planning impact is owner-supplied context, not an assessment result. On wider screens, scroll horizontally to review all fields.</p>
      <div className="accountability-table-scroll" aria-describedby="catalog-scroll-hint"><table className="service-catalog-table"><thead><tr><th>Service group</th><th>Owner and lead</th><th>IL2 plan</th><th>IL5 plan</th><th>Planning impact</th><th>Publication</th><th aria-label="Actions" /></tr></thead><tbody>
        {visibleRows.map((row) => <tr key={row.service_key}>
          <td data-label="Service group"><strong>{row.display_name}</strong><code>{row.service_key}</code>{!row.has_evidence ? <small>No current catalog evidence</small> : null}</td>
          <td data-label="Owner and lead"><strong>{row.owner || "Not supplied"}</strong><span>{row.lead || "Lead not supplied"}</span></td>
          <td data-label="IL2 plan">{planText(row.il2)}</td><td data-label="IL5 plan">{planText(row.il5)}</td>
          <td data-label="Planning impact">{row.service_impact_risk ? <Badge tone="neutral">{titleCase(row.service_impact_risk)}</Badge> : "Not supplied"}</td>
          <td data-label="Publication"><Badge tone={(row.pending_proposals ?? 0) > 0 ? "warning" : approvalTone(row.approval_status)}>{approvalLabel(row)}</Badge></td>
          <td data-label="Actions"><button type="button" className="table-action" onClick={() => access.isAdmin && row.has_evidence ? setEvidenceRow(row) : setSummaryRow(row)} aria-label={`Details for ${row.display_name}`}>Details</button>{row.can_edit ? <button type="button" className="table-action" onClick={() => openEdit(row)}>{access.isAdmin ? "Edit" : "Propose"}<FilePenLine size={15} /></button> : null}</td>
        </tr>)}
        {catalog && !rows.length ? <tr><td colSpan={7} className="mapping-empty">No service groups match this search.</td></tr> : null}
      </tbody></table></div>
      <div className="catalog-mobile-list" aria-label="Service Catalog records">
        {visibleRows.map((row) => <article className="catalog-mobile-card" key={row.service_key}>
          <header><div><strong>{row.display_name}</strong><code>{row.service_key}</code></div><Badge tone={(row.pending_proposals ?? 0) > 0 ? "warning" : approvalTone(row.approval_status)}>{approvalLabel(row)}</Badge></header>
          <dl><div><dt>Owner</dt><dd>{row.owner || "Not supplied"}</dd></div><div><dt>Lead</dt><dd>{row.lead || "Not supplied"}</dd></div><div><dt>IL2 plan</dt><dd>{titleCase(row.il2.status || "not supplied")}{row.il2.date ? ` · ${row.il2.date}` : ""}</dd></div><div><dt>IL5 plan</dt><dd>{titleCase(row.il5.status || "not supplied")}{row.il5.date ? ` · ${row.il5.date}` : ""}</dd></div><div><dt>Planning impact</dt><dd>{row.service_impact_risk ? titleCase(row.service_impact_risk) : "Not supplied"}</dd></div><div><dt>Catalog evidence</dt><dd>{row.has_evidence ? "Current records available" : "No current records"}</dd></div></dl>
          <footer><button type="button" className="secondary-button" onClick={() => access.isAdmin && row.has_evidence ? setEvidenceRow(row) : setSummaryRow(row)}>Details</button>{row.can_edit ? <button type="button" className="secondary-button" onClick={() => openEdit(row)}>{access.isAdmin ? "Edit" : "Propose"}<FilePenLine size={15} /></button> : null}</footer>
        </article>)}
        {catalog && !rows.length ? <p className="mapping-empty">No service groups match this search.</p> : null}
      </div>
      {rows.length > pageSize ? <nav className="catalog-pagination" aria-label="Service Catalog pages"><span>Showing {currentPage * pageSize + 1}–{Math.min((currentPage + 1) * pageSize, rows.length)} of {rows.length}</span><div><button type="button" className="secondary-button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button><span>Page {currentPage + 1} of {pageCount}</span><button type="button" className="secondary-button" disabled={currentPage >= pageCount - 1} onClick={() => setPage(currentPage + 1)}>Next</button></div></nav> : null}
    </section>
    {editor ? <CatalogEditor editor={editor} isAdmin={access.isAdmin} options={catalog?.crypto_module_options ?? []} saving={saving} error={error} onChange={(draft) => setEditor((value) => value ? { ...value, draft } : value)} onClose={closeEditor} onSave={() => void save()} /> : null}
    {evidenceRow ? <ServiceGroupDrawer row={evidenceRow} onClose={() => setEvidenceRow(null)} /> : null}
    {summaryRow ? <CatalogSummaryDialog row={summaryRow} options={catalog?.crypto_module_options ?? []} onClose={() => setSummaryRow(null)} /> : null}
  </div>;
}

function CatalogEditor({ editor, isAdmin, options, saving, error, onChange, onClose, onSave }: { editor: { row?: CatalogRow; draft: CatalogDraft; baseline: CatalogDraft }; isAdmin: boolean; options: CryptoModuleOption[]; saving: boolean; error: string; onChange: (draft: CatalogDraft) => void; onClose: () => void; onSave: () => void }) {
  const draft = editor.draft;
  const panelRef = useCatalogDialogAccessibility(onClose, saving);
  const update = <K extends keyof CatalogDraft>(key: K, value: CatalogDraft[K]) => onChange({ ...draft, [key]: value });
  const changed = !editor.row || (Object.keys(draft) as Array<keyof CatalogDraft>).some((key) => key !== "rationale" && draft[key] !== editor.baseline[key]);
  const canSave = !saving && changed && draft.rationale.trim().length >= 8 && Boolean(draft.display_name.trim() && draft.service_group.trim());
  const dialog = <div className="drawer-backdrop catalog-editor-backdrop" role="presentation" onMouseDown={(event) => { if (!saving && event.currentTarget === event.target) onClose(); }}><section ref={panelRef} tabIndex={-1} className="catalog-editor" role="dialog" aria-modal="true" aria-labelledby="catalog-editor-title"><header><div><p className="eyebrow">{isAdmin ? "Authoritative service record" : "Proposed service change"}</p><h2 id="catalog-editor-title">{editor.row ? `Update ${editor.row.display_name}` : "Add service group"}</h2></div><button type="button" className="icon-button" onClick={onClose} disabled={saving} aria-label="Close editor"><X /></button></header><div className="catalog-editor-body"><p className="catalog-create-guidance">Operational planning metadata only. This record does not establish FIPS validation, deployment, or authorization.</p>{error ? <p className="admin-error catalog-form-error" role="alert">{error}</p> : null}{!editor.row ? <p className="catalog-create-guidance">After saving a new service group, add its exact group-to-service mapping before a service lead can access it.</p> : null}<label className="catalog-comments">{isAdmin ? "Change reason" : "Reason for change"}<small>At least eight characters; identify the source or decision.</small><textarea required minLength={8} value={draft.rationale} onChange={(event) => update("rationale", event.target.value)} /></label><label>Display name <small>The readable name shown throughout CBOM. It can be updated without changing access.</small><input value={draft.display_name} onChange={(event) => update("display_name", event.target.value)} /></label><label>Exact MyID group key <small>{editor.row ? "Immutable after creation. To change it, create the replacement service group and publish its mapping in Admin." : "Use this key when an administrator publishes the matching fedsse-&lt;key&gt;-leads and fedsse-&lt;key&gt;-engineers mappings in Admin."}</small><input disabled={Boolean(editor.row)} value={draft.service_group} onChange={(event) => update("service_group", event.target.value)} placeholder="example-service" /></label><label>Source collection<input disabled={Boolean(editor.row)} value={draft.source_collection} onChange={(event) => update("source_collection", event.target.value)} /></label><label>Owner<input value={draft.owner} onChange={(event) => update("owner", event.target.value)} /></label><label>Owner profile email <small>Optional and informational only</small><input type="email" value={draft.owner_profile_email} onChange={(event) => update("owner_profile_email", event.target.value)} placeholder="name@cisco.com" /></label><label>Service lead<input value={draft.lead} onChange={(event) => update("lead", event.target.value)} /></label><label>Lead profile email <small>Optional and informational only</small><input type="email" value={draft.lead_profile_email} onChange={(event) => update("lead_profile_email", event.target.value)} placeholder="name@cisco.com" /></label><PlanField label="IL2" status={draft.il2_status} date={draft.il2_date} onStatus={(value) => update("il2_status", value)} onDate={(value) => update("il2_date", value)} /><PlanField label="IL5" status={draft.il5_status} date={draft.il5_date} onStatus={(value) => update("il5_status", value)} onDate={(value) => update("il5_date", value)} /><label>Planning impact risk<select value={draft.service_impact_risk} onChange={(event) => update("service_impact_risk", event.target.value)}>{riskOptions.map((risk) => <option key={risk} value={risk}>{risk ? titleCase(risk) : "Not supplied"}</option>)}</select></label><CryptoModulePlansEditor plans={draft.crypto_module_plans} options={options} imported={editor.row?.imported_target_modules ?? []} onChange={(crypto_module_plans) => update("crypto_module_plans", crypto_module_plans)} /><label className="catalog-comments">Comments<textarea value={draft.comments} onChange={(event) => update("comments", event.target.value)} /></label><label className="catalog-comments">Operational attributes <small>Optional JSON object; access and scope fields are rejected.</small><textarea value={draft.attributes_text} onChange={(event) => update("attributes_text", event.target.value)} placeholder={'{\n  "delivery_team": "example"\n}'} /></label></div><footer><span className="catalog-submit-hint">{!changed ? "Change at least one field." : draft.rationale.trim().length < 8 ? "Add a reason of at least eight characters." : "Ready for review."}</span><button type="button" className="secondary-button" disabled={saving} onClick={onClose}>Cancel</button><button type="button" className="primary-button" disabled={!canSave} onClick={onSave}>{isAdmin ? "Save approved record" : "Submit proposal"}</button></footer></section></div>;
  return typeof document === "undefined" ? null : createPortal(dialog, document.body);
}

function CryptoModulePlansEditor({ plans, options, imported, onChange }: { plans: CryptoModulePlan[]; options: CryptoModuleOption[]; imported: ImportedTargetModule[]; onChange: (plans: CryptoModulePlan[]) => void }) {
  const update = (id: string, patch: Partial<CryptoModulePlan>) => onChange(plans.map((plan) => plan.id === id ? { ...plan, ...patch } : plan));
  const attachImported = (id: string, sourceRecord: string) => {
    const source = imported.find((item) => item.record_sha256 === sourceRecord);
    update(id, {
      source_record_sha256: sourceRecord,
      current_module: source?.current_module ?? "",
      current_version: source?.current_version ?? "",
    });
  };
  return <fieldset className="catalog-crypto-plans catalog-comments">
    <legend>Cryptographic module plan</legend>
    <p>Record the current module and an intended target. A selected certificate or vendor source is planning evidence only; deployment, module boundary, approved mode, and scope still require review.</p>
    {imported.length ? <details className="catalog-imported-modules"><summary>Imported target-module records ({imported.length})</summary><ul>{imported.map((item) => <li key={item.record_sha256}><strong>{item.current_module || "Current module not supplied"}{item.current_version ? ` ${item.current_version}` : ""}</strong><span>→ {item.target_module || "Target not supplied"} · {titleCase(item.target_disposition)}</span></li>)}</ul></details> : null}
    {plans.map((plan, index) => {
      const custom = !plan.target_preset_id;
      const selected = options.find((option) => option.id === plan.target_preset_id);
      return <article className="catalog-crypto-plan" key={plan.id}>
        <header><strong>Module plan {index + 1}</strong><button type="button" className="table-action" onClick={() => onChange(plans.filter((item) => item.id !== plan.id))}>Remove</button></header>
        <label>Attach imported module record<select value={plan.source_record_sha256} onChange={(event) => attachImported(plan.id, event.target.value)}><option value="">Catalog-only plan</option>{imported.map((item) => <option key={item.record_sha256} value={item.record_sha256}>{item.current_module || "Current module not supplied"}{item.current_version ? ` ${item.current_version}` : ""} → {item.target_module || "Target not supplied"}</option>)}</select></label>
        <label>Current module<input value={plan.current_module} readOnly={Boolean(plan.source_record_sha256)} onChange={(event) => update(plan.id, { current_module: event.target.value })} placeholder="Module name" /></label>
        <label>Current version<input value={plan.current_version} readOnly={Boolean(plan.source_record_sha256)} onChange={(event) => update(plan.id, { current_version: event.target.value })} placeholder="Version or build" /></label>
        <label className="catalog-crypto-wide">Target module<select value={plan.target_preset_id} onChange={(event) => update(plan.id, { target_preset_id: event.target.value, custom_target_module: "", custom_target_version: "", evidence_basis: event.target.value ? "" : plan.evidence_basis })}><option value="">Custom target module</option>{options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select>{selected ? <small>{selected.module_name}{selected.module_version ? ` ${selected.module_version}` : ""}{selected.certificate_number ? ` · ${selected.certificate_number}` : ""} · {titleCase(selected.public_status)}{selected.source_url ? ` · ${selected.source_url}` : ""}</small> : null}</label>
        {custom ? <><label>Custom target module<input value={plan.custom_target_module} onChange={(event) => update(plan.id, { custom_target_module: event.target.value })} placeholder="Vendor module name" /></label><label>Custom target version<input value={plan.custom_target_version} onChange={(event) => update(plan.id, { custom_target_version: event.target.value })} placeholder="Exact module version" /></label></> : null}
        {custom ? <label>Evidence basis<select value={plan.evidence_basis} onChange={(event) => update(plan.id, { evidence_basis: event.target.value as CryptoModulePlan["evidence_basis"] })}><option value="">Not supplied</option><option value="cmvp_certificate">CMVP certificate</option><option value="cmvp_in_process">CMVP in process</option><option value="vendor_recommendation">Vendor recommendation</option><option value="other">Other supporting record</option></select></label> : null}
        <label>Supporting document URL<input type="url" value={plan.supporting_url} onChange={(event) => update(plan.id, { supporting_url: event.target.value })} placeholder="https://…" /></label>
        <label className="catalog-crypto-wide">Planning note<textarea value={plan.note} onChange={(event) => update(plan.id, { note: event.target.value })} placeholder="Scope, owner, deployment or evidence context" /></label>
      </article>;
    })}
    <button type="button" className="secondary-button catalog-add-module" disabled={plans.length >= 16} onClick={() => onChange([...plans, newCryptoModulePlan()])}>Add module plan</button>
  </fieldset>;
}

function CatalogSummaryDialog({ row, options, onClose }: { row: CatalogRow; options: CryptoModuleOption[]; onClose: () => void }) {
  const panelRef = useCatalogDialogAccessibility(onClose, false);
  const attributes = Object.entries(row.attributes ?? {});
  const dialog = <div className="drawer-backdrop catalog-editor-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}>
    <section ref={panelRef} tabIndex={-1} className="catalog-editor catalog-summary" role="dialog" aria-modal="true" aria-labelledby="catalog-summary-title">
      <header><div><p className="eyebrow">Operational planning record</p><h2 id="catalog-summary-title">{row.display_name}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close details"><X /></button></header>
      <div className="catalog-editor-body">
        <p className="catalog-create-guidance">This record describes service ownership and planning. It does not establish product deployment, FIPS module validation, or an authorization decision.</p>
        <div className="catalog-summary-field"><span>Service group</span><strong>{row.source_collection}/{row.service_group}</strong></div>
        <div className="catalog-summary-field"><span>Catalog evidence</span><strong>{row.has_evidence ? "Current records available" : "No current records"}</strong></div>
        <div className="catalog-summary-field"><span>Owner</span><strong>{row.owner || "Not supplied"}</strong>{row.owner_profile?.email ? <small>{row.owner_profile.email}</small> : null}</div>
        <div className="catalog-summary-field"><span>Lead</span><strong>{row.lead || "Not supplied"}</strong>{row.lead_profile?.email ? <small>{row.lead_profile.email}</small> : null}</div>
        <div className="catalog-summary-field"><span>IL2 plan</span>{planText(row.il2)}</div>
        <div className="catalog-summary-field"><span>IL5 plan</span>{planText(row.il5)}</div>
        <div className="catalog-summary-field"><span>Planning impact</span><strong>{row.service_impact_risk ? titleCase(row.service_impact_risk) : "Not supplied"}</strong></div>
        <div className="catalog-summary-field"><span>Publication</span><strong>{approvalLabel(row)}</strong></div>
        {row.crypto_module_plans?.length ? <div className="catalog-summary-field catalog-comments"><span>Cryptographic module plans</span><ul className="catalog-module-summary">{row.crypto_module_plans.map((plan, index) => { const option = options.find((item) => item.id === plan.target_preset_id); const target = cryptoPlanTarget(plan, option); const evidenceState = plan.evidence_state ? titleCase(plan.evidence_state) : "Not reconciled"; const disposition = plan.planning_disposition ? titleCase(plan.planning_disposition) : "Not supplied"; const basis = (plan.disposition_basis || plan.evidence_basis) ? titleCase(plan.disposition_basis || plan.evidence_basis || "") : "Not supplied"; const evidenceUrl = plan.evidence_url || plan.supporting_url; return <li key={`${plan.current_module}-${plan.target_preset_id}-${index}`}><strong>{plan.current_module || "Current module not supplied"}{plan.current_version ? ` ${plan.current_version}` : ""}</strong><span>→ {target}</span><dl className="catalog-module-evidence"><div><dt>Evidence state</dt><dd className={plan.evidence_state === "evidence_superseded" ? "catalog-evidence-warning" : undefined}>{evidenceState}</dd></div><div><dt>Planning disposition</dt><dd>{disposition}</dd></div><div><dt>Disposition basis</dt><dd>{basis}</dd></div></dl>{evidenceUrl ? <a href={evidenceUrl} target="_blank" rel="noreferrer">Evidence source</a> : null}<small className={plan.evidence_state === "evidence_superseded" ? "catalog-evidence-warning" : undefined}>{cryptoEvidenceExplanation(plan)}</small></li>; })}</ul></div> : null}
        {row.comments ? <div className="catalog-summary-field catalog-comments"><span>Comments</span><p>{row.comments}</p></div> : null}
        {attributes.length ? <div className="catalog-summary-field catalog-comments"><span>Operational attributes</span><dl>{attributes.map(([key, value]) => <React.Fragment key={key}><dt>{titleCase(key)}</dt><dd>{value ?? "Not supplied"}</dd></React.Fragment>)}</dl></div> : null}
      </div>
      <footer><button type="button" className="secondary-button" onClick={onClose}>Close</button></footer>
    </section>
  </div>;
  return typeof document === "undefined" ? null : createPortal(dialog, document.body);
}

function DecisionDialog({ decision, saving, error, onChange, onClose, onSave }: { decision: { proposal: CatalogProposal; value: "approved" | "rejected"; reason: string }; saving: boolean; error: string; onChange: (value: string) => void; onClose: () => void; onSave: () => void }) {
  const panelRef = useCatalogDialogAccessibility(onClose, saving);
  const decisionLabel = decision.value === "approved" ? "Publish planning change" : "Reject planning change";
  const dialog = <div className="drawer-backdrop catalog-editor-backdrop" role="presentation" onMouseDown={(event) => { if (!saving && event.currentTarget === event.target) onClose(); }}><section ref={panelRef} tabIndex={-1} className="catalog-editor catalog-decision" role="dialog" aria-modal="true" aria-labelledby="catalog-decision-title"><header><div><p className="eyebrow">Administrator decision</p><h2 id="catalog-decision-title">{decisionLabel} for {decision.proposal.source_collection}/{decision.proposal.service_group}</h2></div><button type="button" className="icon-button" onClick={onClose} disabled={saving} aria-label="Close decision"><X /></button></header><div className="catalog-editor-body">{error ? <p className="admin-error catalog-form-error" role="alert">{error}</p> : null}<p className="catalog-create-guidance">This decision affects Service Catalog planning metadata only. It does not approve a POA&amp;M, ATO, CMVP or FIPS status, deployment evidence, or access scope.</p><div className="catalog-proposal-changes catalog-comments">{proposalChanges(decision.proposal)}</div><label className="catalog-comments">Decision reason<small>At least eight characters.</small><textarea minLength={8} value={decision.reason} onChange={(event) => onChange(event.target.value)} /></label></div><footer><button type="button" className="secondary-button" disabled={saving} onClick={onClose}>Cancel</button><button type="button" className="primary-button" disabled={saving || decision.reason.trim().length < 8} onClick={onSave}>{decisionLabel}</button></footer></section></div>;
  return typeof document === "undefined" ? null : createPortal(dialog, document.body);
}

function PlanField({ label, status, date, onStatus, onDate }: { label: string; status: string; date: string; onStatus: (value: string) => void; onDate: (value: string) => void }) {
  return <fieldset className="catalog-plan"><legend>{label} planning</legend><label>Status<select value={status} onChange={(event) => onStatus(event.target.value)}>{!status ? <option value="">Not supplied in your scope</option> : null}{status && !planStatuses.includes(status) ? <option value={status}>Imported: {titleCase(status)}</option> : null}{planStatuses.map((option) => <option key={option} value={option}>{titleCase(option)}</option>)}</select></label><label>Target date<input type="date" value={date} onChange={(event) => onDate(event.target.value)} /></label></fieldset>;
}
