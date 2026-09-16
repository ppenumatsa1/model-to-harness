import type { CaseSummary, NativeEvent, Workspace } from "../src/types";

export function viewFor(id: string, overrides: Partial<Workspace> = {}): Workspace {
  return {
    state: {
      case_id: id, run_id: `run-${id}`, customer_id: `customer-${id}`,
      scenario_id: "duplicate-confirmed", complaint: `Complaint for ${id}`,
      status: "running", current_step: "normalize_complaint", approval_required: false,
      checkpoint_id: null, updated_at: "2026-09-16T10:00:00Z",
      refund_status: "not_requested", notification_status: "not_sent"
    },
    memory: {}, outcome: null, approval: null, can_resume: false, can_record_approval: false,
    created_at: "2026-09-16T10:00:00Z", node_statuses: {},
    graph: {
      nodes: [{ id: "billing_validation", label: "billing validation" }, { id: "policy_validation", label: "policy validation" }],
      edges: [{ source: "billing_validation", target: "join_validations" }],
      parallel_groups: [["billing_validation", "policy_validation"]]
    },
    ...overrides
  };
}

export function summaryFor(index: number): CaseSummary {
  const view = viewFor(`case-${index}`);
  return { ...view.state, terminal_status: null,
    created_at: new Date(Date.UTC(2026, 8, 16, 10, 0, 60 - index)).toISOString(),
    updated_at: view.created_at };
}

export function eventFor(id: string, sequence = 1): NativeEvent {
  return {
    case_id: id, run_id: `run-${id}`, sequence, event_id: `${id}-event-${sequence}`,
    event_type: "tool_call_started", node: "normalize_complaint",
    summary: `Normalizing complaint for ${id}`,
    data: { audit_version: 2, actor_type: "system", actor_id: "langgraph-workflow", actor_source: "system" },
    timestamp: "2026-09-16T10:01:00Z"
  };
}

export function businessEvent(type: string, sequence: number, data: Record<string, unknown> = {}, node?: string): NativeEvent {
  const human = ["run_started", "approval_command_recorded", "resume_command_recorded"].includes(type);
  return {
    ...eventFor("case-25", sequence), event_type: type, node,
    data: { audit_version: 2, actor_type: human ? "human" : "system",
      actor_id: human ? `${type === "approval_command_recorded" ? "reviewer" : "operator"}-test` : "langgraph-workflow",
      actor_source: human ? "operator_supplied" : "system", ...data }
  };
}

export class MockEventSource {
  static instances: MockEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  listeners = new Map<string, (event: MessageEvent) => void>();
  closed = false;
  constructor(public url: string) { MockEventSource.instances.push(this); }
  addEventListener(type: string, callback: (event: MessageEvent) => void) { this.listeners.set(type, callback); }
  close() { this.closed = true; }
  emit(type: string, data: unknown) { this.listeners.get(type)?.(new MessageEvent(type, { data: JSON.stringify(data) })); }
  fail() { this.onerror?.(new Event("error")); }
  static latest() { return MockEventSource.instances.at(-1)!; }
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
