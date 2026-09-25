"use client";

import { useEffect, useId, useMemo, useState, type CSSProperties } from "react";
import { motion, useReducedMotion } from "motion/react";
import { CalendarClock, ChevronDown, ChevronLeft, ChevronRight, ClipboardCheck, Download, ExternalLink, FileWarning, FlaskConical, KeyRound, Layers3, ListTree, RefreshCw, ShieldCheck, Tags, UserRound } from "lucide-react";
import { ConsoleShell, DisclosureInfo } from "@/app/components/console-shell";
import { Badge } from "@/app/components/ui/badge";
import { Card } from "@/app/components/ui/card";
import { getPoamAssessment, getTeamMilestones, type CoverageGap, type PoamCandidate, type PoamWorkstream, type PortfolioPoam, type ServiceScopeLink, type TargetModuleRecord, type TeamMilestoneProfile, type TrackerMilestone } from "@/app/lib/team-milestones";
import { getServiceGroupRegister } from "@/components/accountability/accountability-data";
import { ServiceGroupDrawer } from "@/components/accountability/service-accountability";
import type { ServiceGroupRegisterRow } from "@/components/accountability/types";
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

type MigrationGroup = {
  profile: TeamMilestoneProfile;
  register?: ServiceGroupRegisterRow;
  modules: TargetModuleRecord[];
  vendors: string[];
  laneReason?: string;
};

const DNSCRYPT_DESIGN_REVIEW = {
  candidateId: "FIPS3-DNSCRYPT-KDF-CANDIDATE",
  sourceTitle: "DNSCrypt ES3 to ES4: Key Derivation and the FIPS 140-3 Gap",
  sourceSha256: "f1f1545ffea1fd074f0428e6d4cbfab414f013cf71a345237e16062d8c631c34",
};

function moduleVendor(module: TargetModuleRecord) {
  const value = `${module.target_module ?? ""} ${module.current_module ?? ""}`;
  if (/bouncy\s*castle|bc-fja/i.test(value)) return "Bouncy Castle";
  if (/cisco(?:ssl)?/i.test(value)) return "Cisco";
  if (/hashicorp/i.test(value)) return "HashiCorp";
  if (/openssl/i.test(value)) return "OpenSSL";
  if (/aws-lc|amazon/i.test(value)) return "Amazon Web Services";
  if (/gofips|go cryptographic|boringcrypto/i.test(value)) return "Go cryptographic module provider";
  return "Provider not identified";
}

function riskBucket(value: string | null | undefined) {
  const normalized = (value ?? "").trim().toLocaleLowerCase();
  if (normalized === "critical" || normalized === "high") return "critical";
  if (normalized === "moderate" || normalized === "medium") return "moderate";
  return "other";
}

function hasMigrationCardData({ profile, register, modules }: MigrationGroup) {
  return Boolean(
    (register?.documents ?? 0) > 0 ||
    register?.risk_category ||
    profile.owners.length ||
    profile.leads.length ||
    profile.delivery_wave.farthest_explicit_il2_date ||
    profile.delivery_wave.raw_il2_values.length ||
    modules.some((module) => module.current_module || module.target_module || module.asserted_status || module.current_cmvp_cert || module.target_cmvp_cert)
  );
}

function MigrationLane({ title, eyebrow, groups, maxServices, onSelect }: { title: string; eyebrow: string; groups: MigrationGroup[]; maxServices: number; onSelect: (row: ServiceGroupRegisterRow) => void }) {
  if (groups.length === 0) return null;
  const criticalDocuments = groups.filter(({ register }) => riskBucket(register?.risk_category) === "critical").reduce((sum, { register }) => sum + (register?.documents ?? 0), 0);
  const moderateDocuments = groups.filter(({ register }) => riskBucket(register?.risk_category) === "moderate").reduce((sum, { register }) => sum + (register?.documents ?? 0), 0);
  return <section className="poam-migration-lane">
    <header><div><span className="eyebrow">{eyebrow}</span><h3>{title}</h3></div><div className="poam-risk-counts"><span className="critical">{criticalDocuments} critical/high documents</span><span className="moderate">{moderateDocuments} moderate documents</span></div></header>
    <div className="poam-migration-groups">{groups.map(({ profile, register, modules, vendors, laneReason }) => {
      const documents = register?.documents ?? 0;
      const share = maxServices ? Math.max(8, Math.round((documents / maxServices) * 100)) : 8;
      const risk = riskBucket(register?.risk_category);
      return <button type="button" key={profile.service_group} className={cn("poam-migration-group", `risk-${risk}`)} style={{ "--service-share": `${share}%` } as CSSProperties} onClick={() => register && onSelect(register)} disabled={!register} aria-label={`Open ${register?.display_name || serviceGroupDisplayName(profile.service_group)} details`}>
        <span className="poam-migration-name"><strong>{serviceGroupDisplayName(profile.service_group)}</strong><small>{profile.owners.join(" / ") || "Owner not supplied"}</small></span>
        <span className="poam-migration-metrics"><b>{documents}</b><small>document record{documents === 1 ? "" : "s"}</small></span>
        <span className="poam-migration-risk"><Badge tone={risk === "critical" ? "danger" : risk === "moderate" ? "warning" : "neutral"}>{register?.risk_category || "Risk not supplied"}</Badge><small>{profile.delivery_wave.farthest_explicit_il2_date ? <DateOrGap date={profile.delivery_wave.farthest_explicit_il2_date} /> : profile.delivery_wave.raw_il2_values.join(" / ") || "Date not supplied"}</small></span>
        <span className="poam-migration-module"><small>{modules.map((module) => module.target_module || module.current_module || "Module not supplied").filter((value, index, values) => values.indexOf(value) === index).join(" · ")}</small>{vendors.length ? <em>Vendor: {vendors.join(" / ")}</em> : null}{laneReason ? <em>Reason: {laneReason}</em> : null}</span>
      </button>;
    })}</div>
  </section>;
}

