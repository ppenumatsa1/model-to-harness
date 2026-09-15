import type {
  ApprovalCommand,
  CheckoutCase,
  SafeAuditEvent,
  WorkspaceArtifact
} from "./types";

const baseUrl = "/api";
const safeErrorDetails = new Set([
  "fixture not found",
  "case not found",
  "approval rejected",
  "resume rejected",
  "start rejected"
]);

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, init);
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => undefined);
    const detail =
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string" &&
      safeErrorDetails.has(body.detail)
        ? body.detail
        : `Request failed (${response.status})`;
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

const jsonRequest = (method: "POST", body?: unknown): RequestInit => ({
  method,
  headers: { "content-type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body)
});

export const checkoutApi = {
  start: (fixtureId: string, requestId?: string) =>
    request<CheckoutCase>(
      "/cases",
      jsonRequest("POST", { fixture_id: fixtureId, request_id: requestId })
    ),
  case: (caseId: string) => request<CheckoutCase>(`/cases/${encodeURIComponent(caseId)}`),
  events: (caseId: string) =>
    request<SafeAuditEvent[]>(`/cases/${encodeURIComponent(caseId)}/events`),
  workspaceArtifact: (caseId: string) =>
    request<WorkspaceArtifact>(`/cases/${encodeURIComponent(caseId)}/workspace-artifact`),
  approval: (caseId: string, command: ApprovalCommand) =>
    request<CheckoutCase>(
      `/cases/${encodeURIComponent(caseId)}/approval`,
      jsonRequest("POST", command)
    ),
  resume: (caseId: string) =>
    request<CheckoutCase>(`/cases/${encodeURIComponent(caseId)}/resume`, jsonRequest("POST"))
};

export async function loadCaseWorkspace(caseId: string): Promise<{
  case: CheckoutCase;
  events: SafeAuditEvent[];
  artifact: WorkspaceArtifact;
}> {
  const [caseRecord, events, artifact] = await Promise.all([
    checkoutApi.case(caseId),
    checkoutApi.events(caseId),
    checkoutApi.workspaceArtifact(caseId)
  ]);
  return { case: caseRecord, events, artifact };
}
