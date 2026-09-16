import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import App from "./App";
import { businessEvent, deferred, eventFor, MockEventSource, summaryFor, viewFor } from "./test/workspaceFixtures";
import type { RunView } from "./types";

vi.mock("./api", async (original) => {
  const actual = await original<typeof import("./api")>();
  return { ...actual, api: Object.fromEntries(Object.keys(actual.api).map((key) => [key, vi.fn()])) };
});
const agent = vi.hoisted(() => ({ setMessages: vi.fn() }));
vi.mock("@copilotkit/react-core/v2", () => ({ useAgent: () => ({ agent, isReady: true }) }));

const mocked = vi.mocked(api);
const historyRegion = () => screen.getByRole("complementary", { name: "Persisted cases" });
const context = () => screen.getByRole("region", { name: "Selected case context" });
function select(index: number) {
  fireEvent.click(within(historyRegion()).getByRole("button", { name: new RegExp(`Select case case-${index}:`) }));
}
function paused(id: string): RunView {
  const view = viewFor(id);
  return { ...view, state: { ...view.state, status: "paused", approval_required: true, checkpoint_id: `checkpoint-${id}` }, can_record_approval: true };
}

describe("persisted case workspace", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.history.replaceState({}, "", "/");
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
    mocked.scenarios.mockResolvedValue([{ id: "duplicate-confirmed", description: "Duplicate fixture", expected_terminal_status: "completed_refunded", tags: [] }]);
    mocked.cases.mockResolvedValue({ items: [summaryFor(1), summaryFor(2)], next_cursor: null, has_more: false });
    mocked.case.mockImplementation(async (id) => viewFor(id));
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("loads 25 cases ten at a time, preserves older pages on refresh, and selects read-only context", async () => {
    mocked.cases.mockImplementation(async (cursor) => {
      const offset = cursor ? Number(cursor) : 0;
      return { items: Array.from({ length: Math.min(10, 25 - offset) }, (_, index) => summaryFor(offset + index + 1)), next_cursor: offset < 20 ? String(offset + 10) : null, has_more: offset < 20 };
    });
    render(<App />);
    await screen.findByRole("button", { name: "Load more" });
    expect(within(historyRegion()).getAllByRole("listitem")).toHaveLength(10);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(within(historyRegion()).getAllByRole("listitem")).toHaveLength(20));
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByText("End of case history");
    expect(within(historyRegion()).getAllByRole("listitem")).toHaveLength(25);
    expect(mocked.cases.mock.calls.map(([cursor]) => cursor)).toEqual([undefined, "10", "20"]);
    fireEvent.focus(window);
    await waitFor(() => expect(mocked.cases).toHaveBeenCalledTimes(4));
    expect(within(historyRegion()).getAllByRole("listitem")).toHaveLength(25);
    fireEvent.change(screen.getByLabelText("Operator identity"), { target: { value: "previous-opener" } });
    select(25);
    expect(await within(context()).findByText("Complaint for case-25")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "Customer ID" })).not.toBeInTheDocument();
    expect(new URL(window.location.href).searchParams.get("case")).toBe("case-25");
    fireEvent.click(screen.getByRole("button", { name: "New case" }));
    expect(screen.getByRole("textbox", { name: "Customer ID" })).toBeEnabled();
    expect(screen.getByLabelText("Operator identity")).toHaveValue("");
    expect(new URL(window.location.href).searchParams.has("case")).toBe(false);
  });

  it("restores a historical URL directly on reload and renders both audit views from the same ordered events", async () => {
    window.history.replaceState({}, "", "/?case=case-25");
    const first = render(<App />);
    expect(await within(context()).findByText("Complaint for case-25")).toBeVisible();
    expect(mocked.cases).toHaveBeenCalledTimes(1);
    const stream = MockEventSource.latest();
    const second = { ...businessEvent("tool.call.succeeded", 9, { refund_id: "refund-safe" }, "submit_refund"), checkpoint_id: "checkpoint-safe", retry_attempt: 2 };
    act(() => {
      stream.emit("audit", second);
      stream.emit("audit", businessEvent("run.started", 3));
      stream.emit("audit", second);
      stream.emit("audit", eventFor("other-case", 11));
    });
    const timeline = screen.getByRole("list", { name: "Execution events" });
    const audit = screen.getByRole("list", { name: "Business actions" });
    expect(within(timeline).getAllByRole("listitem")).toHaveLength(2);
    expect(within(audit).getAllByRole("listitem")).toHaveLength(2);
    expect(within(timeline).getAllByRole("listitem")[0]).toHaveTextContent("Normalizing complaint for case-25");
    expect(within(audit).getAllByRole("listitem")[0]).toHaveTextContent("Case opened");
    expect(audit).not.toHaveTextContent("checkpoint-safe");
    expect(timeline).toHaveTextContent("checkpoint-safe");
    fireEvent.click(within(audit).getByText("Business evidence"));
    expect(within(audit).getByText("refund-safe")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "outcome" }));
    expect(screen.getByText(/Pending — no persisted outcome/)).toBeVisible();
    first.unmount();
    expect(stream.closed).toBe(true);
    render(<App />);
    expect(await within(context()).findByText("Complaint for case-25")).toBeVisible();
    expect(MockEventSource.latest().url).toContain("after=0");
  });

  it("observes a generated new case while synchronous Start is still pending", async () => {
    const start = deferred<Awaited<ReturnType<typeof api.start>>>();
    mocked.start.mockReturnValue(start.promise);
    let discoveries = 0;
    mocked.case.mockImplementation(async (id) => {
      if (++discoveries === 1) throw new ApiError("Not found", 404);
      return viewFor(id);
    });
    render(<App />);
    expect(screen.getByRole("button", { name: "Start workflow" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Operator identity"), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Start workflow" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Operator identity"), { target: { value: " opener-test " } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Start workflow" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Start workflow" }));
    const payload = mocked.start.mock.calls[0][0];
    expect(payload.operator_id).toBe("opener-test");
    expect(payload.existing_case_id).toMatch(/^[a-f0-9-]{36}$/);
    expect(payload.idempotency_key).toContain(payload.existing_case_id);
    expect(new URL(window.location.href).searchParams.get("case")).toBe(payload.existing_case_id);
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1), { timeout: 2500 });
    act(() => MockEventSource.latest().emit("audit", eventFor(payload.existing_case_id)));
    expect(within(screen.getByRole("list", { name: "Execution events" })).getByText(`Normalizing complaint for ${payload.existing_case_id}`)).toBeVisible();
    expect(screen.getByText(/Starting workflow… Observation remains live/)).toBeVisible();
    expect(within(historyRegion()).getByRole("button", { name: new RegExp(`Select case ${payload.existing_case_id}:`) })).toBeVisible();
    await act(async () => start.resolve({ case_id: payload.existing_case_id, run_id: `run-${payload.existing_case_id}`, status: "running", current_step: "normalize_case", approval_required: false }));
    expect(mocked.start).toHaveBeenCalledTimes(1);
  });

  it("ignores late state, audit, and snapshot responses after selection changes", async () => {
    const old = deferred<RunView>();
    mocked.case.mockImplementation((id) => id === "case-1" ? old.promise : Promise.resolve(viewFor(id)));
    render(<App />);
    await screen.findByText("End of case history");
    select(1);
    select(2);
    expect(await within(context()).findByText("Complaint for case-2")).toBeVisible();
    await act(async () => old.resolve(paused("case-1")));
    expect(context()).not.toHaveTextContent("Complaint for case-1");
    expect(screen.queryByRole("heading", { name: "Approval checkpoint" })).not.toBeInTheDocument();
    const oldStream = MockEventSource.latest();
    select(1);
    expect(await within(context()).findByText("Complaint for case-1")).toBeVisible();
    act(() => {
      oldStream.emit("audit", eventFor("case-2"));
      oldStream.emit("snapshot", viewFor("case-2"));
    });
    expect(oldStream.closed).toBe(true);
    expect(context()).not.toHaveTextContent("Complaint for case-2");
    expect(screen.getByRole("list", { name: "Execution events" })).toBeEmptyDOMElement();
  });

  it("requires trimmed reviewer and reason, reconciles failed commands, and restores persisted Resume after reload", async () => {
    let persisted = paused("case-1");
    mocked.case.mockImplementation(async () => persisted);
    window.history.replaceState({}, "", "/?case=case-1");
    mocked.approve.mockRejectedValueOnce(new Error("Decision rejected"));
    const first = render(<App />);
    const approve = await screen.findByRole("button", { name: "Record approval" });
    expect(approve).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reviewer"), { target: { value: " reviewer-test " } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "   " } });
    expect(approve).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: " Verified evidence " } });
    fireEvent.click(approve);
    await screen.findByText(/Decision rejected/);
    expect(screen.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
    expect(approve).toBeEnabled();
    expect(screen.getByLabelText("Reason")).toHaveValue(" Verified evidence ");
    mocked.approve.mockImplementation(async () => {
      persisted = { ...persisted, can_record_approval: false, can_resume: true, approval: {
        decision: "approve", reviewer_id: "reviewer-test", reason: "Verified evidence",
        decided_at: "2026-09-16T11:00:00Z", checkpoint_id: "checkpoint-case-1"
      } };
      return {};
    });
    fireEvent.click(approve);
    await screen.findByLabelText("Resume operator");
    expect(screen.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
    expect(screen.getByLabelText("Resume operator")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Resume operator"), { target: { value: "  " } });
    expect(screen.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Resume operator"), { target: { value: " resumer-test " } });
    expect(screen.getByRole("button", { name: "Resume checkpoint" })).toBeEnabled();
    expect(mocked.approve).toHaveBeenLastCalledWith("run-case-1", {
      checkpoint_id: "checkpoint-case-1", decision: "approve", reviewer_id: "reviewer-test", reason: "Verified evidence"
    });
    expect(mocked.resume).not.toHaveBeenCalled();
    mocked.resume.mockRejectedValue(new Error("Resume unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Resume checkpoint" }));
    await screen.findByText(/Resume unavailable/);
    expect(mocked.resume).toHaveBeenCalledWith("run-case-1", "checkpoint-case-1", "resumer-test");
    expect(screen.getByRole("button", { name: "Resume checkpoint" })).toBeEnabled();
    persisted = { ...persisted, approval: { ...persisted.approval!, reason: null } };
    first.unmount();
    render(<App />);
    await screen.findByLabelText("Resume operator");
    expect(screen.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
    expect(screen.getByLabelText("Resume operator")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Resume operator"), { target: { value: "another-resumer" } });
    expect(screen.getByRole("button", { name: "Resume checkpoint" })).toBeEnabled();
    expect(screen.getByRole("region", { name: "Approval checkpoint" })).toHaveTextContent("Not recorded (historical approval)");
    expect(screen.getByRole("button", { name: "Record approval" })).toBeDisabled();
  });

  it("keeps an in-flight command tied to its original case when another case is selected", async () => {
    const decision = deferred<unknown>();
    mocked.approve.mockReturnValue(decision.promise);
    mocked.case.mockImplementation(async (id) => id === "case-1" ? paused(id) : viewFor(id));
    window.history.replaceState({}, "", "/?case=case-1");
    render(<App />);
    await screen.findByLabelText("Reviewer");
    fireEvent.change(screen.getByLabelText("Reviewer"), { target: { value: "reviewer" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "verified" } });
    fireEvent.click(screen.getByRole("button", { name: "Record denial" }));
    select(2);
    await within(context()).findByText("Complaint for case-2");
    const reads = mocked.case.mock.calls.length;
    await act(async () => decision.reject(new Error("Old decision failed")));
    expect(mocked.case).toHaveBeenCalledTimes(reads);
    expect(context()).toHaveTextContent("Complaint for case-2");
    expect(screen.queryByText(/Old decision failed/)).not.toBeInTheDocument();
    select(1);
    expect(await screen.findByText(/Old decision failed/)).toBeVisible();
  });

  it("offers retries for history and selected-case read failures without retrying Start", async () => {
    mocked.cases.mockRejectedValueOnce(new Error("History unavailable"));
    mocked.case.mockRejectedValueOnce(new ApiError("Case not found", 404));
    window.history.replaceState({}, "", "/?case=case-1");
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry cases" }));
    await screen.findByText("End of case history");
    expect(mocked.case).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry observation" }));
    await within(context()).findByText("Complaint for case-1");
    expect(mocked.start).not.toHaveBeenCalled();
  });
});
