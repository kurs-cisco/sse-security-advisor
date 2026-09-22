"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Clipboard, KeyRound, RefreshCw, Save, ShieldCheck, UserCog } from "lucide-react";
import { fetchJson } from "@/app/lib/http";
import { Badge } from "@/app/components/ui/badge";
import { Card } from "@/app/components/ui/card";

type Identity = { email: string | null; display_name: string | null; role: string; can_edit: boolean };
type User = { id: number; email: string; display_name: string | null; role: "viewer" | "admin"; status: "invited" | "active" | "disabled"; identity_bound: boolean; last_login_at: string | null };
type Token = { id: string; name: string; token_prefix: string; scopes: string[]; created_at: string; expires_at: string; last_used_at: string | null; revoked_at: string | null; owner_email: string };
type Overlay = { id: number; resource_type: string; resource_key: string; version: number; payload: Record<string, unknown>; rationale: string; created_at: string; created_by_email: string | null };

const scopes = ["catalog:read", "assessment:read", "poam:read", "poam:write", "milestones:write", "annotations:write"];

export function AdminConsole() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [tokens, setTokens] = useState<Token[]>([]);
  const [overlays, setOverlays] = useState<Overlay[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [issuedToken, setIssuedToken] = useState("");
  const [tokenName, setTokenName] = useState("Workbench automation");
  const [tokenDays, setTokenDays] = useState(30);
  const [selectedScopes, setSelectedScopes] = useState<string[]>(["catalog:read", "assessment:read", "poam:read"]);
  const [resourceType, setResourceType] = useState("service_group");
  const [resourceKey, setResourceKey] = useState("");
  const [owner, setOwner] = useState("");
  const [il2Date, setIl2Date] = useState("");
  const [il5Date, setIl5Date] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const [notes, setNotes] = useState("");
  const [rationale, setRationale] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const me = await fetchJson<Identity>("/api/v1/auth/me");
      setIdentity(me);
      if (!me.can_edit) throw new Error("Administrator access is required");
      const [userPage, tokenPage, overlayPage] = await Promise.all([
        fetchJson<{ items: User[] }>("/api/v1/admin/users"),
        fetchJson<{ items: Token[] }>("/api/v1/admin/tokens"),
        fetchJson<{ items: Overlay[] }>("/api/v1/admin/overlays"),
      ]);
      setUsers(userPage.items); setTokens(tokenPage.items); setOverlays(overlayPage.items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Administrative data is unavailable");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function updateUser(user: User, patch: Partial<Pick<User, "role" | "status">>) {
    setError("");
    try {
      await fetchJson(`/api/v1/admin/users/${user.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "User update failed"); }
  }

  async function createToken() {
    setError(""); setIssuedToken("");
    try {
      const result = await fetchJson<{ token: string }>("/api/v1/admin/tokens", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: tokenName, scopes: selectedScopes, expires_in_days: tokenDays }),
      });
      setIssuedToken(result.token); await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Token creation failed"); }
  }

  async function revokeToken(id: string) {
    setError("");
    try { await fetchJson(`/api/v1/admin/tokens/${id}`, { method: "DELETE" }); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Token revocation failed"); }
  }

  async function saveOverlay() {
    setError("");
    const payload: Record<string, unknown> = {};
    if (resourceType === "service_group") {
      if (owner) payload.effective_owners = owner.split(",").map((value) => value.trim()).filter(Boolean);
      if (il2Date) payload.il2_date = il2Date;
      if (il5Date) payload.il5_date = il5Date;
    } else {
      if (owner) payload.responsible_owner = owner;
      if (il2Date) payload.scheduled_completion_date = il2Date;
      if (reviewStatus) payload.review_status = reviewStatus;
    }
    if (notes) payload.admin_notes = notes;
    try {
      await fetchJson("/api/v1/admin/overlays", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resource_type: resourceType, resource_key: resourceKey, payload, rationale }),
      });
      setResourceKey(""); setOwner(""); setIl2Date(""); setIl5Date(""); setReviewStatus(""); setNotes(""); setRationale("");
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Overlay save failed"); }
  }

  if (loading && !identity) return <section className="page-heading"><div><p className="eyebrow">Access administration</p><h1>Loading administrator workspace…</h1></div></section>;
  if (!identity?.can_edit) return <section className="page-heading"><div><p className="eyebrow">Access administration</p><h1>Administrator access required</h1><p className="page-subtitle">Your account has read-only access to the evidence catalog.</p>{error && <p className="admin-error">{error}</p>}</div></section>;

  return <div className="admin-workbench">
    <section className="page-heading"><div><p className="eyebrow">Access &amp; evidence administration</p><h1>Administrator workspace</h1><p className="page-subtitle">Manage access, issue scoped API credentials, and create audited overlays without changing immutable evidence.</p></div><div className="heading-actions"><Badge tone="success"><ShieldCheck size={14} />{identity.email}</Badge><button className="refresh-button" onClick={() => void load()} disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} />Refresh</button></div></section>
    {error && <div className="admin-error" role="alert">{error}</div>}
    <div className="admin-grid">
      <Card className="admin-card"><div className="card-heading"><div><p className="eyebrow">Application RBAC</p><h2><UserCog size={18} />Users</h2></div><Badge tone="info">{users.length}</Badge></div><div className="table-scroll"><table><thead><tr><th>User</th><th>Identity</th><th>Role</th><th>Status</th></tr></thead><tbody>{users.map((user) => <tr key={user.id}><td><strong>{user.email}</strong><small>{user.display_name ?? "No display name"}</small></td><td><Badge tone={user.identity_bound ? "success" : "warning"}>{user.identity_bound ? "Bound" : "Invited"}</Badge></td><td><select value={user.role} onChange={(event) => void updateUser(user, { role: event.target.value as User["role"] })}><option value="viewer">Viewer</option><option value="admin">Admin</option></select></td><td><select value={user.status} onChange={(event) => void updateUser(user, { status: event.target.value as User["status"] })}><option value="invited">Invited</option><option value="active">Active</option><option value="disabled">Disabled</option></select></td></tr>)}</tbody></table></div></Card>
      <Card className="admin-card"><div className="card-heading"><div><p className="eyebrow">Direct API access</p><h2><KeyRound size={18} />Scoped tokens</h2></div></div><div className="admin-form"><label>Name<input value={tokenName} onChange={(event) => setTokenName(event.target.value)} /></label><label>Expires in days<input type="number" min={1} max={90} value={tokenDays} onChange={(event) => setTokenDays(Number(event.target.value))} /></label><fieldset><legend>Scopes</legend>{scopes.map((scope) => <label key={scope} className="scope-option"><input type="checkbox" checked={selectedScopes.includes(scope)} onChange={() => setSelectedScopes((current) => current.includes(scope) ? current.filter((value) => value !== scope) : [...current, scope])} />{scope}</label>)}</fieldset><button className="primary-button" onClick={() => void createToken()} disabled={!tokenName || !selectedScopes.length}><KeyRound size={16} />Generate token</button>{issuedToken && <div className="issued-token"><strong>Copy now — this token will not be shown again.</strong><code>{issuedToken}</code><button onClick={() => void navigator.clipboard.writeText(issuedToken)}><Clipboard size={14} />Copy token</button></div>}</div><div className="token-list">{tokens.map((token) => <article key={token.id}><div><strong>{token.name}</strong><code>{token.token_prefix}…</code><small>{token.scopes.join(" · ")}</small></div>{token.revoked_at ? <Badge tone="neutral">Revoked</Badge> : <button onClick={() => void revokeToken(token.id)}>Revoke</button>}</article>)}</div></Card>
    </div>
    <Card className="admin-card"><div className="card-heading"><div><p className="eyebrow">Immutable evidence overlay</p><h2><Save size={18} />Create reviewed override</h2><p className="coverage-intro">The original source record and checksum remain unchanged. This creates a new versioned administrative layer with rationale.</p></div></div><div className="overlay-form"><label>Resource type<select value={resourceType} onChange={(event) => setResourceType(event.target.value)}><option value="service_group">Service group</option><option value="poam_candidate">POA&amp;M candidate</option></select></label><label>Resource key<input value={resourceKey} onChange={(event) => setResourceKey(event.target.value)} placeholder={resourceType === "service_group" ? "collection/group or group slug" : "POA&M candidate ID"} /></label><label>Effective owner<input value={owner} onChange={(event) => setOwner(event.target.value)} /></label><label>{resourceType === "service_group" ? "IL2 date" : "Mitigation date"}<input type="date" value={il2Date} onChange={(event) => setIl2Date(event.target.value)} /></label>{resourceType === "service_group" && <label>IL5 date<input type="date" value={il5Date} onChange={(event) => setIl5Date(event.target.value)} /></label>}{resourceType === "poam_candidate" && <label>Review status<select value={reviewStatus} onChange={(event) => setReviewStatus(event.target.value)}><option value="">Unchanged</option><option value="draft">Draft</option><option value="under_review">Under review</option><option value="accepted_candidate">Accepted candidate</option></select></label>}<label className="wide">Administrative notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)} /></label><label className="wide">Required rationale<textarea value={rationale} onChange={(event) => setRationale(event.target.value)} /></label><button className="primary-button" onClick={() => void saveOverlay()} disabled={!resourceKey || rationale.trim().length < 8}><Check size={16} />Save audited overlay</button></div><div className="overlay-list">{overlays.slice(0, 20).map((overlay) => <article key={overlay.id}><div><Badge tone="info">{overlay.resource_type.replace("_", " ")}</Badge><strong>{overlay.resource_key}</strong><small>Version {overlay.version} · {overlay.created_by_email ?? "API credential"}</small></div><p>{overlay.rationale}</p></article>)}</div></Card>
  </div>;
}
