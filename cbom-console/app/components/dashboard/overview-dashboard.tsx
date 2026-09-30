"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import { AlertTriangle, ArrowRight, ArrowUpRight, Boxes, CalendarDays, DatabaseZap, FileWarning, Files, Fingerprint, FolderX, LibraryBig, RefreshCw } from "lucide-react";
import { Bar, BarChart, Cell, LabelList, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useConsoleAccess } from "@/app/components/console-shell";
import { Badge } from "@/app/components/ui/badge";
import { Card } from "@/app/components/ui/card";
import { NumberTicker } from "@/app/components/ui/number-ticker";
import { getOverview, getPortfolioOverview } from "@/app/lib/api";
import { fetchJson } from "@/app/lib/http";
import type { OverviewResponse } from "@/app/lib/contracts";
import { cn, formatNumber, serviceGroupDisplayName } from "@/app/lib/utils";

const CHART = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];
const SUMMARY_COMPONENT_CATEGORY_LABELS: Record<string, string> = {
  application: "Applications",
  library: "Libraries",
  framework: "Frameworks",
  "operating-system": "Operating systems",
  device: "Devices",
  file: "Files",
  firmware: "Firmware",
  service: "Services",
  unknown: "Unclassified",
};
const metrics = (overview: OverviewResponse) => {
  const c = overview.counts;
  return [
    { label: "Catalog service groups", value: c.service_groups ?? 0, note: "Visible portfolio scope", icon: Boxes, tone: "indigo" },
    { label: "Catalog records", value: c.unique_documents ?? 0, note: "Deduplicated CBOM, SBOM, and tool records", icon: Files, tone: "blue" },
    { label: "Explicit crypto occurrences", value: c.crypto_component_occurrences ?? 0, note: "Catalog inventory signal only", icon: DatabaseZap, tone: "cyan" },
    { label: "Distinct candidate crypto assets", value: c.unique_crypto_components ?? 0, note: "Deduplicated catalog inventory", icon: LibraryBig, tone: "violet" },
  ];
};

