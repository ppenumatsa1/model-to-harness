import { expect, test } from "@playwright/test";
import type { Page, Response } from "@playwright/test";
import type { CheckoutCase } from "../src/types";

const commandTimeout = 150_000;

const fixtures = [
  { id: "recoverable-inventory-reservation", outcome: "recovered", label: "Recovered", verified: true, remediation: "applied", failure: "none" },
  { id: "captured-payment-approved-remediation", outcome: "recovered", label: "Recovered", verified: true, remediation: "applied", failure: "none", decision: "approved" },
  { id: "payment-pending-manual-review", outcome: "manual_review", label: "Manual review", verified: null, remediation: null, failure: "none" },
  { id: "diagnostic-read-failure", outcome: "failed", label: "Failed", verified: null, remediation: null, failure: "diagnostic_read_failed" },
  { id: "denied-approval", outcome: "closed_denied", label: "Closed after denial", verified: null, remediation: null, failure: "none", decision: "denied" },
  { id: "uncertain-remediation-recovery", outcome: "recovered", label: "Recovered", verified: true, remediation: "applied", failure: "none" },
  { id: "verification-mismatch", outcome: "manual_review", label: "Manual review", verified: false, remediation: "applied", failure: "verification_mismatch" }
] as const;

const caseFields = new Set([
  "case_id", "run_id", "fixture_id", "phase", "diagnostic_disposition",
  "approval_decision", "approval_request_id", "remediation_action",
  "remediation_status", "verification_result", "terminal_status",
  "failure_code", "workspace_artifact", "diagnostic_tools", "harness_mode"
]);
const artifactFields = new Set(["artifact_id", "kind", "revision", "updated_at"]);
const forbiddenField = /prompt|chain.of.thought|credential|password|secret|token|connection.string|checkpoint|operation.key|tool.(?:arguments|results)|raw.(?:workspace|content|model)/i;

function assertSafe(value: unknown): void {
  if (Array.isArray(value)) {
    value.forEach(assertSafe);
  } else if (typeof value === "object" && value !== null) {
    for (const [key, child] of Object.entries(value)) {
      expect(key).not.toMatch(forbiddenField);
      assertSafe(child);
    }
  } else if (typeof value === "string") {
    expect(value).not.toMatch(/postgres(?:ql)?:\/\/|AccountKey=|SharedAccessSignature=|Bearer\s+\S+|BEGIN (?:RSA )?PRIVATE KEY/i);
  }
}

function assertFields(value: Record<string, unknown>, fields: Set<string>): void {
  expect(Object.keys(value).filter((field) => !fields.has(field))).toEqual([]);
  assertSafe(value);
}

function assertCase(value: CheckoutCase): void {
  assertFields(value as unknown as Record<string, unknown>, caseFields);
  assertFields(value.workspace_artifact as unknown as Record<string, unknown>, artifactFields);
}

async function commandResponse(page: Page, path: string, button: string): Promise<CheckoutCase> {
  const responsePromise = page.waitForResponse((response) =>
    new URL(response.url()).pathname === path && response.request().method() === "POST",
    { timeout: commandTimeout }
  );
  await page.getByRole("button", { name: button, exact: true }).click();
  const response = await responsePromise;
  expect(response.ok(), `Command ${path} HTTP status`).toBe(true);
  expect(response.headers()["x-checkout-token"]).toBeUndefined();
  const result = await response.json() as CheckoutCase;
  assertCase(result);
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeEnabled();
  return result;
}

