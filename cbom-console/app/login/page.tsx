import { Boxes, LockKeyhole, ShieldCheck } from "lucide-react";
import { headers } from "next/headers";
import { localAdminAllowed, safeReturnTo } from "@/app/lib/auth-config";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ returnTo?: string; reason?: string }> }) {
  const query = await searchParams;
  const host = (await headers()).get("host") ?? "";
  let hostname = "";
  try { hostname = new URL(`http://${host}`).hostname; } catch { /* Invalid host cannot enable local login. */ }
  const showDevLogin = localAdminAllowed(hostname);
  return <main className="login-page">
    <section className="login-card surface-card" aria-labelledby="login-title">
      <div className="login-brand"><span className="brand-mark"><Boxes size={21} /></span><div><p className="eyebrow">Supply-chain intelligence</p><strong>CBOM Workbench</strong></div></div>
      <div className="login-icon"><ShieldCheck size={27} /></div>
      <p className="eyebrow">FIPS 140-3 transition workspace</p>
      <h1 id="login-title">Sign in to continue</h1>
      <p className="login-copy">Access to candidate crypto inventory, assessment findings, and POA&amp;M working data is restricted.</p>
      {showDevLogin ? <form action="/auth/dev-login" method="post">
        <input type="hidden" name="returnTo" value={safeReturnTo(query.returnTo)} />
        <button className="login-button" type="submit"><LockKeyhole size={17} />Continue in local development</button>
        <p className="login-note">Local click-through only. No identity claims are created, and this mode is blocked in production.</p>
      </form> : <div className="login-cloud-state" role="alert">
        <LockKeyhole size={18} />
        <div><strong>Cloud SSO required</strong><p>{query.reason ?? "Authentication is delegated to the configured OIDC identity provider at the load balancer."}</p></div>
      </div>}
    </section>
  </main>;
}
