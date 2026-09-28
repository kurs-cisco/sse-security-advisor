"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Pencil, Plus, RefreshCw, ShieldCheck, Trash2, X } from "lucide-react";
import { Badge } from "@/app/components/ui/badge";
import { Card } from "@/app/components/ui/card";
import { ApiError, fetchJson } from "@/app/lib/http";

type Product = {
  product_scope_id: string;
  boundary_name: string;
  product_name: string;
};

type ServiceOption = {
  source_collection: string;
  service_group: string;
  display_name: string;
  current_source_files: number;
  fingerprinted_source_files: number;
};

type MappingRow = ServiceOption & {
  service_key: string;
  lead_group: string;
  engineer_group: string;
  product_scope_ids: string[];
};

type MappingResponse = {
  revision: string;
  policy_version: string;
  source: "deployment" | "admin";
  can_manage: boolean;
  products: Product[];
  service_options: ServiceOption[];
  rows: MappingRow[];
};

type EditState = {
  serviceKey: string;
  sourceCollection: string;
  serviceGroup: string;
  productScopeIds: string[];
  reason: string;
};

function serviceOptionKey(option: Pick<ServiceOption, "source_collection" | "service_group">) {
  return `${option.source_collection}/${option.service_group}`;
}

function defaultGroupStem(serviceGroup: string) {
  return serviceGroup.replace(/-no-cbom$/i, "").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
}

function isGroupStem(value: string) {
  return /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value);
}

function productLabel(product: Product) {
  return `${product.product_name} · ${product.boundary_name}`;
}

export function MappingDialog({ title, description, onClose, children, actions }: {
  title: string;
  description: string;
  onClose: () => void;
  children: ReactNode;
  actions: ReactNode;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const main = document.getElementById("main-content");
    const previousOverflow = document.body.style.overflow;
    main?.setAttribute("inert", "");
    document.body.style.overflow = "hidden";
    (dialogRef.current?.querySelector<HTMLElement>(".mapping-dialog-body select, .mapping-dialog-body input:not([type='checkbox']), .mapping-dialog-body textarea")
      ?? dialogRef.current?.querySelector<HTMLElement>("button:not([disabled])"))?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]")];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1)!;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      main?.removeAttribute("inert");
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, []);
  if (typeof document === "undefined") return null;
  return createPortal(
    <div className="mapping-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) closeRef.current(); }}>
      <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} tabIndex={-1} className="mapping-dialog">
        <header><div><h2 id={titleId}>{title}</h2><p id={descriptionId}>{description}</p></div><button type="button" className="icon-button" aria-label="Close dialog" onClick={onClose}><X size={18} /></button></header>
        <div className="mapping-dialog-body">{children}</div>
        <footer>{actions}</footer>
      </section>
    </div>, document.body,
  );
}