export function OverviewDashboard() {
  const { summaryAccess, detailAccess, isAdmin, pairs, activeMode } = useConsoleAccess();
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [detailOverview, setDetailOverview] = useState<OverviewResponse | null>(null);
  const [detailOverviewKey, setDetailOverviewKey] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(() => detailAccess);
  const [detailErrorKey, setDetailErrorKey] = useState<string | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [source, setSource] = useState<"api" | "unavailable">("unavailable");
  const [loading, setLoading] = useState(true);
  const reducedMotion = useReducedMotion();
  const detailScopeKey = useMemo(() => {
    if (activeMode === "admin" || isAdmin) return `admin:${activeMode ?? "unselected"}`;
    const grantedPairs = pairs.map((pair) => `${pair.sourceCollection}/${pair.serviceGroup}/${pair.productScopeId ?? "none"}/${pair.access ?? "none"}`).sort();
    return `${activeMode ?? "unselected"}:${grantedPairs.join("|")}`;
  }, [activeMode, isAdmin, pairs]);
  const detailReady = detailOverviewKey === detailScopeKey && detailOverview !== null;
  const detailError = detailErrorKey === detailScopeKey;
  const detailPending = detailLoading || (detailAccess && !detailReady && !detailError);
  const reload = async () => {
    setLoading(true);
    setDetailOverview(null);
    setDetailOverviewKey(null);
    setDetailErrorKey(null);
    setDetailLoading(detailAccess);
    setRefreshVersion((version) => version + 1);
    const result = await getPortfolioOverview();
    setOverview(result.data);
    setSource(result.source);
    setLoading(false);
  };
  useEffect(() => {
    let cancelled = false;
    void getPortfolioOverview().then((result) => {
      if (!cancelled) {
        setOverview(result.data);
        setSource(result.source);
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [summaryAccess]);
  useEffect(() => {
    let cancelled = false;
    if (!detailAccess) return () => { cancelled = true; };
    void Promise.resolve().then(async () => {
      if (cancelled) return;
      setDetailOverview(null);
      setDetailOverviewKey(null);
      setDetailErrorKey(null);
      setDetailLoading(true);
      const responses = isAdmin
        ? [await fetchJson<OverviewResponse>("/api/v1/dashboard/overview")]
        : await Promise.all(pairs.map((pair) => getOverview(pair).then((result) => result.data)));
      if (cancelled) return;
      const valid = responses.filter((response): response is OverviewResponse => response !== null);
      if (valid.length !== responses.length || !valid.length) {
        setDetailErrorKey(detailScopeKey);
        setDetailLoading(false);
        return;
      }
      const groups = new Map<string, OverviewResponse["service_groups"][number]>();
      const libraries = new Map<string, OverviewResponse["top_crypto_libraries"][number]>();
      for (const response of valid) {
        for (const group of response.service_groups) {
          const key = `${group.source_collection}\u0000${group.slug}`;
          if (!groups.has(key) || groups.get(key)!.source_files < group.source_files) groups.set(key, group);
        }
        for (const library of response.top_crypto_libraries) {
          const key = `${library.name}\u0000${library.version ?? ""}`;
          const existing = libraries.get(key);
          if (!existing || existing.service_count < library.service_count) libraries.set(key, library);
        }
      }
      setDetailOverview({ ...valid[0], service_groups: [...groups.values()], top_crypto_libraries: [...libraries.values()].sort((a, b) => b.service_count - a.service_count).slice(0, 5) });
      setDetailOverviewKey(detailScopeKey);
      setDetailLoading(false);
    }).catch(() => { if (!cancelled) { setDetailOverview(null); setDetailOverviewKey(null); setDetailErrorKey(detailScopeKey); setDetailLoading(false); } });
    return () => { cancelled = true; };
  }, [detailAccess, detailScopeKey, isAdmin, pairs, refreshVersion]);
  const values = useMemo(() => overview ? metrics(overview) : [], [overview]);
  if (!overview && !loading) {
    return <div className="page-container">
      <OverviewHeading loading={loading} source={source} onRefresh={reload} />
      <Card className="catalog-unavailable" role="alert"><FileWarning size={21} /><div><h2>Live catalog is unavailable</h2><p>The catalog could not be loaded. Refresh this page to try again.</p></div></Card>
    </div>;
  }
  if (!overview) {
    return <div className="page-container"><OverviewHeading loading source={source} onRefresh={reload} /></div>;
  }
  const missingFingerprints = Math.max(0, (overview.counts.source_files ?? 0) - (overview.counts.fingerprinted_source_files ?? 0));
  const formatData = overview.format_coverage.map((item) => ({ name: `${item.format_name || item.document_kind} ${item.spec_version}`.trim(), value: item.source_files }));
  const formatTotal = formatData.reduce((total, item) => total + item.value, 0);
  const primaryFormat = formatData[0];
  const useFormatSummary = formatData.length <= 1 || (primaryFormat?.value ?? 0) / Math.max(formatTotal, 1) >= .9;
  const sourceLabel = loading ? "Loading catalog" : source === "api" ? "Catalog loaded" : "Catalog unavailable";
  const chartGroups = [...(detailOverview?.service_groups ?? [])].sort((a, b) => b.source_files - a.source_files || a.display_name.localeCompare(b.display_name)).slice(0, 6).map((group) => ({ ...group, display_name: serviceGroupDisplayName(group.display_name) }));
  const topCryptoData = (detailOverview?.top_crypto_libraries ?? []).map((item) => ({ ...item, name: [item.name, item.version].filter(Boolean).join(" ") }));
  const coverageRequests = overview.counts.pending_source_files ?? 0;
  const emptyGroups = overview.counts.empty_service_groups ?? 0;
  const ingestErrors = overview.counts.ingest_errors ?? 0;
  const componentCategoryCounts = Object.entries((overview.component_types ?? []).reduce<Record<string, number>>((counts, item) => {
    const category = Object.hasOwn(SUMMARY_COMPONENT_CATEGORY_LABELS, item.component_type) ? item.component_type : "unknown";
    counts[category] = (counts[category] ?? 0) + (item.component_occurrences ?? 0);
    return counts;
  }, {})).filter(([, count]) => count > 0).sort(([, left], [, right]) => right - left).map(([category, count]) => ({ label: SUMMARY_COMPONENT_CATEGORY_LABELS[category], value: count }));

  return <div className="page-container">
    <OverviewHeading loading={loading} source={source} sourceLabel={sourceLabel} onRefresh={reload} />
      <div className="section-label dashboard-catalog-heading"><div><p className="eyebrow">Portfolio snapshot</p><h2>Catalog scale</h2></div><p>Counts describe inventory scope, not compliance.</p></div>
      <motion.section className="overview-metric-grid" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reducedMotion ? 0 : .24 }}>
        {values.map(({ label, value, note, icon: Icon, tone }, index) => <motion.div key={label} initial={{ opacity: 0, y: reducedMotion ? 0 : 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: reducedMotion ? 0 : index * .035 }}><Card className={cn("metric-card", `metric-${tone}`)}><div className="metric-icon"><Icon size={19} /></div><div><p>{label}</p><strong><NumberTicker value={value} /></strong><span>{note}</span></div></Card></motion.div>)}
      </motion.section>
      <section className="dashboard-actions">
        <Card className="priority-card"><div className="card-heading"><div><p className="eyebrow">Start here</p><h2>Catalog attention</h2></div><Badge tone="neutral">Processing queue</Badge></div><div className="priority-list">
          {coverageRequests > 0 && <Priority href={detailAccess ? "/inventory?view=coverage" : undefined} icon={AlertTriangle} title="Evidence-collection requests" value={coverageRequests} detail="Missing or conflicting catalog facts; not POA&amp;M candidates" />}
          {emptyGroups > 0 && <Priority href={detailAccess ? "/inventory?view=coverage" : undefined} icon={FolderX} title="Empty registered groups" value={emptyGroups} detail="Registered groups without current parsed source records" />}
          {ingestErrors > 0 && <Priority href={detailAccess ? "/inventory?view=coverage" : undefined} icon={FileWarning} title="Ingestion issues" value={ingestErrors} detail="Catalog processing issues requiring operator review" />}
          {!coverageRequests && !emptyGroups && !ingestErrors && <p className="callout-copy">No catalog evidence-collection requests, empty registered groups, or ingestion issues are currently surfaced for this scope.</p>}
        </div></Card>
        <Card className="transition-card"><div className="transition-icon"><CalendarDays /></div><p className="eyebrow">CMVP policy context</p><h2>September 22, 2026</h2><p>CMVP moved FIPS 140-2 certificates to the Historical List after September 21, 2026. Each ATO boundary and policy requires review; this is not a POA&amp;M due date.</p><Link href="/poam">Open evidence review <ArrowRight /></Link></Card>
      </section>
    <section className="dashboard-grid dashboard-grid-primary">
      <Card className="chart-card coverage-card"><div className="card-heading"><div><p className="eyebrow">{detailAccess ? "Coverage by group" : "Portfolio coverage"}</p><h2>{detailAccess ? "Largest catalog footprints" : "Catalog processing"}</h2></div>{detailAccess ? <Link className="text-link" href="/inventory">Open inventory <ArrowUpRight size={15} /></Link> : null}</div>{detailAccess && detailPending ? <EmptyChart title="Loading detailed charts" detail="Loading authorized catalog details for this workspace." /> : detailAccess && detailReady && detailOverview ? chartGroups.length ? <div className="chart-wrap" role="img" aria-label={`Largest assigned service-group footprints by source file: ${chartGroups.map((group) => `${group.display_name} ${group.source_files}`).join(", ")}`}><ResponsiveContainer width="100%" height="100%"><BarChart data={chartGroups} layout="vertical" margin={{ left: 12, right: 24 }}><XAxis type="number" hide /><YAxis dataKey="display_name" type="category" width={124} axisLine={false} tickLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 13 }} /><Tooltip cursor={{ fill: "var(--chart-cursor)" }} contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 10 }} /><Bar dataKey="source_files" name="Source files" radius={[0, 6, 6, 0]} fill="var(--chart-1)" /></BarChart></ResponsiveContainer></div> : <EmptyChart title="No service-group records" detail="This scope contains no service-group footprint data." /> : detailAccess ? <EmptyChart title="Footprints unavailable" detail={detailError ? "Detailed service coverage could not be loaded. Refresh data to try again." : "Detailed service coverage is unavailable."} /> : <AggregateMetricSummary items={[{ label: "Source files", value: overview.counts.source_files ?? 0 }, { label: "Pending files", value: coverageRequests }, { label: "Empty groups", value: emptyGroups }]} />}<p className="chart-note">Source file totals measure evidence coverage, not a compliance score.</p></Card>
      <Card className="readiness-card"><div className="card-heading"><div><p className="eyebrow">Catalog traceability</p><h2>Catalog observability</h2></div><Fingerprint size={20} className="icon-muted" /></div><div className="readiness-score"><span>{formatNumber(overview.counts.fingerprinted_source_files)} / {formatNumber(overview.counts.source_files)}</span><small>currently observed catalog files with a checksum</small></div><div className="progress-track" role="progressbar" aria-label="Current source-file fingerprint coverage" aria-valuemin={0} aria-valuemax={overview.counts.source_files ?? 0} aria-valuenow={overview.counts.fingerprinted_source_files ?? 0} aria-valuetext={`${formatNumber(overview.counts.fingerprinted_source_files)} of ${formatNumber(overview.counts.source_files)} currently observed catalog files have a checksum`}><div className="progress-fill" style={{ width: `${overview.counts.source_files ? ((overview.counts.fingerprinted_source_files ?? 0) / overview.counts.source_files) * 100 : 0}%` }} /></div><div className="readiness-list"><div><span>Without a current fingerprint</span><strong className={missingFingerprints ? "danger-text" : undefined}>{formatNumber(missingFingerprints)}</strong></div><div><span>Ingestion issues</span><strong className={(overview.counts.ingest_errors ?? 0) ? "danger-text" : undefined}>{formatNumber(overview.counts.ingest_errors)}</strong></div><div><span>Current-file fingerprint versions</span><strong>{formatNumber(overview.counts.fingerprint_versions)}</strong></div></div><p className="chart-note">Current source-file fingerprints measure traceability of ingested inputs. They do not establish evidence currency, deployment, CMVP validation, or compliance.</p></Card>
    </section>
    <section className="dashboard-grid dashboard-grid-secondary">
      <Card className="format-card"><div className="card-heading"><div><p className="eyebrow">Source-file mix</p><h2>Evidence formats</h2></div></div>{!formatData.length ? <EmptyChart title="No evidence-format records" detail="This catalog response contains no source-file format coverage data." /> : useFormatSummary ? <div className="format-summary"><strong>{formatNumber(primaryFormat?.value ?? 0)} / {formatNumber(formatTotal)}</strong><div><span>{primaryFormat?.name || "Unspecified format"}</span><p>{formatData.length === 1 ? "All reported source files use this format." : `${formatNumber(primaryFormat?.value ?? 0)} of ${formatNumber(formatTotal)} reported source files use this format.`}</p></div></div> : <div className="pie-layout"><div className="pie-wrap" role="img" aria-label={`Evidence formats by source file: ${formatData.map((item) => `${item.name} ${item.value}`).join(", ")}`}><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={formatData} dataKey="value" nameKey="name" innerRadius={44} outerRadius={66} paddingAngle={3}>{formatData.map((item, index) => <Cell key={item.name} fill={CHART[index % CHART.length]} />)}</Pie><Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 10 }} /></PieChart></ResponsiveContainer></div><div className="legend-list">{formatData.map((item, index) => <div key={item.name}><span style={{ background: CHART[index % CHART.length] }} /><p>{item.name || "Unspecified"}</p><strong>{formatNumber(item.value)} / {formatNumber(formatTotal)}</strong></div>)}</div></div>}</Card>
      <Card className="chart-card crypto-library-card"><div className="card-heading"><div><p className="eyebrow">{detailAccess ? "Explicit crypto inventory" : "Catalog composition"}</p><h2>{detailAccess ? `Top five libraries by ${isAdmin ? "observed service usage" : "assigned service-group usage"}` : "Component categories"}</h2></div><Badge tone="info">Catalog metadata only</Badge></div>{detailAccess && detailPending ? <EmptyChart title="Loading detailed charts" detail="Loading authorized catalog details for this workspace." /> : detailAccess && detailReady && detailOverview ? topCryptoData.length ? <div className="chart-wrap" role="img" aria-label={`Top explicitly classified crypto libraries by ${isAdmin ? "observed service usage" : "assigned service-group usage"}: ${topCryptoData.map((item) => `${item.name} ${item.service_count} ${isAdmin ? "services" : "assigned service groups"}`).join(", ")}`}><ResponsiveContainer width="100%" height="100%"><BarChart data={topCryptoData} layout="vertical" margin={{ left: 0, right: 48 }}><XAxis type="number" hide /><YAxis dataKey="name" type="category" width={124} axisLine={false} tickLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} /><Tooltip cursor={{ fill: "var(--chart-cursor)" }} contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 10 }} /><Bar dataKey="service_count" name={isAdmin ? "Observed services" : "Assigned service groups"} radius={[0, 6, 6, 0]} fill="var(--chart-2)"><LabelList dataKey="service_count" position="right" formatter={(value: number) => formatNumber(value)} fill="var(--foreground)" fontSize={12} /></Bar></BarChart></ResponsiveContainer></div> : <EmptyChart title="No explicitly classified libraries" detail="This scope returned no library records carrying explicit crypto metadata." /> : detailAccess ? <EmptyChart title="Library coverage unavailable" detail={detailError ? "Detailed library coverage could not be loaded. Refresh data to try again." : "Detailed library coverage is unavailable."} /> : componentCategoryCounts.length ? <AggregateDistribution items={componentCategoryCounts} /> : <EmptyChart title="No component categories" detail="This portfolio summary contains no component-category totals." />}<p className="chart-note">{detailAccess ? "Counts are catalog observations explicitly tagged as crypto-related. They do not establish deployed use, CMVP validation, approved mode, or compliance." : "Counts are unique catalog components by allowlisted category."}</p></Card>
    </section>

  </div>;
}

