import { useState } from "react";
import type { WorkflowState } from "../types";

export function ApprovalPanel({
  state,
  onApprove,
  onResume,
  busy
}: {
  state: WorkflowState | null;
  onApprove: (decision: "approve" | "deny", reviewer: string, reason?: string) => Promise<void>;
  onResume: () => Promise<void>;
  busy: boolean;
}) {
  const [reviewer, setReviewer] = useState("reviewer-1");
  const [reason, setReason] = useState("");
  const [recorded, setRecorded] = useState(false);
  if (!state?.approval_required || !state.checkpoint_id) return null;
  return (
    <section className="panel approval-panel" aria-labelledby="approval-title">
      <div>
        <p className="eyebrow">Durable human-in-the-loop</p>
        <h2 id="approval-title">Approval checkpoint</h2>
        <p>
          Recording a decision does not resume execution. The second explicit command restores
          checkpoint <code>{state.checkpoint_id.slice(0, 12)}…</code>.
        </p>
      </div>
      <div className="approval-form">
        <label>
          Reviewer
          <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
        </label>
        <label>
          Optional reason
          <input value={reason} onChange={(event) => setReason(event.target.value)} />
        </label>
        <div className="button-row">
          <button
            disabled={busy || recorded}
            onClick={async () => {
              await onApprove("approve", reviewer, reason || undefined);
              setRecorded(true);
            }}
          >
            Record approval
          </button>
          <button
            className="secondary danger"
            disabled={busy || recorded}
            onClick={async () => {
              await onApprove("deny", reviewer, reason || undefined);
              setRecorded(true);
            }}
          >
            Record denial
          </button>
          <button className="resume" disabled={busy || !recorded} onClick={onResume}>
            Resume checkpoint
          </button>
        </div>
      </div>
    </section>
  );
}

