"use client";

import { useEffect, useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { CalendarClock, ChevronDown, ChevronLeft, ChevronRight, ClipboardCheck, Download, ExternalLink, FileWarning, FlaskConical, ListTree, RefreshCw, ShieldCheck, Tags, UserRound } from "lucide-react";
import { ConsoleShell, DisclosureInfo } from "@/app/components/console-shell";
import { Badge } from "@/app/components/ui/badge";
import { Card } from "@/app/components/ui/card";
import { getPoamAssessment, getTeamMilestones, type CoverageGap, type PoamCandidate, type PoamWorkstream, type PortfolioPoam, type ServiceScopeLink, type TeamMilestoneProfile, type TrackerMilestone } from "@/app/lib/team-milestones";
import { cn, serviceGroupDisplayName, serviceGroupFromReference } from "@/app/lib/utils";
import "./poam-workbench.css";

type CoverageGapRow = {
  gap: CoverageGap;
  service: string;
  serviceGroup: string;
  serviceGroupName: string;
  sourceFiles: number;
  documents: number;
  documentsWithFipsEvidence: number;
  documentsWithoutFipsEvidence: number;
  ingestIssues: number;
  profile?: TeamMilestoneProfile;
};

function milestoneText(milestone: TrackerMilestone) {
  if (milestone.status === "not_supplied") return <span className="poam-missing">Not supplied</span>;
  if (milestone.status === "not_applicable") return "Not applicable";
  if (milestone.status === "unparseable_or_relative") return <span className="poam-muted">Ignored — no explicit date</span>;
  return milestone.raw_value;
}

function DateOrGap({ date }: { date: string | null | undefined }) {
  return date ? <time dateTime={date}>{new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(`${date}T00:00:00`))}</time> : <span className="poam-missing">Not supplied</span>;
}

function serviceGroupLabel(reference: string) {
  return serviceGroupFromReference(reference);
}

function inventoryLink(view: "services" | "libraries", query: string) {
  return `/inventory?view=${view}&query=${encodeURIComponent(query)}`;
}

function ScopeLinks({ links }: { links: ServiceScopeLink[] }) {
  if (!links.length) return <p className="poam-muted">No document-level scope links were resolved.</p>;
  return <div className="poam-scope-links">{links.map((link) => <article key={`${link.document_id}-${link.service_group_ref}-${link.subject_identity}`}>
    <div className="poam-scope-heading"><div><strong>{link.service_record_name}</strong><small>{serviceGroupLabel(link.service_group_ref)} · document {link.document_id}</small></div><a href={inventoryLink("services", link.service_record_name)}>Open service <ExternalLink size={13} /></a></div>
    <p className="mono poam-scope-subject">{link.subject_name}</p>
    <div className="poam-scope-meta"><span><b>Owner</b>{link.planning?.owners.join(" / ") || "Not supplied"}</span><span><b>Lead</b>{link.planning?.leads.join(" / ") || "Not supplied"}</span><span><b>Delivery wave</b>{link.planning?.delivery_wave.label || "Uncommitted"}</span><span><b>Group IL2</b><DateOrGap date={link.planning?.delivery_wave.farthest_explicit_il2_date} /></span></div>
    {link.libraries.length ? <div className="poam-library-links">{link.libraries.map((library, index) => <a key={`${library.component_identity}-${library.occurrence_id}-${index}`} href={inventoryLink("libraries", library.name)}><FlaskConical size={13} />{library.name}{library.version ? ` @ ${library.version}` : ""}</a>)}</div> : <span className="poam-missing">No component-level library link</span>}
    <small className="poam-eta-note">{link.planning?.eta_inheritance || "ETA mapping not supplied"}</small>
  </article>)}</div>;
}

