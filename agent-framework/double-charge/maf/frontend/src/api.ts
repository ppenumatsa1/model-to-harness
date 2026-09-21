import type {
  AguiEvent,
  CasePage,
  DurableEvent,
  RunView,
  Scenario,
  WorkflowGraph
} from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) {
    super(message);
  }
}

async function json<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(
      typeof body.detail === "string" ? body.detail
        : typeof body.detail?.message === "string" ? body.detail.message : `Request failed: ${response.status}`,
      response.status,
      typeof body.detail?.code === "string" ? body.detail.code : undefined
    );
  }
  return response.json() as Promise<T>;
}

export interface StartPayload {
  request_id?: string;
  complaint: string;
  customer_id: string;
  scenario_id: string;
  operator_id: string;
  existing_case_id: string;
  idempotency_key: string;
}

export const api = {
  scenarios: () => json<Scenario[]>("/api/scenarios"),
  graph: () => json<WorkflowGraph>("/api/workflow/graph"),
  cases: (cursor?: string, signal?: AbortSignal) =>
    json<CasePage>(`/api/cases?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, { signal }),
  case: (caseId: string, signal?: AbortSignal) =>
    json<RunView>(`/api/cases/${encodeURIComponent(caseId)}`, { signal }),
  start: (payload: StartPayload) =>
    json<{
      case_id: string;
      run_id: string;
      status: string;
      current_step: string;
      approval_required: boolean;
      checkpoint_id?: string;
    }>("/api/cases", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload)
    }),
  run: (runId: string, signal?: AbortSignal) => json<RunView>(`/api/runs/${runId}`, { signal }),
  events: (runId: string, after = 0) =>
    json<DurableEvent[]>(`/api/runs/${runId}/events?after=${after}&limit=200`),
  approve: (
    runId: string,
    payload: {
      checkpoint_id: string;
      decision: "approve" | "deny";
      reviewer_id: string;
      reason: string;
    }
  ) =>
    json(`/api/runs/${runId}/approval`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload)
    }),
  resume: (runId: string, checkpointId: string, operatorId: string) =>
    json(`/api/runs/${runId}/resume`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ checkpoint_id: checkpointId, operator_id: operatorId })
    })
};

export function parseAguiSse(text: string): {
  events: AguiEvent[];
  malformed: number;
  lastSequence: number;
} {
  const events: AguiEvent[] = [];
  let malformed = 0;
  let lastSequence = 0;
  for (const block of text.split("\n\n")) {
    const id = block
      .split("\n")
      .find((line) => line.startsWith("id:"))
      ?.slice(3)
      .trim();
    const data = block
      .split("\n")
      .find((line) => line.startsWith("data:"))
      ?.slice(5)
      .trim();
    if (!data) continue;
    try {
      const event = JSON.parse(data) as AguiEvent;
      if (typeof event.type !== "string") throw new Error("missing AG-UI type");
      events.push(event);
      if (id && Number.isFinite(Number(id))) lastSequence = Math.max(lastSequence, Number(id));
    } catch {
      malformed += 1;
    }
  }
  return { events, malformed, lastSequence };
}

export async function fetchAgui(
  runId: string,
  after = 0
): Promise<{ events: AguiEvent[]; malformed: number; lastSequence: number }> {
  const response = await fetch(`/api/runs/${runId}/ag-ui?after=${after}`);
  if (!response.ok) throw new Error("AG-UI projection is disconnected");
  return parseAguiSse(await response.text());
}
