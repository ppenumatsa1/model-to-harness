import type { CasePage, CaseView, NativeEvent, Scenario, StartResponse, Workspace } from "./types";

const JSON_HEADERS = { "Content-Type": "application/json" };

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function checked<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new ApiError(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`, response.status);
  }
  return response.json() as Promise<T>;
}

export async function startCase(input: {
  complaint: string;
  customer_id: string;
  scenario_id: string;
  operator_id: string;
  existing_case_id: string;
  idempotency_key: string;
}): Promise<StartResponse> {
  return checked(
    await fetch("/api/cases", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(input)
    })
  );
}

export async function getCase(caseId: string): Promise<CaseView> {
  return checked(await fetch(`/api/cases/${encodeURIComponent(caseId)}`));
}

export async function getEvents(caseId: string): Promise<NativeEvent[]> {
  return checked(await fetch(`/api/cases/${encodeURIComponent(caseId)}/events`));
}

export async function recordApproval(
  caseId: string,
  checkpointId: string,
  decision: "approve" | "deny",
  reviewerId: string,
  reason: string
): Promise<void> {
  await checked(
    await fetch(`/api/cases/${encodeURIComponent(caseId)}/approval`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({
        checkpoint_id: checkpointId,
        decision,
        reviewer_id: reviewerId,
        reason
      })
    })
  );
}

export async function resumeCase(caseId: string, checkpointId: string, operatorId: string): Promise<StartResponse> {
  return checked(
    await fetch(`/api/cases/${encodeURIComponent(caseId)}/resume`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ checkpoint_id: checkpointId, operator_id: operatorId })
    })
  );
}

export const api = {
  scenarios: async () => checked<Scenario[]>(await fetch("/api/scenarios")),
  cases: async (cursor?: string, signal?: AbortSignal) => checked<CasePage>(
    await fetch(`/api/cases?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, { signal })
  ),
  case: async (caseId: string, signal?: AbortSignal) => checked<Workspace>(
    await fetch(`/api/cases/${encodeURIComponent(caseId)}/workspace`, { signal })
  ),
  start: startCase,
  approve: (caseId: string, payload: {
    checkpoint_id: string; decision: "approve" | "deny"; reviewer_id: string; reason: string;
  }) => recordApproval(caseId, payload.checkpoint_id, payload.decision, payload.reviewer_id, payload.reason),
  resume: resumeCase
};
