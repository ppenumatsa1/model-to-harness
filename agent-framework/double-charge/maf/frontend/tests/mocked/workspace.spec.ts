import { expect, test } from "@playwright/test";
import { businessEvent, summaryFor, viewFor } from "../../src/test/workspaceFixtures";

test("isolated browser restores history, reads native evidence, and keeps controls persisted", async ({ page }) => {
  const requests: string[] = [];
  const view = viewFor("case-25");
  view.state.status = "paused";
  view.state.approval_required = true;
  view.state.checkpoint_id = "checkpoint-case-25";
  view.can_record_approval = true;
  await page.addInitScript(({ audit }) => {
    class NativeStream extends EventTarget {
      onopen: (() => void) | null = null;
      onerror = null;
      timer: ReturnType<typeof setTimeout>;
      constructor() {
        super();
        this.timer = setTimeout(() => {
          this.onopen?.();
          for (const event of [audit, audit]) {
            this.dispatchEvent(new MessageEvent("audit", { data: JSON.stringify(event) }));
          }
        }, 30);
      }
      close() { clearTimeout(this.timer); }
    }
    Object.defineProperty(window, "EventSource", { value: NativeStream });
  }, { audit: businessEvent("run.started", 17) });

  // Every API request is intercepted. No Foundry, database, or workflow commands run.
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push(`${request.method()} ${url.pathname}`);
    if (url.pathname === "/api/scenarios") {
      await route.fulfill({ json: [{ id: "duplicate-confirmed", description: "Mock fixture", expected_terminal_status: "completed_refunded", tags: [] }] });
    } else if (url.pathname === "/api/cases") {
      const offset = Number(url.searchParams.get("cursor") ?? 0);
      await route.fulfill({ json: {
        items: Array.from({ length: Math.min(10, 25 - offset) }, (_, index) => summaryFor(offset + index + 1)),
        next_cursor: offset < 20 ? String(offset + 10) : null, has_more: offset < 20
      } });
    } else if (url.pathname === "/api/cases/case-25") {
      await route.fulfill({ json: view });
    } else if (url.pathname === "/api/runs/run-case-25/approval") {
      const decision = request.postDataJSON();
      expect(decision).toEqual({ checkpoint_id: "checkpoint-case-25", decision: "approve", reviewer_id: "browser-reviewer", reason: "Verified audit evidence" });
      view.approval = { ...decision, decided_at: "2026-09-16T12:00:00Z" };
      view.can_record_approval = false;
      view.can_resume = true;
      await route.fulfill({ json: { status: "recorded", run_id: view.state.run_id, state: view.state } });
    } else {
      await route.fulfill({ status: 404, json: { detail: "Not part of the isolated mock" } });
    }
  });
  await page.goto("/?case=case-25");
  await expect(page.getByRole("region", { name: "Selected case context" })).toContainText("Complaint for case-25");
  const history = page.getByRole("complementary", { name: "Persisted cases" });
  await expect(history.getByRole("listitem")).toHaveCount(10);
  await history.getByRole("button", { name: "Load more" }).click();
  await expect(history.getByRole("listitem")).toHaveCount(20);
  await history.getByRole("button", { name: "Load more" }).click();
  await expect(history.getByRole("listitem")).toHaveCount(25);
  await expect(page.getByRole("list", { name: "Execution events" }).getByRole("listitem")).toHaveCount(1);
  await expect(page.getByRole("complementary", { name: "Audit trail" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Business actions" }).getByRole("listitem")).toHaveCount(1);
  await expect(page.getByText("Native audit: live")).toBeVisible();
  await expect(page.getByRole("button", { name: "Record approval", exact: true })).toBeDisabled();
  await page.getByLabel("Reviewer", { exact: true }).fill(" browser-reviewer ");
  await page.getByLabel("Reason", { exact: true }).fill(" Verified audit evidence ");
  await page.getByRole("button", { name: "Record approval", exact: true }).click();
  await expect(page.getByLabel("Resume operator", { exact: true })).toHaveValue("");
  await expect(page.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
  await page.getByLabel("Resume operator", { exact: true }).fill("browser-resumer");
  await expect(page.getByRole("button", { name: "Resume checkpoint" })).toBeEnabled();
  await expect(page.getByRole("region", { name: "Approval checkpoint" })).toContainText("Verified audit evidence");
  await page.reload();
  await expect(page.getByRole("region", { name: "Selected case context" })).toContainText("Complaint for case-25");
  await expect(page.getByLabel("Resume operator", { exact: true })).toHaveValue("");
  await expect(page.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Record approval", exact: true })).toBeDisabled();
  expect(requests.filter((request) => request.startsWith("POST /api/runs/"))).toEqual(["POST /api/runs/run-case-25/approval"]);
});
