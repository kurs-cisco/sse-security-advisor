"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Boxes, ClipboardCheck, Database, FilePenLine, Info, LockKeyhole, Menu, Moon, PanelLeft, ShieldCheck, Shield, Sun, UserRound, UsersRound, Wrench, X } from "lucide-react";
import { createContext, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { cn, serviceGroupDisplayName } from "@/app/lib/utils";
import type { AccessMode, AuthMeResponse } from "@/app/lib/contracts";
import { ACCESS_MODE_STORAGE_KEY, accessModeHeaders, selectedAccessMode } from "@/app/lib/http";
import type { AssignedScopePair } from "@/app/lib/scope";

const baseNav = [
  { href: "/", label: "Overview", icon: Activity },
  { href: "/inventory", label: "Inventory", icon: Database },
  { href: "/service-catalog", label: "Service Catalog", icon: UsersRound },
  { href: "/poam", label: "POA&M", icon: ClipboardCheck },
];

type AssignedScope = {
  mode?: "assigned" | "portfolio" | "unconfigured";
  service_groups?: string[];
  ato_boundaries?: string[];
  enforcement?: "active" | "denied";
  product_scoped_detail_evidence?: boolean;
  assigned_workspace_placeholders?: boolean;
};

type Identity = AuthMeResponse & { assigned_scope?: AssignedScope };
type ScopeContextValue = {
  mode: "assigned" | "portfolio";
  selected?: AssignedScopePair;
  pairs: AssignedScopePair[];
  summaryAccess: boolean;
  detailAccess: boolean;
  assignedWorkspaceAccess: boolean;
  isAdmin: boolean;
  canProposeReview: boolean;
  canDecideReview: boolean;
  productScopedDetailEvidence: boolean;
  operationalEvidenceNotes: "enabled" | "staged_disabled";
  reviewProposals: "enabled" | "staged_disabled";
  activeMode: AccessMode | null;
};
const ScopeContext = createContext<ScopeContextValue | null>(null);

function portfolioPairs(scope: AssignedScope | undefined): AssignedScopePair[] {
  return (scope?.service_groups ?? []).flatMap((value) => {
    const [sourceCollection, ...rest] = value.split("/");
    const serviceGroup = rest.join("/");
    return sourceCollection && serviceGroup ? [{ sourceCollection, serviceGroup, key: value }] : [];
  });
}

export function useAssignedScope() {
  const scope = useContext(ScopeContext);
  if (!scope?.selected) throw new Error("A service scope is required before loading detailed console data");
  return scope as ScopeContextValue & { selected: AssignedScopePair };
}

export function useConsoleAccess() {
  const scope = useContext(ScopeContext);
  if (!scope) throw new Error("Console access is required before loading console data");
  return scope;
}

function scopeAccess(identity: Identity | null | undefined) {
  if (identity?.kind === "local" && identity?.role === "admin") return "portfolio" as const;
  if (!identity?.access || identity.access.revoked) return "unavailable" as const;
  if (identity.access.effective_role === "admin") return "portfolio" as const;
  // Once the API supplies an effective-access decision, never fall back to a
  // legacy stored role/scope for a cloud identity.
  return identity.access.summary_access || identity.access.grants.length ? "assigned" as const : "unavailable" as const;
}

function effectivePairs(identity: Identity | null | undefined): AssignedScopePair[] {
  const grants = identity?.access?.grants;
  if (grants?.length) return grants.map((grant) => ({
    sourceCollection: grant.source_collection,
    serviceGroup: grant.service_group,
    productScopeId: grant.product_scope_id,
    boundaryName: grant.boundary_name,
    assessmentAuthorizationReference: grant.assessment_authorization_reference,
    access: grant.access,
    key: `${grant.source_collection}/${grant.service_group}/${grant.product_scope_id}`,
  }));
  // Portfolio administrators receive no per-service grant entries. Their
  // server-supplied catalog pairs populate the selector; summary users never
  // inherit these pairs as a fallback.
  const portfolioAdmin = identity?.access?.effective_role === "admin" || (identity?.kind === "local" && identity.role === "admin");
  return portfolioAdmin ? portfolioPairs(identity?.assigned_scope) : [];
}

function pathRequiresWorkspace(pathname: string) {
  return pathname === "/inventory" || pathname === "/service-catalog" || pathname === "/reviews";
}

export function ConsoleShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [dark, setDark] = useState(false);
  const [compact, setCompact] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [identity, setIdentity] = useState<Identity | null | undefined>(undefined);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [modeChooserOpen, setModeChooserOpen] = useState(false);
  const [modeError, setModeError] = useState("");
  const [changingMode, setChangingMode] = useState<AccessMode | null>(null);
  const loadIdentity = async (): Promise<Identity | null> => {
    let response = await fetch("/api/v1/auth/me", { cache: "no-store", headers: accessModeHeaders() });
    // An entitlement may have changed since this browser session selected a
    // mode. Clear the stale presentation choice and re-read verified access.
    if (!response.ok && selectedAccessMode()) {
      window.sessionStorage.removeItem(ACCESS_MODE_STORAGE_KEY);
      response = await fetch("/api/v1/auth/me", { cache: "no-store" });
    }
    const nextIdentity = response.ok ? await response.json() as Identity : null;
    if (!nextIdentity) { setIdentity(null); setIsAdmin(false); return null; }
    setIdentity(nextIdentity);
    // `effective_role` is computed by the API after it validates the selected
    // mode header against verified IdP claims. The stored browser choice is
    // never itself an authorization input.
    setIsAdmin(nextIdentity.access?.effective_role === "admin" || (nextIdentity.kind === "local" && nextIdentity.role === "admin"));
    const available = nextIdentity.access?.available_modes ?? [];
    const storedMode = selectedAccessMode();
    const selectionRequired = available.length > 1 && (!storedMode || !available.includes(storedMode));
    if (selectionRequired && storedMode) window.sessionStorage.removeItem(ACCESS_MODE_STORAGE_KEY);
    setModeChooserOpen(selectionRequired);
    return nextIdentity;
  };
  useEffect(() => {
    const stored = window.localStorage.getItem("cbom-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const useDark = stored ? stored === "dark" : prefersDark;
    document.documentElement.classList.toggle("dark", useDark);
    const update = window.setTimeout(() => setDark(useDark), 0);
    const identityLoad = window.setTimeout(() => { void loadIdentity().catch(() => { setIdentity(null); setIsAdmin(false); }); }, 0);
    return () => { window.clearTimeout(update); window.clearTimeout(identityLoad); };
  }, []);
  useEffect(() => {
    const main = document.getElementById("main-content");
    window.setTimeout(() => main?.focus(), 0);
  }, [pathname]);
  const access = scopeAccess(identity);
  const activeMode = identity?.access?.active_mode ?? null;
  const modeSelectionRequired = Boolean(identity && (identity.access?.available_modes?.length ?? 0) > 1 && !selectedAccessMode());
  const pairs = useMemo(() => effectivePairs(identity), [identity]);
  // The API reports this capability in the authenticated scope response. A
  // product grant alone must not expose pair-scoped evidence before product
  // attribution and query enforcement are operational. Administrators retain
  // their explicitly unpartitioned portfolio inventory path.
  const productScopedDetailEvidence = isAdmin || identity?.assigned_scope?.product_scoped_detail_evidence === true;
  // A server capability gates the separate evidence-observation workflow.
  // A product grant alone must never enable its reads or writes.
  const operationalEvidenceNotes = identity?.capabilities?.operational_evidence_notes === true ? "enabled" : "staged_disabled";
  const reviewProposals = identity?.capabilities?.review_proposals === true ? "enabled" : "staged_disabled";
  const detailAccess = (isAdmin || pairs.length > 0) && productScopedDetailEvidence;
  // This is a distinct, server-advertised capability. It permits only the
  // placeholder list endpoint; it is never used to enable evidence detail.
  const assignedWorkspaceAccess = detailAccess || identity?.assigned_scope?.assigned_workspace_placeholders === true;
  const summaryAccess = isAdmin || Boolean(identity?.access?.summary_access) || detailAccess;
  // Multiple grants are rendered as a combined, server-filtered view. Never
  // quietly choose the first service/product pair as a browser-side scope.
  const selected = pairs.length === 1 ? pairs[0] : undefined;
  const canProposeReview = !isAdmin
    && activeMode === "product_lead"
    && pairs.some((pair) => pair.access === "lead")
    && (operationalEvidenceNotes === "enabled" || reviewProposals === "enabled");
  const canDecideReview = identity?.kind === "human" && identity.access?.effective_role === "admin";
  const nav = [
    ...(summaryAccess ? [baseNav[0]] : []),
    ...(assignedWorkspaceAccess ? baseNav.slice(1, 3) : []),
    ...((operationalEvidenceNotes === "enabled" || reviewProposals === "enabled") && (isAdmin || assignedWorkspaceAccess) ? [{ href: "/reviews", label: "Reviews", icon: FilePenLine }] : []),
    ...(summaryAccess ? [baseNav[3]] : []),
    ...(isAdmin ? [{ href: "/admin", label: "Admin", icon: ShieldCheck }] : []),
  ];
  const mobilePrimaryNav = nav.slice(0, 3);
  const mobileMoreNav = nav.slice(3);
  const mobileMoreActive = mobileMoreNav.some(({ href }) => pathname === href);
  const assignedScopeText = isAdmin
    ? "This administrator has full catalog visibility. Administrative actions remain audited."
    : !productScopedDetailEvidence && pairs.length
    ? "Product evidence attribution is pending. Detailed service evidence stays unavailable until the API enables product partition enforcement."
    : detailAccess
    ? `All ${pairs.length} verified service scope${pairs.length === 1 ? "" : "s"} are available together in this product workspace. Evidence panels retain their exact product attribution; Overview and POA&M show aggregate portfolio summaries.`
    : "This account can view aggregate portfolio summaries only. Detailed records, evidence, and exports are unavailable.";
  const toggleTheme = () => {
    setDark((current) => {
      const next = !current;
      document.documentElement.classList.toggle("dark", next);
      window.localStorage.setItem("cbom-theme", next ? "dark" : "light");
      return next;
    });
  };
  const selectMode = async (mode: AccessMode) => {
    if (!identity?.access?.available_modes?.includes(mode)) return;
    setChangingMode(mode); setModeError("");
    // Hide the previous workspace immediately. Its mounted components may
    // still hold data fetched under a more privileged mode until the next
    // /auth/me response confirms the new effective role.
    setIdentity(undefined);
    try {
      window.sessionStorage.setItem(ACCESS_MODE_STORAGE_KEY, mode);
      const selectedIdentity = await loadIdentity();
      if (selectedIdentity?.access?.active_mode !== mode) throw new Error("Selected mode was not confirmed");
      setModeChooserOpen(false); setProfileOpen(false);
    } catch {
      window.sessionStorage.removeItem(ACCESS_MODE_STORAGE_KEY);
      await loadIdentity().catch(() => { setIdentity(null); setIsAdmin(false); });
      setModeError("Unable to apply that access mode. Your verified access has not changed.");
    } finally { setChangingMode(null); }
  };
  return (
    <div className={cn("console-shell", dark && "dark", compact && "rail-compact")}>
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brand-row">
          <div className="brand-mark"><Boxes size={19} strokeWidth={2.35} /></div>
          {!compact && <div><p className="eyebrow">Supply-chain intelligence</p><p className="brand-name">CBOM Workbench</p></div>}
        </div>
        <nav className="nav-list">
          {nav.map(({ href, label, icon: Icon }) => <Link key={href} href={href} className={cn("nav-link", pathname === href && "nav-link-active")} aria-label={label} title={compact ? label : undefined} aria-current={pathname === href ? "page" : undefined}><Icon size={18} /><span>{label}</span></Link>)}
        </nav>
        <div className="sidebar-foot">
          <div className="connection-pill">Catalog workspace</div>
          {!compact && <p>{isAdmin ? "Administrative evidence workspace" : activeMode === "product_lead" ? "Product lead workspace" : activeMode === "product_engineer" ? "Product engineer workspace · read-only" : "Aggregate summary workspace"}</p>}
        </div>
      </aside>
      <div className="console-main">
        <header className="topbar">
          <button className="icon-button rail-toggle" type="button" aria-label="Toggle compact navigation" onClick={() => setCompact((value) => !value)}><PanelLeft size={18} /></button>
          <p className="topbar-context">FIPS 140-3 transition workspace</p>
          <div className="topbar-actions">
            {summaryAccess ? <DisclosureInfo label="Assigned scope" text={assignedScopeText} /> : null}
            {identity ? <ProfileMenu identity={identity} pairs={pairs} activeMode={activeMode} open={profileOpen} onOpenChange={setProfileOpen} onChooseMode={(mode) => void selectMode(mode)} /> : null}
            <button className="icon-button" type="button" onClick={toggleTheme} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>{dark ? <Sun size={17} /> : <Moon size={17} />}</button>
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>{identity === undefined || modeSelectionRequired ? <ScopeLoading /> : summaryAccess ? <ScopeContext.Provider key={activeMode ?? "unselected"} value={{ mode: access === "portfolio" ? "portfolio" : "assigned", selected, pairs, summaryAccess, detailAccess, assignedWorkspaceAccess, isAdmin, canProposeReview, canDecideReview, productScopedDetailEvidence, operationalEvidenceNotes, reviewProposals, activeMode }}>{pathRequiresWorkspace(pathname) && !assignedWorkspaceAccess ? <DetailUnavailable productPending={!productScopedDetailEvidence && pairs.length > 0} /> : pathname === "/admin" && !isAdmin ? <DetailUnavailable admin /> : children}</ScopeContext.Provider> : <ScopeUnavailable empty={false} denied={identity?.access?.revoked || identity?.assigned_scope?.enforcement === "denied"} configurationRequired={false} />}</main>
      </div>
      <nav className="mobile-nav" aria-label="Mobile navigation">
        {mobilePrimaryNav.map(({ href, label, icon: Icon }) => <Link key={href} href={href} className={cn("mobile-nav-link", pathname === href && "mobile-nav-active")} aria-current={pathname === href ? "page" : undefined}><Icon size={18} /><span>{label}</span></Link>)}
        <button className={cn("mobile-nav-link", "mobile-more-trigger", mobileMoreActive && "mobile-nav-active")} type="button" aria-expanded={mobileMenuOpen} aria-controls="mobile-more-menu" onClick={() => setMobileMenuOpen((open) => !open)}><Menu size={18} /><span>More</span></button>
      </nav>
      {mobileMenuOpen && <MobileMoreMenu entries={mobileMoreNav} pathname={pathname} onClose={() => setMobileMenuOpen(false)} />}
      {modeChooserOpen && identity ? <AccessModeChooser identity={identity} activeMode={activeMode} changingMode={changingMode} error={modeError} onChoose={(mode) => void selectMode(mode)} /> : null}
    </div>
  );
}

function ScopeLoading() {
  return <div className="page-container"><section className="scope-gate" aria-live="polite"><LockKeyhole size={20} /><div><h1>Checking assigned scope</h1><p>Loading the service groups available to this account.</p></div></section></div>;
}

const MODE_DETAILS: Record<AccessMode, { label: string; detail: string; Icon: typeof ShieldCheck }> = {
  admin: { label: "Admin", detail: "All product and administration views", Icon: ShieldCheck },
  product_lead: { label: "Product Lead", detail: "All assigned product views", Icon: Wrench },
  product_engineer: { label: "Product Engineer", detail: "All assigned product views with read-only access", Icon: Shield },
  summary: { label: "Summary viewer", detail: "Aggregate Overview and POA&M summaries", Icon: UserRound },
};

function modeDetail(mode: AccessMode | null | undefined) {
  return mode ? MODE_DETAILS[mode] : null;
}

function ProfileMenu({ identity, pairs, activeMode, open, onOpenChange, onChooseMode }: { identity: Identity; pairs: AssignedScopePair[]; activeMode: AccessMode | null; open: boolean; onOpenChange: (open: boolean) => void; onChooseMode: (mode: AccessMode) => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const detail = modeDetail(activeMode);
  useEffect(() => {
    if (!open) return;
    const trigger = triggerRef.current;
    const close = (event: MouseEvent) => { if (!containerRef.current?.contains(event.target as Node)) onOpenChange(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") onOpenChange(false); };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", escape);
    const focus = window.setTimeout(() => closeRef.current?.focus(), 0);
    return () => { window.clearTimeout(focus); document.removeEventListener("mousedown", close); document.removeEventListener("keydown", escape); trigger?.focus(); };
  }, [open, onOpenChange]);
  const label = identity.display_name || identity.email || "Signed-in user";
  const options = identity.access?.available_modes ?? [];
  const groupCount = new Set(pairs.map((pair) => pair.serviceGroup)).size;
  const verifiedGroups = identity.access?.matched_groups ?? [];
  const serviceNames = [...new Set(pairs.map((pair) => pair.serviceGroup))]
    .sort().map(serviceGroupDisplayName);
  return <div className="profile-menu" ref={containerRef}>
    <button ref={triggerRef} className="profile-trigger" type="button" aria-label="Open user profile" aria-haspopup="dialog" aria-expanded={open} aria-controls="user-profile-panel" onClick={() => onOpenChange(!open)}><UserRound size={17} /><span className="profile-trigger-name">{label}</span></button>
    {open ? <section id="user-profile-panel" className="profile-panel" role="dialog" aria-label="Signed-in user profile">
      <header><div className="profile-avatar" aria-hidden="true">{label.slice(0, 1).toUpperCase()}</div><div><strong>{label}</strong><span>{identity.email || "Verified local development identity"}</span></div><button ref={closeRef} type="button" className="profile-close" aria-label="Close user profile" onClick={() => onOpenChange(false)}><X size={15} /></button></header>
      <div className="profile-current"><span>Active access</span><strong>{detail?.label || "Access being verified"}</strong><small>{detail?.detail}</small></div>
      <div className="profile-coverage"><span>Access coverage</span><strong>{activeMode === "admin" ? "All products and services" : groupCount ? `${groupCount} service group${groupCount === 1 ? "" : "s"} across assigned products` : "Aggregate summaries"}</strong></div>
      {verifiedGroups.length ? <details className="profile-entitlements"><summary>Verified groups ({verifiedGroups.length})</summary><ul>{verifiedGroups.map((group) => <li key={group}>{group}</li>)}</ul></details> : null}
      {serviceNames.length && activeMode !== "admin" ? <details className="profile-entitlements"><summary>Assigned services ({serviceNames.length})</summary><ul>{serviceNames.map((service) => <li key={service}>{service}</li>)}</ul></details> : null}
      {options.length > 1 ? <div className="profile-mode-switch"><span>Switch access mode</span>{options.map((mode) => <button key={mode} type="button" className={mode === activeMode ? "profile-mode-active" : ""} onClick={() => onChooseMode(mode)}>{MODE_DETAILS[mode].label}{mode === activeMode ? <small>Active</small> : null}</button>)}</div> : null}
      <p className="profile-note">Your available modes are derived from verified identity-provider groups. Changing mode never expands your permissions.</p>
    </section> : null}
  </div>;
}

function AccessModeChooser({ identity, activeMode, changingMode, error, onChoose }: { identity: Identity; activeMode: AccessMode | null; changingMode: AccessMode | null; error: string; onChoose: (mode: AccessMode) => void }) {
  const dialogRef = useRef<HTMLElement>(null);
  const modes = identity.access?.available_modes ?? [];
  const recommended = identity.access?.default_mode ?? modes[0];
  useEffect(() => {
    const prior = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focus = window.setTimeout(() => dialogRef.current?.querySelector<HTMLButtonElement>("button")?.focus(), 0);
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])') ?? [])];
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable.at(-1)!;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", trap);
    return () => { window.clearTimeout(focus); document.removeEventListener("keydown", trap); prior?.focus(); };
  }, []);
  return <div className="access-mode-backdrop" role="presentation"><section ref={dialogRef} className="access-mode-dialog" role="dialog" aria-modal="true" aria-labelledby="access-mode-title" aria-describedby="access-mode-description">
    <p className="eyebrow">Verified access</p><h1 id="access-mode-title">Choose your workspace</h1><p id="access-mode-description">You have more than one verified access category. Select the workspace you need for this session.</p>
    <div className="access-mode-options">{modes.map((mode) => { const { label, detail, Icon } = MODE_DETAILS[mode]; const recommended = mode === identity.access?.default_mode; return <button key={mode} type="button" onClick={() => onChoose(mode)} disabled={changingMode !== null}><Icon size={20} /><span><strong>{label}{recommended ? <em>Recommended</em> : null}</strong><small>{detail}</small></span>{changingMode === mode ? <span className="mode-saving">Applying…</span> : null}</button>; })}</div>
    {error ? <p className="access-mode-error" role="alert">{error}</p> : null}
    {recommended ? <button className="access-mode-default" type="button" disabled={changingMode !== null} onClick={() => onChoose(recommended)}>Continue with {MODE_DETAILS[recommended].label}</button> : null}
    {activeMode ? <p className="access-mode-current">Current verified access: {MODE_DETAILS[activeMode].label}</p> : null}
  </section></div>;
}

function ScopeUnavailable({ empty, denied, configurationRequired }: { empty: boolean; denied: boolean; configurationRequired: boolean }) {
  const title = empty ? "No assigned service groups" : "Access unavailable";
  const detail = empty ? "No service groups are available for this account." : configurationRequired ? "Portfolio oversight requires configured service groups." : denied ? "You do not have access to this service group." : "No effective assigned scope is available for this account.";
  return <div className="page-container"><section className="scope-gate scope-gate-unavailable" role="alert"><LockKeyhole size={20} /><div><h1>{title}</h1><p>{detail}</p></div></section></div>;
}

function DetailUnavailable({ admin = false, productPending = false }: { admin?: boolean; productPending?: boolean }) {
  return <div className="page-container"><section className="scope-gate scope-gate-unavailable" role="alert"><LockKeyhole size={20} /><div><h1>{admin ? "Administrator access required" : productPending ? "Product evidence attribution pending" : "Detailed service access required"}</h1><p>{admin ? "This workspace is limited to verified fedsse-admins access." : productPending ? "Detailed product evidence remains unavailable until the API confirms attribution and partition enforcement. Aggregate summaries remain available." : "Your current access provides aggregate summaries only."}</p></div></section></div>;
}

export function DisclosureInfo({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLSpanElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const closeWhenOutside = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", closeWhenOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeWhenOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);
  return <span className="disclosure-info" ref={containerRef}>
    <button className="icon-button disclosure-trigger" type="button" aria-label={label} aria-expanded={open} aria-controls={id} onClick={() => setOpen((value) => !value)}><Info size={17} /></button>
    {open && <span className="disclosure-tooltip" id={id} role="dialog" aria-label={label}><strong>{label}</strong>{text}</span>}
  </span>;
}

function MobileMoreMenu({ entries, pathname, onClose }: { entries: typeof baseNav; pathname: string; onClose: () => void }) {
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prior = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab") return;
      const nodes = [...(menuRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])') ?? [])];
      if (!nodes.length) return;
      const first = nodes[0]; const last = nodes.at(-1)!;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", closeOnEscape);
    window.setTimeout(() => menuRef.current?.querySelector<HTMLElement>("button, a[href]")?.focus(), 0);
    return () => { document.removeEventListener("keydown", closeOnEscape); prior?.focus(); };
  }, [onClose]);
  return <div className="mobile-more-backdrop" onMouseDown={onClose}>
    <div id="mobile-more-menu" className="mobile-more-menu" ref={menuRef} role="dialog" aria-label="More navigation" onMouseDown={(event) => event.stopPropagation()}>
      <div className="mobile-more-heading"><span>More destinations</span><button className="icon-button" type="button" onClick={onClose} aria-label="Close more navigation"><X size={17} /></button></div>
      {entries.map(({ href, label, icon: Icon }) => <Link key={href} href={href} className={cn("mobile-more-link", pathname === href && "mobile-more-link-active")} aria-current={pathname === href ? "page" : undefined} onClick={onClose}><Icon size={18} /><span>{label}</span></Link>)}
    </div>
  </div>;
}
