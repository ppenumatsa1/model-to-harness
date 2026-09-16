import { expect, test } from "@playwright/test";

test("shows graph, audit events, separate approval/resume and normalized outcome", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Double-charge case workspace" })).toBeVisible();
  await page.getByLabel("Scenario fixture").selectOption("retry-safe-refund");
  await page.getByLabel("Operator identity").fill("local-e2e-opener");
  await page.getByRole("button", { name: "Start workflow" }).click();
  await expect(page.getByRole("heading", { name: "Approval checkpoint" })).toBeVisible();
  await expect(page.getByText("tool call started").first()).toBeVisible();
  await page.getByLabel("Reviewer", { exact: true }).fill("local-e2e-reviewer");
  await page.getByLabel("Reason", { exact: true }).fill("Verified deterministic evidence");
  await page.getByRole("button", { name: "Record approval", exact: true }).click();
  await expect(page.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
  await page.getByLabel("Resume operator").fill("local-e2e-resumer");
  await page.getByRole("button", { name: "Resume checkpoint" }).click();
  await expect(page.getByRole("region", { name: "Selected case context" })).toContainText("completed");
  await page.getByRole("button", { name: "outcome", exact: true }).click();
  await expect(page.getByText(/"refund_status": "verified"/)).toBeVisible();
  await expect(page.getByText(/refund verification/i).first()).toBeVisible();
  await expect(page.getByText("tool call retried").first()).toBeVisible();
  await page.locator("summary").filter({ hasText: "Workflow graph" }).click();
  await expect(page.getByRole("region", { name: "Workflow graph" })).toContainText("billing");
  await page.locator("summary").filter({ hasText: "Safe run explainer" }).click();
  await page.getByRole("button", { name: "Explain selected run" }).click();
  await expect(page.locator("blockquote")).toContainText("Exactly one refund");
});