export function ServiceGroupMapping() {
  const [data, setData] = useState<MappingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState<EditState | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [retiring, setRetiring] = useState<MappingRow | null>(null);
  const [retireReason, setRetireReason] = useState("");
  const [dialogError, setDialogError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await fetchJson<MappingResponse>("/api/v1/admin/service-group-mappings", { dedupe: false });
      setData(next);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Service group mappings are unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const productsById = useMemo(() => new Map((data?.products ?? []).map((product) => [product.product_scope_id, product])), [data]);
  const rows = useMemo(() => {
    const term = filter.trim().toLowerCase();
    if (!term) return data?.rows ?? [];
    return (data?.rows ?? []).filter((row) => [row.display_name, row.source_collection, row.service_group, row.lead_group, row.engineer_group]
      .join(" ").toLowerCase().includes(term));
  }, [data?.rows, filter]);
  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visibleRows = rows.slice(safePage * pageSize, (safePage + 1) * pageSize);

  const mappedTargets = useMemo(() => new Map((data?.rows ?? []).map((row) => [serviceOptionKey(row), row.service_key])), [data?.rows]);
  const availableOptions = useMemo(() => (data?.service_options ?? []).filter((option) => !mappedTargets.has(serviceOptionKey(option))), [data?.service_options, mappedTargets]);
  const editingOptions = useMemo(() => {
    if (!editing) return [];
    return (data?.service_options ?? []).filter((option) => {
      const owner = mappedTargets.get(serviceOptionKey(option));
      return !owner || owner === editing.serviceKey;
    });
  }, [data?.service_options, editing, mappedTargets]);

  function startEdit(row: MappingRow) {
    setNotice(""); setError(""); setDialogError(""); setCreateOpen(false); setRetiring(null);
    setEditing({
      serviceKey: row.service_key, sourceCollection: row.source_collection, serviceGroup: row.service_group,
      productScopeIds: [...row.product_scope_ids], reason: "",
    });
  }

  function startCreate() {
    const option = availableOptions[0];
    if (!option) return;
    setNotice(""); setError(""); setDialogError(""); setRetiring(null);
    setEditing({
      serviceKey: defaultGroupStem(option.service_group), sourceCollection: option.source_collection, serviceGroup: option.service_group,
      productScopeIds: data?.products.map((product) => product.product_scope_id) ?? [], reason: "",
    });
    setCreateOpen(true);
  }

  function toggleProduct(productScopeId: string) {
    setEditing((current) => current ? {
      ...current,
      productScopeIds: current.productScopeIds.includes(productScopeId)
        ? current.productScopeIds.filter((id) => id !== productScopeId)
        : [...current.productScopeIds, productScopeId],
    } : current);
  }

  async function save() {
    if (!data || !editing || editing.reason.trim().length < 8 || !editing.productScopeIds.length || !isGroupStem(editing.serviceKey)) return;
    const editingExisting = !createOpen;
    const path = editingExisting
      ? `/api/v1/admin/service-group-mappings/${encodeURIComponent(editing.serviceKey)}`
      : "/api/v1/admin/service-group-mappings";
    try {
      setSaving(true); setDialogError("");
      await fetchJson(path, {
        method: editingExisting ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          service_key: editing.serviceKey,
          source_collection: editing.sourceCollection,
          service_group: editing.serviceGroup,
          product_scope_ids: editing.productScopeIds,
          reason: editing.reason.trim(),
          expected_revision: data.revision,
        }),
      });
      setEditing(null); setCreateOpen(false); setNotice(editingExisting ? "Service mapping updated and recorded in the access-policy audit trail." : "Service mapping added and recorded in the access-policy audit trail.");
      await load();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) setDialogError("This policy changed while you were editing. Close this dialog, refresh, and review the current mapping.");
      else setDialogError(caught instanceof Error ? caught.message : "Mapping update failed");
    } finally { setSaving(false); }
  }

  function startRetire(row: MappingRow) {
    setEditing(null); setCreateOpen(false); setNotice(""); setError(""); setDialogError("");
    setRetireReason(""); setRetiring(row);
  }

  async function retire() {
    if (!data || !data.can_manage || !retiring || retireReason.trim().length < 8) return;
    try {
      setSaving(true); setDialogError("");
      await fetchJson(`/api/v1/admin/service-group-mappings/${encodeURIComponent(retiring.service_key)}`, {
        method: "DELETE", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: retireReason.trim(), expected_revision: data.revision }),
      });
      setRetiring(null); setRetireReason("");
      setNotice("Service mapping retired and recorded in the access-policy audit trail.");
      await load();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) setDialogError("This policy changed before retirement. Close this dialog, refresh, and review the current mapping.");
      else setDialogError(caught instanceof Error ? caught.message : "Mapping retirement failed");
    } finally { setSaving(false); }
  }

  return <Card className="service-group-mapping" aria-label="Authoritative service group mappings">
    <div className="card-heading"><div><p className="eyebrow">Access routing policy</p><h2><ShieldCheck size={18} />Service group mappings</h2><p className="admin-card-note">This mapping routes catalog services and product contexts to exact MyID groups for application access. Product contexts do not establish ATO scope, deployment, CMVP validation, or compliance. MyID membership is managed in MyID and is never changed here.</p></div><div className="mapping-header-actions"><Badge tone={data?.source === "admin" ? "neutral" : "info"}>{data?.source === "admin" ? "Administrator maintained" : "Deployment baseline"}</Badge><button className="refresh-button" type="button" onClick={() => void load()} disabled={loading || saving}><RefreshCw size={16} className={loading ? "spin" : ""} />Refresh</button></div></div>
    {error ? <div className="admin-error" role="alert">{error}</div> : null}
    {notice ? <p className="mapping-notice" role="status">{notice}</p> : null}
    <div className="mapping-toolbar"><label>Find a service or group<input type="search" value={filter} onChange={(event) => { setFilter(event.target.value); setPage(0); }} placeholder="DLP, SaaS API, fedsse-…" /></label><div><details className="mapping-policy-version"><summary>Policy {data?.policy_version ?? "loading"} · revision {data?.revision ? `${data.revision.slice(0, 12)}…` : "—"}</summary><code>Policy: {data?.policy_version ?? "unavailable"}</code><code>Revision: {data?.revision ?? "unavailable"}</code></details>{data?.can_manage ? <><button className="primary-button" type="button" onClick={startCreate} disabled={saving || !availableOptions.length}><Plus size={16} />Add service mapping</button>{!availableOptions.length ? <small className="mapping-add-explanation">All {data.service_options.length} registered services already have a mapping. Retire a mapping before adding another.</small> : null}</> : <small>Read-only policy view</small>}</div></div>
    {loading && !data ? <p className="mapping-empty" role="status">Loading the authoritative mapping…</p> : null}
    {data ? <>
      <p className="table-scroll-hint">Product labels route application access. Current file counts describe catalog inventory only.</p>
      <div className="table-scroll" role="region" aria-label="Service group mappings table" tabIndex={0}><table className="mapping-table"><caption className="sr-only">Service group mappings</caption><thead><tr>
        <th>Catalog service</th><th>Product access contexts</th><th>Exact MyID groups</th>
        {data.can_manage ? <th><span className="sr-only">Mapping actions</span></th> : null}
      </tr></thead><tbody>{visibleRows.map((row) => <tr key={row.service_key}>
        <td><strong>{row.display_name || row.service_group}</strong><small className="mono">{row.source_collection}/{row.service_group}</small><details className="mapping-traceability"><summary>Catalog traceability</summary>{row.fingerprinted_source_files === 0 ? <span className="mapping-evidence-gap"><strong>Evidence gap — </strong>{row.current_source_files === 0 ? "No current catalog source files are observed." : "No current catalog source file with a recorded SHA-256 is observed."} Inventory coverage is unknown; this does not indicate compliance.</span> : row.current_source_files > 0 ? <small>{row.current_source_files.toLocaleString()} current catalog source file{row.current_source_files === 1 ? "" : "s"} · {row.fingerprinted_source_files.toLocaleString()} with recorded SHA-256. Exact hashes are disclosed in authorized catalog evidence views.</small> : <small>Current catalog source-file count unavailable.</small>}</details></td>
        <td><div className="mapping-products">{row.product_scope_ids.map((id) => {
          const product = productsById.get(id);
          return <Badge key={id} tone="info">{product ? productLabel(product) : id}</Badge>;
        })}</div></td>
        <td><code>{row.lead_group}</code><code>{row.engineer_group}</code></td>
        {data.can_manage ? <td className="mapping-actions"><button className="admin-save" type="button" aria-label={`Edit ${row.display_name || row.service_group} mapping`} onClick={() => startEdit(row)} disabled={saving}><Pencil size={14} />Edit</button><button className="mapping-retire" type="button" aria-label={`Retire ${row.display_name || row.service_group} mapping`} onClick={() => startRetire(row)} disabled={saving}><Trash2 size={14} />Retire</button></td> : null}
      </tr>)}{!rows.length ? <tr><td colSpan={data.can_manage ? 4 : 3}><p className="mapping-empty">{filter ? "No service mapping matches this search." : "No service group mappings are configured."}</p></td></tr> : null}</tbody></table></div>
      <div className="mapping-mobile-list" aria-label="Service group mappings">
        {visibleRows.map((row) => <article key={row.service_key} className="mapping-mobile-card">
          <header><div><strong>{row.display_name || row.service_group}</strong><code>{row.source_collection}/{row.service_group}</code></div>{data.can_manage ? <div className="mapping-actions"><button className="admin-save" type="button" aria-label={`Edit ${row.display_name || row.service_group} mapping`} onClick={() => startEdit(row)} disabled={saving}><Pencil size={14} />Edit</button><button className="mapping-retire" type="button" aria-label={`Retire ${row.display_name || row.service_group} mapping`} onClick={() => startRetire(row)} disabled={saving}><Trash2 size={14} />Retire</button></div> : null}</header>
          <section><strong>Product access contexts</strong><div className="mapping-products">{row.product_scope_ids.map((id) => { const product = productsById.get(id); return <Badge key={id} tone="info">{product ? productLabel(product) : id}</Badge>; })}</div></section>
          <section><strong>Exact MyID groups</strong><code>{row.lead_group}</code><code>{row.engineer_group}</code></section>
          <details className="mapping-traceability"><summary>Catalog traceability</summary>{row.fingerprinted_source_files === 0 ? <span className="mapping-evidence-gap"><strong>Evidence gap — </strong>{row.current_source_files === 0 ? "No current catalog source files are observed." : "No current catalog source file with a recorded SHA-256 is observed."} Inventory coverage is unknown; this does not indicate compliance.</span> : row.current_source_files > 0 ? <small>{row.current_source_files.toLocaleString()} current catalog source file{row.current_source_files === 1 ? "" : "s"} · {row.fingerprinted_source_files.toLocaleString()} with recorded SHA-256. Exact hashes are disclosed in authorized catalog evidence views.</small> : <small>Current catalog source-file count unavailable.</small>}</details>
        </article>)}
        {!rows.length ? <p className="mapping-empty">{filter ? "No service mapping matches this search." : "No service group mappings are configured."}</p> : null}
      </div>
      {rows.length > pageSize ? <nav className="mapping-pagination" aria-label="Mapping table pages"><span>{safePage * pageSize + 1}–{Math.min((safePage + 1) * pageSize, rows.length)} of {rows.length} mappings</span><div><button type="button" aria-label="Previous mapping page" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}><ChevronLeft size={16} /></button><span>Page {safePage + 1} of {pageCount}</span><button type="button" aria-label="Next mapping page" disabled={safePage >= pageCount - 1} onClick={() => setPage(safePage + 1)}><ChevronRight size={16} /></button></div></nav> : null}
    </> : null}
    {editing && data ? <MappingDialog
      title={createOpen ? "Add service mapping" : `Edit ${editing.serviceKey} mapping`}
      description="Changes take effect on the next verified request and are recorded in the access-policy audit."
      onClose={() => { if (!saving) { setEditing(null); setCreateOpen(false); setDialogError(""); } }}
      actions={<><button className="admin-save" type="button" disabled={saving} onClick={() => { setEditing(null); setCreateOpen(false); setDialogError(""); }}>Cancel</button><button className="primary-button" type="button" onClick={() => void save()} disabled={saving || editing.reason.trim().length < 8 || !editing.productScopeIds.length || !isGroupStem(editing.serviceKey)}>{saving ? "Saving…" : createOpen ? "Add mapping" : "Save mapping"}</button></>}
    >
      <div className="mapping-editor">
        {dialogError ? <p className="admin-error" role="alert">{dialogError}</p> : null}
        <label>Catalog service<select value={serviceOptionKey({ source_collection: editing.sourceCollection, service_group: editing.serviceGroup })} onChange={(event) => { const option = data.service_options.find((candidate) => serviceOptionKey(candidate) === event.target.value); if (option) setEditing((current) => current ? { ...current, sourceCollection: option.source_collection, serviceGroup: option.service_group, ...(createOpen ? { serviceKey: defaultGroupStem(option.service_group) } : {}) } : current); }}><option value="">Select a service</option>{editingOptions.map((option) => <option key={serviceOptionKey(option)} value={serviceOptionKey(option)}>{option.display_name} · {option.source_collection}/{option.service_group}</option>)}</select></label>
        {createOpen ? <label>Exact group stem<input value={editing.serviceKey} onChange={(event) => setEditing((current) => current ? { ...current, serviceKey: event.target.value.trim().toLowerCase() } : current)} aria-describedby="group-stem-help group-stem-state" aria-invalid={!isGroupStem(editing.serviceKey)} /><small id="group-stem-help">Use the MyID group stem, for example <code>apix</code> for <code>fedsse-apix-leads</code>.</small><small id="group-stem-state" role="status">{isGroupStem(editing.serviceKey) ? "Valid group stem." : "Enter lowercase letters, digits, or hyphens."}</small></label> : <p className="mapping-service-key"><strong>Exact MyID groups</strong><code>fedsse-{editing.serviceKey}-leads</code><code>fedsse-{editing.serviceKey}-engineers</code></p>}
        <fieldset><legend>Product contexts</legend>{data.products.map((product) => <label className="scope-option" key={product.product_scope_id}><input type="checkbox" checked={editing.productScopeIds.includes(product.product_scope_id)} onChange={() => toggleProduct(product.product_scope_id)} /><span><strong>{product.product_name}</strong><small>{product.boundary_name}</small></span></label>)}</fieldset>
        <label>Change reason<textarea value={editing.reason} onChange={(event) => setEditing((current) => current ? { ...current, reason: event.target.value } : current)} minLength={8} maxLength={500} placeholder="Describe why this mapping should change" /></label>
      </div>
    </MappingDialog> : null}
    {retiring && data ? <MappingDialog
      title={`Retire ${retiring.display_name || retiring.service_group} mapping`}
      description="This removes the application grant for this service. MyID memberships remain unchanged."
      onClose={() => { if (!saving) { setRetiring(null); setDialogError(""); } }}
      actions={<><button className="admin-save" type="button" disabled={saving} onClick={() => { setRetiring(null); setDialogError(""); }}>Cancel</button><button className="mapping-retire" type="button" disabled={saving || retireReason.trim().length < 8} onClick={() => void retire()}><Trash2 size={14} />{saving ? "Retiring…" : "Retire mapping"}</button></>}
    >
      <div className="mapping-editor"><p className="mapping-service-key"><strong>Service and groups</strong><code>{retiring.source_collection}/{retiring.service_group}</code><code>{retiring.lead_group}</code><code>{retiring.engineer_group}</code></p>{dialogError ? <p className="admin-error" role="alert">{dialogError}</p> : null}<label>Retirement reason<textarea value={retireReason} onChange={(event) => setRetireReason(event.target.value)} minLength={8} maxLength={500} placeholder="Why should this grant be removed?" /></label></div>
    </MappingDialog> : null}
  </Card>;
}
