export type RunStatus = "running" | "paused" | "completed" | "failed" | "manual_review";

export interface Scenario {
  id: string;
  description: string;
  expected_terminal_status: string;
  tags: string[];
}

export interface WorkflowState {
  case_id: string;
  run_id: string;
  complaint: string;
  customer_id: string;
  scenario_id: string;
  status: RunStatus;
  current_step: string;
  normalized_complaint?: string;
  duplicate_found?: boolean;
  duplicate_summary?: string;
  billing_validation?: { ok: boolean; summary: string; attempts: number };
  policy_validation?: { ok: boolean; summary: string; attempts: number };
  approval_required: boolean;
  approval_decision?: "approve" | "deny";
  checkpoint_id?: string;
  refund_status: string;
  refund_id?: string;
  notification_status: string;
  notification_summary?: string;
  terminal_status?: string;
  failure_code?: string;
}

export interface DurableEvent {
  sequence: number;
  event_id: string;
  case_id: string;
  run_id: string;
  event_type: string;
  node?: string;
  transition?: string;
  checkpoint_id?: string;
  retry_attempt?: number;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface WorkflowGraph {
  nodes: string[];
  edges: [string, string, string?][];
  parallel_groups: string[][];
}

export interface Outcome {
  duplicate_decision: string;
  policy_decision: string;
  approval_decision: string;
  refund_status: string;
  refund_id?: string;
  notification_status: string;
  terminal_status: string;
  failure_code: string;
}

export interface RunView {
  state: WorkflowState;
  memory: Record<string, unknown>;
  outcome?: Outcome;
  graph: WorkflowGraph;
}

export interface AguiEvent {
  type: string;
  metadata?: { sequence?: number; source?: string };
  [key: string]: unknown;
}
