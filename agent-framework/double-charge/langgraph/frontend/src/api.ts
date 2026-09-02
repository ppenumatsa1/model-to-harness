import type { CaseView, NativeEvent, StartResponse } from "./types";

const JSON_HEADERS = { "Content-Type": "application/json" };

async function checked<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function startCase(input: {
  complaint: string;
  customer_id: string;
  scenario_id: string;
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
  return checked(await fetch(`/api/cases/${caseId}`));
}

export async function getEvents(caseId: string): Promise<NativeEvent[]> {
  return checked(await fetch(`/api/cases/${caseId}/events`));
}

export async function recordApproval(
  caseId: string,
  checkpointId: string,
  decision: "approve" | "deny",
  reviewerId: string,
  reason: string
): Promise<void> {
  await checked(
    await fetch(`/api/cases/${caseId}/approval`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({
        checkpoint_id: checkpointId,
        decision,
        reviewer_id: reviewerId,
        reason: reason || null
      })
    })
  );
}

export async function resumeCase(caseId: string): Promise<StartResponse> {
  return checked(
    await fetch(`/api/cases/${caseId}/resume`, {
      method: "POST",
      headers: JSON_HEADERS
    })
  );
}

