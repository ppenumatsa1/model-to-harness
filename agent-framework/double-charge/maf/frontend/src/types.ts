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
  billing_validation?: BranchView | null;
  policy_validation?: BranchView | null;
  approval_required: boolean;
  approval_decision?: "approve" | "deny";
  checkpoint_id?: string;
  refund_status: string;
  refund_id?: string;
  notification_status: string;
  notification_summary?: string;
  terminal_status?: string;
  failure_code?: string;
  updated_at?: string;
}

export type SafeDetail = string | number | boolean | string[] | null;

export interface BranchView {
  branch: string;
  ok: boolean;
  summary: string;
  attempts: number;
  failure_code?: string | null;
  evidence: Record<string, SafeDetail>;
}

export interface DurableEvent {
  sequence: number;
  event_id: string;
  case_id: string;
  run_id: string;
  event_type: string;
  node?: string | null;
  transition?: string | null;
  checkpoint_id?: string | null;
  retry_attempt?: number | null;
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
  memory: Record<string, string>;
  outcome?: Outcome | null;
  approval: Approval | null;
  can_resume: boolean;
  can_record_approval: boolean;
  created_at: string;
  node_statuses: Record<string, string>;
  graph: WorkflowGraph;
}

export interface Approval {
  decision: "approve" | "deny";
  reviewer_id: string;
  reason: string | null;
  decided_at: string;
  checkpoint_id: string | null;
}

export interface CaseSummary {
  case_id: string;
  run_id: string;
  customer_id: string;
  scenario_id: string;
  status: RunStatus;
  current_step: string;
  approval_required: boolean;
  terminal_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface CasePage {
  items: CaseSummary[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface AguiEvent {
  type: string;
  metadata?: { sequence?: number; source?: string };
  [key: string]: unknown;
}
