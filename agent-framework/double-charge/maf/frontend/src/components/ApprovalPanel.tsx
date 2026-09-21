import { useEffect, useState } from "react";
import type { RunView } from "../types";

export function ApprovalPanel({ run, onApprove, onResume, busy }: {
  run: RunView | null;
  onApprove: (decision: "approve" | "deny", reviewer: string, reason: string) => Promise<void>;
  onResume: (operatorId: string) => Promise<void>;
  busy: boolean;
}) {
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [resumeOperator, setResumeOperator] = useState("");
  useEffect(() => {
    setReviewer("");
    setReason("");
  }, [run?.state.run_id, run?.state.checkpoint_id, run?.approval?.decided_at]);
  useEffect(() => {
    setResumeOperator("");
  }, [run?.state.run_id, run?.state.checkpoint_id, run?.can_resume]);
  if (!run || (!run.state.approval_required && !run.approval)) return null;
  const invalid = !reviewer.trim() || !reason.trim();
  return (
    <section className="panel approval-panel" aria-labelledby="approval-title">
      <div>
        <p className="eyebrow">Durable human-in-the-loop</p>
        <h2 id="approval-title">Approval checkpoint</h2>
        <p>Recording a decision does not resume execution. Resume is a separate explicit command.</p>
        {run.approval && <div className="recorded-approval">
          <p>Persisted decision: <strong>{run.approval.decision}</strong></p>
          <p>Reviewer: {run.approval.reviewer_id}</p>
          <p>Reason: {run.approval.reason ?? "Not recorded (historical approval)"}</p>
          <time dateTime={run.approval.decided_at}>{new Date(run.approval.decided_at).toLocaleString()}</time>
        </div>}
      </div>
      <div className="approval-form">
        {run.can_record_approval && <>
          <label>Reviewer
            <input required maxLength={128} disabled={busy} value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
          </label>
          <label>Reason
            <input required maxLength={1000} disabled={busy} value={reason} onChange={(event) => setReason(event.target.value)} />
          </label>
        </>}
        {run.can_resume && <><label>Resume operator
          <input required maxLength={128} value={resumeOperator} disabled={busy} aria-describedby="resume-operator-note"
            onChange={(event) => setResumeOperator(event.target.value)} />
        </label>
          <p id="resume-operator-note">Operator-provided identity; not authenticated. Enter the person requesting this resume.</p>
        </>}
        <div className="button-row">
          <button disabled={busy || !run.can_record_approval || invalid}
            onClick={() => void onApprove("approve", reviewer.trim(), reason.trim())}>Record approval</button>
          <button className="secondary danger" disabled={busy || !run.can_record_approval || invalid}
            onClick={() => void onApprove("deny", reviewer.trim(), reason.trim())}>Record denial</button>
          <button className="resume" disabled={busy || !run.can_resume || !resumeOperator.trim()}
            onClick={() => void onResume(resumeOperator.trim())}>Resume checkpoint</button>
        </div>
      </div>
    </section>
  );
}
