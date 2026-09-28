"use client";

import { useCallback, useEffect, useState, type KeyboardEvent } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Clipboard, KeyRound, RefreshCw, RotateCcw, ShieldCheck, UserCog, UserX } from "lucide-react";
import { fetchJson } from "@/app/lib/http";
import type { AuthMeResponse, EffectiveAccessGrant } from "@/app/lib/contracts";
import { Badge } from "@/app/components/ui/badge";
import { Card } from "@/app/components/ui/card";
import { IngestionWorkspace } from "@/components/admin/ingestion-workspace";
import { MappingDialog, ServiceGroupMapping } from "@/components/admin/service-group-mapping";

type Identity = AuthMeResponse & { can_edit: boolean };
type User = {
  id: number;
  email: string;
  display_name: string | null;
  identity_bound: boolean;
  status?: string;
  last_login_at: string | null;
  last_verified_at: string | null;
  policy_version: string | null;
  group_fingerprint: string | null;
  effective_role: string | null;
  grants?: EffectiveAccessGrant[];
  revoked_at: string | null;
  revoked_reason: string | null;
};
type Token = { id: string; name: string; token_prefix: string; scopes: string[]; created_at: string; expires_at: string; last_used_at: string | null; revoked_at: string | null; owner_email: string };

const scopes = ["catalog:read", "assessment:read", "poam:read", "poam:write", "milestones:write", "annotations:write", "ingestion:read", "ingestion:write"];
const scopeHelp: Record<string, string> = {
  "catalog:read": "Read catalog inventory and evidence metadata.",
  "assessment:read": "Read assessment results and candidate findings.",
  "poam:read": "Read candidate POA&M review records.",
  "poam:write": "Create or update authorized POA&M review records.",
  "milestones:write": "Update planning milestone metadata.",
  "annotations:write": "Add evidence annotations.",
  "ingestion:read": "Read ingestion jobs, outcomes, and logs.",
  "ingestion:write": "Create checksum-gated ingestion jobs.",
};
const scopePresets = {
  "Read-only review": ["catalog:read", "assessment:read", "poam:read"],
  "Ingestion operator": ["catalog:read", "assessment:read", "ingestion:read", "ingestion:write"],
  "POA&M editor": ["catalog:read", "assessment:read", "poam:read", "poam:write", "annotations:write"],
} as const;

const ADMIN_SECTIONS = [
  { id: "mappings", label: "Service mappings", description: "Groups and product scope" },
  { id: "ingestion", label: "Data ingestion", description: "Uploads and job history" },
  { id: "users", label: "Users", description: "Recorded access" },
  { id: "tokens", label: "Scoped tokens", description: "Direct API access" },
] as const;

type AdminSection = (typeof ADMIN_SECTIONS)[number]["id"];

function isAdminSection(value: string | null): value is AdminSection {
  return ADMIN_SECTIONS.some((section) => section.id === value);
}

function grantSummary(grant: EffectiveAccessGrant) {
  return `${grant.source_collection}/${grant.service_group} · ${grant.product_scope_id} (${grant.boundary_name}) · ${grant.access}`;
}

function liveScopeSummary(identity: Identity) {
  const access = identity.access;
  const grants = access?.grants ?? [];
  if (access?.effective_role === "admin") {
    const memberships = grants.length ? ` Additional exact service memberships: ${grants.map(grantSummary).join(", ")}` : "";
    return `Portfolio-wide catalog and administration access; no per-service grant is required.${memberships}`;
  }
  if (grants.length) return grants.map(grantSummary).join(", ");
  if (access?.effective_role === "summary") return "Aggregate summary access; no per-service grants apply";
  return "No exact service grants in this current session";
}

function tokenState(token: Token) {
  if (token.revoked_at) return "Revoked" as const;
  if (Date.parse(token.expires_at) <= Date.now()) return "Expired" as const;
  return "Unrevoked" as const;
}

