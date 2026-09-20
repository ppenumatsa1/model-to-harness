export type ApprovalDecision = "not_required" | "pending" | "approved" | "denied";
export type CasePhase = "open" | "waiting_approval" | "closed";

export interface WorkspaceArtifact {
  artifact_id: string;
  kind: string;
  revision: number;
  updated_at: string;
}

export interface CheckoutCase {
  case_id: string;
  run_id: string;
  fixture_id: string;
  phase: CasePhase;
  diagnostic_disposition: string | null;
  diagnostic_tools?: string[];
  harness_mode?: string;
  approval_decision: ApprovalDecision;
  approval_request_id: string | null;
  remediation_action: string | null;
  remediation_status: string | null;
  verification_result: boolean | null;
  terminal_status: string | null;
  failure_code: string;
  workspace_artifact: WorkspaceArtifact;
}

export interface SafeAuditEvent {
  code: string;
  occurred_at: string;
  summary: string;
}

export interface ApprovalCommand {
  approval_request_id: string;
  decision: Extract<ApprovalDecision, "approved" | "denied">;
  reviewer_id: string;
  reason: string;
}

export interface FixtureOption {
  id: string;
  label: string;
  description: string;
}