function OverviewHeading({ loading, source, sourceLabel, onRefresh }: { loading: boolean; source: "api" | "unavailable"; sourceLabel?: string; onRefresh: () => Promise<void> }) {
  const label = sourceLabel ?? (loading ? "Loading catalog" : source === "api" ? "Catalog loaded" : "Catalog unavailable");
  return <section className="page-heading">
    <div><p className="eyebrow">CBOM catalog and FIPS transition review</p><h1>Service overview</h1><p className="page-subtitle">Review catalog observations and source traceability across service groups.</p></div>
    <div className="heading-actions"><Badge tone={loading ? "neutral" : source === "api" ? "info" : "danger"}>{label}</Badge><button className="refresh-button" type="button" onClick={() => void onRefresh()} disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} />Refresh data</button></div>
  </section>;
}

function Priority({ href, icon: Icon, title, value, detail }: { href?: string; icon: typeof Files; title: string; value: number | string; detail: string }) {
  const content = <><span className="priority-icon"><Icon /></span><span><strong>{title}</strong><small>{detail}</small></span><b>{typeof value === "number" ? formatNumber(value) : value}</b>{href ? <ArrowRight className="priority-arrow" /> : null}</>;
  return href ? <Link className="priority-link" href={href}>{content}</Link> : <div className="priority-link">{content}</div>;
}

function EmptyChart({ title, detail }: { title: string; detail: string }) {
  return <div className="chart-empty"><LibraryBig size={24} /><strong>{title}</strong><span>{detail}</span></div>;
}

function AggregateMetricSummary({ items }: { items: Array<{ label: string; value: number }> }) {
  return <div className="aggregate-summary" aria-label={items.map((item) => `${item.label}: ${formatNumber(item.value)}`).join(". ")}>
    {items.map((item) => <div key={item.label}><span>{item.label}</span><strong>{formatNumber(item.value)}</strong></div>)}
    <p>Portfolio processing totals for the selected workspace.</p>
  </div>;
}

function AggregateDistribution({ items }: { items: Array<{ label: string; value: number }> }) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  return <div className="aggregate-distribution" role="img" aria-label={`Component categories by unique component: ${items.map((item) => `${item.label} ${formatNumber(item.value)}`).join(", ")}`}>
    {items.map((item) => <div key={item.label}><span>{item.label}</span><strong>{formatNumber(item.value)}</strong><i style={{ width: `${Math.max(6, (item.value / Math.max(total, 1)) * 100)}%` }} /></div>)}
    <p>Unique catalog components by category.</p>
  </div>;
}
