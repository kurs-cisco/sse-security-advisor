"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Boxes, ClipboardCheck, Database, Info, Menu, Moon, PanelLeft, ShieldCheck, Sun, UsersRound, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { cn } from "@/app/lib/utils";

const baseNav = [
  { href: "/", label: "Overview", icon: Activity },
  { href: "/inventory", label: "Inventory", icon: Database },
  { href: "/accountability", label: "Accountability", icon: UsersRound },
  { href: "/poam", label: "POA&M", icon: ClipboardCheck },
];

export function ConsoleShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [dark, setDark] = useState(false);
  const [compact, setCompact] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  useEffect(() => {
    const stored = window.localStorage.getItem("cbom-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const useDark = stored ? stored === "dark" : prefersDark;
    document.documentElement.classList.toggle("dark", useDark);
    const update = window.setTimeout(() => setDark(useDark), 0);
    void fetch("/api/v1/auth/me", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : null)
      .then((identity: { role?: string } | null) => setIsAdmin(identity?.role === "admin"))
      .catch(() => setIsAdmin(false));
    return () => window.clearTimeout(update);
  }, []);
  const nav = isAdmin
    ? [...baseNav, { href: "/admin", label: "Admin", icon: ShieldCheck }]
    : baseNav;
  const mobilePrimaryNav = nav.slice(0, 3);
  const mobileMoreNav = nav.slice(3);
  const mobileMoreActive = mobileMoreNav.some(({ href }) => pathname === href);
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
          <div className="connection-pill">Catalog workspace</div>
          {!compact && <p>{isAdmin ? "Administrative evidence workspace" : "Read-only analysis workspace"}</p>}
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
      <nav className="mobile-nav" aria-label="Mobile navigation">
        {mobilePrimaryNav.map(({ href, label, icon: Icon }) => <Link key={href} href={href} className={cn("mobile-nav-link", pathname === href && "mobile-nav-active")} aria-current={pathname === href ? "page" : undefined}><Icon size={18} /><span>{label}</span></Link>)}
        <button className={cn("mobile-nav-link", "mobile-more-trigger", mobileMoreActive && "mobile-nav-active")} type="button" aria-expanded={mobileMenuOpen} aria-controls="mobile-more-menu" onClick={() => setMobileMenuOpen((open) => !open)}><Menu size={18} /><span>More</span></button>
      </nav>
      {mobileMenuOpen && <MobileMoreMenu entries={mobileMoreNav} pathname={pathname} onClose={() => setMobileMenuOpen(false)} />}
    </div>
  );
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
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  return <div className="mobile-more-backdrop" onMouseDown={onClose}>
    <div id="mobile-more-menu" className="mobile-more-menu" ref={menuRef} role="dialog" aria-label="More navigation" onMouseDown={(event) => event.stopPropagation()}>
      <div className="mobile-more-heading"><span>More destinations</span><button className="icon-button" type="button" onClick={onClose} aria-label="Close more navigation"><X size={17} /></button></div>
      {entries.map(({ href, label, icon: Icon }) => <Link key={href} href={href} className={cn("mobile-more-link", pathname === href && "mobile-more-link-active")} aria-current={pathname === href ? "page" : undefined} onClick={onClose}><Icon size={18} /><span>{label}</span></Link>)}
    </div>
  </div>;
}
