import { describe, expect, it } from "vitest";
import { canResume, completedProgress, needsApproval, progressLabel, toolLabel } from "./state";
import type { CheckoutCase, SafeAuditEvent } from "./types";

const pendingCase: CheckoutCase = {
  case_id: "case-1",
  run_id: "run-1",
  fixture_id: "captured-payment-approved-remediation",
  phase: "waiting_approval",
  diagnostic_disposition: "refund_captured_payment",
  approval_decision: "pending",
  approval_request_id: "approval-1",
  remediation_action: null,
  remediation_status: null,
  verification_result: null,
  terminal_status: null,
  failure_code: "none",
  workspace_artifact: {
    artifact_id: "artifact-1",
    kind: "checkout_recovery_plan_evidence_summary",
    revision: 2,
    updated_at: "2026-01-01T00:00:00Z"
  }
};

const events: SafeAuditEvent[] = [
  { code: "case_started", occurred_at: "2026-01-01T00:00:00Z", summary: "Started." },
  { code: "diagnostic_completed", occurred_at: "2026-01-01T00:00:01Z", summary: "Read." }
];

describe("checkout workspace state", () => {
  it("derives progress from safe audit code metadata", () => {
    expect(completedProgress(events)).toEqual(["case_started", "diagnostic"]);
    expect(toolLabel("diagnostic_completed")).toBe("Diagnostic reader");
  });

  it("requires an explicit approval before resume", () => {
    expect(needsApproval(pendingCase)).toBe(true);
    expect(canResume(pendingCase)).toBe(false);
    expect(progressLabel(pendingCase, events)).toBe("Waiting for a durable reviewer decision");
    expect(canResume({ ...pendingCase, approval_decision: "approved" })).toBe(true);
    expect(canResume({ ...pendingCase, approval_decision: "denied" })).toBe(true);
    expect(canResume({ ...pendingCase, phase: "closed", approval_decision: "approved" })).toBe(false);
  });
});
