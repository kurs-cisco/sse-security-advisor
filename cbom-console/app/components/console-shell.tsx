"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Boxes, ClipboardCheck, Database, Info, Moon, PanelLeft, Sun, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/app/lib/utils";

const nav = [
  { href: "/", label: "Overview", icon: Activity },
  { href: "/inventory", label: "Inventory", icon: Database },
  { href: "/accountability", label: "Accountability", icon: UsersRound },
  { href: "/poam", label: "POA&M", icon: ClipboardCheck },
];

export function ConsoleShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [dark, setDark] = useState(false);
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    const stored = window.localStorage.getItem("cbom-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const useDark = stored ? stored === "dark" : prefersDark;
    document.documentElement.classList.toggle("dark", useDark);
    const update = window.setTimeout(() => setDark(useDark), 0);
    return () => window.clearTimeout(update);
  }, []);
  const toggleTheme = () => {
    setDark((current) => {
      const next = !current;
      document.documentElement.classList.toggle("dark", next);
      window.localStorage.setItem("cbom-theme", next ? "dark" : "light");
      return next;
    });
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
          <div className="connection-pill"><span className="connection-dot" />Catalog workspace</div>
          {!compact && <p>Read-only analysis workspace</p>}
        </div>
      </aside>
      <div className="console-main">
        <header className="topbar">
          <button className="icon-button rail-toggle" type="button" aria-label="Toggle compact navigation" onClick={() => setCompact((value) => !value)}><PanelLeft size={18} /></button>
          <p className="topbar-context">FIPS 140-3 transition workspace</p>
          <div className="topbar-actions">
            <DisclosureInfo label="Assessment scope" text="Candidate analysis only. Inventory and FIPS signals require assessor review; they do not prove module validation." />
            <button className="icon-button" type="button" onClick={toggleTheme} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>{dark ? <Sun size={17} /> : <Moon size={17} />}</button>
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>{children}</main>
      </div>
      <nav className="mobile-nav" aria-label="Mobile navigation">{nav.map(({ href, label, icon: Icon }) => <Link key={href} href={href} className={cn("mobile-nav-link", pathname === href && "mobile-nav-active")}><Icon size={18} /><span>{label}</span></Link>)}</nav>
    </div>
  );
}

export function DisclosureInfo({ label, text }: { label: string; text: string }) {
  return <span className="disclosure-info">
    <button className="icon-button disclosure-trigger" type="button" aria-label={label} aria-describedby={`disclosure-${label.replaceAll(" ", "-").toLocaleLowerCase()}`}><Info size={17} /></button>
    <span className="disclosure-tooltip" id={`disclosure-${label.replaceAll(" ", "-").toLocaleLowerCase()}`} role="tooltip"><strong>{label}</strong>{text}</span>
  </span>;
}
