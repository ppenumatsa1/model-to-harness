import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../src/api";
import App from "../src/App";
import { businessEvent, deferred, eventFor, MockEventSource, summaryFor, viewFor } from "./workspaceFixtures";
import type { Workspace } from "../src/types";

vi.mock("../src/api", async (original) => {
  const actual = await original<typeof import("../src/api")>();
  return { ...actual, api: Object.fromEntries(Object.keys(actual.api).map((key) => [key, vi.fn()])) };
});
const agent = vi.hoisted(() => ({ setMessages: vi.fn(), setState: vi.fn() }));
vi.mock("@copilotkit/react-core/v2", () => ({ useAgent: () => ({ agent, isReady: true }) }));
const mocked = vi.mocked(api);
const historyRegion = () => screen.getByRole("complementary", { name: "Persisted cases" });
const context = () => screen.getByRole("region", { name: "Selected case context" });
function select(index: number) {
  fireEvent.click(within(historyRegion()).getByRole("button", { name: new RegExp(`Select case case-${index}:`) }));
}
function paused(id: string): Workspace {
  const view = viewFor(id);
  return { ...view, state: { ...view.state, status: "paused", approval_required: true, checkpoint_id: `checkpoint-${id}` }, can_record_approval: true };
}

describe("persisted LG workspace", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.history.replaceState({}, "", "/");
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
    mocked.scenarios.mockResolvedValue([{ id: "duplicate-confirmed", label: "Duplicate confirmed" }]);
    mocked.cases.mockResolvedValue({ items: [summaryFor(1), summaryFor(2)], next_cursor: null, has_more: false });
    mocked.case.mockImplementation(async (id) => viewFor(id));
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
  it("loads 25 cases ten at a time, retains pages on refresh, and selects historical context", async () => {
    mocked.cases.mockImplementation(async (cursor) => {
      const offset = cursor ? Number(cursor) : 0;
      return { items: Array.from({ length: Math.min(10, 25 - offset) }, (_, i) => summaryFor(offset + i + 1)),
        next_cursor: offset < 20 ? String(offset + 10) : null, has_more: offset < 20 };
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
    expect(screen.getByLabelText("Operator identity")).toHaveValue("");
    expect(new URL(window.location.href).searchParams.has("case")).toBe(false);
  });
  it("restores URL selection and projects native audit in chronological order without exposing arbitrary details", async () => {
    window.history.replaceState({}, "", "/?case=case-25");
    const first = render(<App />);
    await within(context()).findByText("Complaint for case-25");
    const stream = MockEventSource.latest();
    const refund = businessEvent("tool_call_succeeded", 9, {
      refund_id: "refund-safe", checkpoint_id: "checkpoint-safe", arbitrary_secret: "DO_NOT_RENDER",
      attempt: 2
    }, "submit_refund");
    act(() => {
      stream.emit("audit", refund);
      stream.emit("audit", businessEvent("run_started", 3));
      stream.emit("audit", refund);
      stream.emit("audit", eventFor("other-case", 11));
    });
    const timeline = screen.getByRole("list", { name: "Execution events" });
    const audit = screen.getByRole("list", { name: "Business actions" });
    expect(within(timeline).getAllByRole("listitem")).toHaveLength(2);
    expect(within(audit).getAllByRole("listitem")).toHaveLength(2);
    expect(within(audit).getAllByRole("listitem")[0]).toHaveTextContent("Case opened");
    expect(audit).not.toHaveTextContent("checkpoint-safe");
    expect(timeline).toHaveTextContent("checkpoint-safe");
    expect(document.body).not.toHaveTextContent("DO_NOT_RENDER");
    fireEvent.click(within(audit).getByText("Business evidence"));
    expect(within(audit).getByText("refund-safe")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "memory" }));
    expect(within(screen.getByRole("region", { name: "Run data inspector" })).getByText("{}")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "outcome" }));
    expect(screen.getByText(/Pending — no persisted outcome/)).toBeVisible();
    first.unmount();
    expect(stream.closed).toBe(true);
    render(<App />);
    await within(context()).findByText("Complaint for case-25");
    expect(MockEventSource.latest().url).toContain("after=0");
  });
  it("observes a client-generated case before a long synchronous Start response returns", async () => {
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
    await act(async () => start.resolve({ case_id: payload.existing_case_id, run_id: `run-${payload.existing_case_id}`, status: "running", current_step: "normalize_complaint", approval_required: false }));
    expect(mocked.start).toHaveBeenCalledTimes(1);
  });
  it("ignores late state, audit and snapshots after selection changes", async () => {
    const old = deferred<Workspace>();
    mocked.case.mockImplementation((id) => id === "case-1" ? old.promise : Promise.resolve(viewFor(id)));
    render(<App />);
    await screen.findByText("End of case history");
    select(1); select(2);
    await within(context()).findByText("Complaint for case-2");
    await act(async () => old.resolve(paused("case-1")));
    expect(context()).not.toHaveTextContent("Complaint for case-1");
    expect(screen.queryByRole("heading", { name: "Approval checkpoint" })).not.toBeInTheDocument();
    const oldStream = MockEventSource.latest();
    select(1);
    await within(context()).findByText("Complaint for case-1");
    act(() => { oldStream.emit("audit", eventFor("case-2")); oldStream.emit("snapshot", viewFor("case-2")); });
    expect(oldStream.closed).toBe(true);
    expect(context()).not.toHaveTextContent("Complaint for case-2");
    expect(screen.getByRole("list", { name: "Execution events" })).toBeEmptyDOMElement();
  });
  it("requires reviewer/reason, records only, persists explicit Resume and handles lost command responses", async () => {
    let persisted = paused("case-1");
    mocked.case.mockImplementation(async () => persisted);
    window.history.replaceState({}, "", "/?case=case-1");
    mocked.approve.mockRejectedValueOnce(new Error("Decision response lost"));
    const first = render(<App />);
    const approve = await screen.findByRole("button", { name: "Record approval" });
    expect(approve).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reviewer"), { target: { value: " reviewer-test " } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "   " } });
    expect(approve).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: " Verified evidence " } });
    fireEvent.click(approve);
    await screen.findByText(/Decision response lost/);
    expect(screen.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
    expect(approve).toBeEnabled();
    expect(mocked.approve).toHaveBeenCalledTimes(1);
    mocked.approve.mockImplementation(async () => {
      persisted = { ...persisted, can_record_approval: false, can_resume: true, approval: {
        decision: "approve", reviewer_id: "reviewer-test", reason: "Verified evidence",
        decided_at: "2026-09-16T11:00:00Z", checkpoint_id: "checkpoint-case-1", consumed: false
      } };
    });
    fireEvent.click(approve);
    await screen.findByLabelText("Resume operator");
    expect(screen.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Resume operator"), { target: { value: " resumer-test " } });
    expect(mocked.approve).toHaveBeenLastCalledWith("case-1", {
      checkpoint_id: "checkpoint-case-1", decision: "approve", reviewer_id: "reviewer-test", reason: "Verified evidence"
    });
    expect(mocked.resume).not.toHaveBeenCalled();
    mocked.resume.mockRejectedValue(new Error("Resume response lost"));
    fireEvent.click(screen.getByRole("button", { name: "Resume checkpoint" }));
    await screen.findByText(/Resume response lost/);
    expect(mocked.resume).toHaveBeenCalledExactlyOnceWith("case-1", "checkpoint-case-1", "resumer-test");
    expect(screen.getByText(/command outcome may be unknown/)).toBeVisible();
    persisted = { ...persisted, approval: { ...persisted.approval!, reason: null, decided_at: null } };
    first.unmount();
    render(<App />);
    await screen.findByLabelText("Resume operator");
    expect(screen.getByLabelText("Resume operator")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
    expect(screen.getByRole("region", { name: "Approval checkpoint" })).toHaveTextContent("Not recorded (historical approval)");
    expect(screen.getByRole("region", { name: "Approval checkpoint" })).toHaveTextContent("Decision time: Not recorded");
  });
  it("ties a late command failure to its original case without refetching the new selection", async () => {
    const decision = deferred<void>();
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
    expect(screen.queryByText(/Old decision failed/)).not.toBeInTheDocument();
    select(1);
    expect(await screen.findByText(/Old decision failed/)).toBeVisible();
  });
  it("offers read retries without retrying Start and preserves legacy manual-review cases read-only", async () => {
    mocked.cases.mockRejectedValueOnce(new Error("History unavailable"));
    mocked.case.mockRejectedValueOnce(new ApiError("Case not found", 404));
    const historical = paused("case-1");
    historical.state.status = "manual_review";
    historical.state.scenario_id = "verification-mismatch";
    historical.state.complaint = null;
    historical.approval = { decision: "approve", reviewer_id: "old-reviewer", reason: null, decided_at: null, checkpoint_id: "cp", consumed: true };
    historical.can_resume = true;
    mocked.case.mockResolvedValue(historical);
    window.history.replaceState({}, "", "/?case=case-1");
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry cases" }));
    await screen.findByText("End of case history");
    fireEvent.click(screen.getByRole("button", { name: "Retry observation" }));
    await within(context()).findByText("verification-mismatch");
    expect(context()).toHaveTextContent("Not recorded");
    expect(screen.getByRole("button", { name: "Record approval" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Resume checkpoint" })).toBeDisabled();
    expect(screen.queryByLabelText("Reviewer")).not.toBeInTheDocument();
    expect(mocked.start).not.toHaveBeenCalled();
  });
  it("shows six normal demo choices and requires the native five-character complaint minimum", async () => {
    mocked.scenarios.mockResolvedValue([
      ...["duplicate-confirmed", "no-duplicate", "approval-denied", "transient-failure", "retry-safe-refund", "resumed-approval"].map((id) => ({ id, label: id })),
      { id: "verification-mismatch", label: "Verification mismatch" }
    ]);
    render(<App />);
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(6));
    expect(screen.queryByRole("option", { name: "Verification mismatch" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Operator identity"), { target: { value: "operator" } });
    fireEvent.change(screen.getByLabelText("Customer complaint"), { target: { value: "four" } });
    expect(screen.getByRole("button", { name: "Start workflow" })).toBeDisabled();
    expect(screen.getByText("Workflow graph").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("Safe run explainer", { selector: "summary" }).closest("details")).not.toHaveAttribute("open");
  });
});
