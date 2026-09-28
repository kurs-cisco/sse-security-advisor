import { Suspense } from "react";
import { ConsoleShell } from "@/app/components/console-shell";
import { AdminConsole } from "@/components/admin/admin-console";

export default function AdminPage() {
  return <ConsoleShell><div className="page-container"><Suspense fallback={<section className="page-heading"><div><p className="eyebrow">Operations and access</p><h1>Loading administrator workspace…</h1></div></section>}><AdminConsole /></Suspense></div></ConsoleShell>;
}
