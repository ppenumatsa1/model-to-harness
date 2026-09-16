import { expect, test } from "@playwright/test";
import { businessEvent, summaryFor, viewFor } from "../workspaceFixtures";

test("isolated browser restores history, records approval only, explicitly resumes and observes final memory", async ({ page }) => {
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
          for (const event of [audit, audit]) this.dispatchEvent(new MessageEvent("audit", { data: JSON.stringify(event) }));
        }, 30);
        (window as unknown as { nativeStream: NativeStream }).nativeStream = this;
      }
      close() { clearTimeout(this.timer); }
    }
    Object.defineProperty(window, "EventSource", { value: NativeStream });
  }, { audit: businessEvent("run_started", 17) });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push(`${request.method()} ${url.pathname}`);
    if (url.pathname === "/api/scenarios") {
      await route.fulfill({ json: [{ id: "duplicate-confirmed", label: "Duplicate confirmed" }] });
    } else if (url.pathname === "/api/copilotkit/info") {
      await route.fulfill({ json: { version: "0.1.0", actions: [], agents: { "selected-run": { description: "Read-only" } } } });
    } else if (url.pathname === "/api/cases") {
      const offset = Number(url.searchParams.get("cursor") ?? 0);
      expect(url.searchParams.get("limit")).toBe("10");
      await route.fulfill({ json: {
        items: Array.from({ length: Math.min(10, 25 - offset) }, (_, i) => summaryFor(offset + i + 1)),
        next_cursor: offset < 20 ? String(offset + 10) : null, has_more: offset < 20
      } });
    } else if (url.pathname === "/api/cases/case-25/workspace") {
      await route.fulfill({ json: view });
    } else if (url.pathname === "/api/cases/case-25/approval") {
      const decision = request.postDataJSON();
      expect(decision).toEqual({ checkpoint_id: "checkpoint-case-25", decision: "approve", reviewer_id: "browser-reviewer", reason: "Verified audit evidence" });
      view.approval = { ...decision, decided_at: "2026-09-16T12:00:00Z", consumed: false };
      view.can_record_approval = false;
      view.can_resume = true;
      await route.fulfill({ json: { status: "recorded" } });
    } else if (url.pathname === "/api/cases/case-25/resume") {
      expect(request.postDataJSON()).toEqual({ checkpoint_id: "checkpoint-case-25", operator_id: "browser-resumer" });
      view.can_resume = false;
      view.state.status = "running";
      await route.fulfill({ json: { case_id: "case-25", run_id: "run-case-25", status: "running" } });
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
  await expect(page.getByRole("list", { name: "Business actions" }).getByRole("listitem")).toHaveCount(1);
  await expect(page.getByText("Native audit: live")).toBeVisible();
  await page.getByRole("button", { name: "memory", exact: true }).click();
  await expect(page.getByRole("region", { name: "Run data inspector" }).locator("pre")).toHaveText("{}");
  await expect(page.getByRole("button", { name: "Record approval", exact: true })).toBeDisabled();
  await page.getByLabel("Reviewer", { exact: true }).fill(" browser-reviewer ");
  await page.getByLabel("Reason", { exact: true }).fill(" Verified audit evidence ");
  await page.getByRole("button", { name: "Record approval", exact: true }).click();
  await expect(page.getByLabel("Resume operator", { exact: true })).toHaveValue("");
  await expect(page.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
  expect(requests.filter((request) => request.startsWith("POST"))).toEqual(["POST /api/cases/case-25/approval"]);
  await page.reload();
  await expect(page.getByLabel("Resume operator", { exact: true })).toHaveValue("");
  await expect(page.getByRole("button", { name: "Record approval", exact: true })).toBeDisabled();
  await page.getByLabel("Resume operator", { exact: true }).fill("browser-resumer");
  await page.getByRole("button", { name: "Resume checkpoint" }).click();
  await expect(page.getByRole("region", { name: "Selected case context" })).toContainText("running");
  view.state.status = "completed";
  view.state.terminal_status = "completed";
  view.state.refund_status = "verified";
  view.memory = { case_id: "case-25", duplicate_decision: "confirmed", refund_status: "verified" };
  await page.evaluate(({ snapshot, event }) => {
    const stream = (window as unknown as { nativeStream: EventTarget }).nativeStream;
    stream.dispatchEvent(new MessageEvent("audit", { data: JSON.stringify(event) }));
    stream.dispatchEvent(new MessageEvent("snapshot", { data: JSON.stringify(snapshot) }));
  }, { snapshot: view, event: businessEvent("refund_verification", 28, { verified: true, verified_count: 1 }) });
  await expect(page.getByRole("region", { name: "Selected case context" })).toContainText("completed");
  await expect(page.getByRole("list", { name: "Business actions" })).toContainText("Refund verified");
  await page.getByRole("button", { name: "memory", exact: true }).click();
  await expect(page.getByRole("region", { name: "Run data inspector" }).locator("pre")).toContainText('"refund_status": "verified"');
  await expect(page.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
  expect(requests.filter((request) => request.startsWith("POST"))).toEqual([
    "POST /api/cases/case-25/approval", "POST /api/cases/case-25/resume"
  ]);
});

test("isolated browser observes a new case before Start finishes, then retains an unknown command outcome", async ({ page }) => {
  let release!: () => void;
  const responseGate = new Promise<void>((resolve) => { release = resolve; });
  let created: ReturnType<typeof viewFor> | undefined;
  let starts = 0;
  await page.addInitScript(() => {
    class NativeStream extends EventTarget {
      onopen: (() => void) | null = null;
      onerror = null;
      timer: ReturnType<typeof setTimeout>;
      constructor(url: string) {
        super();
        const id = new URL(url, location.href).pathname.split("/")[3];
        this.timer = setTimeout(() => {
          this.onopen?.();
          this.dispatchEvent(new MessageEvent("audit", { data: JSON.stringify({
            sequence: 7, event_id: "start-event", case_id: id, run_id: `run-${id}`,
            event_type: "run_started", timestamp: "2026-09-16T12:00:00Z", summary: "Case opened while Start response pending",
            data: { audit_version: 2, actor_type: "human", actor_source: "operator_supplied", actor_id: "browser-opener" }
          }) }));
        }, 30);
      }
      close() { clearTimeout(this.timer); }
    }
    Object.defineProperty(window, "EventSource", { value: NativeStream });
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/copilotkit/info") {
      await route.fulfill({ json: { version: "0.1.0", actions: [], agents: { "selected-run": { description: "Read-only" } } } });
    } else if (url.pathname === "/api/scenarios") {
      await route.fulfill({ json: [{ id: "duplicate-confirmed", label: "Duplicate confirmed" }] });
    } else if (url.pathname === "/api/cases" && request.method() === "POST") {
      starts += 1;
      const payload = request.postDataJSON();
      expect(payload.operator_id).toBe("browser-opener");
      created = viewFor(payload.existing_case_id);
      created.state.complaint = payload.complaint;
      await responseGate;
      await route.abort("failed");
    } else if (url.pathname === "/api/cases") {
      await route.fulfill({ json: { items: [], has_more: false, next_cursor: null } });
    } else if (url.pathname.endsWith("/workspace") && created) {
      await route.fulfill({ json: created });
    } else await route.fulfill({ status: 404, json: { detail: "Not persisted yet" } });
  });
  await page.goto("/");
  await page.getByLabel("Operator identity").fill(" browser-opener ");
  await page.getByRole("button", { name: "Start workflow" }).click();
  await expect(page.getByRole("list", { name: "Execution events" })).toContainText("Case opened while Start response pending");
  await expect(page.getByText("Starting workflow… Observation remains live.")).toBeVisible();
  expect(starts).toBe(1);
  expect(new URL(page.url()).searchParams.get("case")).toBe(created?.state.case_id);
  release();
  await expect(page.getByRole("alert")).toContainText("command outcome may be unknown");
  expect(starts).toBe(1);
  await expect(page.getByRole("region", { name: "Selected case context" })).toContainText(created!.state.case_id);
});