async function assertSafeWorkspace(page: Page, caseId: string): Promise<void> {
  const [caseResponse, eventsResponse, artifactResponse] = await Promise.all([
    page.request.get(`/api/cases/${caseId}`),
    page.request.get(`/api/cases/${caseId}/events`),
    page.request.get(`/api/cases/${caseId}/workspace-artifact`)
  ]);
  for (const response of [caseResponse, eventsResponse, artifactResponse]) {
    expect(response.ok()).toBe(true);
    expect(response.headers()["x-checkout-token"]).toBeUndefined();
  }
  assertCase(await caseResponse.json() as CheckoutCase);
  const events = await eventsResponse.json() as Record<string, unknown>[];
  expect(events.length).toBeGreaterThan(0);
  events.forEach((event) => assertFields(event, new Set(["code", "occurred_at", "summary"])));
  assertFields(await artifactResponse.json() as Record<string, unknown>, artifactFields);
  const text = await page.locator("body").innerText();
  expect(text).not.toMatch(/postgres(?:ql)?:\/\/|AccountKey=|SharedAccessSignature=|BEGIN (?:RSA )?PRIVATE KEY/i);
  await expect(page.getByRole("heading", { name: "Tool activity and events" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Workspace artifact" })).toBeVisible();
}

async function reloadSelected(page: Page, caseId: string, status: string): Promise<void> {
  await expect(page).toHaveURL(new RegExp(`[?&]case=${caseId}(?:&|$)`));
  await page.reload();
  await expect(page.getByRole("status")).toHaveText(status);
  await expect(page.getByText(caseId, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeEnabled();
}

for (const fixture of fixtures) {
  test(`${fixture.id}: explicit commands, durable refresh, safe projections`, async ({ page }) => {
    const resumes: string[] = [];
    const browserTokens: string[] = [];
    let startResponse: Response | undefined;
    page.on("request", (request) => {
      if (new URL(request.url()).pathname.endsWith("/resume")) resumes.push(request.url());
      if ("x-checkout-token" in request.headers()) browserTokens.push("unexpected browser API token");
    });
    page.on("response", (response) => {
      if (new URL(response.url()).pathname === "/api/cases" && response.request().method() === "POST") {
        startResponse = response;
      }
    });
    await page.goto("/");
    await page.getByLabel("Fixture", { exact: true }).selectOption(fixture.id);
    let current = await commandResponse(page, "/api/cases", "Start recovery");
    expect(startResponse?.request().postDataJSON()).toEqual({
      fixture_id: fixture.id,
      request_id: expect.stringMatching(/^[0-9a-f-]{36}$/)
    });
    expect(current.fixture_id).toBe(fixture.id);

    if ("decision" in fixture) {
      expect(current.phase).toBe("waiting_approval");
      expect(current.approval_decision).toBe("pending");
      expect(current.approval_request_id).toEqual(expect.any(String));
      expect(current.remediation_status).toBeNull();
      const approvalRequestId = current.approval_request_id;
      await reloadSelected(page, current.case_id, "Approval required");
      await expect(page.getByRole("button", { name: "Resume recovery" })).toHaveCount(0);
      await page.getByLabel("Reviewer ID").fill("browser-reviewer");
      await page.getByLabel("Review reason").fill("Reviewed checkout remediation");
      const approvalRequest = page.waitForRequest((request) =>
        new URL(request.url()).pathname.endsWith("/approval") && request.method() === "POST"
      );
      current = await commandResponse(
        page, `/api/cases/${current.case_id}/approval`,
        fixture.decision === "approved" ? "Record approval" : "Record denial"
      );
      expect((await approvalRequest).postDataJSON()).toEqual({
        approval_request_id: approvalRequestId,
        decision: fixture.decision,
        reviewer_id: "browser-reviewer",
        reason: "Reviewed checkout remediation"
      });
      expect(current.phase).toBe("waiting_approval");
      expect(current.approval_decision).toBe(fixture.decision);
      expect(current.terminal_status).toBeNull();
      expect(current.remediation_status).toBeNull();
      await reloadSelected(page, current.case_id, "Ready to resume");
      expect(resumes).toEqual([]);
      current = await commandResponse(page, `/api/cases/${current.case_id}/resume`, "Resume recovery");
      expect(resumes).toHaveLength(1);
    }

    expect(current.phase).toBe("closed");
    expect(current.terminal_status).toBe(fixture.outcome);
    expect(current.remediation_status).toBe(fixture.remediation);
    expect(current.verification_result).toBe(fixture.verified);
    expect(current.failure_code).toBe(fixture.failure);
    await expect(page.getByRole("status")).toHaveText(fixture.label);
    await assertSafeWorkspace(page, current.case_id);
    await reloadSelected(page, current.case_id, fixture.label);
    await assertSafeWorkspace(page, current.case_id);
    expect(browserTokens).toEqual([]);
    await expect(page.getByRole("alert")).toHaveCount(0);
  });
}

test("an ambiguous start response retries the same durable request", async ({ page }) => {
  const requests: Record<string, unknown>[] = [];
  let firstCaseId: string | undefined;
  await page.route("**/api/cases", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    requests.push(route.request().postDataJSON() as Record<string, unknown>);
    if (requests.length === 1) {
      const response = await route.fetch({ timeout: commandTimeout });
      expect(response.ok()).toBe(true);
      firstCaseId = (await response.json() as CheckoutCase).case_id;
      await route.abort("failed");
    } else {
      await route.continue();
    }
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Start recovery", exact: true }).click();
  await expect(page.getByRole("button", { name: "Retry start", exact: true }))
    .toBeEnabled({ timeout: commandTimeout });
  await page.reload();
  const recovered = await commandResponse(page, "/api/cases", "Retry start");
  expect(recovered.case_id).toBe(firstCaseId);
  expect(requests[1]).toEqual(requests[0]);
  const next = await commandResponse(page, "/api/cases", "Start recovery");
  expect(next.case_id).not.toBe(firstCaseId);
  expect(requests[2].request_id).not.toBe(requests[0].request_id);
});
