"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import { AlertTriangle, ArrowRight, ArrowUpRight, Boxes, CalendarDays, DatabaseZap, FileCheck2, FileWarning, Files, Fingerprint, FolderX, LibraryBig, RefreshCw } from "lucide-react";
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ConsoleShell } from "@/app/components/console-shell";
import { Badge } from "@/app/components/ui/badge";
import { Card } from "@/app/components/ui/card";
import { NumberTicker } from "@/app/components/ui/number-ticker";
import { getOverview } from "@/app/lib/api";
import type { OverviewResponse } from "@/app/lib/contracts";
import { cn, formatNumber, serviceGroupDisplayName } from "@/app/lib/utils";

const CHART = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];
const groupLabel = (_slug: string, displayName: string) => serviceGroupDisplayName(displayName);

const metrics = (overview: OverviewResponse) => {
  const c = overview.counts;
  return [
    { label: "Service groups", value: c.service_groups ?? 0, note: "Active portfolio scope", icon: Boxes, tone: "indigo" },
    { label: "Evidence records", value: c.unique_documents ?? 0, note: "CBOM, SBOM and tool evidence", icon: Files, tone: "blue" },
    { label: "Crypto occurrences", value: c.crypto_component_occurrences ?? 0, note: "Explicit candidate-crypto metadata", icon: DatabaseZap, tone: "cyan" },
    { label: "Unique crypto assets", value: c.unique_crypto_components ?? 0, note: "Deduplicated candidate inventory", icon: LibraryBig, tone: "violet" },
  ];
};