function PortfolioRow({ item }: { item: PortfolioPoam }) {
  const [open, setOpen] = useState(false);
  const isActive = item.dimension === "active_certificate_migration";
  return <>
    <tr>
      <td><button type="button" className="poam-expand" onClick={() => setOpen((value) => !value)} aria-expanded={open}><ChevronDown size={17} className={cn(open && "poam-chevron-open")} /><span className="mono">{item.portfolio_poam_id}</span></button><strong>{item.title}</strong><small>{isActive ? "Active-certificate migration dimension" : "CMVP pipeline dependency dimension"}</small></td>
      <td><strong>{item.linked_candidate_count} linked asset candidate{item.linked_candidate_count === 1 ? "" : "s"}</strong><small>{item.affected_service_record_count} service records · {item.affected_library_count} libraries</small></td>
      <td><span>{item.responsible_owners.join(" / ") || "Not supplied"}</span><small>{item.affected_service_groups.map(serviceGroupLabel).join(", ") || "No defensible mapping yet"}</small></td>
      <td><DateOrGap date={item.scheduled_completion_date} /><small>Farthest explicit linked-group IL2</small></td>
      <td><Badge tone="warning">Assessor merge review</Badge><small>{item.unclassified_candidate_count} candidates remain unclassified</small></td>
    </tr>
    {open ? <tr className="poam-detail-row"><td colSpan={5}><div className="poam-portfolio-detail"><div className="poam-portfolio-summary"><div><p className="eyebrow">Candidate condition</p><p>{item.condition}</p></div><div><p className="eyebrow">Milestone deliverables</p><div className="poam-wave-list">{item.milestone_deliverables.filter((wave) => wave.wave !== "uncommitted").map((wave) => <span key={wave.wave}><strong>{wave.label}</strong>{wave.service_groups.map((group) => serviceGroupDisplayName(group.service_group)).join(", ") || "No linked groups"}</span>)}</div></div><div><p className="eyebrow">Merge confirmation gates</p><ul className="coverage-evidence-list">{item.merge_blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul></div></div><ScopeLinks links={item.service_scope_links} /></div></td></tr> : null}
  </>;
}

function profileDetails(profile: TeamMilestoneProfile | undefined) {
  if (!profile?.tracker_rows.length) return <span className="poam-missing">Team mapping not supplied</span>;
  return <div className="coverage-plan">
    <span><strong>Owner</strong>{profile.owners.join(" / ") || "Not supplied"}</span>
    <span><strong>Lead</strong>{profile.leads.join(" / ") || "Not supplied"}</span>
    {profile.tracker_rows.map((row) => <span key={row.team}><strong>{row.team} · IL2 / IL5</strong>{milestoneText(row.il2)} <span className="poam-muted">/</span> {milestoneText(row.il5)}</span>)}
  </div>;
}

function CandidateRow({ candidate }: { candidate: PoamCandidate }) {
  const [open, setOpen] = useState(false);
  const trackerRows = candidate.team_tracker_milestones?.group_milestones.flatMap((group) => group.tracker_rows) ?? [];
  return <>
    <tr>
      <td><button type="button" className="poam-expand" onClick={() => setOpen((value) => !value)} aria-expanded={open}><ChevronDown size={17} className={cn(open && "poam-chevron-open")} /><span className="mono">{candidate.poam_candidate_id}</span></button><strong>{candidate.title}</strong><small>{candidate.linked_finding_count} linked candidate finding{candidate.linked_finding_count === 1 ? "" : "s"}</small></td>
      <td><Badge tone="neutral">{candidate.control_id}</Badge><span className="poam-risk">{candidate.proposed_risk}</span></td>
      <td><span>{candidate.responsible_owner}</span><small>{candidate.affected_services.map(serviceGroupLabel).join(", ")}</small></td>
      <td><DateOrGap date={candidate.milestone_mitigation_date ?? candidate.scheduled_completion_date} /><small>Farthest explicit IL2 date</small></td>
      <td><Badge tone="warning">Draft candidate</Badge></td>
    </tr>
    {open ? <tr className="poam-detail-row"><td colSpan={5}><div className="poam-portfolio-detail"><div className="poam-detail-grid"><div><p className="eyebrow">Proposed remediation</p><p>{candidate.remediation_plan}</p></div><div><p className="eyebrow">Tracker planning context</p>{trackerRows.length ? <div className="poam-milestone-list">{trackerRows.map((row, index) => <div key={`${row.team}-${index}`}><strong>{row.team}</strong><span>Owner: {row.owner || "Not supplied"}</span><span>Lead: {row.lead || "Not supplied"}</span><span>IL2: {milestoneText(row.il2)}</span><span>IL5: {milestoneText(row.il5)}</span><span>CMVP: {row.cmvp_mapping || "Not determined"}</span></div>)}</div> : <p className="poam-muted">Team planning data not supplied.</p>}</div><div><p className="eyebrow">Evidence integrity</p><p>{candidate.evidence_sha256.length} evidence checksum{candidate.evidence_sha256.length === 1 ? "" : "s"} · {candidate.source_sha256.length} source checksum{candidate.source_sha256.length === 1 ? "" : "s"}</p></div></div><div><p className="eyebrow">Linked services, groups, and libraries</p><ScopeLinks links={candidate.service_scope_links ?? []} /></div></div></td></tr> : null}
  </>;
}

function WorkstreamRow({ workstream }: { workstream: PoamWorkstream }) {
  const [open, setOpen] = useState(false);
  return <>
    <tr>
      <td><button type="button" className="poam-expand" onClick={() => setOpen((value) => !value)} aria-expanded={open}><ChevronDown size={17} className={cn(open && "poam-chevron-open")} /><span className="mono">{workstream.workstream_id}</span></button><strong>{workstream.title}</strong><small>{workstream.issue_codes.join(", ")}</small></td>
      <td><strong>{workstream.candidate_count} asset candidate{workstream.candidate_count === 1 ? "" : "s"}</strong><small>{workstream.subject_count} distinct subject{workstream.subject_count === 1 ? "" : "s"} · {workstream.affected_service_count} service group{workstream.affected_service_count === 1 ? "" : "s"}</small></td>
      <td><span>{workstream.responsible_owner}</span><small>{workstream.affected_services.map(serviceGroupLabel).join(", ")}</small></td>
      <td><DateOrGap date={workstream.milestone_mitigation_date} /><small>Explicit IL2 date; clusters split when dates differ</small></td>
      <td><Badge tone="warning">Merge review required</Badge><small>Impact not assessed</small></td>
    </tr>
    {open ? <tr className="poam-detail-row"><td colSpan={5}><div className="poam-detail-grid"><div><p className="eyebrow">Shared remediation</p><p>{workstream.remediation_plan}</p><div className="poam-tag-list">{workstream.tags.map((tag) => <span key={tag}>{tag}</span>)}</div></div><div><p className="eyebrow">Merge confirmation gates</p><ul className="coverage-evidence-list">{workstream.merge_blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul></div><div><p className="eyebrow">Traceability retained</p><p>{workstream.candidate_count} linked asset candidates remain independently addressable. This workstream does not delete or close them.</p></div></div></td></tr> : null}
  </>;
}

function CoverageGapRegister({ rows, filter }: { rows: CoverageGapRow[]; filter: string }) {
  const normalizedFilter = filter.trim().toLocaleLowerCase();
  const visibleRows = rows.filter(({ gap, service, serviceGroupName, profile }) => [gap.observation_id, gap.title, gap.technical_observation, service, serviceGroupName, ...gap.missing_required_facts, ...(profile?.owners ?? []), ...(profile?.leads ?? [])].join(" ").toLocaleLowerCase().includes(normalizedFilter));
  return <Card className="poam-table-card coverage-gap-card"><div className="card-heading"><div><p className="eyebrow">Evidence collection register</p><h2>Coverage gaps / evidence requests</h2><p className="coverage-intro">Zero-document groups are shown first. These are analyst observations, not inferred FIPS failures or POA&amp;M candidates.</p></div><div className="poam-card-actions"><DisclosureInfo label="Coverage gap scope" text="A missing CBOM, SBOM, or FIPS record prevents a posture determination. Collect the listed evidence and obtain system-owner, assessor, and AO review before creating or changing a POA&M." /><Badge tone="info">{visibleRows.length} review-only</Badge></div></div><div className="table-scroll"><table className="poam-table coverage-gap-table"><thead><tr><th>Service group / evidence state</th><th>Coverage</th><th>Observation &amp; reason</th><th>Requested evidence</th><th><UserRound size={14} /> Owner / planning context</th><th>POA&amp;M eligibility</th></tr></thead><tbody>{visibleRows.map((row) => <tr key={`${row.gap.observation_id}-${row.serviceGroup}`}><td><strong>{row.serviceGroupName}</strong><small className="mono">{row.service}</small><Badge tone="warning">{row.gap.assertion_state.replace("_", " ")}</Badge></td><td><strong>{row.documents} document{row.documents === 1 ? "" : "s"}</strong><small>{row.sourceFiles} source file{row.sourceFiles === 1 ? "" : "s"} · {row.documentsWithFipsEvidence} with FIPS evidence</small>{row.ingestIssues ? <small className="danger-text">{row.ingestIssues} ingestion issue{row.ingestIssues === 1 ? "" : "s"}</small> : null}</td><td><strong>{row.gap.title}</strong><small>{row.gap.technical_observation}</small><small className="mono">{row.gap.observation_id}</small></td><td><ul className="coverage-evidence-list">{row.gap.missing_required_facts.map((item) => <li key={item}>{item}</li>)}</ul></td><td>{profileDetails(row.profile)}</td><td><Badge tone="neutral">Not eligible</Badge><small>Evidence collection only</small></td></tr>)}{visibleRows.length === 0 ? <tr><td colSpan={6} className="poam-empty">No coverage gaps match this filter.</td></tr> : null}</tbody></table></div></Card>;
}

export function PoamWorkbench() {
  const [data, setData] = useState<Awaited<ReturnType<typeof getPoamAssessment>> | null>(null);
  const [milestones, setMilestones] = useState<Awaited<ReturnType<typeof getTeamMilestones>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [registerMode, setRegisterMode] = useState<"portfolio" | "workstreams" | "candidates">("portfolio");
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const reducedMotion = useReducedMotion();
  const refresh = async () => { setLoading(true); const [assessmentResult, milestoneResult] = await Promise.all([getPoamAssessment({ page, pageSize, query: filter }), getTeamMilestones()]); setData(assessmentResult); setMilestones(milestoneResult); setLoading(false); };
  useEffect(() => {
    const controller = new AbortController();
    void getTeamMilestones(controller.signal).then((milestoneResult) => {
      if (controller.signal.aborted) return;
      setMilestones(milestoneResult);
    });
    return () => { controller.abort(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      void getPoamAssessment({ page, pageSize, query: filter, signal: controller.signal }).then((assessmentResult) => {
        if (controller.signal.aborted) return;
        setData(assessmentResult);
        setLoading(false);
      });
    }, filter ? 250 : 0);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [page, filter]);

  const assessment = data?.data;
  const profileByGroup = useMemo(() => new Map((milestones?.data?.groups ?? []).map((profile) => [profile.service_group, profile])), [milestones]);
  const coverageGaps = useMemo<CoverageGapRow[]>(() => {
    const rollups = new Map((assessment?.service_groups ?? []).map((row) => [row.service, row]));
    return (assessment?.coverage_gaps ?? []).flatMap((gap) => gap.scope.service_groups.map((serviceGroup) => {
      const service = `${gap.scope.source_collection}/${serviceGroup}`;
      const rollup = rollups.get(service);
      return {
        gap, service, serviceGroup, serviceGroupName: serviceGroupDisplayName(rollup?.service_group_name ?? serviceGroup),
        sourceFiles: rollup?.source_files ?? 0, documents: rollup?.documents ?? 0,
        documentsWithFipsEvidence: rollup?.documents_with_fips_evidence ?? 0,
        documentsWithoutFipsEvidence: rollup?.documents_without_fips_evidence ?? 0,
        ingestIssues: rollup?.ingest_issues ?? 0, profile: profileByGroup.get(serviceGroup),
      };
    })).sort((left, right) => left.documents - right.documents || left.serviceGroupName.localeCompare(right.serviceGroupName));
  }, [assessment, profileByGroup]);
  const candidates = assessment?.poam_items ?? [];
  const workstreams = assessment?.poam_workstreams ?? [];
  const portfolioItems = assessment?.portfolio_poam_items ?? [];
  const normalizedFilter = filter.trim().toLocaleLowerCase();
  const visibleWorkstreams = workstreams.filter((workstream) => [workstream.workstream_id, workstream.title, workstream.responsible_owner, ...workstream.issue_codes, ...workstream.affected_services, ...workstream.tags].join(" ").toLocaleLowerCase().includes(normalizedFilter));
  const candidateTotal = assessment?.poam_page?.total ?? candidates.length;
  const pageCount = Math.max(1, Math.ceil(candidateTotal / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visibleCandidates = candidates;
  const assessmentUnavailable = !loading && data?.source === "unavailable";
  const milestoneUnavailable = !loading && milestones?.source === "unavailable";

  return <ConsoleShell><div className="page-container poam-page">
    <section className="page-heading"><div><p className="eyebrow">SC-13 remediation candidates</p><h1>POA&amp;M review queue</h1><p className="page-subtitle">Review the two portfolio migration dimensions, then trace every group milestone to its service records, libraries, and underlying asset evidence.</p></div><div className="heading-actions"><Badge tone={loading ? "neutral" : assessment ? "success" : "danger"}>{loading ? "Loading assessment" : assessment ? "Live assessment" : "Assessment unavailable"}</Badge>{assessment ? <><a className="secondary-button" href="/api/v1/fips/compliance-package.zip" download><Download size={17} />Compliance ZIP</a><a className="secondary-button" href="/api/v1/fips/portfolio-poam.csv" download><Download size={17} />Portfolio CSV</a><a className="secondary-button" href="/api/v1/fips/poam.csv" download><Download size={17} />Asset CSV</a></> : null}<button className="refresh-button" type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} />Refresh</button></div></section>

    {assessmentUnavailable ? <Card className="poam-unavailable" role="alert"><FileWarning size={21} /><div><h2>Live FIPS assessment is unavailable</h2><p>No sample POA&amp;M or milestone records are shown. Restore the catalog API, then refresh this page.</p><code>{data?.error}</code></div></Card> : null}
    {milestoneUnavailable ? <Card className="poam-unavailable poam-unavailable-compact" role="status"><CalendarClock size={19} /><div><strong>Team Tracker planning metadata is unavailable.</strong><p>Candidate and coverage records remain live, but owner, lead, IL2, and IL5 context cannot be displayed until the tracker endpoint recovers.</p></div></Card> : null}

    {assessment ? <>
      <Card className="poam-table-card"><div className="card-heading"><div><p className="eyebrow">Traceable remediation hierarchy</p><h2>{registerMode === "portfolio" ? "Two portfolio POA&M candidates" : registerMode === "workstreams" ? "Proposed issue workstreams" : "Asset-level candidate evidence"}</h2><p className="coverage-intro">Portfolio rows separate active-certificate migrations from CMVP pipeline dependencies. Every service, group, library, ETA, finding, and checksum remains linked beneath them.</p></div><div className="poam-card-actions"><DisclosureInfo label="Consolidation rules" text="Portfolio rows are candidate views, not accepted merges. Active certificates still require exact deployment matching. In-Test/In-Progress modules remain open dependencies. Unclassified candidates stay visible until module disposition is supported." /><label className="poam-filter"><span className="sr-only">Filter issue workstreams, candidates, and coverage gaps</span><input value={filter} onChange={(event) => { setFilter(event.target.value); setPage(0); }} placeholder="Filter issue, group, owner…" /></label></div></div><div className="poam-register-tabs" role="group" aria-label="POA&M register view"><button type="button" aria-pressed={registerMode === "portfolio"} onClick={() => setRegisterMode("portfolio")}><ShieldCheck size={16} />Portfolio candidates <span>{portfolioItems.length}</span></button><button type="button" aria-pressed={registerMode === "workstreams"} onClick={() => setRegisterMode("workstreams")}><ListTree size={16} />Issue clusters <span>{workstreams.length}</span></button><button type="button" aria-pressed={registerMode === "candidates"} onClick={() => setRegisterMode("candidates")}><Tags size={16} />Asset evidence <span>{candidateTotal}</span></button></div>{registerMode === "portfolio" ? <div className="table-scroll"><table className="poam-table"><thead><tr><th>Portfolio POA&amp;M candidate</th><th>Linked scope</th><th><UserRound size={14} /> Owner / groups</th><th>IL2 mitigation date</th><th>Review state</th></tr></thead><tbody>{portfolioItems.map((item) => <PortfolioRow key={item.portfolio_poam_id} item={item} />)}</tbody></table></div> : registerMode === "workstreams" ? <div className="table-scroll"><table className="poam-table"><thead><tr><th>Issue workstream</th><th>Consolidated scope</th><th><UserRound size={14} /> Owner / groups</th><th>IL2 mitigation date</th><th>Merge state</th></tr></thead><tbody>{visibleWorkstreams.map((workstream) => <WorkstreamRow key={workstream.workstream_id} workstream={workstream} />)}{visibleWorkstreams.length === 0 ? <tr><td colSpan={5} className="poam-empty">No issue workstreams match this filter.</td></tr> : null}</tbody></table></div> : <><div className="table-scroll"><table className="poam-table"><thead><tr><th>Candidate &amp; finding</th><th>Control / risk</th><th><UserRound size={14} /> Owner / group</th><th>IL2 mitigation date</th><th>Review state</th></tr></thead><tbody>{visibleCandidates.map((candidate) => <CandidateRow key={candidate.poam_candidate_id} candidate={candidate} />)}{candidates.length === 0 ? <tr><td colSpan={5} className="poam-empty">No candidate records match this filter.</td></tr> : null}</tbody></table></div>{candidateTotal > 0 ? <div className="poam-pagination"><span>{safePage * pageSize + 1}–{Math.min((safePage + 1) * pageSize, candidateTotal)} of {candidateTotal} candidates</span><div><button type="button" aria-label="Previous candidate page" onClick={() => setPage(Math.max(0, safePage - 1))} disabled={loading || safePage === 0}><ChevronLeft size={16} /></button><span>Page {safePage + 1} of {pageCount}</span><button type="button" aria-label="Next candidate page" onClick={() => setPage(Math.min(pageCount - 1, safePage + 1))} disabled={loading || safePage >= pageCount - 1}><ChevronRight size={16} /></button></div></div> : null}</>}</Card>
      <Card className="poam-wave-card"><div className="card-heading"><div><p className="eyebrow">Group-level milestone deliverables</p><h2>October, December, and March delivery waves</h2><p className="coverage-intro">Each service category keeps its own Team Tracker IL2 commitment. Wave targets organize delivery; they do not replace the group date or establish module validation.</p></div><DisclosureInfo label="ETA inheritance" text="Service records and libraries inherit planning context from their mapped service group. The POA&M mitigation date remains the farthest explicit linked IL2 date; relative phrases are not converted." /></div><div className="poam-wave-grid">{(assessment.portfolio_delivery_waves ?? []).filter((wave) => wave.wave !== "uncommitted").map((wave) => <section key={wave.wave}><span className="eyebrow">{wave.label}</span><strong>{wave.service_group_count} service categor{wave.service_group_count === 1 ? "y" : "ies"}</strong><div>{wave.service_groups.map((group) => <a key={group.service_group} href={`/accountability?group=${encodeURIComponent(group.service_group)}`}><span>{serviceGroupDisplayName(group.service_group)}</span><small>{group.farthest_explicit_il2_date ? <DateOrGap date={group.farthest_explicit_il2_date} /> : group.raw_il2_values.join(" / ") || "Not supplied"}</small></a>)}</div></section>)}</div></Card>
      <CoverageGapRegister rows={coverageGaps} filter={filter} />
      <motion.section className="poam-kpis" aria-label="Assessment summary" initial={{ opacity: 0, y: reducedMotion ? 0 : 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: reducedMotion ? 0 : .22 }}><Card><ListTree size={20} /><div><span>Issue workstreams</span><strong>{workstreams.length}</strong></div></Card><Card><ClipboardCheck size={20} /><div><span>Asset candidates</span><strong>{assessment.summary.deduplicated_poam_candidates}</strong></div></Card><Card><FileWarning size={20} /><div><span>Evidence gaps</span><strong>{assessment.summary.needs_review_findings}</strong></div></Card><Card><CalendarClock size={20} /><div><span>Coverage requests</span><strong>{coverageGaps.length}</strong></div></Card></motion.section>
    </> : null}

    {milestones?.data ? <Card className="poam-milestone-card"><details><summary><span><span className="eyebrow">Team Tracker planning data</span><strong>Owner, lead, IL2, and IL5 milestone register</strong></span><span className="poam-summary-actions"><DisclosureInfo label="Milestone date rules" text="Planning metadata only. Relative phrases are ignored; only explicit IL2 dates can become candidate mitigation dates." /><Badge tone="info">{milestones.data.all_tracker_rows.length} tracker rows</Badge></span></summary><div className="poam-milestone-scroll"><table><thead><tr><th>Team</th><th>Mapped service groups</th><th>Owner</th><th>Lead</th><th>IL2</th><th>IL5</th></tr></thead><tbody>{milestones.data.all_tracker_rows.map((row) => <tr key={row.team}><td><strong>{row.team}</strong></td><td>{row.mapped_service_groups?.join(", ") || <span className="poam-missing">Unmapped</span>}</td><td>{row.owner || <span className="poam-missing">Not supplied</span>}</td><td>{row.lead || <span className="poam-missing">Not supplied</span>}</td><td>{milestoneText(row.il2)}</td><td>{milestoneText(row.il5)}</td></tr>)}</tbody></table></div></details></Card> : null}
  </div></ConsoleShell>;
}