function MigrationPlanView({ groups, dnsGroup, filter, onSelect }: { groups: MigrationGroup[]; dnsGroup?: MigrationGroup; filter: string; onSelect: (row: ServiceGroupRegisterRow) => void }) {
  const normalizedFilter = filter.trim().toLocaleLowerCase();
  const visible = groups.filter(({ profile, register, modules, vendors }) => [profile.service_group, profile.service_group.replaceAll(/[-_]/g, " "), serviceGroupDisplayName(profile.service_group), register?.display_name, ...profile.owners, ...profile.leads, register?.risk_category, register?.comments, ...vendors, ...modules.flatMap((module) => [module.current_module, module.target_module, module.asserted_status])].filter(Boolean).join(" ").toLocaleLowerCase().includes(normalizedFilter));
  const active = visible.filter(({ modules }) => modules.some((module) => module.target_disposition === "active_certificate"));
  const activeGroups = new Set(active.map(({ profile }) => profile.service_group));
  const pipeline = visible.filter(({ profile, modules }) => !activeGroups.has(profile.service_group) && modules.some((module) => module.target_disposition === "cmvp_in_process"));
  const marchOrBeyond = active.filter(({ profile }) => profile.delivery_wave.wave === "march_2027" || Boolean(profile.delivery_wave.farthest_explicit_il2_date && profile.delivery_wave.farthest_explicit_il2_date > "2027-03-31"));
  const unresolvedActive = active.filter(({ profile }) => profile.delivery_wave.wave === "uncommitted" && !marchOrBeyond.some(({ profile: row }) => row.service_group === profile.service_group));
  const classifiedPipeline = pipeline.map((group) => {
    const modules = group.modules.filter((module) => module.target_disposition === "cmvp_in_process");
    const vendors = Array.from(new Set(modules.map(moduleVendor)));
    return { ...group, modules, vendors };
  });
  const vendorDependencies = classifiedPipeline.filter(({ vendors }) => vendors.some((vendor) => vendor !== "Provider not identified"));
  const assignedGroups = new Set([...activeGroups, ...pipeline.map(({ profile }) => profile.service_group)]);
  const unassigned = visible.filter(({ profile }) => !assignedGroups.has(profile.service_group) && profile.service_group !== dnsGroup?.profile.service_group).map((group) => ({
    ...group,
    laneReason: Array.from(new Set(group.modules.map((module) => module.disposition_basis).filter(Boolean))).join(" ") || "No supported active-certificate or CMVP pipeline disposition is supplied.",
  }));
  const maxServices = Math.max(1, ...visible.map(({ register }) => register?.documents ?? 0));
  const laneProps = { maxServices };
  return <div className="poam-migration-view">
    <div className="poam-migration-note"><Layers3 size={18} /><p><strong>Planning view — mutually exclusive service groups.</strong> A group with an active-certificate target is assigned to its IL2 delivery lane first. Remaining pending-certification groups are assigned to named-vendor dependency, while unsupported or incomplete dispositions stay visible with their exclusion reason. Risk labels are user-approved planning assertions, not assessor determinations.</p></div>
    <div className="poam-migration-grid">
      <MigrationLane {...laneProps} onSelect={onSelect} eyebrow="Active module" title="October deliverable" groups={active.filter(({ profile }) => profile.delivery_wave.wave === "october_2026")} />
      <MigrationLane {...laneProps} onSelect={onSelect} eyebrow="Active module" title="December deliverable" groups={active.filter(({ profile }) => profile.delivery_wave.wave === "december_2026")} />
      <MigrationLane {...laneProps} onSelect={onSelect} eyebrow="Active module" title="March or beyond deliverable" groups={marchOrBeyond} />
      <MigrationLane {...laneProps} onSelect={onSelect} eyebrow="Active module" title="Completed / date unresolved" groups={unresolvedActive} />
      <MigrationLane {...laneProps} onSelect={onSelect} eyebrow="External dependency" title="In-Test / In-Progress vendor dependency" groups={vendorDependencies} />
      <MigrationLane {...laneProps} onSelect={onSelect} eyebrow="Planning gap" title="Not assigned to a migration lane" groups={unassigned} />
    </div>
    {dnsGroup && [dnsGroup.profile.service_group, dnsGroup.profile.service_group.replaceAll(/[-_]/g, " "), serviceGroupDisplayName(dnsGroup.profile.service_group), dnsGroup.register?.display_name, ...dnsGroup.profile.owners, DNSCRYPT_DESIGN_REVIEW.sourceTitle].join(" ").toLocaleLowerCase().includes(normalizedFilter) ? <section className="poam-dnscrypt-card">
      <div className="poam-dnscrypt-heading"><KeyRound size={21} /><div><span className="eyebrow">DNSCrypt key derivation function POA&amp;M</span><h3>Replace raw ES3 ECDH key use with reviewed ES4 KDF construction</h3></div><Badge tone="warning">Candidate · review required</Badge></div>
      <div className="poam-dnscrypt-grid"><div><small>Candidate / control</small><strong className="mono">{DNSCRYPT_DESIGN_REVIEW.candidateId}</strong><span>SC-13 · proposed risk not assessed</span></div><div><small>Planning scope</small><strong>DNS Platform · {dnsGroup.register?.documents ?? 0} document record{dnsGroup.register?.documents === 1 ? "" : "s"}</strong><span>{dnsGroup.register?.risk_category || "Group risk not supplied"} service-impact context · owner {dnsGroup.profile.owners.join(" / ") || "not supplied"}</span></div><div><small>Target date</small><strong>{dnsGroup.profile.delivery_wave.farthest_explicit_il2_date ? <DateOrGap date={dnsGroup.profile.delivery_wave.farthest_explicit_il2_date} /> : "Not supplied"}</strong><span>Group IL2 planning metadata only</span></div></div>
      <div className="poam-dnscrypt-detail"><div><h4>Candidate condition</h4><p>The supplied design review states that ES3 passes the raw P-256 ECDH output directly to AES-256-GCM and reuses one key in both directions. ES4 is described as work-in-progress, so implementation and deployment remain unverified.</p></div><div><h4>Proposed remediation</h4><p>Implement the reviewed HKDF-SHA-256 Extract/Expand design, bind context to protocol/version and both public keys, and use separate client-to-resolver, resolver-to-client, and padding keys.</p></div><div><h4>Acceptance evidence</h4><ul><li>Merged implementation and tests for both peers</li><li>Approved-mode/provider evidence inside the validated boundary</li><li>Deployment-to-module/version/certificate correlation</li><li>Authorized assessor and AO review</li></ul></div></div>
      <footer><span>{DNSCRYPT_DESIGN_REVIEW.sourceTitle}</span><span className="mono">Source SHA-256: {DNSCRYPT_DESIGN_REVIEW.sourceSha256}</span><span>User-supplied design evidence; raw PDF is not committed to Git or catalog-ingested.</span></footer>
    </section> : null}
  </div>;
}

