import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import { parseAguiSse } from "../../src/api";

test("shows graph, retry evidence, approval controls, and terminal outcome", async ({ page }) => {
  let copilotRuntimePosts = 0;
  let directAssistantPosts = 0;
  await page.route("**/api/cases", async (route) => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    await route.continue({
      postData: JSON.stringify({
        ...request.postDataJSON(),
        existing_case_id: `browser-${randomUUID()}`,
        idempotency_key: `browser-${randomUUID()}`
      })
    });
  });
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (
      request.method() === "POST" &&
      pathname === "/api/copilotkit/agent/selected-run/run"
    ) {
      copilotRuntimePosts += 1;
    }
    if (request.method() === "POST" && pathname.endsWith("/assistant")) {
      directAssistantPosts += 1;
    }
  });
  page.on("pageerror", (error) => console.error(`browser page error: ${error.message}`));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Double-charge case workspace" })).toBeVisible();
  await page.getByLabel("Scenario fixture").selectOption("retry-safe-refund");
  await page.getByRole("button", { name: "Start workflow" }).click();
  await expect(page.getByRole("heading", { name: "Approval checkpoint" })).toBeVisible();
  await page.getByRole("button", { name: "Record approval" }).click();
  await page.getByRole("button", { name: "Resume checkpoint" }).click();
  const retryEvents = page
    .getByRole("region", { name: "Execution timeline" })
    .getByText("tool.call.retried", { exact: true });
  await expect(retryEvents.first()).toBeVisible();
  await page.getByRole("button", { name: "outcome" }).click();
  await expect(
    page.locator(".inspector-panel pre").filter({
      hasText: '"terminal_status": "completed_refunded"'
    })
  ).toBeVisible();
  await expect(page.getByText("No chain-of-thought")).toBeVisible();
  const explanationResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/copilotkit/agent/selected-run/run",
    { timeout: 60_000 }
  );
  await page.getByRole("button", { name: "Explain selected run" }).click();
  const response = await explanationResponse;
  expect(response.ok()).toBe(true);
  const projection = parseAguiSse(await response.text());
  expect(projection.malformed).toBe(0);
  expect(projection.events.some((event) => event.type === "RUN_FINISHED")).toBe(true);
  const answer = projection.events
    .filter((event) => event.type === "TEXT_MESSAGE_CONTENT")
    .map((event) => {
      if (typeof event.delta !== "string") {
        throw new Error("Selected-run text event has no string delta");
      }
      return event.delta;
    })
    .join("");
  expect(answer.trim().length).toBeGreaterThan(0);
  await expect(page.locator(".assistant-panel blockquote")).toHaveText(answer);
  await expect(page.locator(".assistant-panel [role=alert]")).toHaveCount(0);
  expect(copilotRuntimePosts).toBe(1);
  expect(directAssistantPosts).toBe(0);

  await page.getByLabel("Scenario fixture").selectOption("no-duplicate");
  await page.getByRole("button", { name: "Start workflow" }).click();
  await expect(
    page.locator(".inspector-panel pre").filter({
      hasText: '"terminal_status": "completed_no_refund"'
    })
  ).toBeVisible();
  await expect(retryEvents).toHaveCount(0);
});
