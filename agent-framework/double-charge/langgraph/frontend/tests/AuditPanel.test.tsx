import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AuditPanel } from "../src/components/AuditPanel";
import { businessEvent, viewFor } from "./workspaceFixtures";

afterEach(cleanup);
describe("business audit presentation", () => {
  it("renders allowlisted evidence and actors, never arbitrary event summaries or tool/model details", () => {
    const event = businessEvent("tool_call_succeeded", 1, {
      refund_id: "safe-refund", attempt: 2, checkpoint_id: "private-checkpoint",
      prompt: "private-prompt", tool_arguments: { credential: "private-credential" }, chain_of_thought: "private-reasoning"
    }, "submit_refund");
    event.summary = "arbitrary-private-summary";
    render(<AuditPanel run={viewFor("case-25")} events={[event]} />);
    const entries = screen.getByRole("list", { name: "Business actions" });
    expect(entries).toHaveTextContent("Refund recorded");
    expect(entries).toHaveTextContent("System");
    expect(entries).toHaveTextContent("safe-refund");
    expect(entries).not.toHaveTextContent("private-");
    expect(entries).not.toHaveTextContent("arbitrary-private-summary");
    expect(entries).not.toHaveTextContent("tool_call_succeeded");
  });
  it("keeps historical closure immutable when a later snapshot or memory changes", () => {
    const terminal = businessEvent("run_completed", 1, {
      terminal_status: "manual_review", refund_status: "mismatch", notification_status: "not_sent"
    });
    const run = viewFor("case-25");
    const { rerender } = render(<AuditPanel run={run} events={[terminal]} />);
    const before = screen.getByRole("list", { name: "Business actions" }).textContent;
    run.outcome = {
      case_id: "case-25", run_id: "run-case-25", duplicate_decision: "confirmed", policy_decision: "eligible",
      approval_decision: "approved", refund_status: "verified", notification_status: "sent",
      terminal_status: "completed_refunded", event_summary: []
    };
    run.memory = { refund_status: "verified" };
    rerender(<AuditPanel run={run} events={[terminal]} />);
    expect(screen.getByRole("list", { name: "Business actions" }).textContent).toBe(before);
    expect(screen.getByText("Case closed — refunded")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Business actions" })).toHaveTextContent("Manual review required");
  });
  it("never invents approval audit from current snapshot or invents historical actor identities", () => {
    const run = viewFor("case-25");
    run.approval = { decision: "approve", checkpoint_id: "cp", reviewer_id: "snapshot-reviewer", reason: null, decided_at: null, consumed: true };
    run.can_resume = true;
    render(<AuditPanel run={run} events={[
      businessEvent("approval_command_recorded", 1, { audit_version: undefined, decision: "approve" }),
      businessEvent("run_resumed", 2, { audit_version: undefined })
    ]} />);
    const entries = screen.getByRole("list", { name: "Business actions" });
    expect(within(entries).getAllByText("Actor unknown / not recorded")).toHaveLength(2);
    expect(entries).not.toHaveTextContent("snapshot-reviewer");
    expect(entries).not.toHaveTextContent("Processing continued");
    expect(screen.getByRole("status")).toHaveTextContent("Missing facts are not inferred");
  });
  it("does not fabricate an approval or terminal action from an empty event stream", () => {
    const run = viewFor("case-25");
    run.state.status = "completed";
    run.state.approval_decision = "approve";
    render(<AuditPanel run={run} events={[]} />);
    expect(screen.getByRole("list", { name: "Business actions" })).toBeEmptyDOMElement();
    expect(screen.getByText("No business actions recorded yet.")).toBeInTheDocument();
  });
});
