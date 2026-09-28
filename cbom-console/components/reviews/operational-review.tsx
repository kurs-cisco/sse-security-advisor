"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ClipboardCheck, RefreshCw, Send, X } from "lucide-react";
import { Badge } from "@/app/components/ui/badge";
import { Card } from "@/app/components/ui/card";
import { fetchJson } from "@/app/lib/http";
import type { AssignedScopePair } from "@/app/lib/scope";
import { useConsoleAccess } from "@/app/components/console-shell";
import { AssignedServiceUnion } from "@/components/access/assigned-service-union";

type ReviewStatus = "pending" | "approved" | "rejected";

export type OperationalReviewProposal = {
  id: string;
  source_collection: string;
  service_group: string;
  product_scope_id: "secure-access-government" | "secure-access-defense";
  assessment_authorization_reference: string | null;
  resource_type: "finding" | "poam_candidate";
  resource_key: string;
  proposed_note: string;
  rationale: string;
  status: ReviewStatus;
  submitted_at: string;
  submitted_by_email?: string | null;
  decided_at: string | null;
  decided_by_email?: string | null;
  decision_reason: string | null;
};

type ProposalPage = { items: OperationalReviewProposal[]; total: number };
type OperationalEvidenceNote = {
  id: string;
  source_collection: string;
  service_group: string;
  product_scope_id: "secure-access-government" | "secure-access-defense";
  finding_id: string;
  note: string;
  lead_rationale: string;
  status: ReviewStatus;
  submitted_at: string;
  submitted_by_email?: string | null;
  decided_at: string | null;
  decided_by_email?: string | null;
  decision_reason: string | null;
};
type EvidenceNotePage = { items: OperationalEvidenceNote[]; total: number };
type ReviewResource = {
  resourceType: "finding" | "poam_candidate";
  resourceKey: string;
  label: string;
};
type AuditEvent = {
  id: number;
  action: string;
  resource_type: string;
  resource_key: string;
  occurred_at: string;
  actor_email: string | null;
  outcome: string | null;
};
type QueueSection = "queue" | "audit";
const queueSections: Array<{ id: QueueSection; label: string }> = [
  { id: "queue", label: "Decision queue" },
  { id: "audit", label: "Audit trail" },
];

function queueSectionFromLocation(): QueueSection {
  if (typeof window === "undefined") return "queue";
  return new URLSearchParams(window.location.search).get("section") === "audit"
    ? "audit"
    : "queue";
}

function reviewParams(scope: AssignedScopePair) {
  const params = new URLSearchParams({
    source_collection: scope.sourceCollection,
    service_group: scope.serviceGroup,
  });
  if (scope.productScopeId)
    params.set("product_scope_id", scope.productScopeId);
  return params;
}

function statusTone(
  status: ReviewStatus,
): "neutral" | "warning" | "success" | "danger" {
  if (status === "approved") return "success";
  if (status === "rejected") return "danger";
  return "warning";
}

function formatTimestamp(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))
    : "Not recorded";
}

/**
 * This is deliberately separate from catalog, planning, finding, and POA&M
 * data. A successful approval makes an operational review note visible; it
 * never changes source evidence or an assessment conclusion in the browser.
 */
