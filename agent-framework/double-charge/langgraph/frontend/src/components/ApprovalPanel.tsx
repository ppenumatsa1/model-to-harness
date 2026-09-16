import { useEffect, useState } from "react";
import type { Workspace } from "../types";

export function ApprovalPanel({ run, onApprove, onResume, busy }: {
  run?: Workspace;
  onApprove: (decision: "approve" | "deny", reviewer: string, reason: string) => Promise<void>;
  onResume: (operator: string) => Promise<void>;
  busy: boolean;
}) {
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [operator, setOperator] = useState("");
  useEffect(() => { setReviewer(""); setReason(""); }, [
    run?.state.run_id, run?.state.checkpoint_id, run?.approval?.decided_at, run?.can_record_approval
  ]);
  useEffect(() => setOperator(""), [run?.state.run_id, run?.state.checkpoint_id, run?.can_resume]);
  if (!run || (!run.state.approval_required && !run.approval)) return null;
  const paused = run.state.status === "paused";
  const canRecord = paused && run.can_record_approval;
  const canResume = paused && run.can_resume;
  const invalid = !reviewer.trim() || !reason.trim();
  return <section className="panel approval-panel" aria-labelledby="approval-title">
    <h2 id="approval-title">Approval checkpoint</h2>
    <p>Recording a decision does not resume execution. Resume is a separate explicit command.</p>
    {run.approval && <div className="recorded-approval">
      <p>Persisted decision: <strong>{run.approval.decision}</strong></p>
      <p>Reviewer: {run.approval.reviewer_id || "Not recorded"}</p>
      <p>Reason: {run.approval.reason ?? "Not recorded (historical approval)"}</p>
      {run.approval.decided_at ? <time dateTime={run.approval.decided_at}>{new Date(run.approval.decided_at).toLocaleString()}</time>
        : <p>Decision time: Not recorded</p>}
    </div>}
    <div className="approval-form">
      {canRecord && <>
        <label>Reviewer<input required maxLength={128} disabled={busy} value={reviewer} onChange={(e) => setReviewer(e.target.value)} /></label>
        <label>Reason<textarea required maxLength={1000} disabled={busy} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      </>}
      {canResume && <>
        <label>Resume operator<input required maxLength={128} disabled={busy} value={operator} onChange={(e) => setOperator(e.target.value)} /></label>
        <p className="boundary-note">Operator-provided identity; not authenticated.</p>
      </>}
      <div className="button-row">
        <button disabled={busy || !canRecord || invalid} onClick={() => void onApprove("approve", reviewer.trim(), reason.trim())}>Record approval</button>
        <button disabled={busy || !canRecord || invalid} onClick={() => void onApprove("deny", reviewer.trim(), reason.trim())}>Record denial</button>
        <button disabled={busy || !canResume || !operator.trim()} onClick={() => void onResume(operator.trim())}>Resume checkpoint</button>
      </div>
    </div>
  </section>;
}
