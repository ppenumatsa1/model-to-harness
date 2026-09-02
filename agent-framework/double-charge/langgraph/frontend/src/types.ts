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
  checkpoint_id?: string;
}

export interface Outcome {
  case_id: string;
  run_id: string;
  duplicate_decision: string;
  policy_decision: string;
  approval_decision: string;
  refund_status: string;
  refund_id?: string;
  notification_status: string;
  terminal_status: string;
  failure_code?: string;
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
  node?: string;
  status?: string;
  summary: string;
  data: Record<string, unknown>;
}

export interface AguiEvent {
  type: string;
  runId: string;
  sequence: number;
  [key: string]: unknown;
}

