"use client";

import { useEffect, useId, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { motion, useReducedMotion } from "motion/react";
import { CalendarClock, ChevronDown, ChevronLeft, ChevronRight, ClipboardCheck, Download, ExternalLink, FileWarning, FlaskConical, Layers3, ListTree, RefreshCw, ShieldCheck, Tags, UserRound } from "lucide-react";
import { DisclosureInfo, useConsoleAccess } from "@/app/components/console-shell";
import { Badge } from "@/app/components/ui/badge";
import { Card } from "@/app/components/ui/card";
import { StatusBanner } from "@/app/components/ui/status-banner";
import { getPoamAssessment, getTeamMilestones, hasCatalogPlanningOverlay, planningDispositionBasis, planningTargetCertificate, planningTargetDisposition, planningTargetModule, planningTargetVersion, type AnalystObservation, type CoverageGap, type PoamAssessment, type PoamCandidate, type PoamWorkstream, type PortfolioPoam, type ServiceScopeLink, type TargetModuleRecord, type TeamMilestoneProfile, type TeamMilestones, type TrackerMilestone } from "@/app/lib/team-milestones";
import { ServiceGroupDrawer } from "@/components/accountability/service-group-drawer";
import { getServiceGroupRegister } from "@/components/accountability/accountability-data";
import { AssignedServiceUnion } from "@/components/access/assigned-service-union";
import type { ServiceGroupRegisterRow } from "@/components/accountability/types";
import { cn, serviceGroupDisplayName, serviceGroupFromReference } from "@/app/lib/utils";
import { scopeQuery, type AssignedScopePair } from "@/app/lib/scope";
import { accessModeHeaders, fetchJson } from "@/app/lib/http";
import { milestoneRowDisplay } from "@/app/lib/milestone-display";
import { planningLaneKey, planningLaneLabel, planningLaneStats, type PlanningLaneKey } from "@/app/lib/poam-planning";
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

type PoamView = "legacy_poam" | "workstreams" | "candidates" | "migration" | "portfolio" | "evidence" | "milestones";

type MigrationGroup = {
  profile: TeamMilestoneProfile;
  register?: ServiceGroupRegisterRow;
  catalog?: CatalogPlanningRow;
  documentCount?: number;
  modules: TargetModuleRecord[];
  vendors: string[];
  laneReason?: string;
};

type CatalogPlanningRow = {
  service_key: string;
  source_collection: string;
  service_group: string;
  display_name: string;
  owner: string | null;
  lead: string | null;
  il2: { status: string | null; date: string | null };
  il5: { status: string | null; date: string | null };
  service_impact_risk: string | null;
  comments: string | null;
};

type SharedPlanningResponse = {
  scope: "portfolio-planning";
  source_collection: "sse-cboms";
  catalog: CatalogPlanningRow[];
  document_counts: Array<{ service_key: string; documents: number }>;
  milestones: TeamMilestones;
};

function moduleVendor(module: TargetModuleRecord) {
  const value = `${planningTargetModule(module) ?? ""} ${module.current_module ?? ""}`;
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

function hasMigrationCardData({ profile, register, catalog, documentCount, modules }: MigrationGroup) {
  return Boolean(
    catalog?.service_key ||
    (documentCount ?? register?.documents ?? 0) > 0 ||
    catalog?.service_impact_risk || register?.risk_category ||
    catalog?.owner || catalog?.lead || catalog?.il2.date || catalog?.il2.status ||
    profile.owners.length ||
    profile.leads.length ||
    profile.delivery_wave.farthest_explicit_il2_date ||
    profile.delivery_wave.raw_il2_values.length ||
    modules.some((module) => module.current_module || planningTargetModule(module) || module.asserted_status || module.current_cmvp_cert || planningTargetCertificate(module))
  );
}

function planningProfiles(milestones: TeamMilestones | null | undefined, catalogRows: CatalogPlanningRow[]): TeamMilestoneProfile[] {
  const profiles = new Map((milestones?.groups ?? []).map((profile) => [profile.service_group, profile]));
  for (const row of catalogRows) {
    if (row.source_collection !== "sse-cboms" || profiles.has(row.service_group)) continue;
    profiles.set(row.service_group, {
      service_group: row.service_group,
      mapping_status: "not_mapped",
      empty_service_category: true,
      owners: [], leads: [], target_modules: [], tracker_rows: [],
      delivery_wave: {
        wave: "uncommitted", label: "Uncommitted", target_date: null,
        farthest_explicit_il2_date: null, raw_il2_values: [],
      },
    });
  }
  return Array.from(profiles.values());
}

function MigrationLane({ title, eyebrow, groups, maxServices, onSelect }: { title: string; eyebrow: string; groups: MigrationGroup[]; maxServices: number; onSelect?: (row: ServiceGroupRegisterRow) => void }) {
  if (groups.length === 0) return null;
  const stats = planningLaneStats(groups.map(({ profile, register, catalog, documentCount }) => ({
    serviceKey: catalog?.service_key || register?.service_key || `sse-cboms/${profile.service_group}`,
    risk: catalog ? catalog.service_impact_risk : register?.risk_category,
    serviceRecords: documentCount ?? register?.documents ?? 0,
  })));
  const stat = (label: string, bucket: { groups: number; serviceRecords: number }, style: string) => <span className={style} key={label}><strong>{label}</strong> {bucket.groups} {bucket.groups === 1 ? "group" : "groups"} · {bucket.serviceRecords} catalog {bucket.serviceRecords === 1 ? "record" : "records"}</span>;
  return <section className="poam-migration-lane">
    <header><div><span className="eyebrow">{eyebrow}</span><h3>{title}</h3></div><div className="poam-risk-counts" aria-label="Service groups and linked catalog records by planned impact risk">{stat("Critical", stats.critical, "critical")}{stat("Moderate", stats.moderate, "moderate")}{stats.other.groups ? stat("Other / unset", stats.other, "other") : null}{stat("Total", stats.total, "total")}</div></header>
    <div className="poam-migration-groups">{groups.map(({ profile, register, catalog, documentCount, modules, vendors, laneReason }) => {
      const documents = documentCount ?? register?.documents ?? 0;
      const share = maxServices ? Math.max(8, Math.round((documents / maxServices) * 100)) : 8;
      const riskLabel = catalog ? catalog.service_impact_risk : register?.risk_category;
      const risk = riskBucket(riskLabel);
      const owner = catalog ? catalog.owner : profile.owners.join(" / ");
      const delivery = catalog ? catalog.il2 : null;
      const content = <>
        <span className="poam-migration-name"><strong>{catalog?.display_name || serviceGroupDisplayName(profile.service_group)}</strong><small>{owner || "Owner not supplied"}</small></span>
        <span className="poam-migration-metrics"><b>{documents}</b><small>document record{documents === 1 ? "" : "s"}</small></span>
        <span className="poam-migration-risk"><Badge tone="neutral">{riskLabel ? `Planned impact: ${riskLabel}` : "Planned impact not supplied"}</Badge><small>IL2 plan: {delivery ? delivery.date ? <DateOrGap date={delivery.date} /> : delivery.status?.replaceAll("_", " ") || "Not supplied" : profile.delivery_wave.farthest_explicit_il2_date ? <DateOrGap date={profile.delivery_wave.farthest_explicit_il2_date} /> : profile.delivery_wave.raw_il2_values.join(" / ") || "Date not supplied"}</small></span>
        <span className="poam-migration-module"><small>{modules.length ? modules.map((module) => planningTargetModule(module) || module.current_module || "Module not supplied").filter((value, index, values) => values.indexOf(value) === index).join(" · ") : "Module target not supplied"}</small>{vendors.length ? <em>Vendor: {vendors.join(" / ")}</em> : null}{laneReason ? <em>Reason: {laneReason}</em> : null}</span>
      </>;
      const className = cn("poam-migration-group", `risk-${risk}`);
      const style = { "--service-share": `${share}%` } as CSSProperties;
      return register && onSelect
        ? <button type="button" key={profile.service_group} className={className} style={style} onClick={() => onSelect(register)} aria-label={`Open ${register.display_name} details`}>{content}</button>
        : <div key={profile.service_group} className={className} style={style}>{content}</div>;
    })}</div>
  </section>;
}

function MigrationPlanView({ groups, filter, onSelect }: { groups: MigrationGroup[]; filter: string; onSelect?: (row: ServiceGroupRegisterRow) => void }) {
  if (!groups.length) return <div className="poam-inline-warning" role="status">No planning records match this view.</div>;
  const normalizedFilter = filter.trim().toLocaleLowerCase();
  const visible = groups.filter(({ profile, register, catalog, modules, vendors }) => [profile.service_group, profile.service_group.replaceAll(/[-_]/g, " "), catalog?.display_name, register?.display_name, catalog?.owner, catalog?.lead, ...profile.owners, ...profile.leads, catalog?.service_impact_risk, register?.risk_category, catalog?.comments, register?.comments, ...vendors, ...modules.flatMap((module) => [module.current_module, planningTargetModule(module), module.asserted_status])].filter(Boolean).join(" ").toLocaleLowerCase().includes(normalizedFilter));
  const lanes = new Map<PlanningLaneKey, MigrationGroup[]>();
  for (const group of visible) {
    const active = group.modules.some((module) => planningTargetDisposition(module) === "active_certificate");
    const modules = active ? group.modules.filter((module) => planningTargetDisposition(module) === "active_certificate") : group.modules.some((module) => planningTargetDisposition(module) === "cmvp_in_process") ? group.modules.filter((module) => planningTargetDisposition(module) === "cmvp_in_process") : group.modules;
    const vendors = Array.from(new Set(modules.map(moduleVendor)));
    const key = planningLaneKey({
      il2Status: group.catalog ? group.catalog.il2.status : (group.profile.delivery_wave.raw_il2_values[0] || ""),
      il2Date: group.catalog ? group.catalog.il2.date : group.profile.delivery_wave.farthest_explicit_il2_date,
      moduleDispositions: group.modules.map(planningTargetDisposition),
      namedPipelineVendor: vendors.some((vendor) => vendor !== "Provider not identified"),
    });
    const laneReason = key.startsWith("unclassified:") ? Array.from(new Set(group.modules.map(planningDispositionBasis).filter(Boolean))).join(" ") || "No supported active-certificate or CMVP pipeline disposition is supplied." : undefined;
    const rows = lanes.get(key) || [];
    rows.push({ ...group, modules, vendors, laneReason });
    lanes.set(key, rows);
  }
  const maxServices = Math.max(1, ...visible.map(({ register, documentCount }) => documentCount ?? register?.documents ?? 0));
  const laneOrder = (key: PlanningLaneKey) => key.startsWith("date:") ? `0:${key}` : `1:${key}`;
  return <div className="poam-migration-view">
    <div className="poam-migration-note"><Layers3 size={18} /><p><strong>Service Catalog planning, grouped once per service group.</strong> Approved IL2 plans determine the month for catalog target modules. Pipeline and unsupported targets remain separate. Each count pairs service groups with linked catalog document records; records are not unique deployed services. Planning values do not establish module validation or an assessor conclusion.</p></div>
    <div className="poam-migration-grid">
      {Array.from(lanes.entries()).sort(([left], [right]) => laneOrder(left).localeCompare(laneOrder(right))).map(([key, rows]) => <MigrationLane key={key} maxServices={maxServices} onSelect={onSelect} {...planningLaneLabel(key)} groups={rows} />)}
    </div>
  </div>;
}

function milestoneText(milestone: TrackerMilestone) {
  if (milestone.status === "done") return <Badge tone="neutral">Reported complete</Badge>;
  if (milestone.status === "vendor_dependency") return <Badge tone="warning">VENDOR DEPENDENCY</Badge>;
  if (milestone.status === "not_applicable") return <Badge tone="neutral">NA</Badge>;
  if (milestone.status === "not_supplied") return <span className="poam-missing">Not supplied</span>;
  if (milestone.status === "unparseable_or_relative") return <span className="poam-muted">Ignored — no explicit date</span>;
  return milestone.raw_value;
}

function DateOrGap({ date }: { date: string | null | undefined }) {
  return date ? <time dateTime={date}>{new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(`${date}T00:00:00`))}</time> : <span className="poam-missing">Not supplied</span>;
}

function asCoverageGap(observation: AnalystObservation): CoverageGap | null {
  const scope = observation.scope;
  if (!scope?.source_collection || !scope.service_groups?.length) return null;
  return {
    observation_id: observation.observation_id,
    output_type: "analyst_observation",
    assertion_state: observation.assertion_state === "not_assessable" ? "not_assessable" : "evidence_gap",
    poam_eligibility: false,
    title: observation.title,
    technical_observation: observation.technical_observation || "Review-only analyst observation.",
    scope: { source_collection: scope.source_collection, service_groups: scope.service_groups, ato_boundary: scope.ato_boundary ?? null },
    missing_required_facts: observation.missing_required_facts ?? [],
    evidence: observation.evidence ?? [],
    limitations: observation.limitations ?? [],
    review: { requires_authorized_assessor_review: true, requires_ao_review: true, requires_system_owner_attestation: true },
  };
}

function missingFactLabel(value: string) {
  const labels: Record<string, string> = {
    ato_boundary: "ATO boundary",
    source_collection: "source collection",
    service_groups: "service groups",
    accountable_owner: "accountable owner",
    assessment_as_of: "assessment as-of time",
    reporting_profile: "reporting profile",
    authority_register: "authority register",
    authority_freshness_review: "authority freshness review",
  };
  return labels[value] || value.replaceAll("_", " ");
}

function AssessmentProvenance({ assessment }: { assessment: NonNullable<Awaited<ReturnType<typeof getPoamAssessment>>["data"]> }) {
  const policy = assessment.policy;
  const scope = assessment.scope;
  const authorities = policy?.authoritative_sources ?? [];
  const run = assessment.assessment_run;
  const profile = assessment.assessment_contract?.reporting_profile || "No profile selected — not reportable";
  const serviceGroups = Array.isArray(scope?.service_group)
    ? scope.service_group.join(", ")
    : scope?.service_group;
  const scopeLabel = scope?.source_collection
    ? `${scope.source_collection}${serviceGroups ? ` / ${serviceGroups}` : " / selected service scope"}`
    : "Scope not supplied";
  const freshness = run?.authority_freshness_review ?? assessment.assessment_contract?.authority_freshness_review;
  const freshnessComplete = assessment.assessment_contract?.authority_freshness_state === "reviewed_for_assessment" && Boolean(freshness?.reviewed_at && freshness?.reviewed_by && freshness?.reference && freshness?.sha256);
  return <section className="assessment-provenance" aria-label="Assessment provenance">
    <div><span className="eyebrow">Assessment provenance</span><strong>{scopeLabel}</strong><small>Selected collection/group pair. Planning and deployment assertions without collection provenance are not shown.</small></div>
    <div><span>Authority register</span><strong>{run?.authority_register?.path || assessment.assessment_contract?.authority_register_path || "Not supplied"}</strong><small>{run?.authority_register?.sha256 || assessment.assessment_contract?.authority_register_sha256 || "checksum not supplied"} · retrieved {run?.authority_register?.retrieved_at || assessment.assessment_contract?.authority_retrieved_on || "not supplied"}</small></div>
    <div><span>Authority freshness review</span><strong>{freshnessComplete ? "Reviewed for this assessment" : "Incomplete — candidate output withheld"}</strong><small>{freshnessComplete ? `${freshness?.reviewed_at} · ${freshness?.reviewed_by} · ${freshness?.reference} · ${freshness?.sha256}` : "Review date, reviewer, immutable reference, and checksum are required."}</small></div>
    <div><span>Assessment as of</span><strong>{run?.assessment_as_of || policy?.assessment_as_of || "not supplied"}</strong><small>{policy?.assessment_timezone || "timezone not supplied"} · rules {policy?.policy_version || "not supplied"}</small></div>
    <div><span>Profile</span><strong>{profile}</strong><small>Export preview only until profile-specific validation is available.</small></div>
    <div className="assessment-run"><span>Assessment run</span><strong>{run?.assessment_run_id || "Not established"}</strong><small>{run ? assessment.assessment_contract?.fingerprint || "fingerprint not supplied" : "A schema-valid assessment run is required before candidate output."}</small></div>
    {assessment.assessment_run_id ? <div className="assessment-run"><span>Internal analysis ID</span><strong>{assessment.assessment_run_id}</strong><small>Execution correlation only; not an eligible assessment run manifest.</small></div> : null}
    {authorities.length ? <div className="assessment-authorities"><span>Authorities</span>{authorities.map((authority, index) => authority.url ? <a key={`${authority.url}-${index}`} href={authority.url} target="_blank" rel="noreferrer">{authority.title || "Source"} · retrieved {authority.retrieved_on || "not supplied"}</a> : <small key={`${authority.title}-${index}`}>{authority.title || "Source"} · retrieved {authority.retrieved_on || "not supplied"}</small>)}</div> : null}
  </section>;
}

function serviceGroupLabel(reference: string) {
  return serviceGroupFromReference(reference);
}

function inventoryLink(view: "services" | "libraries", query: string) {
  return `/inventory?view=${view}&query=${encodeURIComponent(query)}`;
}

function dispositionLabel(value: string) {
  return value === "active_certificate" ? "Certificate target" :
    value === "cmvp_in_process" ? "CMVP pipeline target" :
      value.replaceAll("_", " ");
}

function targetDispositionTone(modules: TargetModuleRecord[], status: string): "success" | "warning" | "danger" | "neutral" {
  const states = modules.filter((module) => planningTargetDisposition(module) === status).map((module) => module.verification?.overall?.state);
  if (states.some((state) => state === "contradicted" || state === "conflicting_evidence")) return "danger";
  if (states.some((state) => state === "partially_corroborated" || state === "not_observed")) return "warning";
  if (status === "cmvp_in_process") return "warning";
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

function planningVerificationTone(value: string | undefined): "warning" | "danger" | "neutral" {
  if (value === "contradicted" || value === "conflicting_evidence") return "danger";
  if (value === "partially_corroborated" || value === "not_observed") return "warning";
  return "neutral";
}

function TargetModuleList({ modules }: { modules: NonNullable<PortfolioPoam["target_modules"]> }) {
  if (!modules.length) return <p className="poam-muted">No target-module mapping supports this dimension.</p>;
  return <div className="poam-target-modules">{modules.map((module, index) => <article key={module.record_sha256 || `${module.team}-${module.current_module}-${index}`}>
    <div><strong>{module.team || "Team not supplied"}</strong><Badge tone={targetDispositionTone([module], planningTargetDisposition(module))}>{dispositionLabel(planningTargetDisposition(module))}</Badge></div>
    <p><span>{module.current_module || "Current module not supplied"}{module.current_version ? ` @ ${module.current_version}` : ""}</span><b>→</b><span>{planningTargetModule(module) || "Target module not supplied"}{planningTargetVersion(module) ? ` @ ${planningTargetVersion(module)}` : ""}</span></p>
    {hasCatalogPlanningOverlay(module) ? <small>Service Catalog plan{module.planning_origin === "catalog_only" ? " (no imported tracker record linked)" : ""}</small> : <small>Imported tracker assertion</small>}
    <small>{module.current_cmvp_cert ? `Imported current certificate reference: ${module.current_cmvp_cert}` : "Imported current certificate reference not supplied"} · {planningTargetCertificate(module) ? `Target public CMVP reference: ${planningTargetCertificate(module)}` : "Target public CMVP reference not supplied"} · {module.asserted_status || "Imported status not supplied"}</small>
    {hasCatalogPlanningOverlay(module) && (module.target_module !== planningTargetModule(module) || module.target_version !== planningTargetVersion(module) || module.target_cmvp_cert !== planningTargetCertificate(module)) ? <small>Imported target retained: {module.target_module || "not supplied"}{module.target_version ? ` @ ${module.target_version}` : ""}{module.target_cmvp_cert ? ` · ${module.target_cmvp_cert}` : ""}</small> : null}
    <small>{planningDispositionBasis(module)}</small>
    {module.public_module_suggestions?.map((suggestion, suggestionIndex) => <small key={`${suggestion.module_name}-${suggestion.module_version}-${suggestion.certificate_number}-${suggestionIndex}`}>Public module reference: {suggestion.module_name || "module not supplied"}{suggestion.module_version ? ` @ ${suggestion.module_version}` : ""}{suggestion.certificate_number ? ` · ${suggestion.certificate_number}` : ""}{suggestion.source_url ? <> · <a href={suggestion.source_url} target="_blank" rel="noreferrer">{suggestion.source_title || "source"}</a></> : null} · Suggestion only: {suggestion.suggestion_basis || "select and approve a Service Catalog plan before using this reference as planning metadata."}</small>)}
    <div className="poam-verification-grid">
      <span><b>Inventory corroboration</b><Badge tone={planningVerificationTone(module.verification?.current_inventory_match?.state)}>{verificationLabel(module.verification?.current_inventory_match?.state)}</Badge></span>
      <span><b>Public-source corroboration</b><Badge tone={planningVerificationTone(module.verification?.public_authority_alignment?.state)}>{hasCatalogPlanningOverlay(module) ? "catalog-linked planning evidence" : verificationLabel(module.verification?.public_authority_alignment?.state)}</Badge></span>
      <span><b>Deployment applicability</b><Badge tone="neutral">not assessable</Badge></span>
    </div>
    {module.evidence_summary?.evidence_count ? <small>{module.evidence_summary.evidence_count} evidence record{module.evidence_summary.evidence_count === 1 ? "" : "s"} retained; exact-pair evidence detail is not available.</small> : <small>No corroborating evidence record loaded</small>}
  </article>)}</div>;
}

function ScopeLinks({ links }: { links: ServiceScopeLink[] }) {
  if (!links.length) return <p className="poam-muted">No document-level scope links were resolved.</p>;
  return <div className="poam-scope-links">{links.map((link) => <article key={`${link.document_id}-${link.service_group_ref}-${link.subject_identity}`}>
    <div className="poam-scope-heading"><div><strong>{link.service_record_name}</strong><small>{serviceGroupLabel(link.service_group_ref)} · document {link.document_id}</small></div><small>Exact-pair inventory navigation is unavailable.</small></div>
    <p className="mono poam-scope-subject">{link.subject_name}</p>
    <div className="poam-scope-meta"><span><b>Owner</b>{link.planning?.owners.join(" / ") || "Not supplied"}</span><span><b>Lead</b>{link.planning?.leads.join(" / ") || "Not supplied"}</span><span><b>Delivery wave</b>{link.planning?.delivery_wave.label || "Uncommitted"}</span><span><b>Group IL2</b><DateOrGap date={link.planning?.delivery_wave.farthest_explicit_il2_date} /></span></div>
    {link.libraries.length ? <div className="poam-library-links">{link.libraries.map((library, index) => <span key={`${library.component_identity}-${library.occurrence_id}-${index}`}><FlaskConical size={13} />{library.name}{library.version ? ` @ ${library.version}` : ""}</span>)}</div> : <span className="poam-missing">No component-level library link</span>}
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
    <span><strong>Planning owner</strong>{profile.owners.join(" / ") || "Not supplied"}</span>
    <span><strong>Planning lead</strong>{profile.leads.join(" / ") || "Not supplied"}</span>
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
      <td><Badge tone="warning">Candidate</Badge><small>Authorized assessor, AO, and system-owner review required</small></td>
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

function CandidateCards({ candidates }: { candidates: PoamCandidate[] }) {
  return <div className="poam-record-cards">{candidates.map((candidate) => <article key={candidate.poam_candidate_id}><div><span className="eyebrow">Draft candidate</span><strong className="mono">{candidate.poam_candidate_id}</strong><p>{candidate.title}</p></div><div><span>Control / proposed risk</span><Badge tone="neutral">{candidate.control_id}</Badge><small>{candidate.proposed_risk}</small></div><div><span>Owner / scoped groups</span><strong>{candidate.responsible_owner}</strong><small>{candidate.affected_services.map(serviceGroupLabel).join(", ")}</small></div><div><span>Latest explicit linked IL2</span><strong><DateOrGap date={candidate.milestone_mitigation_date ?? candidate.scheduled_completion_date} /></strong><small>{candidate.linked_finding_count} linked candidate finding{candidate.linked_finding_count === 1 ? "" : "s"}</small></div><details><summary>Evidence, planning context, and review requirements</summary><p>Authorized assessor, AO, and system-owner review required.</p><p>Evidence integrity: {candidate.evidence_sha256.length} evidence checksum{candidate.evidence_sha256.length === 1 ? "" : "s"} · {candidate.source_sha256.length} source checksum{candidate.source_sha256.length === 1 ? "" : "s"}.</p><p className="mono">Source checksums: {candidate.source_sha256.join(", ") || "not supplied"}</p><ScopeLinks links={candidate.service_scope_links ?? []} /></details></article>)}</div>;
}

function WorkstreamCards({ workstreams }: { workstreams: PoamWorkstream[] }) {
  return <div className="poam-record-cards">{workstreams.map((workstream) => <article key={workstream.workstream_id}><div><span className="eyebrow">Issue workstream</span><strong className="mono">{workstream.workstream_id}</strong><p>{workstream.title}</p></div><div><span>Consolidated scope</span><strong>{workstream.candidate_count} asset candidate{workstream.candidate_count === 1 ? "" : "s"}</strong><small>{workstream.subject_count} distinct subject{workstream.subject_count === 1 ? "" : "s"} · {workstream.affected_service_count} service group{workstream.affected_service_count === 1 ? "" : "s"}</small></div><div><span>Owner / scoped groups</span><strong>{workstream.responsible_owner}</strong><small>{workstream.affected_services.map(serviceGroupLabel).join(", ")}</small></div><div><span>Latest explicit linked IL2</span><strong><DateOrGap date={workstream.milestone_mitigation_date} /></strong><small>Merge review required · impact not assessed</small></div><details><summary>Remediation and merge requirements</summary><p>{workstream.remediation_plan}</p><ul className="coverage-evidence-list">{workstream.merge_blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul><p>{workstream.candidate_count} linked asset candidates remain independently addressable.</p></details></article>)}</div>;
}

type CoverageGapGroup = { key: string; rows: CoverageGapRow[]; lead: CoverageGapRow };

function CoverageGapGroupRow({ group }: { group: CoverageGapGroup }) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const { lead } = group;
  const observationIds = Array.from(new Set(group.rows.map((row) => row.gap.observation_id)));
  const evidenceCount = group.rows.reduce((count, row) => count + row.gap.evidence.length, 0);
  return <>
    <tr>
      <td><button type="button" className="poam-expand" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls={detailId}><ChevronDown size={17} className={cn(open && "poam-chevron-open")} /><span>{lead.serviceGroupName}</span></button><small className="mono">{lead.service}</small><Badge tone="warning">{lead.gap.assertion_state === "not_assessable" ? "Not assessable" : "Evidence gap"}</Badge></td>
      <td><strong>{observationIds.length} observation{observationIds.length === 1 ? "" : "s"}</strong><small>{group.rows.length} scoped service observation{group.rows.length === 1 ? "" : "s"}; display grouping only</small><small>{lead.documents} catalog document record{lead.documents === 1 ? "" : "s"} · {lead.sourceFiles} source file{lead.sourceFiles === 1 ? "" : "s"}</small></td>
      <td><strong>{lead.gap.title}</strong><small>{lead.gap.technical_observation}</small></td>
      <td><Badge tone="neutral">Not eligible</Badge><small>Evidence collection only</small></td>
    </tr>
    {open ? <tr className="poam-detail-row" id={detailId}><td colSpan={4}><div className="poam-evidence-detail"><div><p className="eyebrow">Required evidence</p><ul className="coverage-evidence-list">{Array.from(new Set(group.rows.flatMap((row) => row.gap.missing_required_facts))).map((item) => <li key={item}>{missingFactLabel(item)}</li>)}</ul></div><div><p className="eyebrow">Traceability retained</p><p>{observationIds.map((id) => <span key={id} className="mono poam-observation-id">{id}</span>)}</p><small>{evidenceCount} retained evidence reference{evidenceCount === 1 ? "" : "s"}. Source and evidence checksums remain attached to the underlying analyst observations.</small></div><div><p className="eyebrow">Review requirements</p><p>System owner, authorized assessor, and AO review are required before any candidate can be created or changed.</p><small>{Array.from(new Set(group.rows.flatMap((row) => row.gap.limitations))).join(" ") || "No additional limitation supplied."}</small></div></div></td></tr> : null}
  </>;
}

function CoverageGapCards({ groups }: { groups: CoverageGapGroup[] }) {
  return <div className="poam-record-cards">{groups.map((group) => {
    const { lead } = group;
    const ids = Array.from(new Set(group.rows.map((row) => row.gap.observation_id)));
    return <article key={group.key}><div><span className="eyebrow">Evidence-collection request</span><strong>{lead.serviceGroupName}</strong><small className="mono">{lead.service}</small></div><div><span>Evidence state / eligibility</span><Badge tone="warning">{lead.gap.assertion_state === "not_assessable" ? "Not assessable" : "Evidence gap"}</Badge><small>Not eligible for POA&amp;M; evidence collection only.</small></div><div><span>Observation count</span><strong>{ids.length} source observation{ids.length === 1 ? "" : "s"}</strong><small>{group.rows.length} scoped service observation{group.rows.length === 1 ? "" : "s"}; display grouping only.</small></div><div><span>Observation and reason</span><strong>{lead.gap.title}</strong><small>{lead.gap.technical_observation}</small></div><details><summary>Required evidence, IDs, and review requirements</summary><ul className="coverage-evidence-list">{Array.from(new Set(group.rows.flatMap((row) => row.gap.missing_required_facts))).map((item) => <li key={item}>{missingFactLabel(item)}</li>)}</ul><p className="mono">Observation IDs: {ids.join(", ")}</p><p>System owner, authorized assessor, and AO review are required before any candidate can be created or changed.</p></details></article>;
  })}</div>;
}

function CoverageGapRegister({ rows, filter }: { rows: CoverageGapRow[]; filter: string }) {
  const [page, setPage] = useState(0);
  const pageSize = 25;
  const normalizedFilter = filter.trim().toLocaleLowerCase();
  const visibleRows = rows.filter(({ gap, service, serviceGroupName, profile }) => [gap.observation_id, gap.title, gap.technical_observation, service, serviceGroupName, ...gap.missing_required_facts, ...(profile?.owners ?? []), ...(profile?.leads ?? [])].join(" ").toLocaleLowerCase().includes(normalizedFilter));
  const groupedRows = useMemo<CoverageGapGroup[]>(() => {
    const groups = new Map<string, CoverageGapRow[]>();
    for (const row of visibleRows) {
      const key = [row.service, row.gap.assertion_state, row.gap.title, [...row.gap.missing_required_facts].sort().join("|")].join("::");
      groups.set(key, [...(groups.get(key) ?? []), row]);
    }
    return Array.from(groups, ([key, members]) => ({ key, rows: members, lead: members[0] }));
  }, [visibleRows]);
  const pageCount = Math.max(1, Math.ceil(groupedRows.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = groupedRows.slice(safePage * pageSize, (safePage + 1) * pageSize);
  return <Card className="poam-table-card coverage-gap-card"><div className="card-heading"><div><p className="eyebrow">Evidence collection register</p><h2>Evidence-collection requests</h2><p className="coverage-intro">Evidence request — not POA&amp;M eligible. Missing or conflicting catalog facts prevent a posture determination. These observations are not vulnerabilities or POA&amp;M candidates.</p></div><div className="poam-card-actions"><DisclosureInfo label="Evidence collection scope" text="Display groups share service scope, assertion state, reason, and required facts. Grouping does not deduplicate or alter observations. Collect the listed evidence and obtain system-owner, assessor, and AO review before creating or changing a POA&M." /><Badge tone="info">{visibleRows.length} noneligible observations</Badge></div></div><div className="table-scroll poam-desktop-records"><table className="poam-table coverage-gap-table"><thead><tr><th>Service group / evidence state</th><th>Observation count</th><th>Observation &amp; reason</th><th>POA&amp;M eligibility</th></tr></thead><tbody>{pageRows.map((group) => <CoverageGapGroupRow key={group.key} group={group} />)}{visibleRows.length === 0 ? <tr><td colSpan={4} className="poam-empty">No evidence requests match this filter.</td></tr> : null}</tbody></table></div><CoverageGapCards groups={pageRows} />{visibleRows.length ? <nav className="poam-pagination" aria-label="Evidence request pages"><span>{safePage * pageSize + 1}–{Math.min((safePage + 1) * pageSize, groupedRows.length)} of {groupedRows.length} display groups · {visibleRows.length} source observations retained</span><div><button type="button" onClick={() => setPage((current) => Math.max(0, current - 1))} disabled={safePage === 0}>Previous</button><span>Page {safePage + 1} of {pageCount}</span><button type="button" onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))} disabled={safePage >= pageCount - 1}>Next</button></div></nav> : null}</Card>;
}

type PortfolioPoamSummary = {
  assessment_contract?: { complete?: boolean; state?: string };
  summary?: {
    deduplicated_poam_candidates?: number;
    proposed_remediation_workstreams?: number;
    portfolio_poam_candidates?: number;
    needs_review_findings?: number;
    coverage_gap_observations?: number;
    needs_review_observations?: number;
  };
};

type OwnerDirectedPoamMilestone = {
  label: string;
  target_date: string | null;
  status: string;
  detail?: string | null;
};

type OwnerDirectedPoamDeviation = {
  title: string;
  detail: string;
  reference_url?: string | null;
  artifact?: { reference_url?: string | null } | null;
};

type OwnerDirectedPoamItem = {
  id: string;
  title: string;
  kind: "owner_directed_draft_deviation" | "owner_directed_candidate";
  control_id: string;
  risk: { value: string; assertion: string } | string;
  risk_assertion?: string;
  status: string;
  summary: string;
  milestones: OwnerDirectedPoamMilestone[];
  deviations: OwnerDirectedPoamDeviation[];
  impact_summary?: {
    critical: { service_group_count: number; catalog_record_count: number };
    moderate: { service_group_count: number; catalog_record_count: number };
    other: { service_group_count: number; catalog_record_count: number };
    total: { service_group_count: number; catalog_record_count: number };
  };
  limitations: string[];
};

type OwnerDirectedPoamResponse = {
  items: OwnerDirectedPoamItem[];
};

function ownerDirectedKindLabel(kind: OwnerDirectedPoamItem["kind"]) {
  return kind === "owner_directed_candidate" ? "Planning draft candidate" : "Planning draft";
}

function ownerDirectedRiskLabel(item: OwnerDirectedPoamItem) {
  const value = typeof item.risk === "string" ? item.risk : item.risk.value;
  return `${value} · planning input`;
}

function ownerDirectedReferenceUrl(deviation: OwnerDirectedPoamDeviation) {
  return deviation.reference_url ?? deviation.artifact?.reference_url ?? null;
}

function ownerDirectedDistinctStatus(item: OwnerDirectedPoamItem) {
  const status = item.status.replaceAll("_", " ");
  const canonical = (value: string) => value.toLocaleLowerCase().trim().replace(/[-_\s]+/g, " ");
  if (canonical(status) === "owner directed draft deviation" || canonical(status) === "owner directed candidate") return "Assessment pending";
  return canonical(status) === canonical(ownerDirectedKindLabel(item.kind)) ? null : status;
}

function planningMilestoneStatusLabel(status: string) {
  const labels: Record<string, string> = {
    planning_window: "Planning window",
    verification_required: "Verification required",
    assessment_pending: "Assessment pending",
    user_asserted_planning: "Planning input",
    reported_complete: "Reported complete",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function planningMilestoneDateLabel(status: string) {
  return status === "planning_window" ? "Date varies by service" : "No target date";
}

function ScopeImpactSummary({ impact }: { impact: OwnerDirectedPoamItem["impact_summary"] }) {
  if (!impact) return <small className="poam-muted">Impact summary is unavailable.</small>;
  const metric = (label: string, value: { service_group_count: number; catalog_record_count: number }, className: string) => <span className={className} key={label}><strong>{label}</strong> {value.service_group_count} {value.service_group_count === 1 ? "group" : "groups"} · {value.catalog_record_count} catalog {value.catalog_record_count === 1 ? "record" : "records"}</span>;
  return <div className="poam-scope-impact">
    <div className="poam-scope-impact-counts" aria-label="Affected service groups and catalog records by planned impact risk">
      {metric("Critical", impact.critical, "critical")}
      {metric("Moderate", impact.moderate, "moderate")}
      {metric("Other / unset", impact.other, "other")}
      {metric("Total", impact.total, "total")}
    </div>
    <small>Counts use the current Service Catalog impact category and linked catalog records. Planning cards group module targets separately.</small>
  </div>;
}

function OwnerDirectedPoamRegister({ refreshKey = 0 }: { refreshKey?: number }) {
  const [data, setData] = useState<OwnerDirectedPoamResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = async () => {
    setLoading(true); setError(null);
    try {
      setData(await fetchJson<OwnerDirectedPoamResponse>("/api/v1/portfolio/risk-assessment-poam", { dedupe: false }));
    } catch {
      setData(null);
      setError("We couldn’t load the POA&M planning drafts. Refresh to try again.");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [refreshKey]);
  return <Card className="poam-table-card owner-directed-poam-card">
    <div className="card-heading"><div><p className="eyebrow">Draft planning register</p><h2>POA&amp;M planning drafts — read-only</h2><p className="coverage-intro">Read-only planning drafts. They record submitted planning context and remain subject to assessment and approval.</p></div><div className="poam-card-actions"><Badge tone="warning">Read-only</Badge><button className="refresh-button" type="button" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? "spin" : ""} />Refresh</button></div></div>
    {error ? <StatusBanner title="POA&M planning drafts need a refresh" detail={error} onRetry={() => void load()} /> : null}
    {loading && !data ? <div className="poam-inline-warning" role="status">Loading POA&amp;M planning drafts…</div> : null}
    {data ? <div className="table-scroll"><table className="poam-table owner-directed-poam-table"><thead><tr><th>Draft reference and impact</th><th>Control / risk</th><th>Milestones</th><th>Deviation and dependency detail</th><th>Assessment status</th></tr></thead><tbody>{data.items.map((item, index) => { const distinctStatus = ownerDirectedDistinctStatus(item); return <tr key={item.id}><td data-label="Draft reference and impact"><span className="mono">Draft {String(index + 1).padStart(2, "0")}</span><strong>{item.title}</strong><small>{item.summary}</small><ScopeImpactSummary impact={item.impact_summary} /></td><td data-label="Control / risk"><Badge tone="warning">{item.control_id === "SC-13" ? "SC-13 (proposed mapping)" : item.control_id}</Badge><span className="poam-risk">{ownerDirectedRiskLabel(item)}</span></td><td data-label="Milestones"><div className="poam-milestone-list">{item.milestones.map((milestone) => <div key={`${milestone.label}-${milestone.target_date ?? "unscheduled"}`}><strong>{milestone.label}</strong><span>{milestone.target_date ? <DateOrGap date={milestone.target_date} /> : planningMilestoneDateLabel(milestone.status)} · {planningMilestoneStatusLabel(milestone.status)}</span>{milestone.detail ? <small>{milestone.detail}</small> : null}</div>)}</div></td><td data-label="Deviation and dependency detail"><ul className="owner-directed-poam-details">{item.deviations.map((deviation) => { const referenceUrl = ownerDirectedReferenceUrl(deviation); return <li key={deviation.title}><strong>{deviation.title}</strong><span>{deviation.detail}</span>{referenceUrl ? <a href={referenceUrl} target="_blank" rel="noreferrer">Source context <ExternalLink size={13} /></a> : null}</li>; })}</ul></td><td data-label="Assessment status"><Badge tone="warning">{ownerDirectedKindLabel(item.kind)}</Badge>{distinctStatus ? <small>{distinctStatus}</small> : null}{item.limitations.length ? <details><summary>Limitations</summary><ul>{item.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></details> : null}</td></tr>; })}{data.items.length === 0 ? <tr><td colSpan={5} className="poam-empty">No POA&amp;M planning drafts are available.</td></tr> : null}</tbody></table></div> : null}
  </Card>;
}

function MilestoneRegister({ data, catalog = [] }: { data: TeamMilestones; catalog?: CatalogPlanningRow[] }) {
  const rows = data.all_tracker_rows.map((row) => ({ row, display: milestoneRowDisplay(row, catalog) }));
  return <Card className="poam-milestone-card"><div className="card-heading"><div><p className="eyebrow">Team target-module planning data</p><h2>Owner, lead, target state, IL2, and IL5 milestone register</h2></div><div className="poam-summary-actions"><DisclosureInfo label="Milestone and module rules" text="Planning metadata only. Service Catalog plans can link a public CMVP certificate or pipeline source, but still require exact deployment correlation." /><Badge tone="info">{data.all_tracker_rows.length} tracker rows</Badge></div></div><div className="poam-milestone-scroll"><table><thead><tr><th>Team</th><th>Mapped service groups</th><th>Owner</th><th>Lead</th><th>Target state</th><th>IL2</th><th>IL5</th></tr></thead><tbody>{rows.map(({ row, display }) => <tr key={row.team}><td><strong>{display.team}</strong></td><td>{display.mappedServiceGroups.join(", ") || <span className="poam-missing">Unmapped</span>}</td><td>{row.owner || <span className="poam-missing">Not supplied</span>}</td><td>{row.lead || <span className="poam-missing">Not supplied</span>}</td><td>{row.target_modules?.length ? <div className="poam-target-state">{Array.from(new Set(row.target_modules.map(planningTargetDisposition))).map((status) => <Badge key={status} tone={targetDispositionTone(row.target_modules ?? [], status)}>{dispositionLabel(status)}</Badge>)}</div> : <span className="poam-missing">Not determined</span>}</td><td>{milestoneText(row.il2)}</td><td>{milestoneText(row.il5)}</td></tr>)}</tbody></table></div><div className="poam-milestone-cards">{rows.map(({ row, display }) => <article key={row.team}><div><span className="eyebrow">Team</span><strong>{display.team}</strong><small>{display.mappedServiceGroups.join(", ") || "Unmapped service groups"}</small></div><div><span>Owner / lead</span><strong>{row.owner || "Not supplied"}</strong><small>{row.lead || "Lead not supplied"}</small></div><div><span>Catalog target state</span>{row.target_modules?.length ? <div className="poam-target-state">{Array.from(new Set(row.target_modules.map(planningTargetDisposition))).map((status) => <Badge key={status} tone={targetDispositionTone(row.target_modules ?? [], status)}>{dispositionLabel(status)}</Badge>)}</div> : <span className="poam-missing">Not determined</span>}</div><div><span>Catalog IL2</span>{milestoneText(row.il2)}<span>Catalog IL5</span>{milestoneText(row.il5)}</div><details><summary>Target-module details and limitations</summary><TargetModuleList modules={row.target_modules ?? []} /><small>Planning values can cite public module records, but they do not establish deployed use, approved mode, or authorization.</small></details></article>)}</div></Card>;
}


function AggregatePoamSummary() {
  const [data, setData] = useState<PortfolioPoamSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [planning, setPlanning] = useState<SharedPlanningResponse | null>(null);
  const [planningError, setPlanningError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [draftRefreshKey, setDraftRefreshKey] = useState(0);
  const [view, setView] = useState<"legacy_poam" | "migration" | "milestones">(() => {
    if (typeof window === "undefined") return "legacy_poam";
    const requested = new URLSearchParams(window.location.search).get("view");
    return requested === "migration" || requested === "milestones" ? requested : "legacy_poam";
  });
  const [filter, setFilter] = useState("");
  const tabId = useId();
  const load = async (refreshDrafts = false) => {
    setLoading(true); setError(null); setPlanningError(null);
    if (refreshDrafts) setDraftRefreshKey((value) => value + 1);
    const [summaryResult, planningResult] = await Promise.allSettled([
      fetchJson<PortfolioPoamSummary>("/api/v1/portfolio/poam-summary"),
      fetchJson<SharedPlanningResponse>("/api/v1/portfolio/poam-planning"),
    ]);
    if (summaryResult.status === "fulfilled") setData(summaryResult.value);
    else {
      setData(null);
      setError("We couldn’t load the Risk Assessment summary. Refresh to try again.");
    }
    if (planningResult.status === "fulfilled") setPlanning(planningResult.value);
    else { setPlanning(null); setPlanningError("We couldn’t load Planning and Team milestones. Refresh to try again."); }
    setLoading(false);
  };
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    const onPopState = () => {
      const requested = new URLSearchParams(window.location.search).get("view");
      setView(requested === "migration" || requested === "milestones" ? requested : "legacy_poam");
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  const chooseView = (next: "legacy_poam" | "migration" | "milestones") => {
    if (view === next) return;
    setView(next);
    const params = new URLSearchParams(window.location.search);
    params.set("view", next);
    window.history.pushState(window.history.state, "", `${window.location.pathname}?${params.toString()}`);
  };
  const onViewKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const views: Array<"legacy_poam" | "migration" | "milestones"> = ["legacy_poam", "migration", "milestones"];
    const current = views.indexOf(view);
    const next = event.key === "ArrowRight" ? views[(current + 1) % views.length] : event.key === "ArrowLeft" ? views[(current - 1 + views.length) % views.length] : event.key === "Home" ? views[0] : event.key === "End" ? views[views.length - 1] : null;
    if (!next) return;
    event.preventDefault(); chooseView(next);
    event.currentTarget.querySelector<HTMLButtonElement>(`#${CSS.escape(`${tabId}-${next}`)}`)?.focus();
  };
  const migrationGroups = useMemo<MigrationGroup[]>(() => {
    if (!planning) return [];
    const catalog = new Map(planning.catalog.map((row) => [row.service_key, row]));
    const documents = new Map(planning.document_counts.map((row) => [row.service_key, row.documents]));
    return planningProfiles(planning.milestones, planning.catalog).map((profile) => {
      const key = `${planning.source_collection}/${profile.service_group}`;
      return { profile, catalog: catalog.get(key), documentCount: documents.get(key) ?? 0, modules: profile.target_modules, vendors: [] };
    }).filter(hasMigrationCardData);
  }, [planning]);
  const summary = data?.summary ? {
    ...data.summary,
    // The aggregate card includes review findings and coverage-gap observations.
    needs_review_findings: data.summary.needs_review_observations ?? 0,
  } : undefined;
  return <div className="page-container poam-page">
    <section className="page-heading"><div><p className="eyebrow">Portfolio planning</p><h1>Risk Assessment</h1><p className="page-subtitle">All-service Planning and Team milestones are read-only. POA&amp;M planning drafts remain available for review.</p></div><div className="heading-actions"><Badge tone={loading ? "neutral" : error || planningError ? "warning" : data?.assessment_contract?.complete ? "info" : "warning"}>{loading ? "Loading planning" : error || planningError ? "Refresh needed" : "Read-only planning"}</Badge><button className="refresh-button" type="button" onClick={() => void load(true)} disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} />Refresh</button></div></section>
    {error ? <StatusBanner title="Risk Assessment summary needs a refresh" detail={error} onRetry={() => void load()} /> : null}
    {summary ? <section className="poam-kpis" aria-label="Aggregate POA&M summary"><Card><ClipboardCheck size={20} /><div><span>Deduplicated draft POA&amp;M candidates</span><strong>{summary.deduplicated_poam_candidates ?? 0}</strong></div></Card><Card><ListTree size={20} /><div><span>Remediation workstreams</span><strong>{summary.proposed_remediation_workstreams ?? 0}</strong></div></Card><Card><ShieldCheck size={20} /><div><span>Portfolio dimensions</span><strong>{summary.portfolio_poam_candidates ?? 0}</strong></div></Card><Card><FileWarning size={20} /><div><span>Evidence observations requiring review</span><strong>{summary.needs_review_findings ?? 0}</strong></div></Card></section> : null}
    {planningError ? <StatusBanner title="Planning and Team milestones need a refresh" detail={planningError} onRetry={() => void load()} /> : null}
    <section className="poam-register-tabs" role="tablist" aria-label="Risk Assessment views" onKeyDown={onViewKeyDown}>
      <button type="button" id={`${tabId}-legacy_poam`} role="tab" aria-selected={view === "legacy_poam"} aria-controls={`${tabId}-panel`} tabIndex={view === "legacy_poam" ? 0 : -1} onClick={() => chooseView("legacy_poam")}>POA&amp;M</button>
      <button type="button" id={`${tabId}-migration`} role="tab" aria-selected={view === "migration"} aria-controls={`${tabId}-panel`} tabIndex={view === "migration" ? 0 : -1} onClick={() => chooseView("migration")}>Planning <b>{planning ? migrationGroups.length : "—"}</b></button>
      <button type="button" id={`${tabId}-milestones`} role="tab" aria-selected={view === "milestones"} aria-controls={`${tabId}-panel`} tabIndex={view === "milestones" ? 0 : -1} onClick={() => chooseView("milestones")}>Team milestones <b>{planning?.milestones.all_tracker_rows.length ?? "—"}</b></button>
    </section>
    <div id={`${tabId}-panel`} role="tabpanel" aria-labelledby={`${tabId}-${view}`}>
      {loading && !planning ? <Card className="poam-unavailable poam-unavailable-compact" role="status"><RefreshCw size={19} className="spin" /><div><strong>Loading portfolio planning</strong></div></Card> : null}
      {view === "legacy_poam" ? <OwnerDirectedPoamRegister refreshKey={draftRefreshKey} /> : null}
      {planning && view === "migration" ? <Card className="poam-table-card"><div className="card-heading"><div><p className="eyebrow">Service Catalog planning</p><h2>Module migration delivery view</h2><p className="coverage-intro">Approved plans organize imported module assertions. This view does not establish FIPS validation or candidate findings.</p></div><label className="poam-filter"><span className="sr-only">Filter Planning</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter group, owner…" /></label></div><MigrationPlanView groups={migrationGroups} filter={filter} /></Card> : null}
      {planning && view === "milestones" ? <MilestoneRegister data={planning.milestones} catalog={planning.catalog} /> : null}
    </div>
  </div>;
}

export function PoamWorkbench() {
  const access = useConsoleAccess();
  if (access.isAdmin) return <DetailedPoamWorkbench key="admin" />;
  return <><AggregatePoamSummary />{access.pairs.length ? <AssignedServiceUnion title="POA&M evidence across assigned products" headingLevel={2} description="Portfolio Planning and Team milestones above cover all services. Detailed catalog evidence below remains scoped to each verified product grant; candidate output and exports retain their separate assessment gate." renderScope={access.detailAccess ? (scope) => <DetailedPoamWorkbench scope={scope} embedded /> : undefined} /> : null}</>;
}

function DetailedPoamWorkbench({ scope, embedded = false }: { scope?: AssignedScopePair; embedded?: boolean }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof getPoamAssessment>> | null>(null);
  const [draftRefreshKey, setDraftRefreshKey] = useState(0);
  const assessmentContractIncomplete = data?.data?.assessment_contract?.complete === false;
  // The general assessment contract and a product-specific evidence contract
  // are separate gates. A scoped product view must not offer exports just
  // because the broader contract happens to be complete.
  const productAssessmentContract = (data?.data as (PoamAssessment & {
    product_assessment_contract?: { candidate_eligible?: boolean; exports_allowed?: boolean };
  }) | null)?.product_assessment_contract;
  // An exact product grant may expose catalog evidence before the accountable
  // product assessment contract exists. Do not call the deliberately
  // fail-closed FIPS endpoint in that state.
  const productAssessmentRequestPending = Boolean(scope && !scope.assessmentAuthorizationReference);
  const exportsAllowed = !scope || productAssessmentContract?.exports_allowed === true;
  const productExportPending = Boolean(scope && !exportsAllowed);
  const productCandidateOutputWithheld = Boolean(productAssessmentRequestPending || (scope && productAssessmentContract?.candidate_eligible === false));
  // The contract is unknown until the assessment arrives. Do not advertise
  // candidate output during the initial render.
  const candidateOutputWithheld = Boolean(!data?.data || assessmentContractIncomplete || productCandidateOutputWithheld || productExportPending);
  const [milestones, setMilestones] = useState<Awaited<ReturnType<typeof getTeamMilestones>> | null>(null);
  const [registerRows, setRegisterRows] = useState<ServiceGroupRegisterRow[]>([]);
  const [registerLoaded, setRegisterLoaded] = useState(false);
  const [catalogRows, setCatalogRows] = useState<CatalogPlanningRow[]>([]);
  const [catalogLoaded, setCatalogLoaded] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [selectedService, setSelectedService] = useState<ServiceGroupRegisterRow | null>(null);
  const [registerError, setRegisterError] = useState<string | null>(scope ? "Planning data is unavailable because the imported Team Tracker lacks source_collection provenance for this selected pair." : null);
  const [exportError, setExportError] = useState("");
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState(() => typeof window === "undefined" || embedded ? "" : new URLSearchParams(window.location.search).get("query") ?? "");
  const [selectedRegisterMode, setRegisterMode] = useState<PoamView>(() => {
    if (typeof window === "undefined" || embedded) return "workstreams";
    const view = new URLSearchParams(window.location.search).get("view");
    return view === "legacy_poam" || view === "migration" || view === "portfolio" || view === "candidates" || view === "workstreams" || view === "evidence" || view === "milestones" ? view : "legacy_poam";
  });
  const registerMode = scope && (selectedRegisterMode === "migration" || selectedRegisterMode === "milestones") ? "evidence" : candidateOutputWithheld && (selectedRegisterMode === "portfolio" || selectedRegisterMode === "workstreams" || selectedRegisterMode === "candidates") ? "evidence" : selectedRegisterMode;
  const tabId = useId();
  const tabRefs = useRef<Partial<Record<PoamView, HTMLButtonElement | null>>>({});
  const [page, setPage] = useState(() => {
    if (typeof window === "undefined" || embedded) return 0;
    const raw = Number(new URLSearchParams(window.location.search).get("page"));
    return Number.isInteger(raw) && raw > 1 ? raw - 1 : 0;
  });
  const pageSize = 20;
  const reducedMotion = useReducedMotion();
  const refresh = async () => {
    if (productAssessmentRequestPending) return;
    setLoading(true);
    setDraftRefreshKey((value) => value + 1);
    if (!scope && (registerMode === "migration" || registerMode === "milestones")) {
      setMilestones(null);
      setRegisterLoaded(false);
      setCatalogLoaded(false);
      setCatalogError(null);
    }
    const assessmentResult = await getPoamAssessment({ page, pageSize, query: filter, scope });
    setData(assessmentResult);
    setLoading(false);
  };
  useEffect(() => {
    if (productAssessmentRequestPending) {
      const timer = window.setTimeout(() => setLoading(false), 0);
      return () => window.clearTimeout(timer);
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      void getPoamAssessment({ page, pageSize, query: filter, scope, signal: controller.signal }).then((assessmentResult) => {
        if (controller.signal.aborted) return;
        setData(assessmentResult);
        setLoading(false);
      });
    }, filter ? 250 : 0);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [page, filter, productAssessmentRequestPending, scope]);
  useEffect(() => {
    // Assessment evidence should load before optional planning metadata.
    if (!data?.data || milestones) return;
    void getTeamMilestones(scope).then(setMilestones);
  }, [data?.data, milestones, scope]);
  useEffect(() => {
    // The full register only contributes to the Planning migration lanes.
    if (scope || registerMode !== "migration" || registerLoaded) return;
    const controller = new AbortController();
    void getServiceGroupRegister({ query: "", owner: "", lead: "", il2State: "", il5State: "", action: "", sort: "service_group", direction: "asc", page: 0, pageSize: 250, signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        if (result.total > result.items.length) throw new Error("Portfolio register exceeds one page");
        setRegisterRows(result.items);
        setRegisterError(null);
        setRegisterLoaded(true);
      })
      .catch(() => { if (!controller.signal.aborted) { setRegisterError("Catalog document counts could not be loaded. Refresh to try again."); setRegisterLoaded(true); } });
    return () => controller.abort();
  }, [scope, registerMode, registerLoaded]);
  useEffect(() => {
    if (scope || (registerMode !== "migration" && registerMode !== "milestones") || catalogLoaded) return;
    const controller = new AbortController();
    void fetchJson<{ items: CatalogPlanningRow[] }>("/api/v1/service-catalog", { signal: controller.signal, dedupe: false })
      .then((result) => {
        if (controller.signal.aborted) return;
        setCatalogRows(result.items);
        setCatalogError(null);
        setCatalogLoaded(true);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setCatalogError("Current Service Catalog planning could not be loaded. Refresh to try again.");
        setCatalogLoaded(true);
      });
    return () => controller.abort();
  }, [scope, registerMode, catalogLoaded]);
  useEffect(() => {
    if (embedded || !data) return;
    const params = new URLSearchParams(window.location.search);
    params.set("view", registerMode);
    if (filter) params.set("query", filter); else params.delete("query");
    if (page) params.set("page", String(page + 1)); else params.delete("page");
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, [data, embedded, filter, page, registerMode]);
  useEffect(() => {
    if (embedded) return;
    const onPopState = () => {
      const params = new URLSearchParams(window.location.search);
      const view = params.get("view");
      setRegisterMode(view === "legacy_poam" || view === "migration" || view === "portfolio" || view === "candidates" || view === "workstreams" || view === "evidence" || view === "milestones" ? view : "legacy_poam");
      setFilter(params.get("query") ?? "");
      const nextPage = Number(params.get("page"));
      setPage(Number.isInteger(nextPage) && nextPage > 1 ? nextPage - 1 : 0);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [embedded]);

  const assessment = data?.data;
  const milestoneCatalogState = catalogError ? "error" : milestones?.source === "unavailable" ? "unavailable" : milestones === null || !catalogLoaded ? "loading" : "ready";
  const profileByGroup = useMemo(() => new Map((milestones?.data?.groups ?? []).map((profile) => [profile.service_group, profile])), [milestones]);
  const coverageGaps = useMemo<CoverageGapRow[]>(() => {
    const rollups = new Map((assessment?.service_groups ?? []).map((row) => [row.service, row]));
    const observationSource = assessment?.analyst_observations ?? assessment?.coverage_gaps ?? [];
    const observations = observationSource.map(asCoverageGap).filter((item): item is CoverageGap => item !== null);
    return observations.flatMap((gap) => gap.scope.service_groups.map((serviceGroup) => {
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
    const registerByGroup = new Map(registerRows.map((row) => [row.service_key, row]));
    const catalogByGroup = new Map(catalogRows.map((row) => [row.service_key, row]));
    return planningProfiles(milestones?.data, catalogRows)
      .map((profile) => ({ profile, register: registerByGroup.get(`sse-cboms/${profile.service_group}`), catalog: catalogByGroup.get(`sse-cboms/${profile.service_group}`), modules: profile.target_modules, vendors: [] }))
      .filter(hasMigrationCardData);
  }, [milestones, registerRows, catalogRows]);
  const candidates = assessment?.poam_items ?? [];
  const noneligibleObservationCount = assessment?.analyst_observations?.length ?? assessment?.coverage_gaps?.length ?? 0;
  const workstreams = assessment?.poam_workstreams ?? [];
  const portfolioItems = useMemo(
    () => assessmentContractIncomplete ? [] : assessment?.portfolio_poam_items ?? [],
    [assessment?.portfolio_poam_items, assessmentContractIncomplete],
  );
  const normalizedFilter = filter.trim().toLocaleLowerCase();
  const visibleWorkstreams = workstreams.filter((workstream) => [workstream.workstream_id, workstream.title, workstream.responsible_owner, ...workstream.issue_codes, ...workstream.affected_services, ...workstream.tags].join(" ").toLocaleLowerCase().includes(normalizedFilter));
  const candidateTotal = assessment?.poam_page?.total ?? candidates.length;
  const pageCount = Math.max(1, Math.ceil(candidateTotal / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visibleCandidates = candidates;
  const assessmentUnavailable = !loading && data?.source === "unavailable";
  const milestoneUnavailable = !loading && milestones?.source === "unavailable";
  const availableViews: PoamView[] = scope
    ? candidateOutputWithheld ? ["legacy_poam", "evidence"] : ["legacy_poam", "workstreams", "candidates", "portfolio", "evidence"]
    : candidateOutputWithheld ? ["legacy_poam", "migration", "evidence", "milestones"]
    : ["legacy_poam", "workstreams", "candidates", "migration", "portfolio", "evidence", "milestones"];
  const viewLabels: Record<PoamView, string> = {
    legacy_poam: "POA&M",
    workstreams: "Draft candidate review", candidates: "Draft candidates", migration: "Planning", portfolio: "Migration dimensions",
    evidence: "Evidence requests", milestones: "Team milestones",
  };
  const chooseView = (view: PoamView) => {
    if (view === registerMode) return;
    setRegisterMode(view);
    setPage(0);
    if (!embedded) {
      const params = new URLSearchParams(window.location.search);
      params.set("view", view);
      params.delete("page");
      window.history.pushState(window.history.state, "", `${window.location.pathname}?${params.toString()}`);
    }
  };
  const onViewKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const index = availableViews.indexOf(registerMode);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % availableViews.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + availableViews.length) % availableViews.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = availableViews.length - 1;
    else return;
    event.preventDefault();
    const view = availableViews[next];
    chooseView(view);
    tabRefs.current[view]?.focus();
  };
  const exportQuery = scope ? `?${scopeQuery(scope)}` : "";
  const downloadExport = async (path: string, filename: string) => {
    setExportError("");
    try {
      const response = await fetch(`${path}${exportQuery}`, { cache: "no-store", headers: accessModeHeaders() });
      if (!response.ok) throw new Error(`Export request returned ${response.status}`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click(); anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      setExportError("The export could not be downloaded. Try again.");
    }
  };

  return <div className="page-container poam-page">
    <section className="page-heading"><div><p className="eyebrow">Assessment workspace</p><h1>Risk Assessment</h1><p className="page-subtitle">{loading && !assessment ? "Loading assessment and evidence views…" : assessmentContractIncomplete ? "Required assessment facts are incomplete. Review the evidence requests below; candidate output is withheld." : productCandidateOutputWithheld || productExportPending ? "Product assessment evidence is pending independent verification. Review the evidence observations below; candidate output and exports are withheld." : assessment ? "Review POA&M planning drafts, service planning, and supporting evidence." : "Assessment data is unavailable. Try refreshing this view."}</p></div><div className="heading-actions"><Badge tone={loading ? "neutral" : candidateOutputWithheld || productExportPending ? "warning" : assessment ? "success" : "danger"}>{loading ? "Loading assessment" : assessmentContractIncomplete ? "Contract incomplete" : productCandidateOutputWithheld || productExportPending ? "Product verification pending" : assessment ? "Assessment loaded" : "Assessment unavailable"}</Badge>{assessment && !candidateOutputWithheld && exportsAllowed ? <><button className="secondary-button" type="button" onClick={() => void downloadExport("/api/v1/fips/compliance-package.zip", "cbom-candidate-evidence.zip")}><Download size={17} />Candidate evidence ZIP</button><button className="secondary-button" type="button" onClick={() => void downloadExport("/api/v1/fips/portfolio-poam.csv", "cbom-migration-dimensions.csv")}><Download size={17} />Draft migration-dimension CSV</button><button className="secondary-button" type="button" onClick={() => void downloadExport("/api/v1/fips/poam.csv", "cbom-candidate-assets.csv")}><Download size={17} />Candidate asset CSV</button></> : null}{assessmentContractIncomplete ? <span className="poam-export-disabled">Exports unavailable — assessment contract incomplete</span> : productCandidateOutputWithheld || productExportPending ? <span className="poam-export-disabled">Exports unavailable — product assessment evidence requires independent verification</span> : null}<button className="refresh-button" type="button" onClick={() => void refresh()} disabled={loading || productAssessmentRequestPending}><RefreshCw size={17} className={loading ? "spin" : ""} />Refresh</button></div></section>
    {exportError ? <p className="poam-inline-warning" role="alert">{exportError}</p> : null}

    {loading && !assessment ? <Card className="poam-unavailable poam-unavailable-compact" role="status"><RefreshCw size={19} className="spin" /><div><strong>Loading evidence</strong><p>The assessment view will appear when its contract and scoped observations are ready.</p></div></Card> : null}
    {productAssessmentRequestPending ? <StatusBanner title="Product assessment verification pending" detail="This verified product grant permits scoped catalog evidence. Candidate FIPS assessment and exports are withheld until an immutable product assessment authorization reference is recorded and independently verified." /> : assessmentUnavailable ? <StatusBanner title={scope ? "Scoped Risk Assessment needs a refresh" : "Risk Assessment needs a refresh"} detail="We couldn’t load the current assessment. Refresh to try again." onRetry={() => void refresh()} /> : null}
    {milestoneUnavailable ? <Card className="poam-unavailable poam-unavailable-compact" role="status"><CalendarClock size={19} /><div><strong>Team milestones need a refresh.</strong><p>Evidence observations remain available. Refresh to load current owners, leads, and milestone dates.</p></div></Card> : null}

	    {assessment ? <>
	      {assessment.assessment_contract?.complete === false ? registerMode === "legacy_poam" ? <p className="poam-legacy-contract-note" role="status">Assessment contract incomplete. This read-only planning draft register remains available; candidate output, exports, and approval remain withheld.</p> : <StatusBanner title="Assessment evidence contract incomplete" detail={`Candidate POA&M output is withheld. Complete the listed scope, authority, and review facts; this does not establish compliance or a deficiency. Evidence request — not POA&M eligible. Missing: ${(assessment.assessment_contract.missing_required_facts ?? []).map(missingFactLabel).join(", ") || "required scope or policy facts"}.`} onRetry={() => void refresh()} /> : null}
	      <details className="poam-provenance-disclosure"><summary>Assessment provenance</summary><AssessmentProvenance assessment={assessment} /></details>
      <section className="poam-register-tabs" role="tablist" aria-label="Risk Assessment views" onKeyDown={onViewKeyDown}>
        {availableViews.map((view) => <button key={view} id={`${tabId}-${view}`} ref={(node) => { tabRefs.current[view] = node; }} type="button" role="tab" aria-selected={registerMode === view} aria-controls={`${tabId}-panel`} tabIndex={registerMode === view ? 0 : -1} onClick={() => chooseView(view)}><span>{viewLabels[view]}</span>{view === "legacy_poam" ? null : view === "workstreams" ? <b>{workstreams.length}</b> : view === "candidates" ? <b>{candidateTotal}</b> : view === "migration" ? <b>{catalogLoaded && registerLoaded && milestones?.data && !catalogError && !registerError ? migrationGroups.length : "—"}</b> : view === "portfolio" ? <b>{portfolioItems.length}</b> : view === "evidence" ? <b>{coverageGaps.length}</b> : <b>{milestones?.data?.all_tracker_rows.length ?? "—"}</b>}</button>)}
	      </section>
	      <div id={`${tabId}-panel`} role="tabpanel" aria-labelledby={`${tabId}-${registerMode}`}>
	        {registerMode === "workstreams" || registerMode === "candidates" || registerMode === "migration" || registerMode === "portfolio" ? <Card className="poam-table-card"><div className="card-heading"><div><p className="eyebrow">{registerMode === "migration" ? "Service Catalog planning" : "Traceable remediation hierarchy"}</p><h2>{registerMode === "migration" ? "Module migration delivery view" : registerMode === "portfolio" ? "Selected service-group migration dimensions" : registerMode === "workstreams" ? "Issue clusters requiring merge review" : "Asset-level candidate evidence"}</h2><p className="coverage-intro">{registerMode === "migration" ? "Approved Service Catalog plans organize imported module target assertions. Planning changes do not establish FIPS validation or create candidate findings." : "Candidates require authorized assessor, AO, and system-owner review. Migration-dimension views are planning assertions, not assessor determinations."}</p></div><div className="poam-card-actions"><DisclosureInfo label="Consolidation rules" text="Migration lanes assign each service group once. Selected service-group migration dimensions remain overlapping candidate views, not accepted merges or disjoint totals." /><label className="poam-filter"><span className="sr-only">Filter the current POA&M view</span><input value={filter} onChange={(event) => { setFilter(event.target.value); setPage(0); }} placeholder="Filter issue, group, owner…" /></label></div></div>{registerError && registerMode === "migration" ? <div className="poam-inline-warning" role="status">{registerError}</div> : null}{catalogError && registerMode === "migration" ? <div className="poam-inline-warning" role="status">{catalogError}</div> : null}{registerMode === "migration" ? catalogLoaded && registerLoaded && milestones ? <MigrationPlanView groups={migrationGroups} filter={filter} onSelect={setSelectedService} /> : <div className="poam-inline-warning" role="status">Loading current Service Catalog plans and catalog records…</div> : registerMode === "portfolio" ? <div className="table-scroll"><table className="poam-table"><thead><tr><th>Selected service-group migration dimension</th><th>Linked scope</th><th><UserRound size={14} /> Owner / groups</th><th>Latest linked IL2 date</th><th>Review state</th></tr></thead><tbody>{portfolioItems.map((item) => <PortfolioRow key={item.portfolio_poam_id} item={item} />)}{portfolioItems.length === 0 ? <tr><td colSpan={5} className="poam-empty">No selected service-group migration dimensions match this filter.</td></tr> : null}</tbody></table></div> : registerMode === "workstreams" ? <><div className="table-scroll poam-desktop-records"><table className="poam-table"><thead><tr><th>Issue workstream</th><th>Consolidated scope</th><th><UserRound size={14} /> Owner / groups</th><th>Latest linked IL2 date</th><th>Merge state</th></tr></thead><tbody>{visibleWorkstreams.map((workstream) => <WorkstreamRow key={workstream.workstream_id} workstream={workstream} />)}{visibleWorkstreams.length === 0 ? <tr><td colSpan={5} className="poam-empty">No issue workstreams match this filter.</td></tr> : null}</tbody></table></div><WorkstreamCards workstreams={visibleWorkstreams} /></> : <><div className="table-scroll poam-desktop-records"><table className="poam-table"><thead><tr><th>Candidate &amp; finding</th><th>Control / proposed risk</th><th><UserRound size={14} /> Owner / group</th><th>Latest linked IL2 date</th><th>Review state</th></tr></thead><tbody>{visibleCandidates.map((candidate) => <CandidateRow key={candidate.poam_candidate_id} candidate={candidate} />)}{candidates.length === 0 ? <tr><td colSpan={5} className="poam-empty">No candidate records match this filter.</td></tr> : null}</tbody></table></div><CandidateCards candidates={visibleCandidates} />{candidateTotal > 0 ? <div className="poam-pagination"><span>{safePage * pageSize + 1}–{Math.min((safePage + 1) * pageSize, candidateTotal)} of {candidateTotal} candidates</span><div><button type="button" aria-label="Previous candidate page" onClick={() => setPage(Math.max(0, safePage - 1))} disabled={loading || safePage === 0}><ChevronLeft size={16} /></button><span>Page {safePage + 1} of {pageCount}</span><button type="button" aria-label="Next candidate page" onClick={() => setPage(Math.min(pageCount - 1, safePage + 1))} disabled={loading || safePage >= pageCount - 1}><ChevronRight size={16} /></button></div></div> : null}</>}</Card> : null}
        {registerMode === "legacy_poam" ? <OwnerDirectedPoamRegister refreshKey={draftRefreshKey} /> : null}
        {registerMode === "evidence" ? <CoverageGapRegister rows={coverageGaps} filter={filter} /> : null}
        {registerMode === "milestones" ? milestoneCatalogState === "error" ? <StatusBanner title="Team milestones need a refresh" detail={catalogError || "Current Service Catalog planning could not be loaded."} onRetry={() => void refresh()} /> : milestoneCatalogState === "loading" ? <Card className="poam-unavailable poam-unavailable-compact" role="status"><RefreshCw size={19} className="spin" /><div><strong>Loading Team milestones</strong><p>Loading current Service Catalog names for the milestone register…</p></div></Card> : milestones?.data ? <MilestoneRegister data={milestones.data} catalog={catalogRows} /> : null : null}
	      </div>
	      {registerMode === "workstreams" ? <motion.section className="poam-kpis" aria-label="Assessment summary" initial={{ opacity: 0, y: reducedMotion ? 0 : 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: reducedMotion ? 0 : .22 }}><Card><ListTree size={20} /><div><span>Issue workstreams</span><strong>{workstreams.length}</strong></div></Card><Card><ClipboardCheck size={20} /><div><span>Deduplicated draft POA&amp;M candidates</span><strong>{assessment.summary.deduplicated_poam_candidates}</strong></div></Card><Card><FileWarning size={20} /><div><span>Review-only findings</span><strong>{assessment.summary.needs_review_findings}</strong></div></Card><Card><CalendarClock size={20} /><div><span>Noneligible observations</span><strong>{noneligibleObservationCount}</strong></div></Card></motion.section> : null}
	    </> : null}
    {selectedService ? <ServiceGroupDrawer row={selectedService} onClose={() => setSelectedService(null)} /> : null}
  </div>;
}
