import { expect, test } from "@playwright/test";

test("shows graph, retry evidence, approval controls, and terminal outcome", async ({ page }) => {
  let copilotRuntimePosts = 0;
  let directAssistantPosts = 0;
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
  await expect(page.getByRole("heading", { name: "Double-charge workflow lab" })).toBeVisible();
  await page.getByLabel("Fixture").selectOption("retry-safe-refund");
  await page.getByRole("button", { name: "Start workflow" }).click();
  await expect(page.getByRole("heading", { name: "Approval checkpoint" })).toBeVisible();
  await page.getByRole("button", { name: "Record approval" }).click();
  await page.getByRole("button", { name: "Resume checkpoint" }).click();
  await expect(page.getByText("tool.call.retried")).toBeVisible();
  await page.getByRole("button", { name: "outcome" }).click();
  await expect(
    page.locator(".inspector-panel pre").filter({
      hasText: '"terminal_status": "completed_refunded"'
    })
  ).toBeVisible();
  await expect(page.getByText("No chain-of-thought")).toBeVisible();
  await page.getByRole("button", { name: "Explain selected run" }).click();
  await expect(page.locator(".assistant-panel blockquote")).toContainText(
    "Current status is"
  );
  expect(copilotRuntimePosts).toBe(1);
  expect(directAssistantPosts).toBe(0);

  await page.getByLabel("Fixture").selectOption("no-duplicate");
  await page.getByRole("button", { name: "Start workflow" }).click();
  await expect(
    page.locator(".inspector-panel pre").filter({
      hasText: '"terminal_status": "completed_no_refund"'
    })
  ).toBeVisible();
  await expect(page.getByText("tool.call.retried")).toHaveCount(0);
});
