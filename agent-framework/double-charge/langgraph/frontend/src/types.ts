export type RunStatus =
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "manual_review";

export interface StartResponse {
  case_id: string;
  run_id: string;
  status: RunStatus;
  current_step: string;
  approval_required: boolean;
  checkpoint_id?: string | null;
}

export interface Outcome {
  case_id: string;
  run_id: string;
  duplicate_decision: string;
  policy_decision: string;
  approval_decision: string;
  refund_status: string;
  refund_id?: string | null;
  notification_status: string;
  terminal_status: string;
  failure_code?: string | null;
  event_summary: string[];
}

export interface CaseView extends StartResponse {
  workflow_state: Record<string, unknown>;
  selected_memory: Record<string, unknown>;
  outcome?: Outcome;
}

export interface NativeEvent {
  sequence: number;
  event_id: string;
  case_id: string;
  run_id: string;
  event_type: string;
  timestamp: string;
  node?: string | null;
  status?: string | null;
  summary: string;
  data: Record<string, unknown>;
}

export interface AguiEvent {
  type: string;
  runId: string;
  sequence: number;
  [key: string]: unknown;
}

export interface Scenario {
  id: string;
  label: string;
  description?: string;
}

export interface WorkflowState {
  case_id: string;
  run_id: string;
  customer_id: string;
  scenario_id: string | null;
  complaint: string | null;
  status: RunStatus;
  current_step: string;
  checkpoint_id: string | null;
  approval_required: boolean;
  updated_at: string;
  normalized_complaint?: string | null;
  duplicate_decision?: string | null;
  validation_results?: { billing?: { ok: boolean; code?: string | null; summary: string } | null;
    policy?: { ok: boolean; code?: string | null; summary: string } | null };
  approval_decision?: string | null;
  refund_attempts?: number | null;
  refund_status?: string | null;
  refund_id?: string | null;
  notification_status?: string | null;
  failure_code?: string | null;
  terminal_status?: string | null;
  safe_summaries?: string[];
}

export interface Approval {
  checkpoint_id: string | null;
  decision: "approve" | "deny";
  reviewer_id: string;
  reason: string | null;
  decided_at: string | null;
  consumed: boolean;
}

export interface WorkflowGraph {
  nodes: { id: string; label: string }[];
  edges: { source: string; target: string; label?: string | null }[];
  parallel_groups: string[][];
}

export interface Workspace {
  state: WorkflowState;
  memory: Record<string, unknown>;
  outcome: Outcome | null;
  approval: Approval | null;
  can_resume: boolean;
  can_record_approval: boolean;
  created_at: string;
  node_statuses: Record<string, "pending" | "running" | "completed" | "failed" | "paused" | "skipped">;
  graph: WorkflowGraph;
}

export interface CaseSummary {
  case_id: string;
  run_id: string;
  customer_id: string;
  scenario_id: string | null;
  status: RunStatus;
  current_step: string;
  terminal_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface CasePage {
  items: CaseSummary[];
  has_more: boolean;
  next_cursor: string | null;
}
