import { useEffect, useRef, useState } from "react";
import { ApiError, checkoutApi, loadCaseWorkspace } from "./api";
import { browserIntentStore, selectCaseUrl, selectedCaseId } from "./persistence";
import { canResume, completedProgress, humanize, needsApproval, progressLabel, toolLabel } from "./state";
import { caseStatus } from "./status";
import type { CheckoutCase, FixtureOption, SafeAuditEvent, WorkspaceArtifact } from "./types";

const fixtures: FixtureOption[] = [
  {
    id: "recoverable-inventory-reservation",
    label: "Recover inventory reservation",
    description: "Recreates an expired inventory reservation."
  },
  {
    id: "captured-payment-approved-remediation",
    label: "Captured payment requires approval",
    description: "Pauses for a reviewer before the customer-impacting remediation."
  },
  {
    id: "payment-pending-manual-review",
    label: "Pending payment manual review",
    description: "Routes an ambiguous payment to manual review."
  },
  {
    id: "diagnostic-read-failure",
    label: "Diagnostic read failure",
    description: "Reports a deterministic diagnostic failure safely."
  },
  {
    id: "denied-approval",
    label: "Denied approval",
    description: "Closes the case without remediation when a reviewer denies it."
  },
  {
    id: "uncertain-remediation-recovery",
    label: "Uncertain remediation recovery",
    description: "Recovers a remediable response through durable verification."
  },
  {
    id: "verification-mismatch",
    label: "Verification mismatch",
    description: "Routes a mismatching authoritative state to manual review."
  }
];

function safeErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The command could not be completed. Please try again.";
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Unavailable" : date.toLocaleString();
}

function Value({ children }: { children: string | number | boolean | null }) {
  if (children === null) return <span className="muted">Not available</span>;
  return <span>{typeof children === "boolean" ? (children ? "Verified" : "Not verified") : children}</span>;
}

