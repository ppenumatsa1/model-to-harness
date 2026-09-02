import { expect, test } from "@playwright/test";

test("shows graph, audit events, approval and normalized outcome", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "See every safe workflow decision." })).toBeVisible();
  await page.getByLabel("Scenario").selectOption("retry-safe-refund");
  await page.getByRole("button", { name: "Start durable run" }).click();
  await expect(page.getByRole("heading", { name: "Reviewer decision required" })).toBeVisible();
  await expect(page.getByText("tool call started").first()).toBeVisible();
  await page.getByRole("button", { name: "Approve & resume" }).click();
  await expect(page.getByText("completed", { exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "outcome" }).click();
  await expect(page.getByText(/"refund_status": "verified"/)).toBeVisible();
  await expect(page.getByText(/refund verification/i).first()).toBeVisible();
  await expect(page.getByText("tool call retried").first()).toBeVisible();
  await page.getByRole("button", { name: "Explain selected run" }).click();
  await expect(page.locator("blockquote")).toContainText("Exactly one refund");
});