export function AdminConsole() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [tokens, setTokens] = useState<Token[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [usersLoading, setUsersLoading] = useState(false);
  const [tokensLoading, setTokensLoading] = useState(false);
  const [usersLoaded, setUsersLoaded] = useState(false);
  const [tokensLoaded, setTokensLoaded] = useState(false);
  const [usersError, setUsersError] = useState("");
  const [tokensError, setTokensError] = useState("");
  const [issuedToken, setIssuedToken] = useState("");
  const [tokenName, setTokenName] = useState("Workbench automation");
  const [tokenDays, setTokenDays] = useState(30);
  const [selectedScopes, setSelectedScopes] = useState<string[]>(["catalog:read", "assessment:read", "poam:read"]);
  const [changingUser, setChangingUser] = useState<number | null>(null);
  const [canManageRoster, setCanManageRoster] = useState(false);
  const [revokingToken, setRevokingToken] = useState<string | null>(null);
  const [pendingAccess, setPendingAccess] = useState<{ user: User; action: "revoke" | "restore" } | null>(null);
  const [accessReason, setAccessReason] = useState("");
  const [pendingToken, setPendingToken] = useState<Token | null>(null);
  const [dialogError, setDialogError] = useState("");
  const querySection = searchParams.get("section");
  const activeSection: AdminSection = isAdminSection(querySection) ? querySection : "mappings";
  const unrevokedTokenCount = tokens.filter((token) => tokenState(token) === "Unrevoked").length;
  const revokedTokenCount = tokens.filter((token) => tokenState(token) === "Revoked").length;
  const expiredTokenCount = tokens.filter((token) => tokenState(token) === "Expired").length;

  function selectSection(section: AdminSection) {
    const next = new URLSearchParams(searchParams.toString());
    next.set("section", section);
    router.push(`${pathname}?${next.toString()}`, { scroll: false });
  }

  function onSectionKeyDown(event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = (currentIndex + 1) % ADMIN_SECTIONS.length;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex = (currentIndex - 1 + ADMIN_SECTIONS.length) % ADMIN_SECTIONS.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = ADMIN_SECTIONS.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const next = ADMIN_SECTIONS[nextIndex];
    selectSection(next.id);
    window.requestAnimationFrame(() => document.getElementById(`admin-tab-${next.id}`)?.focus());
  }

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const me = await fetchJson<Identity>("/api/v1/auth/me");
      setIdentity(me);
      setCanManageRoster(me.capabilities?.roster_revoke_restore === true);
      if (!me.can_edit) throw new Error("Administrator access is required");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Administrator access is unavailable");
    } finally { setLoading(false); }
  }, []);

  const loadUsers = useCallback(async () => {
    setUsersLoading(true); setUsersError("");
    try {
      const page = await fetchJson<{ items: User[] }>("/api/v1/admin/users");
      setUsers(page.items); setUsersLoaded(true);
    } catch (caught) {
      setUsersError(caught instanceof Error ? caught.message : "Recorded users are unavailable");
    } finally { setUsersLoading(false); }
  }, []);

  const loadTokens = useCallback(async () => {
    setTokensLoading(true); setTokensError("");
    try {
      const page = await fetchJson<{ items: Token[] }>("/api/v1/admin/tokens");
      setTokens(page.items); setTokensLoaded(true);
    } catch (caught) {
      setTokensError(caught instanceof Error ? caught.message : "Scoped tokens are unavailable");
    } finally { setTokensLoading(false); }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (!identity?.can_edit || activeSection !== "users") return;
    const timer = window.setTimeout(() => void loadUsers(), 0);
    return () => window.clearTimeout(timer);
  }, [activeSection, identity?.can_edit, loadUsers]);

  useEffect(() => {
    if (!identity?.can_edit || activeSection !== "tokens") return;
    const timer = window.setTimeout(() => void loadTokens(), 0);
    return () => window.clearTimeout(timer);
  }, [activeSection, identity?.can_edit, loadTokens]);

  async function refreshWorkspace() {
    await load();
    if (activeSection === "users") await loadUsers();
    if (activeSection === "tokens") await loadTokens();
  }

  async function changeUserAccess(user: User, action: "revoke" | "restore", reason: string) {
    if (!canManageRoster) return;
    setDialogError("");
    try {
      setChangingUser(user.id);
      await fetchJson(`/api/v1/admin/users/${user.id}/access`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, reason: reason.trim() }) });
      await loadUsers();
      setPendingAccess(null);
      setAccessReason("");
    } catch (caught) { setDialogError(caught instanceof Error ? caught.message : `User ${action} failed`); }
    finally { setChangingUser(null); }
  }

  async function createToken() {
    if (!tokenName.trim() || !selectedScopes.length || !Number.isInteger(tokenDays) || tokenDays < 1 || tokenDays > 90) return;
    setTokensError(""); setIssuedToken("");
    try {
      const result = await fetchJson<{ token: string }>("/api/v1/admin/tokens", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: tokenName, scopes: selectedScopes, expires_in_days: tokenDays }),
      });
      setIssuedToken(result.token); await loadTokens();
    } catch (caught) { setTokensError(caught instanceof Error ? caught.message : "Token creation failed"); }
  }

  async function revokeToken(id: string) {
    setDialogError("");
    try { setRevokingToken(id); await fetchJson(`/api/v1/admin/tokens/${id}`, { method: "DELETE" }); await loadTokens(); setPendingToken(null); }
    catch (caught) { setDialogError(caught instanceof Error ? caught.message : "Token revocation failed"); }
    finally { setRevokingToken(null); }
  }

  if (loading && !identity) return <section className="page-heading"><div><p className="eyebrow">Access administration</p><h1>Loading administrator workspace…</h1></div></section>;
  if (!identity?.can_edit) return <section className="page-heading"><div><p className="eyebrow">Access administration</p><h1>Administrator access required</h1><p className="page-subtitle">Your account has read-only access to the evidence catalog.</p>{error && <p className="admin-error">{error}</p>}</div></section>;

  return <div className="admin-workbench">
    <section className="page-heading"><div><p className="eyebrow">Operations and access</p><h1>Administrator workspace</h1><p className="page-subtitle">Manage service mappings, ingestion, recorded access, and scoped API credentials.</p></div><div className="heading-actions"><Badge tone="success"><ShieldCheck size={14} />{identity.email}</Badge><button className="refresh-button" type="button" onClick={() => void refreshWorkspace()} disabled={loading || (activeSection === "users" && usersLoading) || (activeSection === "tokens" && tokensLoading)}><RefreshCw size={17} className={loading || (activeSection === "users" && usersLoading) || (activeSection === "tokens" && tokensLoading) ? "spin" : ""} />Refresh access</button></div></section>
    {error && <div className="admin-error" role="alert">{error}</div>}
    <div className="admin-section-tabs" role="tablist" aria-label="Administrator workspace sections">
      {ADMIN_SECTIONS.map((section, index) => <button key={section.id} id={`admin-tab-${section.id}`} type="button" role="tab" aria-selected={activeSection === section.id} aria-controls={`admin-panel-${section.id}`} tabIndex={activeSection === section.id ? 0 : -1} className={activeSection === section.id ? "admin-section-tab admin-section-tab-active" : "admin-section-tab"} onClick={() => selectSection(section.id)} onKeyDown={(event) => onSectionKeyDown(event, index)}><span>{section.label}</span>{section.id === "users" ? <Badge tone="info">{usersLoading ? "…" : usersLoaded ? users.length : "Not loaded"}</Badge> : section.id === "tokens" ? <Badge tone="neutral">{tokensLoading ? "…" : tokensLoaded ? tokens.length : "Not loaded"}</Badge> : <small>{section.description}</small>}</button>)}
    </div>
    <section id="admin-panel-mappings" role="tabpanel" aria-labelledby="admin-tab-mappings" hidden={activeSection !== "mappings"} className="admin-tab-panel">{activeSection === "mappings" ? <ServiceGroupMapping /> : null}</section>
    <section id="admin-panel-ingestion" role="tabpanel" aria-labelledby="admin-tab-ingestion" hidden={activeSection !== "ingestion"} className="admin-tab-panel">{activeSection === "ingestion" ? <IngestionWorkspace operatorReady={identity.kind !== "local"} /> : null}</section>
    <section id="admin-panel-users" role="tabpanel" aria-labelledby="admin-tab-users" hidden={activeSection !== "users"} className="admin-tab-panel">
      <Card className="admin-card"><div className="card-heading"><div><p className="eyebrow">Access roster</p><h2><UserCog size={18} />Users</h2><p className="admin-card-note">This table contains historical application access snapshots for users who reached the application. It does not represent current MyID membership, a live authorization decision, or the full directory.</p></div><Badge tone="info">{usersLoading ? "Loading" : users.length}</Badge></div><div className="admin-form"><section className="rounded-lg border border-border bg-muted/40 p-3" aria-label="Current signed session"><p className="eyebrow">Current signed session only</p><strong className="mt-1 block text-sm">{identity.email || "Verified local development identity"} · {identity.access?.effective_role ?? identity.role ?? "Access being verified"}</strong><small className="mt-1 block text-muted-foreground">{liveScopeSummary(identity)}</small><small className="mt-1 block text-muted-foreground">This is the only live verified access decision shown here · policy {identity.access?.policy_version ?? "not recorded"}</small></section></div>{usersError ? <p className="admin-error" role="alert">{usersError}</p> : null}{!canManageRoster ? <p className="admin-card-note">Revoke and restore are unavailable until the access-control migration and audited API capability are active.</p> : null}<div className="table-scroll"><table><thead><tr><th>User</th><th>Historical application snapshot</th><th>Recorded application state</th>{canManageRoster ? <th><span className="sr-only">Access action</span></th> : null}</tr></thead><tbody>{users.map((user) => {
        const historicalSnapshot = Boolean(user.last_verified_at || user.effective_role || (user.grants ?? []).length);
        return <tr key={user.id}><td><strong>{user.email}</strong><small>{user.display_name ?? "No display name"} · last application sign-in {user.last_login_at ? new Date(user.last_login_at).toLocaleDateString() : "never"}</small></td><td><strong>{historicalSnapshot ? user.effective_role ?? "Historical verification recorded" : "No recorded verified session"}</strong><small>{(user.grants ?? []).length ? (user.grants ?? []).map(grantSummary).join(", ") : historicalSnapshot ? "No exact service grants recorded in this historical snapshot" : "No recorded historical service grants"}</small><small>{historicalSnapshot ? `Recorded ${user.last_verified_at ? new Date(user.last_verified_at).toLocaleString() : "time not recorded"} · policy ${user.policy_version ?? "not recorded"}` : "No historical policy or verification time is recorded"}</small></td><td><Badge tone={user.revoked_at || user.status === "disabled" ? "danger" : user.identity_bound ? "info" : "warning"}>{user.revoked_at ? "Revoked locally" : user.status === "disabled" ? "Disabled locally" : user.identity_bound ? "Identity binding recorded" : "No recorded verified session"}</Badge>{user.revoked_reason ? <small>{user.revoked_reason}</small> : null}</td>{canManageRoster ? <td>{user.revoked_at ? <button className="admin-save" type="button" disabled={changingUser === user.id} onClick={() => { setDialogError(""); setPendingAccess({ user, action: "restore" }); }}><RotateCcw size={14} />{changingUser === user.id ? "Restoring…" : "Restore"}</button> : <button className="admin-save" type="button" disabled={changingUser === user.id} onClick={() => { setDialogError(""); setPendingAccess({ user, action: "revoke" }); }}><UserX size={14} />{changingUser === user.id ? "Revoking…" : "Revoke"}</button>}</td> : null}</tr>;
      })}{usersLoading && !users.length ? <tr><td colSpan={canManageRoster ? 4 : 3} className="admin-empty">Loading recorded application users…</td></tr> : null}{!usersLoading && !usersError && usersLoaded && !users.length ? <tr><td colSpan={canManageRoster ? 4 : 3} className="admin-empty">No recorded application users yet.</td></tr> : null}</tbody></table></div></Card>
    </section>
    <section id="admin-panel-tokens" role="tabpanel" aria-labelledby="admin-tab-tokens" hidden={activeSection !== "tokens"} className="admin-tab-panel">
      <Card className="admin-card admin-token-card"><div className="card-heading"><div><p className="eyebrow">Direct API access</p><h2><KeyRound size={18} />Scoped tokens</h2><p className="admin-card-note">Choose the smallest scope set required. “Unrevoked” indicates only that this recorded token is neither revoked nor past its recorded expiry; it is not a live authorization decision.</p></div><Badge tone="neutral">{tokensLoading ? "Loading" : `${unrevokedTokenCount} unrevoked · ${revokedTokenCount} revoked${expiredTokenCount ? ` · ${expiredTokenCount} expired` : ""}`}</Badge></div>{tokensError ? <p className="admin-error" role="alert">{tokensError}</p> : null}<div className="admin-form"><label>Name<input value={tokenName} onChange={(event) => setTokenName(event.target.value)} /></label><label>Expires in days<input type="number" min={1} max={90} value={tokenDays} onChange={(event) => { const next = Number(event.target.value); setTokenDays(Number.isFinite(next) ? next : 0); }} /><small>{Number.isInteger(tokenDays) && tokenDays >= 1 && tokenDays <= 90 ? `Expires after ${tokenDays} day${tokenDays === 1 ? "" : "s"}; maximum 90 days.` : "Enter a whole number from 1 to 90."}</small></label><fieldset><legend>Scope presets</legend><div className="scope-presets">{Object.entries(scopePresets).map(([label, preset]) => <button type="button" key={label} onClick={() => setSelectedScopes([...preset])}>{label}</button>)}</div></fieldset><fieldset><legend>Scopes</legend>{scopes.map((scope) => <label key={scope} className="scope-option"><input type="checkbox" checked={selectedScopes.includes(scope)} onChange={() => setSelectedScopes((current) => current.includes(scope) ? current.filter((value) => value !== scope) : [...current, scope])} /><span><code>{scope}</code><small>{scopeHelp[scope]}</small></span></label>)}</fieldset><button className="primary-button" type="button" onClick={() => void createToken()} disabled={!tokenName.trim() || !selectedScopes.length || !Number.isInteger(tokenDays) || tokenDays < 1 || tokenDays > 90}><KeyRound size={16} />Generate token</button>{issuedToken && <div className="issued-token"><strong>Copy now — this token will not be shown again.</strong><code>{issuedToken}</code><button type="button" onClick={() => void navigator.clipboard.writeText(issuedToken)}><Clipboard size={14} />Copy token</button></div>}</div><div className="token-list">{tokens.map((token) => { const state = tokenState(token); return <article key={token.id}><div><strong>{token.name}</strong><code>{token.token_prefix}…</code><small>{token.scopes.join(" · ")}</small><small>Created {new Date(token.created_at).toLocaleDateString()} · expires {new Date(token.expires_at).toLocaleDateString() } · last used {token.last_used_at ? new Date(token.last_used_at).toLocaleDateString() : "never"}</small></div><div className="token-actions"><Badge tone={state === "Revoked" ? "danger" : state === "Expired" ? "warning" : "neutral"}>{state}</Badge>{state === "Unrevoked" ? <button type="button" disabled={revokingToken === token.id} onClick={() => { setDialogError(""); setPendingToken(token); }}>{revokingToken === token.id ? "Revoking…" : "Revoke"}</button> : null}</div></article>; })}{tokensLoading && !tokens.length ? <p className="admin-empty">Loading scoped tokens…</p> : null}{!tokensLoading && !tokensError && tokensLoaded && !tokens.length ? <p className="admin-empty">No API tokens have been issued.</p> : null}</div></Card>
    </section>
    {pendingAccess ? <MappingDialog title={`${pendingAccess.action === "revoke" ? "Revoke" : "Restore"} user access`} description={pendingAccess.user.email} onClose={() => { if (changingUser === null) { setPendingAccess(null); setAccessReason(""); } }} actions={<><button type="button" className="admin-save" disabled={changingUser !== null} onClick={() => { setPendingAccess(null); setAccessReason(""); }}>Cancel</button><button type="button" className={pendingAccess.action === "revoke" ? "mapping-retire" : "primary-button"} disabled={changingUser !== null || accessReason.trim().length < 8} onClick={() => void changeUserAccess(pendingAccess.user, pendingAccess.action, accessReason)}>{changingUser !== null ? "Saving…" : pendingAccess.action === "revoke" ? "Revoke access" : "Restore access"}</button></>}><div className="mapping-editor"><label>Reason<input value={accessReason} onChange={(event) => setAccessReason(event.target.value)} maxLength={2000} placeholder="At least 8 characters" /></label>{dialogError ? <p className="admin-error" role="alert">{dialogError}</p> : null}</div></MappingDialog> : null}
    {pendingToken ? <MappingDialog title="Revoke API token" description={`${pendingToken.name} · ${pendingToken.token_prefix}…`} onClose={() => { if (revokingToken === null) setPendingToken(null); }} actions={<><button type="button" className="admin-save" disabled={revokingToken !== null} onClick={() => setPendingToken(null)}>Cancel</button><button type="button" className="mapping-retire" disabled={revokingToken !== null} onClick={() => void revokeToken(pendingToken.id)}>{revokingToken !== null ? "Revoking…" : "Revoke token"}</button></>}><div className="mapping-editor"><p>Existing clients using this token will lose access immediately.</p>{dialogError ? <p className="admin-error" role="alert">{dialogError}</p> : null}</div></MappingDialog> : null}
  </div>;
}
