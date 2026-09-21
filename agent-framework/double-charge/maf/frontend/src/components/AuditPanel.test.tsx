import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AuditPanel } from "./AuditPanel";
import { businessEvent, viewFor } from "../test/workspaceFixtures";

afterEach(cleanup);

describe("business-facing Audit trail", () => {
  it("renders actors and selected evidence without exposing technical codes, identifiers, or arbitrary summaries", () => {
    const event = {
      ...businessEvent("approval.recorded", 991, { decision: "approve", reason: "Both charges match", unrestricted: "not-business-evidence" }),
      event_id: "technical-event-id", run_id: "technical-run-id", checkpoint_id: "technical-checkpoint-id",
      node: "approval_checkpoint", summary: "Arbitrary model-generated-looking summary"
    };
    render(<AuditPanel run={viewFor("case-25")} events={[event]} />);
    expect(screen.getByRole("heading", { name: "Audit trail" })).toBeVisible();
    expect(screen.getByText("Simulation")).toBeVisible();
    expect(screen.getAllByText("case-25")).toHaveLength(1);
    expect(screen.getAllByText("customer-case-25")).toHaveLength(1);
    const list = screen.getByRole("list", { name: "Business actions" });
    expect(within(list).getByText("Refund approved")).toBeVisible();
    expect(within(list).getByText("Reviewer: reviewer-test (operator-provided; not authenticated)")).toBeVisible();
    fireEvent.click(within(list).getByText("Business evidence"));
    expect(within(list).getByText("Both charges match")).toBeVisible();
    for (const value of ["991", "technical-event-id", "technical-run-id", "technical-checkpoint-id", "approval.recorded", "approval_checkpoint", "not-business-evidence", "Arbitrary model-generated-looking summary"]) {
      expect(list).not.toHaveTextContent(value);
    }
  });

  it("keeps historical closure immutable when the current snapshot changes", () => {
    const closure = businessEvent("run.failed", 1, {
      terminal_status: "manual_review", refund_status: "manual_review", notification_status: "not_sent",
      failure_code: "refund_outcome_uncertain"
    });
    const run = viewFor("case-25");
    run.state.terminal_status = "manual_review";
    const { rerender } = render(<AuditPanel run={run} events={[closure]} />);
    const historyBefore = screen.getByRole("list", { name: "Business actions" }).textContent;
    rerender(<AuditPanel run={{
      ...run, state: { ...run.state, terminal_status: "completed_refunded", refund_status: "verified" }
    }} events={[closure]} />);
    expect(screen.getByText("Current resolution (snapshot)")).toBeVisible();
    expect(screen.getByText("Case closed — refunded")).toBeVisible();
    expect(screen.getByRole("list", { name: "Business actions" }).textContent).toBe(historyBefore);
    expect(screen.getByRole("list", { name: "Business actions" })).toHaveTextContent("The refund outcome remains uncertain");
  });

  it("does not create approval history from a snapshot, even when Resume is available", () => {
    render(<AuditPanel run={viewFor("case-25", {
      can_resume: true, approval: { decision: "approve", reviewer_id: "snapshot-reviewer", reason: "snapshot-reason", decided_at: "2026-09-16T12:00:00Z", checkpoint_id: "snapshot-checkpoint" }
    })} events={[businessEvent("run.started", 1)]} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.queryByText("Refund approved")).not.toBeInTheDocument();
    expect(screen.queryByText("snapshot-reason")).not.toBeInTheDocument();
    expect(screen.queryByText("Resume requested")).not.toBeInTheDocument();
  });

  it("labels simulated notification without claiming customer delivery", () => {
    render(<AuditPanel run={viewFor("case-25")} events={[businessEvent("notification.sent", 1)]} />);
    expect(screen.getByText("Customer notification simulated")).toBeVisible();
    expect(screen.getByText(/not confirmation of delivery to the customer/)).toBeVisible();
    expect(screen.getByRole("list", { name: "Business actions" })).toHaveTextContent("System");
  });

  it("shows incompatible-record notice instead of invented actors or a fixed checklist", () => {
    const old = businessEvent("run.started", 1);
    old.payload = {};
    render(<AuditPanel run={viewFor("case-25")} events={[old]} />);
    expect(screen.getByRole("status")).toHaveTextContent("incompatible audit versions or actor information");
    expect(screen.getByRole("list", { name: "Business actions" })).toBeEmptyDOMElement();
    expect(screen.queryByText("System")).not.toBeInTheDocument();
    expect(screen.getByText("No business actions recorded yet.")).toBeVisible();
  });
});