export function OperationalReviewPanel({
  scope,
  canPropose,
  resources,
  productReviewEligible,
  observationNotesAvailable,
  reviewProposalsAvailable,
}: {
  scope: AssignedScopePair;
  canPropose: boolean;
  resources: ReviewResource[];
  productReviewEligible: boolean;
  observationNotesAvailable: boolean;
  reviewProposalsAvailable: boolean;
}) {
  const [page, setPage] = useState<ProposalPage | null>(null);
  const [observationPage, setObservationPage] =
    useState<EvidenceNotePage | null>(null);
  const [note, setNote] = useState("");
  const [resourceId, setResourceId] = useState("");
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [revision, setRevision] = useState(0);

  const load = useCallback(async () => {
    if (!reviewProposalsAvailable && !observationNotesAvailable) {
      setPage(null);
      setObservationPage(null);
      setError("");
      return;
    }
    setError("");
    try {
      const params = reviewParams(scope);
      const [proposals, observations] = await Promise.all([
        reviewProposalsAvailable
          ? fetchJson<ProposalPage>(`/api/v1/review-proposals?${params}`)
          : Promise.resolve(null),
        observationNotesAvailable
          ? fetchJson<EvidenceNotePage>(
              `/api/v1/operational-evidence-notes?${params}`,
            )
          : Promise.resolve(null),
      ]);
      setPage(proposals);
      setObservationPage(observations);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Operational review proposals are unavailable.",
      );
    }
  }, [observationNotesAvailable, reviewProposalsAvailable, scope]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load, revision]);

  const selectedResource = resources.find(
    (resource) =>
      `${resource.resourceType}:${resource.resourceKey}` === resourceId,
  );
  async function submit() {
    if (
      !note.trim() ||
      !rationale.trim() ||
      !selectedResource ||
      !scope.productScopeId
    )
      return;
    if (selectedResource.resourceType === "finding") {
      if (!observationNotesAvailable) {
        setError(
          "The operational evidence-observation note service is not available for this product scope.",
        );
        return;
      }
      setSubmitting(true);
      setError("");
      try {
        await fetchJson(
          `/api/v1/operational-evidence-notes?${reviewParams(scope)}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              source_collection: scope.sourceCollection,
              service_group: scope.serviceGroup,
              product_scope_id: scope.productScopeId,
              finding_id: selectedResource.resourceKey,
              note: note.trim(),
              lead_rationale: rationale.trim(),
            }),
          },
        );
        setNote("");
        setRationale("");
        setResourceId("");
        setRevision((value) => value + 1);
      } catch (caught) {
        setError(
          caught instanceof Error
            ? caught.message
            : "The operational evidence-observation note could not be submitted.",
        );
      } finally {
        setSubmitting(false);
      }
      return;
    }
    if (
      selectedResource.resourceType === "poam_candidate" &&
      !scope.assessmentAuthorizationReference
    ) {
      setError(
        "A draft POA&M candidate note requires an immutable authorization reference.",
      );
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await fetchJson<OperationalReviewProposal>(
        `/api/v1/review-proposals?${reviewParams(scope)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_collection: scope.sourceCollection,
            service_group: scope.serviceGroup,
            product_scope_id: scope.productScopeId,
            resource_type: selectedResource.resourceType,
            resource_key: selectedResource.resourceKey,
            proposed_note: note.trim(),
            rationale: rationale.trim(),
          }),
        },
      );
      setNote("");
      setRationale("");
      setResourceId("");
      setRevision((value) => value + 1);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The review proposal could not be submitted.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card className="operational-review-card">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Operational review</p>
          <h2>
            <ClipboardCheck size={18} />
            Review proposal history
          </h2>
          <p className="admin-card-note">
            Approved notes are operational records and do not change catalog
            evidence.
          </p>
        </div>
        <button
          className="icon-button"
          type="button"
          aria-label="Refresh operational review proposals"
          onClick={() => setRevision((value) => value + 1)}
          disabled={
            (!page && !observationPage) ||
            (!reviewProposalsAvailable && !observationNotesAvailable)
          }
        >
          <RefreshCw size={16} />
        </button>
      </div>
      {error ? (
        <p className="admin-error" role="alert">
          {error}
        </p>
      ) : null}
      {!reviewProposalsAvailable && !observationNotesAvailable ? (
        <p className="review-empty">
          Operational review proposals are disabled for this product scope.
          Scoped catalog evidence remains read-only until the administrator
          enables the review workflow.
        </p>
      ) : null}
      {(reviewProposalsAvailable || observationNotesAvailable) &&
      !page &&
      !observationPage &&
      !error ? (
        <p className="review-empty">Loading operational review proposals…</p>
      ) : null}
      {page?.items.filter(
        (proposal) => proposal.resource_type === "poam_candidate",
      ).length ? (
        <section
          className="review-proposal-list"
          aria-label="Draft POA&M candidate review history"
        >
          {page.items
            .filter((proposal) => proposal.resource_type === "poam_candidate")
            .map((proposal) => (
              <article key={proposal.id}>
                <div className="review-proposal-head">
                  <Badge tone={statusTone(proposal.status)}>
                    {proposal.status}
                  </Badge>
                  <span>{formatTimestamp(proposal.submitted_at)}</span>
                </div>
                <strong>
                  draft POA&amp;M candidate · {proposal.resource_key}
                </strong>
                <small>{proposal.product_scope_id}</small>
                <p>{proposal.proposed_note}</p>
                <small>Rationale: {proposal.rationale}</small>
                <small>
                  Authorization reference:{" "}
                  {proposal.assessment_authorization_reference ||
                    "Not supplied"}
                </small>
                {proposal.status !== "pending" ? (
                  <small>
                    {proposal.status === "approved"
                      ? "Administrator-reviewed operational record"
                      : "Rejected"}{" "}
                    by {proposal.decided_by_email || "Administrator"} ·{" "}
                    {formatTimestamp(proposal.decided_at)}
                    {proposal.decision_reason
                      ? ` · ${proposal.decision_reason}`
                      : ""}
                  </small>
                ) : null}
              </article>
            ))}
        </section>
      ) : page ? (
        <p className="review-empty">
          No draft POA&amp;M candidate review proposals have been submitted for
          this service scope.
        </p>
      ) : null}
      {observationNotesAvailable && observationPage?.items.length ? (
        <section
          className="review-proposal-list"
          aria-label="Operational evidence-observation note history"
        >
          <h3>Operational evidence-observation notes</h3>
          {observationPage.items.map((observation) => (
            <article key={observation.id}>
              <div className="review-proposal-head">
                <Badge tone={statusTone(observation.status)}>
                  {observation.status}
                </Badge>
                <span>{formatTimestamp(observation.submitted_at)}</span>
              </div>
              <strong>Operational evidence-observation note</strong>
              <small>
                {observation.product_scope_id} · finding observation{" "}
                {observation.finding_id}
              </small>
              <p>{observation.note}</p>
              <small>Lead rationale: {observation.lead_rationale}</small>
              {observation.status !== "pending" ? (
                <small>
                  {observation.status === "approved"
                    ? "Administrator-reviewed operational record"
                    : "Rejected"}{" "}
                  by {observation.decided_by_email || "Administrator"} ·{" "}
                  {formatTimestamp(observation.decided_at)}
                  {observation.decision_reason
                    ? ` · ${observation.decision_reason}`
                    : ""}
                </small>
              ) : null}
            </article>
          ))}
        </section>
      ) : observationNotesAvailable && observationPage ? (
        <p className="review-empty">
          No operational evidence-observation notes have been submitted for this
          product scope.
        </p>
      ) : null}
      {canPropose && resources.length && scope.productScopeId ? (
        <form
          className="review-proposal-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <h3>
            {selectedResource?.resourceType === "finding"
              ? "Propose an operational evidence-observation note"
              : "Propose an operational review note"}
          </h3>
          {selectedResource?.resourceType === "finding" ? (
            <p className="admin-card-note">
              This note records an evidence observation for the selected product
              scope. It is not an assessment, POA&amp;M candidate,
              authorization, or remediation disposition.
            </p>
          ) : (
            <p className="admin-card-note">
              Product context: {scope.productScopeId}. Immutable authorization
              reference:{" "}
              {scope.assessmentAuthorizationReference || "Not supplied"}.
            </p>
          )}
          <label>
            Scoped review item
            <select
              value={resourceId}
              required
              onChange={(event) => setResourceId(event.target.value)}
            >
              <option value="">
                Select a finding observation
                {productReviewEligible ? " or draft POA&M candidate" : ""}
              </option>
              {resources.map((resource) => (
                <option
                  key={`${resource.resourceType}:${resource.resourceKey}`}
                  value={`${resource.resourceType}:${resource.resourceKey}`}
                >
                  {resource.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            {selectedResource?.resourceType === "finding"
              ? "Evidence-observation note"
              : "Proposed note"}
            <textarea
              value={note}
              minLength={8}
              maxLength={2000}
              required
              onChange={(event) => setNote(event.target.value)}
              placeholder={
                selectedResource?.resourceType === "finding"
                  ? "Describe the evidence observation for administrator review."
                  : "Describe the operational context that needs administrator review."
              }
            />
          </label>
          <label>
            {selectedResource?.resourceType === "finding"
              ? "Lead rationale"
              : "Review rationale"}
            <textarea
              value={rationale}
              minLength={8}
              maxLength={2000}
              required
              onChange={(event) => setRationale(event.target.value)}
              placeholder={
                selectedResource?.resourceType === "finding"
                  ? "Explain why this evidence observation needs administrator review."
                  : "Explain why this scoped note should be approved."
              }
            />
          </label>
          {selectedResource?.resourceType === "finding" &&
          !observationNotesAvailable ? (
            <p className="review-empty">
              Operational evidence-observation notes will be available after the
              product-scoped note service is enabled.
            </p>
          ) : null}
          <button
            className="primary-button"
            type="submit"
            disabled={
              submitting ||
              !note.trim() ||
              !rationale.trim() ||
              !selectedResource ||
              (selectedResource?.resourceType === "finding" &&
                !observationNotesAvailable) ||
              (selectedResource?.resourceType === "poam_candidate" &&
                !scope.assessmentAuthorizationReference)
            }
          >
            <Send size={16} />
            {submitting
              ? "Submitting…"
              : selectedResource?.resourceType === "finding"
                ? "Submit evidence-observation note"
                : "Submit for administrator approval"}
          </button>
        </form>
      ) : null}
      {canPropose && !resources.length ? (
        <p className="review-empty">
          {!reviewProposalsAvailable && !observationNotesAvailable
            ? "The administrator has not enabled the scoped review workflow for this product scope."
            : !scope.assessmentAuthorizationReference
              ? "Product assessment verification is pending. Scoped catalog evidence remains read-only; no review proposal can be created."
              : "No source evidence or reviewable candidate record is available for this product scope. A proposal cannot be created."}
        </p>
      ) : null}
    </Card>
  );
}

export function OperationalReviewQueue() {
  const { canDecideReview, operationalEvidenceNotes, reviewProposals } =
    useConsoleAccess();
  const observationNotesAvailable = operationalEvidenceNotes === "enabled";
  const reviewProposalsAvailable = reviewProposals === "enabled";
  const [page, setPage] = useState<ProposalPage | null>(null);
  const [observationPage, setObservationPage] =
    useState<EvidenceNotePage | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [decisionNotes, setDecisionNotes] = useState<Record<string, string>>(
    {},
  );
  const [audit, setAudit] = useState<AuditEvent[] | null>(null);
  const [revision, setRevision] = useState(0);
  const [activeSection, setActiveSection] = useState<QueueSection>(
    queueSectionFromLocation,
  );
  const tabRefs = useRef<Record<QueueSection, HTMLButtonElement | null>>({
    queue: null,
    audit: null,
  });
  const selectSection = useCallback(
    (section: QueueSection) => {
      if (section === activeSection) return;
      const params = new URLSearchParams(window.location.search);
      if (section === "queue") params.delete("section");
      else params.set("section", section);
      const query = params.toString();
      window.history.pushState(
        window.history.state,
        "",
        `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
      );
      setActiveSection(section);
    },
    [activeSection],
  );
  useEffect(() => {
    const restoreSection = () => setActiveSection(queueSectionFromLocation());
    window.addEventListener("popstate", restoreSection);
    return () => window.removeEventListener("popstate", restoreSection);
  }, []);
  const load = useCallback(async () => {
    if (!reviewProposalsAvailable && !observationNotesAvailable) {
      setPage(null);
      setObservationPage(null);
      setAudit(null);
      setError("");
      return;
    }
    setError("");
    try {
      const [proposals, observations, auditPage] = await Promise.all([
        reviewProposalsAvailable
          ? fetchJson<ProposalPage>("/api/v1/admin/review-proposals")
          : Promise.resolve(null),
        observationNotesAvailable
          ? fetchJson<EvidenceNotePage>(
              "/api/v1/admin/operational-evidence-notes",
            )
          : Promise.resolve(null),
        fetchJson<{ items: AuditEvent[] }>("/api/v1/admin/audit?limit=100"),
      ]);
      setPage(
        proposals
          ? {
              ...proposals,
              items: proposals.items.filter(
                (proposal) => proposal.status === "pending",
              ),
              total: proposals.items.filter(
                (proposal) => proposal.status === "pending",
              ).length,
            }
          : null,
      );
      setObservationPage(
        observations
          ? {
              ...observations,
              items: observations.items.filter(
                (observation) => observation.status === "pending",
              ),
              total: observations.items.filter(
                (observation) => observation.status === "pending",
              ).length,
            }
          : null,
      );
      setAudit(
        auditPage.items.filter(
          (event) => event.resource_type === "lead_review_proposal",
        ),
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The review queue is unavailable.",
      );
    }
  }, [observationNotesAvailable, reviewProposalsAvailable]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load, revision]);
  async function decide(
    proposal: OperationalReviewProposal,
    decision: "approved" | "rejected",
  ) {
    if (!canDecideReview) return;
    setBusy(proposal.id);
    setError("");
    try {
      await fetchJson<OperationalReviewProposal>(
        `/api/v1/admin/review-proposals/${encodeURIComponent(proposal.id)}/decision`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision,
            decision_reason: decisionNotes[proposal.id]?.trim() || "",
          }),
        },
      );
      setRevision((value) => value + 1);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The review decision could not be saved.",
      );
    } finally {
      setBusy(null);
    }
  }
  async function decideObservation(
    observation: OperationalEvidenceNote,
    decision: "approved" | "rejected",
  ) {
    if (!canDecideReview) return;
    const noteKey = `observation:${observation.id}`;
    setBusy(noteKey);
    setError("");
    try {
      await fetchJson<OperationalEvidenceNote>(
        `/api/v1/admin/operational-evidence-notes/${encodeURIComponent(observation.id)}/decision`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision,
            reason: decisionNotes[noteKey]?.trim() || "",
          }),
        },
      );
      setRevision((value) => value + 1);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The evidence-observation decision could not be saved.",
      );
    } finally {
      setBusy(null);
    }
  }
  const pending = (page?.total ?? 0) + (observationPage?.total ?? 0);
  const loaded =
    (reviewProposalsAvailable ? Boolean(page) : true) &&
    (!observationNotesAvailable || Boolean(observationPage));
  const workflowsAvailable =
    reviewProposalsAvailable || observationNotesAvailable;
  const selectAdjacentSection = (current: QueueSection, direction: -1 | 1) => {
    const currentIndex = queueSections.findIndex(
      (section) => section.id === current,
    );
    const next =
      queueSections[
        (currentIndex + direction + queueSections.length) % queueSections.length
      ].id;
    selectSection(next);
    tabRefs.current[next]?.focus();
  };
  return (
    <Card className="admin-card operational-review-queue">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Approval queue</p>
          <h2>
            <ClipboardCheck size={18} />
            Operational review records
          </h2>
          <p className="admin-card-note">
            Approve or reject scoped operational records. A decision does not
            alter catalog evidence.
          </p>
        </div>
        <Badge tone={workflowsAvailable && pending ? "warning" : "neutral"}>
          {workflowsAvailable ? (loaded ? pending : "…") : "Disabled"}
          {workflowsAvailable ? " pending" : ""}
        </Badge>
      </div>
      <div
        className="review-section-tabs"
        role="tablist"
        aria-label="Operational review sections"
      >
        {queueSections.map((section) => (
          <button
            key={section.id}
            id={`review-section-${section.id}`}
            ref={(node) => {
              tabRefs.current[section.id] = node;
            }}
            type="button"
            role="tab"
            aria-selected={activeSection === section.id}
            aria-controls={`review-section-panel-${section.id}`}
            tabIndex={activeSection === section.id ? 0 : -1}
            onClick={() => selectSection(section.id)}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
                event.preventDefault();
                selectAdjacentSection(section.id, -1);
              } else if (
                event.key === "ArrowRight" ||
                event.key === "ArrowDown"
              ) {
                event.preventDefault();
                selectAdjacentSection(section.id, 1);
              } else if (event.key === "Home") {
                event.preventDefault();
                selectSection("queue");
                tabRefs.current.queue?.focus();
              } else if (event.key === "End") {
                event.preventDefault();
                selectSection("audit");
                tabRefs.current.audit?.focus();
              }
            }}
          >
            {section.label}
          </button>
        ))}
      </div>
      {activeSection === "queue" ? (
        <section
          id="review-section-panel-queue"
          className="review-section-panel"
          role="tabpanel"
          aria-labelledby="review-section-queue"
        >
          {!canDecideReview ? (
            <p className="review-empty">
              A signed-in human administrator is required to decide records.
              This development session can inspect the queue.
            </p>
          ) : null}
          {!workflowsAvailable ? (
            <p className="review-empty">
              Operational review workflows are disabled. No review records are
              requested.
            </p>
          ) : null}
          {!observationNotesAvailable && workflowsAvailable ? (
            <p className="review-empty">
              Operational evidence-observation notes remain unavailable until
              the API enables the separately scoped note service.
            </p>
          ) : null}
          {error ? (
            <p className="admin-error" role="alert">
              {error}
            </p>
          ) : null}
          {workflowsAvailable && !loaded && !error ? (
            <p className="review-empty">Loading approval queue…</p>
          ) : null}
          {page && !page.items.length ? (
            <p className="review-empty">
              No draft POA&amp;M candidate review proposals are awaiting an
              administrator decision.
            </p>
          ) : null}
          {page?.items.length ? (
            <section
              className="review-queue-list"
              aria-label="Draft POA&M candidate approval queue"
            >
              {page.items.map((proposal) => (
                <article key={proposal.id}>
                  <div>
                    <strong>
                      {proposal.source_collection}/{proposal.service_group}
                    </strong>
                    <small>
                      {proposal.product_scope_id} · requested by{" "}
                      {proposal.submitted_by_email || "Unknown user"} ·{" "}
                      {formatTimestamp(proposal.submitted_at)}
                    </small>
                  </div>
                  <p>{proposal.proposed_note}</p>
                  <small>
                    {proposal.resource_type.replaceAll("_", " ")} ·{" "}
                    {proposal.resource_key} · Rationale: {proposal.rationale}
                  </small>
                  <small>
                    Authorization reference:{" "}
                    {proposal.assessment_authorization_reference ||
                      "Not supplied"}
                  </small>
                  {canDecideReview ? (
                    <>
                      <label>
                        Decision reason
                        <textarea
                          minLength={8}
                          maxLength={2000}
                          required
                          value={decisionNotes[proposal.id] ?? ""}
                          onChange={(event) =>
                            setDecisionNotes((current) => ({
                              ...current,
                              [proposal.id]: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <div className="review-decision-actions">
                        <button
                          className="admin-save"
                          type="button"
                          disabled={
                            busy === proposal.id ||
                            (decisionNotes[proposal.id]?.trim().length ?? 0) < 8
                          }
                          onClick={() => void decide(proposal, "rejected")}
                        >
                          <X size={14} />
                          Reject
                        </button>
                        <button
                          className="primary-button"
                          type="button"
                          disabled={
                            busy === proposal.id ||
                            (decisionNotes[proposal.id]?.trim().length ?? 0) < 8
                          }
                          onClick={() => void decide(proposal, "approved")}
                        >
                          <Check size={15} />
                          {busy === proposal.id ? "Saving…" : "Approve"}
                        </button>
                      </div>
                    </>
                  ) : null}
                </article>
              ))}
            </section>
          ) : null}
          {observationPage && !observationPage.items.length ? (
            <p className="review-empty">
              No operational evidence-observation notes are awaiting an
              administrator decision.
            </p>
          ) : null}
          {observationPage?.items.length ? (
            <section
              className="review-queue-list"
              aria-label="Operational evidence-observation note approval queue"
            >
              <h3>Operational evidence-observation notes</h3>
              {observationPage.items.map((observation) => {
                const noteKey = `observation:${observation.id}`;
                return (
                  <article key={observation.id}>
                    <div>
                      <strong>
                        {observation.source_collection}/
                        {observation.service_group}
                      </strong>
                      <small>
                        {observation.product_scope_id} · requested by{" "}
                        {observation.submitted_by_email || "Unknown user"} ·{" "}
                        {formatTimestamp(observation.submitted_at)}
                      </small>
                    </div>
                    <strong>Operational evidence-observation note</strong>
                    <p>{observation.note}</p>
                    <small>
                      Finding observation {observation.finding_id} · Lead
                      rationale: {observation.lead_rationale}
                    </small>
                    {canDecideReview ? (
                      <>
                        <label>
                          Decision reason
                          <textarea
                            minLength={8}
                            maxLength={2000}
                            required
                            value={decisionNotes[noteKey] ?? ""}
                            onChange={(event) =>
                              setDecisionNotes((current) => ({
                                ...current,
                                [noteKey]: event.target.value,
                              }))
                            }
                          />
                        </label>
                        <div className="review-decision-actions">
                          <button
                            className="admin-save"
                            type="button"
                            disabled={
                              busy === noteKey ||
                              (decisionNotes[noteKey]?.trim().length ?? 0) < 8
                            }
                            onClick={() =>
                              void decideObservation(observation, "rejected")
                            }
                          >
                            <X size={14} />
                            Reject
                          </button>
                          <button
                            className="primary-button"
                            type="button"
                            disabled={
                              busy === noteKey ||
                              (decisionNotes[noteKey]?.trim().length ?? 0) < 8
                            }
                            onClick={() =>
                              void decideObservation(observation, "approved")
                            }
                          >
                            <Check size={15} />
                            {busy === noteKey ? "Saving…" : "Approve"}
                          </button>
                        </div>
                      </>
                    ) : null}
                  </article>
                );
              })}
            </section>
          ) : null}
        </section>
      ) : null}
      {activeSection === "audit" ? (
        <section
          id="review-section-panel-audit"
          className="review-section-panel review-audit"
          role="tabpanel"
          aria-labelledby="review-section-audit"
          aria-label="Draft POA&M candidate review audit"
        >
          <h3>Recent draft POA&amp;M candidate review audit events</h3>
          {audit?.length ? (
            audit.map((event) => (
              <p key={event.id}>
                <code>{event.action}</code>
                <span>
                  {event.actor_email || "Administrator"} ·{" "}
                  {formatTimestamp(event.occurred_at)} · {event.resource_key}
                </span>
              </p>
            ))
          ) : (
            <p className="review-empty">
              No operational review audit events have been recorded.
            </p>
          )}
        </section>
      ) : null}
    </Card>
  );
}

type ScopedAssessment = {
  findings?: Array<{
    finding_id: string;
    title: string;
  }>;
  poam_items?: Array<{ poam_candidate_id: string; title: string }>;
  product_assessment_contract?: {
    candidate_eligible?: boolean;
    exports_allowed?: boolean;
  };
};

export function OperationalReviewWorkspace() {
  const access = useConsoleAccess();
  if (access.isAdmin)
    return (
      <div className="operational-review-workspace">
        <section className="page-heading">
          <div>
            <p className="eyebrow">Operational review</p>
            <h1>Administrator approval</h1>
            <p className="page-subtitle">
              Review operational records and audit events when a workflow is
              enabled.
            </p>
          </div>
        </section>
        <OperationalReviewQueue />
      </div>
    );
  if (!access.productScopedDetailEvidence)
    return (
      <AssignedServiceUnion
        title="Reviews across assigned products"
        description="All verified service grants appear together. Review proposals remain unavailable until exact product evidence and administrator approval workflow are enabled."
      />
    );
  if (access.pairs.length !== 1)
    return (
      <AssignedServiceUnion
        title="Reviews across assigned products"
        description="Every verified service appears together. Review controls depend on the current server-approved capability."
        renderScope={(scope) => <ScopedOperationalReview scope={scope} />}
      />
    );
  if (!access.selected)
    return (
      <section className="scope-gate scope-gate-unavailable" role="alert">
        <ClipboardCheck />
        <div>
          <h1>Service-lead access required</h1>
          <p>No exact service grant is available.</p>
        </div>
      </section>
    );
  return <ScopedOperationalReview scope={access.selected} />;
}

function ScopedOperationalReview({ scope }: { scope: AssignedScopePair }) {
  const access = useConsoleAccess();
  const canPropose =
    access.activeMode === "product_lead" &&
    scope.access === "lead" &&
    (access.reviewProposals === "enabled" ||
      access.operationalEvidenceNotes === "enabled");
  const reviewProposalsAvailable =
    access.reviewProposals === "enabled" &&
    Boolean(scope.assessmentAuthorizationReference);
  const productAssessmentRequestAllowed = Boolean(
    scope.assessmentAuthorizationReference,
  );
  const [resources, setResources] = useState<ReviewResource[]>([]);
  const [resourceError, setResourceError] = useState("");
  const [productContract, setProductContract] = useState<NonNullable<
    ScopedAssessment["product_assessment_contract"]
  > | null>(null);
  const [productContractScopeKey, setProductContractScopeKey] = useState("");
  const productReviewEligibilityAvailable =
    productContractScopeKey === scope?.key &&
    productContract?.candidate_eligible === true;

  useEffect(() => {
    if (
      !canPropose ||
      !access.productScopedDetailEvidence ||
      !productAssessmentRequestAllowed
    )
      return;
    const controller = new AbortController();
    const params = reviewParams(scope);
    params.set("include_findings", "true");
    void fetchJson<ScopedAssessment>(`/api/v1/fips/assessment?${params}`, {
      signal: controller.signal,
    })
      .then((assessment) => {
        setProductContractScopeKey(scope.key);
        setProductContract(assessment.product_assessment_contract ?? null);
        setResources([
          ...(assessment.findings ?? []).map((finding) => ({
            resourceType: "finding" as const,
            resourceKey: finding.finding_id,
            label: `Evidence observation · ${finding.title || finding.finding_id}`,
          })),
          ...(assessment.product_assessment_contract?.candidate_eligible
            ? (assessment.poam_items ?? []).map((candidate) => ({
                resourceType: "poam_candidate" as const,
                resourceKey: candidate.poam_candidate_id,
                label: `Draft POA&M candidate · ${candidate.title || candidate.poam_candidate_id}`,
              }))
            : []),
        ]);
      })
      .catch((caught) => {
        if ((caught as Error).name !== "AbortError")
          setResourceError(
            caught instanceof Error
              ? caught.message
              : "Scoped review items are unavailable.",
          );
      });
    return () => controller.abort();
  }, [
    canPropose,
    access.productScopedDetailEvidence,
    productAssessmentRequestAllowed,
    scope,
  ]);

  if (!canPropose || !scope.productScopeId)
    return (
      <section className="scope-gate scope-gate-unavailable" role="status">
        <ClipboardCheck />
        <div>
          <h2>Read-only product grant</h2>
          <p>
            This service appears in the combined access view, but the selected
            mode does not permit a proposal for this exact product scope.
          </p>
        </div>
      </section>
    );
  return (
    <div className="operational-review-workspace">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Scoped operational review</p>
          <h1>Service review proposals</h1>
          <p className="page-subtitle">
            Proposals are limited to {scope.key}. An administrator other than
            the requester must decide each proposal.
          </p>
          {!productAssessmentRequestAllowed ? (
            <p className="admin-card-note">
              Product assessment verification is pending. Scoped catalog
              evidence remains read-only; FIPS candidates and reviewable
              findings are not requested.
            </p>
          ) : !productReviewEligibilityAvailable ? (
            <p className="admin-card-note">
              Candidate and export eligibility has not been verified for this
              product scope. Evidence-observation notes remain available for
              administrator review when the note service is enabled.
            </p>
          ) : null}
        </div>
      </section>
      {resourceError ? (
        <p className="admin-error" role="alert">
          Scoped review items could not be loaded: {resourceError}
        </p>
      ) : null}
      <OperationalReviewPanel
        scope={scope}
        canPropose
        resources={resources}
        productReviewEligible={productReviewEligibilityAvailable}
        observationNotesAvailable={
          access.operationalEvidenceNotes === "enabled"
        }
        reviewProposalsAvailable={reviewProposalsAvailable}
      />
    </div>
  );
}
