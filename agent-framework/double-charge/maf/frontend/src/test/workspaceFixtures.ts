import type { CaseSummary, DurableEvent, RunView } from "../types";

export function viewFor(id: string, overrides: Partial<RunView> = {}): RunView {
  return {
    state: {
      case_id: id, run_id: `run-${id}`, customer_id: `customer-${id}`,
      scenario_id: "duplicate-confirmed", complaint: `Complaint for ${id}`,
      status: "running", current_step: "normalize_case", approval_required: false,
      refund_status: "not_started", notification_status: "not_started"
    },
    memory: { customer_id: `customer-${id}` },
    outcome: null, approval: null, can_resume: false, can_record_approval: false,
    created_at: "2026-09-16T10:00:00Z", node_statuses: {},
    graph: { nodes: [], edges: [], parallel_groups: [] },
    ...overrides
  };
}

export function summaryFor(index: number): CaseSummary {
  const view = viewFor(`case-${index}`);
  return {
    ...view.state,
    terminal_status: null,
    created_at: new Date(Date.UTC(2026, 8, 16, 10, 0, 60 - index)).toISOString(),
    updated_at: view.created_at
  };
}

export function eventFor(id: string, sequence = 1): DurableEvent {
  return {
    case_id: id, run_id: `run-${id}`, sequence, event_id: `${id}-event-${sequence}`,
    event_type: "node.started", node: "normalize_case",
    summary: `Normalizing complaint for ${id}`,
    payload: { audit_version: 2, actor_type: "system", actor_id: "maf-workflow", actor_source: "system" },
    created_at: "2026-09-16T10:01:00Z"
  };
}

export function businessEvent(eventType: string, sequence: number, payload: Record<string, unknown> = {}, node?: string): DurableEvent {
  const human = ["run.started", "approval.recorded", "workflow.resumed"].includes(eventType);
  return {
    ...eventFor("case-25", sequence), event_type: eventType, node,
    payload: {
      audit_version: 2, actor_type: human ? "human" : "system",
      actor_id: human ? `${eventType === "approval.recorded" ? "reviewer" : "operator"}-test` : "maf-workflow",
      actor_source: human ? "operator_supplied" : "system", ...payload
    }
  };
}

export class MockEventSource {
  static instances: MockEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  listeners = new Map<string, (event: MessageEvent) => void>();
  closed = false;
  constructor(public url: string) { MockEventSource.instances.push(this); }
  addEventListener(type: string, callback: (event: MessageEvent) => void) {
    this.listeners.set(type, callback);
  }
  close() { this.closed = true; }
  emit(type: string, data: unknown) {
    this.listeners.get(type)?.(new MessageEvent(type, { data: JSON.stringify(data) }));
  }
  fail() { this.onerror?.(new Event("error")); }
  static latest() { return MockEventSource.instances.at(-1)!; }
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