export function OverviewDashboard() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [source, setSource] = useState<"api" | "unavailable">("unavailable");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reducedMotion = useReducedMotion();
  const reload = async () => {
    setLoading(true);
    const result = await getOverview();
    setOverview(result.data);
    setSource(result.source);
    setError(result.source === "unavailable" ? result.error : null);
    setLoading(false);
  };
  useEffect(() => {
    let cancelled = false;
    void getOverview().then((result) => {
      if (!cancelled) {
        setOverview(result.data);
        setSource(result.source);
        setError(result.source === "unavailable" ? result.error : null);
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, []);
  const values = useMemo(() => overview ? metrics(overview) : [], [overview]);
  if (!overview && !loading) {
    return <ConsoleShell><div className="page-container">
      <OverviewHeading loading={loading} source={source} onRefresh={reload} />
      <Card className="catalog-unavailable" role="alert"><FileWarning size={21} /><div><h2>Live catalog is unavailable</h2><p>No sample counts, inventory records, or chart data are shown. Restore the catalog API, then refresh this page.</p><code>{error}</code></div></Card>
    </div></ConsoleShell>;
  }
  if (!overview) {
    return <ConsoleShell><div className="page-container"><OverviewHeading loading source={source} onRefresh={reload} /></div></ConsoleShell>;
  }
  const missingFingerprints = Math.max(0, (overview.counts.source_files ?? 0) - (overview.counts.fingerprinted_source_files ?? 0));
  const formatData = overview.format_coverage.map((item) => ({ name: `${item.format_name || item.document_kind} ${item.spec_version}`.trim(), value: item.source_files }));
  const topCryptoData = overview.top_crypto_libraries.map((item) => ({ ...item, name: [item.name, item.version].filter(Boolean).join(" ") }));
  const chartGroups = overview.service_groups.slice(0, 6).map((group) => ({ ...group, display_name: groupLabel(group.slug, group.display_name) }));
  const sourceLabel = loading ? "Loading catalog" : source === "api" ? "Live catalog" : "Catalog unavailable";

  return <ConsoleShell><div className="page-container">
    <OverviewHeading loading={loading} source={source} sourceLabel={sourceLabel} onRefresh={reload} />

    <div className="section-label dashboard-catalog-heading"><div><p className="eyebrow">Portfolio snapshot</p><h2>Catalog scale</h2></div><p>Counts describe inventory scope, not compliance.</p></div>
    <motion.section className="overview-metric-grid" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reducedMotion ? 0 : .24 }}>
      {values.map(({ label, value, note, icon: Icon, tone }, index) => <motion.div key={label} initial={{ opacity: 0, y: reducedMotion ? 0 : 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: reducedMotion ? 0 : index * .035 }}><Card className={cn("metric-card", `metric-${tone}`)}><div className="metric-icon"><Icon size={19} /></div><div><p>{label}</p><strong><NumberTicker value={value} /></strong><span>{note}</span></div></Card></motion.div>)}
    </motion.section>

    <section className="dashboard-actions">
      <Card className="priority-card"><div className="card-heading"><div><p className="eyebrow">Start here</p><h2>Review priorities</h2></div><Badge tone="neutral">Action queue</Badge></div><div className="priority-list">
        <Priority href="/inventory" icon={AlertTriangle} title="Resolve pending source data" value={overview.counts.pending_source_files ?? 0} detail="Empty, invalid, unsupported, or failed inputs" />
        <Priority href="/inventory" icon={FolderX} title="Confirm empty service categories" value={overview.counts.empty_service_groups ?? 0} detail="Includes categories intentionally retained without catalog files" />
        <Priority href="/poam" icon={FileCheck2} title="Review draft POA&M candidates" value="Open" detail="Authorized review is required before auditor submission" />
      </div></Card>
      <Card className="transition-card"><div className="transition-icon"><CalendarDays /></div><p className="eyebrow">Transition checkpoint</p><h2>September 22, 2026</h2><p>Use the POA&amp;M queue to prioritize IL2 remediation planning before the team checkpoint.</p><Link href="/poam">Open review queue <ArrowRight /></Link></Card>
    </section>

    <section className="dashboard-grid dashboard-grid-primary">
      <Card className="chart-card coverage-card"><div className="card-heading"><div><p className="eyebrow">Coverage by group</p><h2>Largest catalog footprints</h2></div><Link className="text-link" href="/inventory">Open inventory <ArrowUpRight size={15} /></Link></div><div className="chart-wrap" role="img" aria-label={`Largest service-group footprints by source file: ${chartGroups.map((group) => `${group.display_name} ${group.source_files}`).join(", ")}`}><ResponsiveContainer width="100%" height="100%"><BarChart data={chartGroups} layout="vertical" margin={{ left: 12, right: 24 }}><XAxis type="number" hide /><YAxis dataKey="display_name" type="category" width={124} axisLine={false} tickLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 13 }} /><Tooltip cursor={{ fill: "var(--chart-cursor)" }} contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 10 }} /><Bar dataKey="source_files" name="Source files" radius={[0, 6, 6, 0]} fill="var(--chart-1)" /></BarChart></ResponsiveContainer></div><p className="chart-note">Source file totals measure evidence coverage, not a compliance score.</p></Card>
      <Card className="readiness-card"><div className="card-heading"><div><p className="eyebrow">Refresh integrity</p><h2>Data readiness</h2></div><Fingerprint size={20} className="icon-muted" /></div><div className="readiness-score"><span>{formatNumber(overview.counts.fingerprinted_source_files)}</span><small>fingerprinted source files</small></div><div className="progress-track"><div className="progress-fill" style={{ width: `${overview.counts.source_files ? ((overview.counts.fingerprinted_source_files ?? 0) / overview.counts.source_files) * 100 : 0}%` }} /></div><div className="readiness-list"><div><span>Missing fingerprints</span><strong className={missingFingerprints ? "danger-text" : "success-text"}>{formatNumber(missingFingerprints)}</strong></div><div><span>Ingestion errors</span><strong className={(overview.counts.ingest_errors ?? 0) ? "danger-text" : "success-text"}>{formatNumber(overview.counts.ingest_errors)}</strong></div><div><span>Fingerprint versions</span><strong>{formatNumber(overview.counts.fingerprint_versions)}</strong></div></div></Card>
    </section>

    <section className="dashboard-grid dashboard-grid-secondary">
      <Card className="format-card"><div className="card-heading"><div><p className="eyebrow">Document mix</p><h2>Evidence formats</h2></div></div><div className="pie-layout"><div className="pie-wrap" role="img" aria-label={`Evidence formats: ${formatData.map((item) => `${item.name} ${item.value}`).join(", ")}`}><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={formatData} dataKey="value" nameKey="name" innerRadius={44} outerRadius={66} paddingAngle={3}>{formatData.map((item, index) => <Cell key={item.name} fill={CHART[index % CHART.length]} />)}</Pie><Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 10 }} /></PieChart></ResponsiveContainer></div><div className="legend-list">{formatData.map((item, index) => <div key={item.name}><span style={{ background: CHART[index % CHART.length] }} /><p>{item.name || "Unspecified"}</p><strong>{formatNumber(item.value)}</strong></div>)}</div></div></Card>
      <Card className="chart-card crypto-library-card"><div className="card-heading"><div><p className="eyebrow">Candidate crypto inventory</p><h2>Top five libraries by service usage</h2></div><Badge tone="info">Explicit metadata</Badge></div>{topCryptoData.length ? <div className="chart-wrap" role="img" aria-label={`Top crypto libraries by service usage: ${topCryptoData.map((item) => `${item.name} ${item.service_count}`).join(", ")}`}><ResponsiveContainer width="100%" height="100%"><BarChart data={topCryptoData} layout="vertical" margin={{ left: 0, right: 28 }}><XAxis type="number" hide /><YAxis dataKey="name" type="category" width={124} axisLine={false} tickLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} /><Tooltip cursor={{ fill: "var(--chart-cursor)" }} contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 10 }} /><Bar dataKey="service_count" name="Services" radius={[0, 6, 6, 0]} fill="var(--chart-2)" /></BarChart></ResponsiveContainer></div> : <div className="chart-empty"><LibraryBig size={24} /><strong>No explicitly classified libraries</strong><span>This scope returned no library records carrying explicit crypto metadata.</span></div>}<p className="chart-note">Versions remain distinct canonical assets; bars rank distinct service evidence records.</p></Card>
    </section>

    <Card className="service-table-card dashboard-service-index"><div className="card-heading"><div><p className="eyebrow">Service-group index</p><h2>Coverage and data-quality signals</h2></div><Link className="text-link" href="/inventory">Explore full inventory <ArrowUpRight size={16} /></Link></div><div className="table-scroll"><table><thead><tr><th>Service group</th><th>Collection</th><th>Evidence files</th><th>Service records</th><th>Data signal</th></tr></thead><tbody>{overview.service_groups.slice(0, 8).map((group) => <tr key={`${group.source_collection}-${group.slug}`}><td><strong>{groupLabel(group.slug, group.display_name)}</strong><span className="mono">{group.slug}</span></td><td><span className="mono">{group.source_collection}</span></td><td>{formatNumber(group.source_files)}</td><td>{formatNumber(group.unique_documents)}</td><td>{group.issues > 0 ? <Badge tone="warning">{group.issues} issue{group.issues === 1 ? "" : "s"}</Badge> : <Badge tone="success">Ready to inspect</Badge>}</td></tr>)}</tbody></table></div></Card>
  </div></ConsoleShell>;
}

function OverviewHeading({ loading, source, sourceLabel, onRefresh }: { loading: boolean; source: "api" | "unavailable"; sourceLabel?: string; onRefresh: () => Promise<void> }) {
  const label = sourceLabel ?? (loading ? "Loading catalog" : source === "api" ? "Live catalog" : "Catalog unavailable");
  return <section className="page-heading">
    <div><p className="eyebrow">FIPS 140-3 migration intelligence</p><h1>Portfolio overview</h1><p className="page-subtitle">Start with the work that needs attention, then trace every signal to its service record and source fingerprint.</p></div>
    <div className="heading-actions"><Badge tone={loading ? "neutral" : source === "api" ? "success" : "danger"}>{label}</Badge><button className="refresh-button" type="button" onClick={() => void onRefresh()} disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} />Refresh data</button></div>
  </section>;
}

function Priority({ href, icon: Icon, title, value, detail }: { href: string; icon: typeof Files; title: string; value: number | string; detail: string }) {
  return <Link className="priority-link" href={href}><span className="priority-icon"><Icon /></span><span><strong>{title}</strong><small>{detail}</small></span><b>{typeof value === "number" ? formatNumber(value) : value}</b><ArrowRight className="priority-arrow" /></Link>;
}