function milestoneText(milestone: TrackerMilestone) {
  if (milestone.status === "done") return <Badge tone="success">DONE</Badge>;
  if (milestone.status === "vendor_dependency") return <Badge tone="warning">VENDOR DEPENDENCY</Badge>;
  if (milestone.status === "not_applicable") return <Badge tone="neutral">NA</Badge>;
  if (milestone.status === "not_supplied") return <span className="poam-missing">Not supplied</span>;
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

function dispositionLabel(value: string) {
  return value === "active_certificate" ? "Asserted active certificate target" :
    value === "cmvp_in_process" ? "CMVP in test / progress" :
      value.replaceAll("_", " ");
}

function targetDispositionTone(modules: TargetModuleRecord[], status: string): "success" | "warning" | "danger" | "neutral" {
  const states = modules.filter((module) => module.target_disposition === status).map((module) => module.verification?.overall?.state);
  if (states.some((state) => state === "contradicted" || state === "conflicting_evidence")) return "danger";
  if (states.some((state) => state === "partially_corroborated" || state === "not_observed")) return "warning";
  if (status === "cmvp_in_process") return "warning";
  if (status === "active_certificate" && states.length > 0 && states.every((state) => state === "corroborated")) return "success";
  return "neutral";
}

function verificationLabel(value: string | undefined) {
  return (value || "not_assessable").replaceAll("_", " ");
}

function verificationTone(value: string | undefined): "success" | "warning" | "danger" | "neutral" {
  if (value === "corroborated") return "success";
  if (value === "contradicted" || value === "conflicting_evidence") return "danger";
  if (value === "partially_corroborated" || value === "not_observed") return "warning";
  return "neutral";
}

function TargetModuleList({ modules }: { modules: NonNullable<PortfolioPoam["target_modules"]> }) {
  if (!modules.length) return <p className="poam-muted">No target-module mapping supports this dimension.</p>;
  return <div className="poam-target-modules">{modules.map((module, index) => <article key={module.record_sha256 || `${module.team}-${module.current_module}-${index}`}>
    <div><strong>{module.team || "Team not supplied"}</strong><Badge tone={targetDispositionTone([module], module.target_disposition)}>{dispositionLabel(module.target_disposition)}</Badge></div>
    <p><span>{module.current_module || "Current module not supplied"}{module.current_version ? ` @ ${module.current_version}` : ""}</span><b>→</b><span>{module.target_module || "Target module not supplied"}</span></p>
    <small>{module.target_cmvp_cert || module.current_cmvp_cert ? `Asserted certificate: ${module.target_cmvp_cert || module.current_cmvp_cert}` : "Certificate not supplied"} · {module.asserted_status || "Status not supplied"}</small>
    <small>{module.disposition_basis}</small>
    <div className="poam-verification-grid">
      <span><b>CBOM inventory</b><Badge tone={verificationTone(module.verification?.current_inventory_match?.state)}>{verificationLabel(module.verification?.current_inventory_match?.state)}</Badge></span>
      <span><b>Authority evidence</b><Badge tone={verificationTone(module.verification?.public_authority_alignment?.state)}>{verificationLabel(module.verification?.public_authority_alignment?.state)}</Badge></span>
      <span><b>Deployment</b><Badge tone="neutral">not assessable</Badge></span>
    </div>
    {module.evidence_summary?.evidence_count ? <a className="poam-evidence-link" href={`/api/v1/fips/target-modules/${module.record_sha256}/evidence`} target="_blank" rel="noreferrer">{module.evidence_summary.evidence_count} evidence record{module.evidence_summary.evidence_count === 1 ? "" : "s"}<ExternalLink size={12} /></a> : <small>No corroborating evidence record loaded</small>}
  </article>)}</div>;
}

function ScopeLinks({ links }: { links: ServiceScopeLink[] }) {
  if (!links.length) return <p className="poam-muted">No document-level scope links were resolved.</p>;
  return <div className="poam-scope-links">{links.map((link) => <article key={`${link.document_id}-${link.service_group_ref}-${link.subject_identity}`}>
    <div className="poam-scope-heading"><div><strong>{link.service_record_name}</strong><small>{serviceGroupLabel(link.service_group_ref)} · document {link.document_id}</small></div><a href={inventoryLink("services", link.service_record_name)}>Open service <ExternalLink size={13} /></a></div>
    <p className="mono poam-scope-subject">{link.subject_name}</p>
    <div className="poam-scope-meta"><span><b>Owner</b>{link.planning?.owners.join(" / ") || "Not supplied"}</span><span><b>Lead</b>{link.planning?.leads.join(" / ") || "Not supplied"}</span><span><b>Delivery wave</b>{link.planning?.delivery_wave.label || "Uncommitted"}</span><span><b>Group IL2</b><DateOrGap date={link.planning?.delivery_wave.farthest_explicit_il2_date} /></span></div>
    {link.libraries.length ? <div className="poam-library-links">{link.libraries.map((library, index) => <a key={`${library.component_identity}-${library.occurrence_id}-${index}`} href={inventoryLink("libraries", library.name)}><FlaskConical size={13} />{library.name}{library.version ? ` @ ${library.version}` : ""}</a>)}</div> : <span className="poam-missing">No component-level library link</span>}
    {link.planning?.target_modules?.length ? <details className="poam-scope-targets"><summary>{link.planning.target_modules.length} team target-module record{link.planning.target_modules.length === 1 ? "" : "s"}</summary><TargetModuleList modules={link.planning.target_modules} /></details> : null}
    <small className="poam-eta-note">{link.planning?.eta_inheritance || "ETA mapping not supplied"}</small>
  </article>)}</div>;
}

function PortfolioRow({ item }: { item: PortfolioPoam }) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const isActive = item.dimension === "active_certificate_migration";
  return <>
    <tr>
      <td><button type="button" className="poam-expand" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls={detailId}><ChevronDown size={17} className={cn(open && "poam-chevron-open")} /><span className="mono">{item.portfolio_poam_id}</span></button><strong>{item.title}</strong><small>{isActive ? "Active-certificate migration dimension" : "CMVP pipeline dependency dimension"}</small></td>
      <td><strong>{item.linked_candidate_count} linked asset candidate{item.linked_candidate_count === 1 ? "" : "s"}</strong><small>{item.affected_service_record_count} service records · {item.affected_library_count} libraries · {item.target_module_count ?? 0} target modules</small></td>
      <td><span>{item.responsible_owners.join(" / ") || "Not supplied"}</span><small>{item.affected_service_groups.map(serviceGroupLabel).join(", ") || "No defensible mapping yet"}</small></td>
      <td><DateOrGap date={item.scheduled_completion_date} /><small>Farthest explicit linked-group IL2</small></td>
      <td><Badge tone="warning">Assessor merge review</Badge><small>Review dimension; candidates may appear in both rows</small></td>
    </tr>
    {open ? <tr className="poam-detail-row" id={detailId}><td colSpan={5}><div className="poam-portfolio-detail"><div className="poam-portfolio-summary"><div><p className="eyebrow">Candidate condition</p><p>{item.condition}</p></div><div><p className="eyebrow">Merge confirmation gates</p><ul className="coverage-evidence-list">{item.merge_blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul></div></div><details className="poam-secondary-detail"><summary>Planning milestones and target-module basis</summary><div className="poam-wave-list">{item.milestone_deliverables.filter((wave) => wave.wave !== "uncommitted").map((wave) => <span key={wave.wave}><strong>{wave.label}</strong>{wave.service_groups.map((group) => serviceGroupDisplayName(group.service_group)).join(", ") || "No linked groups"}</span>)}</div><TargetModuleList modules={item.target_modules ?? []} />{item.target_module_source?.source_file_sha256 ? <small className="mono poam-source-hash">Source SHA-256: {item.target_module_source.source_file_sha256}</small> : null}</details><ScopeLinks links={item.service_scope_links} /></div></td></tr> : null}
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
  const detailId = useId();
  const trackerRows = candidate.team_tracker_milestones?.group_milestones.flatMap((group) => group.tracker_rows) ?? [];
  return <>
    <tr>
      <td><button type="button" className="poam-expand" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls={detailId}><ChevronDown size={17} className={cn(open && "poam-chevron-open")} /><span className="mono">{candidate.poam_candidate_id}</span></button><strong>{candidate.title}</strong><small>{candidate.linked_finding_count} linked candidate finding{candidate.linked_finding_count === 1 ? "" : "s"}</small></td>
      <td><Badge tone="neutral">{candidate.control_id}</Badge><span className="poam-risk">{candidate.proposed_risk}</span></td>
      <td><span>{candidate.responsible_owner}</span><small>{candidate.affected_services.map(serviceGroupLabel).join(", ")}</small></td>
      <td><DateOrGap date={candidate.milestone_mitigation_date ?? candidate.scheduled_completion_date} /><small>Latest explicit linked IL2 date</small></td>
      <td><Badge tone="warning">Draft candidate</Badge></td>
    </tr>
    {open ? <tr className="poam-detail-row" id={detailId}><td colSpan={5}><div className="poam-portfolio-detail"><div className="poam-detail-grid"><div><p className="eyebrow">Proposed remediation</p><p>{candidate.remediation_plan}</p></div><div><p className="eyebrow">Evidence integrity</p><p>{candidate.evidence_sha256.length} evidence checksum{candidate.evidence_sha256.length === 1 ? "" : "s"} · {candidate.source_sha256.length} source checksum{candidate.source_sha256.length === 1 ? "" : "s"}</p></div></div><details className="poam-secondary-detail"><summary>Tracker planning context</summary>{trackerRows.length ? <div className="poam-milestone-list">{trackerRows.map((row, index) => <div key={`${row.team}-${index}`}><strong>{row.team}</strong><span>Owner: {row.owner || "Not supplied"}</span><span>Lead: {row.lead || "Not supplied"}</span><span>IL2: {milestoneText(row.il2)}</span><span>IL5: {milestoneText(row.il5)}</span><span>CMVP: {row.cmvp_mapping || "Not determined"}</span></div>)}</div> : <p className="poam-muted">Team planning data not supplied.</p>}</details><div><p className="eyebrow">Linked services, groups, and libraries</p><ScopeLinks links={candidate.service_scope_links ?? []} /></div></div></td></tr> : null}
  </>;
}

function WorkstreamRow({ workstream }: { workstream: PoamWorkstream }) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  return <>
    <tr>
      <td><button type="button" className="poam-expand" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls={detailId}><ChevronDown size={17} className={cn(open && "poam-chevron-open")} /><span className="mono">{workstream.workstream_id}</span></button><strong>{workstream.title}</strong><small>{workstream.issue_codes.join(", ")}</small></td>
      <td><strong>{workstream.candidate_count} asset candidate{workstream.candidate_count === 1 ? "" : "s"}</strong><small>{workstream.subject_count} distinct subject{workstream.subject_count === 1 ? "" : "s"} · {workstream.affected_service_count} service group{workstream.affected_service_count === 1 ? "" : "s"}</small></td>
      <td><span>{workstream.responsible_owner}</span><small>{workstream.affected_services.map(serviceGroupLabel).join(", ")}</small></td>
      <td><DateOrGap date={workstream.milestone_mitigation_date} /><small>Explicit IL2 date; clusters split when dates differ</small></td>
      <td><Badge tone="warning">Merge review required</Badge><small>Impact not assessed</small></td>
    </tr>
    {open ? <tr className="poam-detail-row" id={detailId}><td colSpan={5}><div className="poam-detail-grid"><div><p className="eyebrow">Shared remediation</p><p>{workstream.remediation_plan}</p><div className="poam-tag-list">{workstream.tags.map((tag) => <span key={tag}>{tag}</span>)}</div></div><div><p className="eyebrow">Merge confirmation gates</p><ul className="coverage-evidence-list">{workstream.merge_blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul></div><div><p className="eyebrow">Traceability retained</p><p>{workstream.candidate_count} linked asset candidates remain independently addressable. This workstream does not delete or close them.</p></div></div></td></tr> : null}
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
  const [registerRows, setRegisterRows] = useState<ServiceGroupRegisterRow[]>([]);
  const [selectedService, setSelectedService] = useState<ServiceGroupRegisterRow | null>(null);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState(() => typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("query") ?? "");
  const [registerMode, setRegisterMode] = useState<"migration" | "portfolio" | "workstreams" | "candidates">(() => {
    if (typeof window === "undefined") return "workstreams";
    const view = new URLSearchParams(window.location.search).get("view");
    return view === "migration" || view === "portfolio" || view === "candidates" || view === "workstreams" ? view : "workstreams";
  });
  const [page, setPage] = useState(() => {
    if (typeof window === "undefined") return 0;
    const raw = Number(new URLSearchParams(window.location.search).get("page"));
    return Number.isInteger(raw) && raw > 1 ? raw - 1 : 0;
  });
  const pageSize = 20;
  const reducedMotion = useReducedMotion();
  const loadRegister = async (signal?: AbortSignal) => {
    try {
      const result = await getServiceGroupRegister({ query: "", owner: "", lead: "", il2State: "", il5State: "", action: "", sort: "service_group", direction: "asc", page: 0, pageSize: 250, signal });
      setRegisterRows(result.items);
      setRegisterError(null);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setRegisterError(error instanceof Error ? error.message : "Accountability register is unavailable");
    }
  };
  const refresh = async () => { setLoading(true); const [assessmentResult, milestoneResult] = await Promise.all([getPoamAssessment({ page, pageSize, query: filter }), getTeamMilestones(), loadRegister()]); setData(assessmentResult); setMilestones(milestoneResult); setLoading(false); };
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
    void getServiceGroupRegister({ query: "", owner: "", lead: "", il2State: "", il5State: "", action: "", sort: "service_group", direction: "asc", page: 0, pageSize: 250, signal: controller.signal }).then((result) => {
      if (controller.signal.aborted) return;
      setRegisterRows(result.items);
      setRegisterError(null);
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setRegisterError(error instanceof Error ? error.message : "Accountability register is unavailable");
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
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    params.set("view", registerMode);
    if (filter) params.set("query", filter); else params.delete("query");
    if (page) params.set("page", String(page + 1)); else params.delete("page");
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, [filter, page, registerMode]);

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
  const migrationGroups = useMemo<MigrationGroup[]>(() => {
    const registerByGroup = new Map(registerRows.map((row) => [row.service_group, row]));
    return (milestones?.data?.groups ?? [])
      .filter((profile) => profile.target_modules?.length)
      .map((profile) => ({ profile, register: registerByGroup.get(profile.service_group), modules: profile.target_modules, vendors: [] }))
      .filter(hasMigrationCardData);
  }, [milestones, registerRows]);
  const dnsGroup = migrationGroups.find(({ profile }) => profile.service_group === "dns-platform");
  const migrationPlanCount = new Set(migrationGroups.map(({ profile }) => profile.service_group)).size;
  const candidates = assessment?.poam_items ?? [];
  const workstreams = assessment?.poam_workstreams ?? [];
  const portfolioItems = useMemo(
    () => assessment?.portfolio_poam_items ?? [],
    [assessment?.portfolio_poam_items],
  );
  const portfolioSummary = useMemo(() => {
    const appearances = new Map<string, number>();
    for (const item of portfolioItems) {
      for (const candidateId of item.linked_candidate_ids) {
        appearances.set(candidateId, (appearances.get(candidateId) ?? 0) + 1);
      }
    }
    return {
      uniqueLinked: appearances.size,
      overlapping: [...appearances.values()].filter((count) => count > 1).length,
      unclassified: Math.max(0, ...portfolioItems.map((item) => item.unclassified_candidate_count)),
    };
  }, [portfolioItems]);
  const normalizedFilter = filter.trim().toLocaleLowerCase();
  const visibleWorkstreams = workstreams.filter((workstream) => [workstream.workstream_id, workstream.title, workstream.responsible_owner, ...workstream.issue_codes, ...workstream.affected_services, ...workstream.tags].join(" ").toLocaleLowerCase().includes(normalizedFilter));
  const candidateTotal = assessment?.poam_page?.total ?? candidates.length;
  const pageCount = Math.max(1, Math.ceil(candidateTotal / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visibleCandidates = candidates;
  const assessmentUnavailable = !loading && data?.source === "unavailable";
  const milestoneUnavailable = !loading && milestones?.source === "unavailable";

  return <ConsoleShell><div className="page-container poam-page">
    <section className="page-heading"><div><p className="eyebrow">SC-13 remediation candidates</p><h1>POA&amp;M review queue</h1><p className="page-subtitle">Review the two overlapping portfolio migration dimensions, then trace every group milestone to its service records, libraries, and underlying asset evidence.</p></div><div className="heading-actions"><Badge tone={loading ? "neutral" : assessment ? "success" : "danger"}>{loading ? "Loading assessment" : assessment ? "Assessment loaded" : "Assessment unavailable"}</Badge>{assessment ? <><a className="secondary-button" href="/api/v1/fips/compliance-package.zip" download><Download size={17} />Candidate evidence ZIP</a><a className="secondary-button" href="/api/v1/fips/portfolio-poam.csv" download><Download size={17} />Draft portfolio CSV</a><a className="secondary-button" href="/api/v1/fips/poam.csv" download><Download size={17} />Candidate asset CSV</a></> : null}<button className="refresh-button" type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} />Refresh</button></div></section>

    {assessmentUnavailable ? <Card className="poam-unavailable" role="alert"><FileWarning size={21} /><div><h2>Live FIPS assessment is unavailable</h2><p>No sample POA&amp;M or milestone records are shown. Restore the catalog API, then refresh this page.</p><code>{data?.error}</code></div></Card> : null}
    {milestoneUnavailable ? <Card className="poam-unavailable poam-unavailable-compact" role="status"><CalendarClock size={19} /><div><strong>Team Tracker planning metadata is unavailable.</strong><p>Candidate and coverage records remain live, but owner, lead, IL2, and IL5 context cannot be displayed until the tracker endpoint recovers.</p></div></Card> : null}

    {assessment ? <>
      <Card className="poam-table-card"><div className="card-heading"><div><p className="eyebrow">Traceable remediation hierarchy</p><h2>{registerMode === "migration" ? "Module migration delivery view" : registerMode === "portfolio" ? "Overlapping portfolio review dimensions" : registerMode === "workstreams" ? "Issue clusters requiring merge review" : "Asset-level candidate evidence"}</h2><p className="coverage-intro">Start with issue clusters for consolidation gates and candidate evidence. Migration and portfolio views are planning context, not accepted POA&amp;Ms or module-validation evidence. {portfolioSummary.uniqueLinked} linked candidates are shown across {portfolioItems.length} overlapping dimensions.</p></div><div className="poam-card-actions"><DisclosureInfo label="Consolidation rules" text="Migration lanes assign each service group once. Portfolio rows remain overlapping candidate views, not accepted merges or disjoint totals. Active certificates still require exact deployment matching. In-Test/In-Progress modules remain open dependencies." /><label className="poam-filter"><span className="sr-only">Filter migration groups, workstreams, candidates, and coverage gaps</span><input value={filter} onChange={(event) => { setFilter(event.target.value); setPage(0); }} placeholder="Filter issue, group, owner…" /></label></div></div><div className="poam-register-tabs" role="group" aria-label="POA&M register view"><button type="button" aria-pressed={registerMode === "workstreams"} onClick={() => setRegisterMode("workstreams")}><ListTree size={16} />Review queue <span>{workstreams.length}</span></button><button type="button" aria-pressed={registerMode === "candidates"} onClick={() => setRegisterMode("candidates")}><Tags size={16} />Asset evidence <span>{candidateTotal}</span></button><button type="button" aria-pressed={registerMode === "migration"} onClick={() => setRegisterMode("migration")}><Layers3 size={16} />Migration plan <span>{migrationPlanCount}</span></button><button type="button" aria-pressed={registerMode === "portfolio"} onClick={() => setRegisterMode("portfolio")}><ShieldCheck size={16} />Portfolio dimensions <span>{portfolioItems.length}</span></button></div>{registerError && registerMode === "migration" ? <div className="poam-inline-warning" role="status">Risk and document counts are unavailable: {registerError}</div> : null}{registerMode === "migration" ? <MigrationPlanView groups={migrationGroups} dnsGroup={dnsGroup} filter={filter} onSelect={setSelectedService} /> : registerMode === "portfolio" ? <div className="table-scroll"><table className="poam-table"><thead><tr><th>Portfolio review dimension</th><th>Linked scope</th><th><UserRound size={14} /> Owner / groups</th><th>Latest linked IL2 date</th><th>Review state</th></tr></thead><tbody>{portfolioItems.map((item) => <PortfolioRow key={item.portfolio_poam_id} item={item} />)}{portfolioItems.length === 0 ? <tr><td colSpan={5} className="poam-empty">No portfolio review dimensions match this filter.</td></tr> : null}</tbody></table></div> : registerMode === "workstreams" ? <div className="table-scroll"><table className="poam-table"><thead><tr><th>Issue workstream</th><th>Consolidated scope</th><th><UserRound size={14} /> Owner / groups</th><th>Latest linked IL2 date</th><th>Merge state</th></tr></thead><tbody>{visibleWorkstreams.map((workstream) => <WorkstreamRow key={workstream.workstream_id} workstream={workstream} />)}{visibleWorkstreams.length === 0 ? <tr><td colSpan={5} className="poam-empty">No issue workstreams match this filter.</td></tr> : null}</tbody></table></div> : <><div className="table-scroll"><table className="poam-table"><thead><tr><th>Candidate &amp; finding</th><th>Control / proposed risk</th><th><UserRound size={14} /> Owner / group</th><th>Latest linked IL2 date</th><th>Review state</th></tr></thead><tbody>{visibleCandidates.map((candidate) => <CandidateRow key={candidate.poam_candidate_id} candidate={candidate} />)}{candidates.length === 0 ? <tr><td colSpan={5} className="poam-empty">No candidate records match this filter.</td></tr> : null}</tbody></table></div>{candidateTotal > 0 ? <div className="poam-pagination"><span>{safePage * pageSize + 1}–{Math.min((safePage + 1) * pageSize, candidateTotal)} of {candidateTotal} candidates</span><div><button type="button" aria-label="Previous candidate page" onClick={() => setPage(Math.max(0, safePage - 1))} disabled={loading || safePage === 0}><ChevronLeft size={16} /></button><span>Page {safePage + 1} of {pageCount}</span><button type="button" aria-label="Next candidate page" onClick={() => setPage(Math.min(pageCount - 1, safePage + 1))} disabled={loading || safePage >= pageCount - 1}><ChevronRight size={16} /></button></div></div> : null}</>}</Card>
      <Card className="poam-wave-card"><div className="card-heading"><div><p className="eyebrow">Group-level milestone deliverables</p><h2>October, December, and March delivery waves</h2><p className="coverage-intro">Each service category keeps its own Team Tracker IL2 commitment. Wave targets organize delivery; they do not replace the group date or establish module validation.</p></div><DisclosureInfo label="ETA inheritance" text="Service records and libraries inherit planning context from their mapped service group. The POA&M mitigation date remains the farthest explicit linked IL2 date; relative phrases are not converted." /></div><div className="poam-wave-grid">{(assessment.portfolio_delivery_waves ?? []).filter((wave) => wave.wave !== "uncommitted").map((wave) => <section key={wave.wave}><span className="eyebrow">{wave.label}</span><strong>{wave.service_group_count} service categor{wave.service_group_count === 1 ? "y" : "ies"}</strong><div>{wave.service_groups.map((group) => <a key={group.service_group} href={`/accountability?group=${encodeURIComponent(group.service_group)}`}><span>{serviceGroupDisplayName(group.service_group)}</span><small>{group.farthest_explicit_il2_date ? <DateOrGap date={group.farthest_explicit_il2_date} /> : group.raw_il2_values.join(" / ") || "Not supplied"}</small></a>)}</div></section>)}</div></Card>
      <CoverageGapRegister rows={coverageGaps} filter={filter} />
      <motion.section className="poam-kpis" aria-label="Assessment summary" initial={{ opacity: 0, y: reducedMotion ? 0 : 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: reducedMotion ? 0 : .22 }}><Card><ListTree size={20} /><div><span>Issue workstreams</span><strong>{workstreams.length}</strong></div></Card><Card><ClipboardCheck size={20} /><div><span>Asset candidates</span><strong>{assessment.summary.deduplicated_poam_candidates}</strong></div></Card><Card><FileWarning size={20} /><div><span>Review-only findings</span><strong>{assessment.summary.needs_review_findings}</strong></div></Card><Card><CalendarClock size={20} /><div><span>Coverage requests</span><strong>{coverageGaps.length}</strong></div></Card></motion.section>
    </> : null}

    {milestones?.data ? <Card className="poam-milestone-card"><details><summary><span><span className="eyebrow">Team target-module planning data</span><strong>Owner, lead, target state, IL2, and IL5 milestone register</strong></span><span className="poam-summary-actions"><DisclosureInfo label="Milestone and module rules" text="Planning metadata only. Relative phrases are ignored; only explicit IL2 dates can become candidate mitigation dates. Asserted status and certificate values still require exact deployment correlation." /><Badge tone="info">{milestones.data.all_tracker_rows.length} tracker rows</Badge></span></summary><div className="poam-milestone-scroll"><table><thead><tr><th>Team</th><th>Mapped service groups</th><th>Owner</th><th>Lead</th><th>Target state</th><th>IL2</th><th>IL5</th></tr></thead><tbody>{milestones.data.all_tracker_rows.map((row) => <tr key={row.team}><td><strong>{row.team}</strong></td><td>{row.mapped_service_groups?.join(", ") || <span className="poam-missing">Unmapped</span>}</td><td>{row.owner || <span className="poam-missing">Not supplied</span>}</td><td>{row.lead || <span className="poam-missing">Not supplied</span>}</td><td>{row.target_modules?.length ? <div className="poam-target-state">{Array.from(new Set(row.target_modules.map((module) => module.target_disposition))).map((status) => <Badge key={status} tone={targetDispositionTone(row.target_modules ?? [], status)}>{dispositionLabel(status)}</Badge>)}</div> : <span className="poam-missing">Not determined</span>}</td><td>{milestoneText(row.il2)}</td><td>{milestoneText(row.il5)}</td></tr>)}</tbody></table></div></details></Card> : null}
    {selectedService ? <ServiceGroupDrawer row={selectedService} onClose={() => setSelectedService(null)} /> : null}
  </div></ConsoleShell>;
}