export default function App() {
  const [startIntents] = useState(browserIntentStore);
  const [retryStart, setRetryStart] = useState(Boolean(startIntents.current));
  const [fixtureId, setFixtureId] = useState(startIntents.current?.fixture_id ?? fixtures[0].id);
  const [initialCaseId] = useState(() => selectedCaseId(new URL(window.location.href)));
  const [caseRecord, setCaseRecord] = useState<CheckoutCase | null>(null);
  const [events, setEvents] = useState<SafeAuditEvent[]>([]);
  const [artifact, setArtifact] = useState<WorkspaceArtifact | null>(null);
  const [reviewerId, setReviewerId] = useState("");
  const [reviewReason, setReviewReason] = useState("Reviewed checkout remediation");
  const [busy, setBusy] = useState(Boolean(initialCaseId));
  const commandInFlight = useRef(false);
  const [error, setError] = useState<string | null>(null);

  const status = caseStatus(caseRecord);
  const selectedFixture = fixtures.find((fixture) => fixture.id === fixtureId);
  const progress = completedProgress(events);

  useEffect(() => {
    if (!initialCaseId) return;
    let active = true;
    void loadCaseWorkspace(initialCaseId)
      .then((workspace) => {
        if (!active) return;
        setCaseRecord(workspace.case);
        setEvents(workspace.events);
        setArtifact(workspace.artifact);
      })
      .catch((reason: unknown) => {
        if (active) setError(safeErrorMessage(reason));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => { active = false; };
  }, [initialCaseId]);

  async function refresh(caseId = caseRecord?.case_id): Promise<void> {
    if (!caseId) return;
    const workspace = await loadCaseWorkspace(caseId);
    setCaseRecord(workspace.case);
    setEvents(workspace.events);
    setArtifact(workspace.artifact);
  }

  async function perform(command: () => Promise<CheckoutCase>): Promise<void> {
    if (commandInFlight.current) return;
    commandInFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const updatedCase = await command();
      if (updatedCase.case_id !== caseRecord?.case_id) {
        setEvents([]);
        setArtifact(null);
        setReviewerId("");
      }
      setCaseRecord(updatedCase);
      window.history.replaceState(null, "", selectCaseUrl(new URL(window.location.href), updatedCase.case_id));
      await refresh(updatedCase.case_id);
    } catch (reason) {
      setError(safeErrorMessage(reason));
    } finally {
      commandInFlight.current = false;
      setBusy(false);
    }
  }

  function startCase(): void {
    void perform(async () => {
      const intent = startIntents.begin(fixtureId);
      try {
        const started = await checkoutApi.start(fixtureId, intent.request_id);
        startIntents.complete();
        setRetryStart(false);
        return started;
      } catch (reason) {
        const canRetry = !(reason instanceof ApiError) || reason.status >= 500 || reason.status === 408;
        if (!canRetry) startIntents.complete();
        setRetryStart(canRetry);
        throw reason;
      }
    });
  }

  function recordApproval(decision: "approved" | "denied"): void {
    if (!caseRecord?.approval_request_id || !reviewerId.trim() || !reviewReason.trim()) {
      setError("A pending approval request, reviewer ID, and reason are required.");
      return;
    }
    void perform(() =>
      checkoutApi.approval(caseRecord.case_id, {
        approval_request_id: caseRecord.approval_request_id!,
        decision,
        reviewer_id: reviewerId.trim(),
        reason: reviewReason.trim()
      })
    );
  }

  function resumeCase(): void {
    if (!caseRecord) return;
    void perform(() => checkoutApi.resume(caseRecord.case_id));
  }

  async function refreshSelectedCase(): Promise<void> {
    if (commandInFlight.current) return;
    commandInFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await refresh(caseRecord?.case_id ?? initialCaseId ?? undefined);
    } catch (reason) {
      setError(safeErrorMessage(reason));
    } finally {
      commandInFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Microsoft Agent Framework · recovery workspace</p>
          <h1>Checkout recovery</h1>
          <p className="intro">
            Run deterministic fixtures and review durable, safe workflow metadata.
          </p>
        </div>
        <div className={`status-badge ${status.tone}`} role="status">
          <span aria-hidden="true" />
          {status.label}
        </div>
      </header>

      <section className="card start-card" aria-labelledby="start-title">
        <div>
          <p className="eyebrow">New recovery case</p>
          <h2 id="start-title">Start a fixture</h2>
          <p>{selectedFixture?.description}</p>
        </div>
        <div className="start-form">
          <label htmlFor="fixture">Fixture</label>
          <select
            id="fixture"
            value={fixtureId}
            disabled={busy}
            onChange={(event) => {
              setFixtureId(event.target.value);
              setRetryStart(startIntents.current?.fixture_id === event.target.value);
            }}
          >
            {fixtures.map((fixture) => (
              <option key={fixture.id} value={fixture.id}>
                {fixture.label}
              </option>
            ))}
          </select>
          <button type="button" className="button primary" disabled={busy} onClick={startCase}>
            {busy ? "Working…" : retryStart ? "Retry start" : "Start recovery"}
          </button>
          {retryStart && <p className="muted">Retries reuse the same durable start request.</p>}
        </div>
      </section>

      {error && (
        <div className="error-banner" role="alert">
          {error}
          {initialCaseId && !caseRecord && (
            <button type="button" className="button secondary" disabled={busy} onClick={() => void refreshSelectedCase()}>
              Retry loading case
            </button>
          )}
        </div>
      )}

      {caseRecord && (
        <>
          <section className="card summary-card" aria-labelledby="case-title">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Selected case</p>
                <h2 id="case-title">{caseRecord.fixture_id}</h2>
              </div>
              <button
                type="button"
                className="button secondary"
                disabled={busy}
                onClick={() => void refreshSelectedCase()}
              >
                Refresh
              </button>
            </div>
            <p className="progress-label">{progressLabel(caseRecord, events)}</p>
            <ol className="progress" aria-label="Recovery progress">
              {(["case_started", "diagnostic", "approval", "remediation", "verification", "outcome"] as const).map(
                (step) => (
                  <li
                    key={step}
                    className={
                      progress.includes(step)
                        ? "complete"
                        : step === "approval" && needsApproval(caseRecord)
                          ? "current"
                          : ""
                    }
                  >
                    {humanize(step)}
                  </li>
                )
              )}
            </ol>
            <dl className="metadata-grid">
              <div>
                <dt>Case ID</dt>
                <dd>{caseRecord.case_id}</dd>
              </div>
              <div>
                <dt>Run ID</dt>
                <dd>{caseRecord.run_id}</dd>
              </div>
              <div>
                <dt>Phase</dt>
                <dd>{humanize(caseRecord.phase)}</dd>
              </div>
              <div>
                <dt>Diagnostic</dt>
                <dd><Value>{caseRecord.diagnostic_disposition && humanize(caseRecord.diagnostic_disposition)}</Value></dd>
              </div>
              {caseRecord.harness_mode && (
                <div>
                  <dt>Harness mode</dt>
                  <dd>{humanize(caseRecord.harness_mode)}</dd>
                </div>
              )}
              {caseRecord.diagnostic_tools && (
                <div>
                  <dt>Diagnostic tools</dt>
                  <dd>{caseRecord.diagnostic_tools.map(humanize).join(", ") || "None"}</dd>
                </div>
              )}
            </dl>
          </section>

          {needsApproval(caseRecord) && (
            <section className="card approval-card" aria-labelledby="approval-title">
              <div>
                <p className="eyebrow">Durable command boundary</p>
                <h2 id="approval-title">Reviewer approval required</h2>
                <p>Record an approval or denial first. Resume is a separate command.</p>
              </div>
              <div className="approval-actions">
                <label htmlFor="reviewer">Reviewer ID</label>
                <input
                  id="reviewer"
                  value={reviewerId}
                  maxLength={120}
                  disabled={busy}
                  onChange={(event) => setReviewerId(event.target.value)}
                />
                <label htmlFor="review-reason">Review reason</label>
                <input
                  id="review-reason"
                  value={reviewReason}
                  maxLength={500}
                  disabled={busy}
                  onChange={(event) => setReviewReason(event.target.value)}
                />
                {!caseRecord.approval_request_id && (
                  <p role="alert">The approval request is unavailable. Refresh before recording a decision.</p>
                )}
                <div>
                  <button
                    type="button"
                    className="button primary"
                    disabled={busy || !caseRecord.approval_request_id || !reviewerId.trim() || !reviewReason.trim()}
                    onClick={() => recordApproval("approved")}
                  >
                    Record approval
                  </button>
                  <button
                    type="button"
                    className="button danger"
                    disabled={busy || !caseRecord.approval_request_id || !reviewerId.trim() || !reviewReason.trim()}
                    onClick={() => recordApproval("denied")}
                  >
                    Record denial
                  </button>
                </div>
              </div>
            </section>
          )}

          {canResume(caseRecord) && (
            <section className="card resume-card" aria-labelledby="resume-title">
              <div>
                <p className="eyebrow">Next explicit command</p>
                <h2 id="resume-title">Decision recorded</h2>
                <p>Resume only after the durable reviewer decision is recorded.</p>
              </div>
              <button type="button" className="button primary" disabled={busy} onClick={resumeCase}>
                Resume recovery
              </button>
            </section>
          )}

          <div className="workspace-grid">
            <section className="card" aria-labelledby="tool-title">
              <p className="eyebrow">Safe audit projection</p>
              <h2 id="tool-title">Tool activity and events</h2>
              {events.length === 0 ? (
                <p className="muted">No safe event metadata is available.</p>
              ) : (
                <ol className="event-list">
                  {events.map((event, index) => (
                    <li key={`${event.code}-${event.occurred_at}-${index}`}>
                      <strong>{toolLabel(event.code)}</strong>
                      <span>{humanize(event.code)}</span>
                      <p>{event.summary}</p>
                      <time dateTime={event.occurred_at}>{formatDate(event.occurred_at)}</time>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <section className="card" aria-labelledby="outcome-title">
              <p className="eyebrow">Evidence and outcome</p>
              <h2 id="outcome-title">Recovery result</h2>
              <dl className="result-list">
                <div>
                  <dt>Approval decision</dt>
                  <dd>{humanize(caseRecord.approval_decision)}</dd>
                </div>
                <div>
                  <dt>Remediation action</dt>
                  <dd><Value>{caseRecord.remediation_action && humanize(caseRecord.remediation_action)}</Value></dd>
                </div>
                <div>
                  <dt>Remediation status</dt>
                  <dd><Value>{caseRecord.remediation_status && humanize(caseRecord.remediation_status)}</Value></dd>
                </div>
                <div>
                  <dt>Verification evidence</dt>
                  <dd><Value>{caseRecord.verification_result}</Value></dd>
                </div>
                <div>
                  <dt>Outcome</dt>
                  <dd><Value>{caseRecord.terminal_status && humanize(caseRecord.terminal_status)}</Value></dd>
                </div>
                <div>
                  <dt>Failure code</dt>
                  <dd>{humanize(caseRecord.failure_code)}</dd>
                </div>
              </dl>

              <h3>Workspace artifact</h3>
              <dl className="result-list artifact-list">
                <div>
                  <dt>Artifact ID</dt>
                  <dd>{artifact?.artifact_id ?? caseRecord.workspace_artifact.artifact_id}</dd>
                </div>
                <div>
                  <dt>Kind</dt>
                  <dd>{humanize(artifact?.kind ?? caseRecord.workspace_artifact.kind)}</dd>
                </div>
                <div>
                  <dt>Revision</dt>
                  <dd>{artifact?.revision ?? caseRecord.workspace_artifact.revision}</dd>
                </div>
                <div>
                  <dt>Updated</dt>
                  <dd>{formatDate(artifact?.updated_at ?? caseRecord.workspace_artifact.updated_at)}</dd>
                </div>
              </dl>
            </section>
          </div>
        </>
      )}
    </main>
  );
}
