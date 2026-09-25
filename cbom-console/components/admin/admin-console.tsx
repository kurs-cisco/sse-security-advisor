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
  const [draftUsers, setDraftUsers] = useState<Record<number, Pick<User, "role" | "status">>>({});
  const [savingUser, setSavingUser] = useState<number | null>(null);
  const [revokingToken, setRevokingToken] = useState<string | null>(null);

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
      setUsers(userPage.items); setTokens(tokenPage.items); setDraftUsers({});
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
      setSavingUser(user.id);
      await fetchJson(`/api/v1/admin/users/${user.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "User update failed"); }
    finally { setSavingUser(null); }
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
    if (!window.confirm("Revoke this token now? Existing clients will lose access immediately and this cannot be undone.")) return;
    try { setRevokingToken(id); await fetchJson(`/api/v1/admin/tokens/${id}`, { method: "DELETE" }); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Token revocation failed"); }
    finally { setRevokingToken(null); }
  }

  if (loading && !identity) return <section className="page-heading"><div><p className="eyebrow">Access administration</p><h1>Loading administrator workspace…</h1></div></section>;
  if (!identity?.can_edit) return <section className="page-heading"><div><p className="eyebrow">Access administration</p><h1>Administrator access required</h1><p className="page-subtitle">Your account has read-only access to the evidence catalog.</p>{error && <p className="admin-error">{error}</p>}</div></section>;

  return <div className="admin-workbench">
    <section className="page-heading"><div><p className="eyebrow">Operations and access</p><h1>Administrator workspace</h1><p className="page-subtitle">Ingest checksum-gated evidence, track asynchronous jobs, manage users, and issue least-privilege API credentials.</p></div><div className="heading-actions"><Badge tone="success"><ShieldCheck size={14} />{identity.email}</Badge><button className="refresh-button" onClick={() => void load()} disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} />Refresh access</button></div></section>
    {error && <div className="admin-error" role="alert">{error}</div>}
    <IngestionWorkspace operatorReady={identity.kind !== "local"} />
    <div className="admin-grid">
      <Card className="admin-card"><div className="card-heading"><div><p className="eyebrow">Application RBAC</p><h2><UserCog size={18} />Users</h2><p className="admin-card-note">Changes are staged locally. Review each row, then save it explicitly.</p></div><Badge tone="info">{users.length}</Badge></div><div className="table-scroll"><table><thead><tr><th>User</th><th>Identity</th><th>Role</th><th>Status</th><th><span className="sr-only">Save access change</span></th></tr></thead><tbody>{users.map((user) => { const draft = draftUsers[user.id] ?? { role: user.role, status: user.status }; const changed = draft.role !== user.role || draft.status !== user.status; return <tr key={user.id}><td><strong>{user.email}</strong><small>{user.display_name ?? "No display name"} · last sign-in {user.last_login_at ? new Date(user.last_login_at).toLocaleDateString() : "never"}</small></td><td><Badge tone={user.identity_bound ? "success" : "warning"}>{user.identity_bound ? "Bound" : "Invited"}</Badge></td><td><select aria-label={`Role for ${user.email}`} value={draft.role} disabled={savingUser === user.id} onChange={(event) => setDraftUsers((current) => ({ ...current, [user.id]: { ...draft, role: event.target.value as User["role"] } }))}><option value="viewer">Viewer</option><option value="admin">Admin</option></select></td><td><select aria-label={`Status for ${user.email}`} value={draft.status} disabled={savingUser === user.id} onChange={(event) => setDraftUsers((current) => ({ ...current, [user.id]: { ...draft, status: event.target.value as User["status"] } }))}><option value="invited">Invited</option><option value="active">Active</option><option value="disabled">Disabled</option></select></td><td><button className="admin-save" type="button" disabled={!changed || savingUser === user.id} onClick={() => { if (window.confirm(`Save access changes for ${user.email}? Role: ${draft.role}. Status: ${draft.status}.`)) void updateUser(user, draft); }}> {savingUser === user.id ? "Saving…" : "Save"}</button></td></tr>; })}</tbody></table></div></Card>
      <Card className="admin-card"><div className="card-heading"><div><p className="eyebrow">Direct API access</p><h2><KeyRound size={18} />Scoped tokens</h2><p className="admin-card-note">Choose the smallest scope set required. Tokens cannot be recovered after creation.</p></div></div><div className="admin-form"><label>Name<input value={tokenName} onChange={(event) => setTokenName(event.target.value)} /></label><label>Expires in days<input type="number" min={1} max={90} value={tokenDays} onChange={(event) => setTokenDays(Number(event.target.value))} /><small>Expires after {tokenDays} day{tokenDays === 1 ? "" : "s"}; maximum 90 days.</small></label><fieldset><legend>Scope presets</legend><div className="scope-presets">{Object.entries(scopePresets).map(([label, preset]) => <button type="button" key={label} onClick={() => setSelectedScopes([...preset])}>{label}</button>)}</div></fieldset><fieldset><legend>Scopes</legend>{scopes.map((scope) => <label key={scope} className="scope-option"><input type="checkbox" checked={selectedScopes.includes(scope)} onChange={() => setSelectedScopes((current) => current.includes(scope) ? current.filter((value) => value !== scope) : [...current, scope])} /><span><code>{scope}</code><small>{scopeHelp[scope]}</small></span></label>)}</fieldset><button className="primary-button" onClick={() => void createToken()} disabled={!tokenName || !selectedScopes.length}><KeyRound size={16} />Generate token</button>{issuedToken && <div className="issued-token"><strong>Copy now — this token will not be shown again.</strong><code>{issuedToken}</code><button onClick={() => void navigator.clipboard.writeText(issuedToken)}><Clipboard size={14} />Copy token</button></div>}</div><div className="token-list">{tokens.map((token) => <article key={token.id}><div><strong>{token.name}</strong><code>{token.token_prefix}…</code><small>{token.scopes.join(" · ")}</small><small>Created {new Date(token.created_at).toLocaleDateString()} · expires {new Date(token.expires_at).toLocaleDateString()} · last used {token.last_used_at ? new Date(token.last_used_at).toLocaleDateString() : "never"}</small></div>{token.revoked_at ? <Badge tone="neutral">Revoked</Badge> : <button disabled={revokingToken === token.id} onClick={() => void revokeToken(token.id)}>{revokingToken === token.id ? "Revoking…" : "Revoke"}</button>}</article>)}</div></Card>
    </div>
  </div>;
}
