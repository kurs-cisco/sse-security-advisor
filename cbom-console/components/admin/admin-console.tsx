"use client";

import { useCallback, useEffect, useState } from "react";
import { Clipboard, KeyRound, RefreshCw, ShieldCheck, UserCog } from "lucide-react";
import { fetchJson } from "@/app/lib/http";
import { Badge } from "@/app/components/ui/badge";
import { Card } from "@/app/components/ui/card";
import { IngestionWorkspace } from "@/components/admin/ingestion-workspace";

type Identity = { kind: string; email: string | null; display_name: string | null; role: string; can_edit: boolean };
type User = { id: number; email: string; display_name: string | null; role: "viewer" | "admin"; status: "invited" | "active" | "disabled"; identity_bound: boolean; last_login_at: string | null };
type Token = { id: string; name: string; token_prefix: string; scopes: string[]; created_at: string; expires_at: string; last_used_at: string | null; revoked_at: string | null; owner_email: string };

const scopes = ["catalog:read", "assessment:read", "poam:read", "poam:write", "milestones:write", "annotations:write", "ingestion:read", "ingestion:write"];

export function AdminConsole() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [tokens, setTokens] = useState<Token[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [issuedToken, setIssuedToken] = useState("");
  const [tokenName, setTokenName] = useState("Workbench automation");
  const [tokenDays, setTokenDays] = useState(30);
  const [selectedScopes, setSelectedScopes] = useState<string[]>(["catalog:read", "assessment:read", "poam:read"]);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const me = await fetchJson<Identity>("/api/v1/auth/me");
      setIdentity(me);
      if (!me.can_edit) throw new Error("Administrator access is required");
      const [userPage, tokenPage] = await Promise.all([
        fetchJson<{ items: User[] }>("/api/v1/admin/users"),
        fetchJson<{ items: Token[] }>("/api/v1/admin/tokens"),
      ]);
      setUsers(userPage.items); setTokens(tokenPage.items);
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

  if (loading && !identity) return <section className="page-heading"><div><p className="eyebrow">Access administration</p><h1>Loading administrator workspace…</h1></div></section>;
  if (!identity?.can_edit) return <section className="page-heading"><div><p className="eyebrow">Access administration</p><h1>Administrator access required</h1><p className="page-subtitle">Your account has read-only access to the evidence catalog.</p>{error && <p className="admin-error">{error}</p>}</div></section>;

  return <div className="admin-workbench">
    <section className="page-heading"><div><p className="eyebrow">Operations and access</p><h1>Administrator workspace</h1><p className="page-subtitle">Ingest checksum-gated evidence, track asynchronous jobs, manage users, and issue least-privilege API credentials.</p></div><div className="heading-actions"><Badge tone="success"><ShieldCheck size={14} />{identity.email}</Badge><button className="refresh-button" onClick={() => void load()} disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} />Refresh access</button></div></section>
    {error && <div className="admin-error" role="alert">{error}</div>}
    <IngestionWorkspace operatorReady={identity.kind !== "local"} />
    <div className="admin-grid">
      <Card className="admin-card"><div className="card-heading"><div><p className="eyebrow">Application RBAC</p><h2><UserCog size={18} />Users</h2></div><Badge tone="info">{users.length}</Badge></div><div className="table-scroll"><table><thead><tr><th>User</th><th>Identity</th><th>Role</th><th>Status</th></tr></thead><tbody>{users.map((user) => <tr key={user.id}><td><strong>{user.email}</strong><small>{user.display_name ?? "No display name"}</small></td><td><Badge tone={user.identity_bound ? "success" : "warning"}>{user.identity_bound ? "Bound" : "Invited"}</Badge></td><td><select value={user.role} onChange={(event) => void updateUser(user, { role: event.target.value as User["role"] })}><option value="viewer">Viewer</option><option value="admin">Admin</option></select></td><td><select value={user.status} onChange={(event) => void updateUser(user, { status: event.target.value as User["status"] })}><option value="invited">Invited</option><option value="active">Active</option><option value="disabled">Disabled</option></select></td></tr>)}</tbody></table></div></Card>
      <Card className="admin-card"><div className="card-heading"><div><p className="eyebrow">Direct API access</p><h2><KeyRound size={18} />Scoped tokens</h2></div></div><div className="admin-form"><label>Name<input value={tokenName} onChange={(event) => setTokenName(event.target.value)} /></label><label>Expires in days<input type="number" min={1} max={90} value={tokenDays} onChange={(event) => setTokenDays(Number(event.target.value))} /></label><fieldset><legend>Scopes</legend>{scopes.map((scope) => <label key={scope} className="scope-option"><input type="checkbox" checked={selectedScopes.includes(scope)} onChange={() => setSelectedScopes((current) => current.includes(scope) ? current.filter((value) => value !== scope) : [...current, scope])} />{scope}</label>)}</fieldset><button className="primary-button" onClick={() => void createToken()} disabled={!tokenName || !selectedScopes.length}><KeyRound size={16} />Generate token</button>{issuedToken && <div className="issued-token"><strong>Copy now — this token will not be shown again.</strong><code>{issuedToken}</code><button onClick={() => void navigator.clipboard.writeText(issuedToken)}><Clipboard size={14} />Copy token</button></div>}</div><div className="token-list">{tokens.map((token) => <article key={token.id}><div><strong>{token.name}</strong><code>{token.token_prefix}…</code><small>{token.scopes.join(" · ")}</small></div>{token.revoked_at ? <Badge tone="neutral">Revoked</Badge> : <button onClick={() => void revokeToken(token.id)}>Revoke</button>}</article>)}</div></Card>
    </div>
  </div>;
}
